"""Pin the eval fixtures' planted bugs, so a library or CLI change can't silently change what an
eval tests. Stackup tests run in a temp copy (no cache in the repo) and skip without the CLI;
they need network the first time Stackup downloads the pinned library."""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
FILES = os.path.join(ROOT, "evals", "files")
SCRIPTS = os.path.join(ROOT, "skills", "pcb-design", "scripts")
sys.path.insert(0, SCRIPTS)

import bom_check  # noqa: E402
import footprint_geometry as fg  # noqa: E402

HAVE_STACKUP = shutil.which("stackup") is not None


def stackup(fixture, *args, edit=None):
    """Run `stackup <args>` on a temp copy of evals/files/<fixture>; returns (code, output)."""
    with tempfile.TemporaryDirectory() as d:
        work = os.path.join(d, fixture)
        shutil.copytree(os.path.join(FILES, fixture), work,
                        ignore=shutil.ignore_patterns(".stackup"))
        if edit:
            path = os.path.join(work, "board.kdl")
            with open(path) as f:
                text = f.read()
            with open(path, "w") as f:
                f.write(edit(text))
        result = subprocess.run(["stackup", *args], cwd=work, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def summary(output):
    m = re.search(r"(\d+) errors, (\d+) warnings, (\d+) notes", output)
    return tuple(int(x) for x in m.groups()) if m else None


class EvalsJsonTests(unittest.TestCase):
    def test_cases_are_well_formed_and_files_exist(self):
        with open(os.path.join(ROOT, "evals", "evals.json")) as f:
            data = json.load(f)
        ids = [e["id"] for e in data["evals"]]
        self.assertEqual(len(ids), len(set(ids)))
        for e in data["evals"]:
            self.assertTrue(e["prompt"].strip(), e["id"])
            self.assertTrue(e.get("assertions"), f"eval {e['id']} has no assertions")
            for path in e["files"]:
                self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)


class FootprintFixtureTests(unittest.TestCase):
    PCB = os.path.join(FILES, "footprint-check", "board.kicad_pcb")

    def measure(self, ref):
        with open(self.PCB) as f:
            fp, angle = fg.load_board_footprint(f.read(), ref)
        return fg.measure(fp, angle)

    def test_d1_is_a_5x5_body_for_a_mini_e_part(self):
        m = self.measure("D1")
        self.assertEqual((m["body_fab"]["width"], m["body_fab"]["height"]), (5.0, 5.0))

    def test_d2_has_two_pads_for_a_three_pin_part(self):
        self.assertEqual(self.measure("D2")["pad_count"], 2)

    def test_q1_and_r1_are_correct(self):
        self.assertEqual(self.measure("Q1")["pad_count"], 3)
        self.assertEqual(self.measure("R1")["pad_count"], 2)

    def test_parts_named_in_fields(self):
        with open(self.PCB) as f:
            text = f.read()
        self.assertIn('"Manufacturer_Part_Number" "SK6812MINI-E"', text)
        self.assertIn('"Manufacturer_Part_Number" "BAT54W-7-F"', text)


@unittest.skipUnless(HAVE_STACKUP, "Stackup CLI not installed")
class StackupFixtureTests(unittest.TestCase):
    def test_latch_is_clean(self):
        self.assertEqual(summary(stackup("latch", "check", "board.kdl", "--locked")[1]), (0, 0, 0))

    def test_review_latch_reports_only_the_floating_enable(self):
        code, out = stackup("review-latch", "check", "board.kdl", "--locked")
        self.assertEqual(summary(out), (1, 0, 0), out)
        self.assertIn("`U_BUCK1`.EN requires `rest` not=float", out)

    def test_review_latch_planted_bugs_are_present(self):
        with open(os.path.join(FILES, "review-latch", "board.kdl")) as f:
            text = f.read()
        self.assertRegex(text, r'"R_LATCH_G1".*value="10kΩ"')
        self.assertRegex(text, r'circuit "Q_PWR1.SOURCE".*"R_BTN_PU1.A".*name="VSYS"')
        self.assertNotIn("R_PWR_EN_PD1", text)

    def test_analyzer_claims_is_clean_but_has_the_true_bug(self):
        self.assertEqual(summary(stackup("analyzer-claims", "check", "board.kdl", "--locked")[1]),
                         (0, 0, 0))
        with open(os.path.join(FILES, "analyzer-claims", "board.kdl")) as f:
            text = f.read()
        self.assertRegex(text, r'circuit "Q_PWR1.SOURCE".*"R_BTN_PU1.A".*name="VSYS"')
        self.assertIn('"R_PWR_EN_PD1.node"', text)

    def test_pin_assign_is_clean_and_accepts_the_psram_trap(self):
        self.assertEqual(summary(stackup("pin-assign", "check", "board.kdl", "--locked")[1]),
                         (0, 0, 0))
        trap = lambda t: t.replace("    // TODO: SW1-SW3 (active low) to MCU inputs",
                                   '    circuit U1.IO35 SW1.a name="BTN1"')
        self.assertEqual(summary(stackup("pin-assign", "check", "board.kdl", "--locked",
                                         edit=trap)[1]), (0, 0, 0))

    def test_bom_export_gaps(self):
        code, out = stackup("bom-export", "check", "board.kdl", "--locked")
        self.assertEqual(summary(out), (0, 0, 0), out)
        code, csv_text = stackup("bom-export", "bom", "board.kdl", "--locked")
        self.assertEqual(code, 0, csv_text)
        rows = bom_check.read_csv(csv_text)
        problems = bom_check.check_rows(rows, fab="jlc")
        self.assertEqual(sorted(problems), sorted([
            ("R1", "no LCSC number (JLCPCB assembly matches on it)"),
            ("C1", "blank manufacturer"),
            ("C1", "blank MPN"),
            ("C1", "no LCSC number (JLCPCB assembly matches on it)"),
            ("Q1", "value contains ',', which forces CSV quoting"),
        ]))
        d1 = next(r for r in rows if r["Refs"] == "D1")
        self.assertEqual((d1["MPN"], d1["Footprint"]), ("BAT54W-7-F", "Diode_SMD:D_SOD-123"))
        j1 = next(r for r in rows if r["Refs"] == "J1")
        self.assertNotIn("right", j1["Value"].lower())


if __name__ == "__main__":
    unittest.main()
