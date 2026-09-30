import contextlib
import csv
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import bom_check  # noqa: E402
import bom_export as x  # noqa: E402

HEADER = "Refs,Quantity,Value,Footprint,MF,MPN,LCSC,Mouser,DigiKey,Hand,DNP\n"
LINES = {
    "R": '"R1,R2","2","100kΩ","Resistor_SMD:R_0402_1005Metric","UNI-ROYAL","0402WGF1003TCE","C25741","","","",""\n',
    "D": '"D1","1","1N4148W","Diode_SMD:D_SOD-123","ST","1N4148W","C81598","","","",""\n',
    "J": '"J1","1","PH 2-pin RIGHT-ANGLE","Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal","JST","S2B-PH-K(LF)(SN)","C265016","","","",""\n',
    "U": '"U1","1","ESP32","Espressif:ESP32-S3-WROOM-1","Espressif","ESP32-S3-WROOM-1-N8","C2913198","","","",""\n',
    "H": '"U2","1","XBee3","Xbee3:XB324Z8UTJ","Digi","XB3-24Z8UT-J","","","","Yes","Yes"\n',
}


def rows(*keys):
    return bom_check.read_csv(HEADER + "".join(LINES[k] for k in keys))


class PackageTests(unittest.TestCase):
    def test_size_code(self):
        self.assertEqual(x.package_of(rows("R")[0]), "0402")

    def test_package_code(self):
        self.assertEqual(x.package_of(rows("D")[0]), "SOD-123")

    def test_connector_family_keeps_footprint_name(self):
        self.assertEqual(x.package_of(rows("J")[0]), "JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal")

    def test_part_specific_footprint_keeps_name(self):
        self.assertEqual(x.package_of(rows("U")[0]), "ESP32-S3-WROOM-1")

    def test_override(self):
        self.assertEqual(x.package_of(rows("R")[0], {"R2": "0402 1%"}), "0402 1%")


class LongValueTests(unittest.TestCase):
    def test_passive(self):
        row = rows("R")[0]
        self.assertEqual(x.long_value(row, "0402"), "100kΩ | 0402WGF1003TCE | UNI-ROYAL | 0402")

    def test_repeated_value_and_mpn_collapse(self):
        self.assertEqual(x.long_value(rows("D")[0], "SOD-123"), "1N4148W | ST | SOD-123")

    def test_unsafe_characters_removed(self):
        row = {"Value": 'P-FET, 30V; "fast"', "MPN": "AO3401A", "MF": "AOS"}
        self.assertEqual(x.long_value(row, "SOT-23"), "P-FET 30V fast | AO3401A | AOS | SOT-23")

    def test_parse_overrides(self):
        self.assertEqual(x.parse_overrides(["J1=holder, 18650"]), {"J1": "holder 18650"})
        with self.assertRaises(ValueError):
            x.parse_overrides(["J1"])


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.rows = x.expand(rows("R", "D", "H"))

    def read(self, writer):
        buf = io.StringIO()
        writer(self.rows, buf)
        return list(csv.reader(io.StringIO(buf.getvalue())))

    def test_jlc_leaves_out_hand_and_dnp(self):
        out = self.read(x.write_jlc)
        self.assertEqual(out[0], ["Comment", "Designator", "Footprint", "LCSC Part #"])
        self.assertEqual([r[1] for r in out[1:]], ["R1,R2", "D1"])
        self.assertEqual(out[1], ["100kΩ | 0402WGF1003TCE | UNI-ROYAL | 0402", "R1,R2",
                                  "R_0402_1005Metric", "C25741"])

    def test_value_only_marks_dnp(self):
        out = self.read(x.write_value_only)
        self.assertEqual(out[0], ["Designator", "Footprint", "Quantity", "Value"])
        self.assertTrue(out[3][3].endswith("| DNP"))

    def test_purchasing_adds_columns(self):
        out = self.read(x.write_purchasing)
        self.assertIn("Package", out[0])
        self.assertIn("LongValue", out[0])


class MainTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = x.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_writes_files(self):
        with tempfile.TemporaryDirectory() as d:
            bom = os.path.join(d, "bom.csv")
            open(bom, "w").write(HEADER + LINES["R"] + LINES["J"])
            jlc = os.path.join(d, "jlc.csv")
            code, out, err = self.run_main([bom, "--jlc", jlc])
            self.assertEqual(code, 0, err)
            self.assertIn("RIGHT-ANGLE", open(jlc).read())

    def test_problems_stop_export_unless_forced(self):
        with tempfile.TemporaryDirectory() as d:
            bom = os.path.join(d, "bom.csv")
            open(bom, "w").write(HEADER + '"C1","1","100nF","Capacitor_SMD:C_0402_1005Metric","","","","","","",""\n')
            out_file = os.path.join(d, "v.csv")
            code, _, err = self.run_main([bom, "--value-only", out_file])
            self.assertEqual(code, 1)
            self.assertIn("blank MPN", err)
            self.assertFalse(os.path.exists(out_file))
            code, _, _ = self.run_main([bom, "--value-only", out_file, "--force"])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(out_file))

    def test_jlc_output_applies_lcsc_rule(self):
        with tempfile.TemporaryDirectory() as d:
            bom = os.path.join(d, "bom.csv")
            open(bom, "w").write(HEADER + LINES["R"].replace("C25741", ""))
            code, _, err = self.run_main([bom, "--jlc", os.path.join(d, "j.csv")])
            self.assertEqual(code, 1)
            self.assertIn("no LCSC", err)

    def test_package_override_clears_package_problem(self):
        with tempfile.TemporaryDirectory() as d:
            bom = os.path.join(d, "bom.csv")
            open(bom, "w").write(HEADER + '"J9","1","Stick","Custom:Thing","Acme","ST-1","","","","Yes","Yes"\n')
            v = os.path.join(d, "v.csv")
            self.assertEqual(self.run_main([bom, "--value-only", v])[0], 1)
            code, _, err = self.run_main([bom, "--value-only", v, "--package", "J9=18x22mm module"])
            self.assertEqual(code, 0, err)
            self.assertIn("18x22mm module", open(v).read())

    def test_needs_an_output(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                x.main(["bom.csv"])


if __name__ == "__main__":
    unittest.main()
