import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import footprint_geometry as g  # noqa: E402

# A 4-pad part: two columns 5.45 mm apart, rows 1.5 mm apart, 3.2 x 2.8 mm body.
FOOTPRINT = """(footprint "Test:LED4"
  (layer "F.Cu")
  (attr smd)
  (fp_rect (start -1.6 -1.4) (end 1.6 1.4) (layer "F.Fab"))
  (fp_line (start -3.65 -1.87) (end 3.65 -1.87) (layer "F.CrtYd"))
  (fp_line (start -3.65 1.87) (end 3.65 1.87) (layer "F.CrtYd"))
  (fp_text user "a \\"quoted\\" (paren)" (at 0 0) (layer "F.Fab"))
  (pad "1" smd roundrect (at -2.725 0.75) (size 1.35 0.82) (layers "F.Cu"))
  (pad "2" smd roundrect (at -2.725 -0.75) (size 1.35 0.82) (layers "F.Cu"))
  (pad "3" smd roundrect (at 2.725 -0.75) (size 1.35 0.82) (layers "F.Cu"))
  (pad "4" smd roundrect (at 2.725 0.75) (size 1.35 0.82) (layers "F.Cu"))
)
"""

# The same part placed on a board rotated 90 degrees: pad angles include the rotation.
BOARD = """(kicad_pcb
  (footprint "Test:LED4" (layer "F.Cu") (at 10 20 90)
    (property "Reference" "D1" (at 0 0 90) (layer "F.SilkS"))
    (attr smd)
    (fp_rect (start -1.6 -1.4) (end 1.6 1.4) (layer "F.Fab"))
    (pad "1" smd roundrect (at -2.725 0.75 90) (size 1.35 0.82) (layers "F.Cu"))
    (pad "2" smd roundrect (at -2.725 -0.75 90) (size 1.35 0.82) (layers "F.Cu"))
  )
  (footprint "Test:R" (layer "F.Cu") (at 0 0)
    (property "Reference" "R1" (at 0 0) (layer "F.SilkS"))
    (pad "1" thru_hole circle (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu"))
    (pad "2" thru_hole oval (at 2.54 0) (size 1.6 1.6) (drill oval 0.8 1.2) (layers "*.Cu"))
  )
)
"""

# A reverse-mount part: a 3.4 x 3.0 mm cutout on Edge.Cuts, rect pads whose inner edges sit
# 0.35 mm outside it, and the fields a board carries.
REVERSE_MOUNT = """(footprint "Test:REV"
  (property "Reference" "D1" (at 0 0) (layer "F.SilkS"))
  (property "Value" "SK6812MINI-E" (at 0 0) (layer "F.Fab"))
  (property "Datasheet" "" (at 0 0) (layer "F.Fab"))
  (property "Manufacturer_Part_Number" "SK6812MINI-E" (at 0 0) (layer "F.Fab"))
  (attr smd)
  (fp_rect (start -1.7 -1.5) (end 1.7 1.5) (layer "Edge.Cuts"))
  (pad "1" smd rect (at -2.725 0.75) (size 1.35 0.82) (layers "B.Cu"))
  (pad "4" smd rect (at 2.725 0.75) (size 1.35 0.82) (layers "B.Cu"))
)
"""


# An addressable LED whose pads were numbered after a symbol (1 VSS, 2 DIN, 3 VDD, 4 DOUT) while
# its datasheet numbers the pins 1 VDD, 2 DOUT, 3 GND, 4 DIN. Both net syntaxes appear: the
# numbered (net 3 "GND") and KiCad 10's (net "GND").
SYMBOL_NUMBERED = """(kicad_pcb
  (footprint "Custom:LED4" (layer "F.Cu") (at 0 0)
    (property "Reference" "D1" (at 0 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -2.725 0.75) (size 1.35 0.82) (layers "B.Cu") (net 1 "GND") (pinfunction "VSS"))
    (pad "2" smd rect (at -2.725 -0.75) (size 1.35 0.82) (layers "B.Cu") (net "RGB_DIN") (pinfunction "DIN"))
    (pad "3" smd rect (at 2.725 -0.75) (size 1.35 0.82) (layers "B.Cu") (net "3V3") (pinfunction "VDD"))
    (pad "4" smd rect (at 2.725 0.75) (size 1.35 0.82) (layers "B.Cu") (pinfunction "DOUT"))
  )
  (footprint "Custom:LED4" (layer "F.Cu") (at 0 0)
    (property "Reference" "D2" (at 0 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -2.725 -0.75) (size 1.35 0.82) (layers "B.Cu") (net "3V3") (pinfunction "vdd"))
    (pad "2" smd rect (at -2.725 0.75) (size 1.35 0.82) (layers "B.Cu") (pinfunction "DOUT"))
    (pad "3" smd rect (at 2.725 0.75) (size 1.35 0.82) (layers "B.Cu") (net "GND") (pinfunction "GND"))
    (pad "4" smd rect (at 2.725 -0.75) (size 1.35 0.82) (layers "B.Cu") (net "RGB_DIN") (pinfunction "DIN"))
  )
)
"""

DATASHEET_PINS = "1=VDD,2=DOUT,3=GND,4=DIN"


class ParseTests(unittest.TestCase):
    def test_quoted_strings_with_escapes_and_parens(self):
        root = g.parse('(a "x \\"y\\" (z)" (b 1 2))')
        self.assertEqual(root, [["a", 'x "y" (z)', ["b", "1", "2"]]])

    def test_unbalanced(self):
        with self.assertRaises(ValueError):
            g.parse("(a (b)")
        with self.assertRaises(ValueError):
            g.parse("(a))")


class MeasureTests(unittest.TestCase):
    def setUp(self):
        self.m = g.measure(g.load_library_footprint(FOOTPRINT))

    def test_pads(self):
        self.assertEqual(self.m["type"], "smd")
        self.assertEqual(self.m["pad_count"], 4)
        self.assertEqual(self.m["pad_numbers"], ["1", "2", "3", "4"])

    def test_pitch_and_spans(self):
        self.assertEqual(self.m["pitches"], [1.5, 5.45])
        self.assertAlmostEqual(self.m["pad_center_span"]["width"], 5.45)
        self.assertAlmostEqual(self.m["pad_center_span"]["height"], 1.5)
        self.assertAlmostEqual(self.m["pad_outer_extent"]["width"], 6.8)
        self.assertAlmostEqual(self.m["pad_outer_extent"]["height"], 2.32)

    def test_body_and_courtyard(self):
        self.assertAlmostEqual(self.m["body_fab"]["width"], 3.2)
        self.assertAlmostEqual(self.m["body_fab"]["height"], 2.8)
        self.assertAlmostEqual(self.m["courtyard"]["width"], 7.3)

    def test_report_mentions_key_numbers(self):
        report = g.format_report(self.m)
        self.assertIn("Pads: 4", report)
        self.assertIn("5.450 x 1.500", report)
        self.assertIn("3.200 x 2.800", report)


class BoardTests(unittest.TestCase):
    def test_rotation_on_board_is_removed(self):
        fp, angle = g.load_board_footprint(BOARD, "D1")
        self.assertEqual(angle, 90.0)
        pads = g.measure(fp, angle)["pads"]
        self.assertEqual((pads[0]["width"], pads[0]["height"]), (1.35, 0.82))

    def test_ignoring_rotation_would_swap_sizes(self):
        fp, _ = g.load_board_footprint(BOARD, "D1")
        pad = g.measure(fp, 0.0)["pads"][0]
        self.assertEqual((pad["width"], pad["height"]), (0.82, 1.35))

    def test_drills_including_oval(self):
        fp, angle = g.load_board_footprint(BOARD, "R1")
        pads = g.measure(fp, angle)["pads"]
        self.assertEqual([p["drill"] for p in pads], [0.8, 0.8])
        self.assertEqual(g.measure(fp, angle)["type"], "unspecified")

    def test_missing_reference(self):
        with self.assertRaises(LookupError):
            g.load_board_footprint(BOARD, "U9")


class GraphicsTests(unittest.TestCase):
    def test_circle_arc_poly_points(self):
        circle = g.parse('(fp_circle (center 0 0) (end 1 0) (layer "F.Fab"))')[0]
        self.assertEqual(g.graphic_points(circle), [[-1.0, -1.0], [1.0, 1.0]])
        arc = g.parse('(fp_arc (start 0 1) (mid 1 0) (end 0 -1) (layer "F.Fab"))')[0]
        self.assertEqual(len(g.graphic_points(arc)), 3)
        poly = g.parse('(fp_poly (pts (xy 0 0) (xy 2 0) (xy 2 3)) (layer "F.Fab"))')[0]
        self.assertEqual(g.box_of(g.graphic_points(poly)).height, 3.0)

    def test_back_layer_used_when_no_front(self):
        fp = g.parse('(footprint "X" (fp_rect (start 0 0) (end 4 2) (layer "B.Fab")))')[0]
        self.assertEqual(g.layer_box(fp, "Fab").width, 4.0)
        self.assertIsNone(g.layer_box(fp, "CrtYd"))


class PropertiesTests(unittest.TestCase):
    def test_fields_reported_and_empty_ones_dropped(self):
        m = g.measure(g.load_library_footprint(REVERSE_MOUNT))
        self.assertEqual(m["properties"], {"Reference": "D1", "Value": "SK6812MINI-E",
                                           "Manufacturer_Part_Number": "SK6812MINI-E"})
        report = g.format_report(m)
        self.assertIn("Manufacturer_Part_Number: SK6812MINI-E", report)
        self.assertNotIn("Datasheet", report)


class EdgeCutsTests(unittest.TestCase):
    def test_cutout_size_and_pad_clearance(self):
        m = g.measure(g.load_library_footprint(REVERSE_MOUNT))
        self.assertAlmostEqual(m["edge_cuts"]["width"], 3.4)
        self.assertAlmostEqual(m["edge_cuts"]["height"], 3.0)
        self.assertAlmostEqual(m["edge_cuts_pad_clearance"]["gap"], 0.35)
        self.assertIn("3.400 x 3.000, closest pad", g.format_report(m))

    def test_no_cutout(self):
        m = g.measure(g.load_library_footprint(FOOTPRINT))
        self.assertIsNone(m["edge_cuts"])
        self.assertIsNone(m["edge_cuts_pad_clearance"])
        self.assertIn("Edge.Cuts cutout:  none", g.format_report(m))

    def test_rounded_pad_corners_add_clearance(self):
        # A cutout corner diagonal to a pad corner: 0.3 mm apart in x and y.
        segment = [((0.0, 0.0), (0.0, -1.0))]
        square = g.Pad("1", "smd", "rect", 0.8, 0.8, 1.0, 1.0)
        rounded = g.Pad("1", "smd", "roundrect", 0.8, 0.8, 1.0, 1.0, corner_radius=0.25)
        self.assertAlmostEqual(g.pad_clearance(segment, [square])[0], 0.4243, places=4)
        # Corner circle center at (0.55, 0.55), radius 0.25: 0.7778 - 0.25.
        self.assertAlmostEqual(g.pad_clearance(segment, [rounded])[0], 0.5278, places=4)

    def test_overlap_is_zero(self):
        pad = g.Pad("1", "smd", "rect", 0.0, 0.0, 1.0, 1.0)
        self.assertEqual(g.pad_clearance([((0.2, 0.0), (3.0, 0.0))], [pad]), (0.0, "1"))
        self.assertEqual(g.pad_clearance([((-2.0, 0.0), (2.0, 0.0))], [pad]), (0.0, "1"))
        self.assertIsNone(g.pad_clearance([], [pad]))

    def test_pad_corner_radius_from_shape(self):
        fp = g.parse('(footprint "X"'
                     ' (pad "1" smd roundrect (at 0 0) (size 1 0.8) (roundrect_rratio 0.1))'
                     ' (pad "2" smd roundrect (at 2 0) (size 1 0.8))'
                     ' (pad "3" thru_hole oval (at 4 0) (size 1.2 1.6) (drill 0.8))'
                     ' (pad "4" smd rect (at 6 0) (size 1 1)))')[0]
        radii = [p.corner_radius for p in g.read_pads(fp)]
        self.assertEqual([round(r, 4) for r in radii], [0.08, 0.2, 0.6, 0.0])

    def test_arc_follows_the_mid_point(self):
        # Quarter circle of radius 1 about the origin, bulging toward (-0.707, -0.707).
        pts = g.arc_points([-1, 0], [-math.sqrt(0.5), -math.sqrt(0.5)], [0, -1])
        self.assertAlmostEqual(min(p[0] for p in pts), -1.0)
        self.assertAlmostEqual(max(p[0] for p in pts), 0.0)
        for x, y in pts:
            self.assertAlmostEqual(math.hypot(x, y), 1.0)
        # The same ends through the other side of the circle sweep 270 degrees.
        pts = g.arc_points([-1, 0], [math.sqrt(0.5), math.sqrt(0.5)], [0, -1])
        self.assertAlmostEqual(max(p[0] for p in pts), 1.0, places=2)
        self.assertEqual(g.arc_points([0, 0], [1, 1], [2, 2]), [[0, 0], [2, 2]])

    def test_every_graphic_kind_becomes_segments(self):
        fp = g.parse('(footprint "X"'
                     ' (fp_line (start 0 0) (end 1 0) (layer "Edge.Cuts"))'
                     ' (fp_circle (center 5 5) (end 6 5) (layer "Edge.Cuts"))'
                     ' (fp_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (layer "Edge.Cuts"))'
                     ' (fp_line (start 0 0) (end 9 9) (layer "F.SilkS")))')[0]
        segments = g.edge_cut_segments(fp)
        self.assertEqual(len(segments), 1 + g.ARC_STEPS + 3)
        box = g.box_of([pt for seg in segments for pt in seg])
        self.assertAlmostEqual(box.max_x, 6.0)


class LibraryLookupTests(unittest.TestCase):
    def test_finds_in_lib_dir_before_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Test.pretty"))
            path = os.path.join(d, "Test.pretty", "LED4.kicad_mod")
            with open(path, "w") as f:
                f.write(FOOTPRINT)
            self.assertEqual(g.find_library_file("Test:LED4", [d], env={}), path)

    def test_env_dir(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "Test.pretty"))
            path = os.path.join(d, "Test.pretty", "LED4.kicad_mod")
            open(path, "w").close()
            self.assertEqual(g.find_library_file("Test:LED4", [], env={"KICAD_FOOTPRINT_DIR": d}), path)

    def test_bad_names(self):
        with self.assertRaises(ValueError):
            g.find_library_file("NoColon", [], env={})
        with self.assertRaises(FileNotFoundError):
            g.find_library_file("Nope:Missing", [], env={})


class PinNumberingTests(unittest.TestCase):
    def measure(self, ref):
        return g.measure(*g.load_board_footprint(SYMBOL_NUMBERED, ref))

    def test_reads_net_and_pin_function(self):
        pads = {p["number"]: p for p in self.measure("D1")["pads"]}
        self.assertEqual((pads["1"]["net"], pads["1"]["pin_function"]), ("GND", "VSS"))
        self.assertEqual(pads["2"]["net"], "RGB_DIN")
        self.assertIsNone(pads["4"]["net"])

    def test_library_footprint_has_no_connectivity(self):
        pad = g.measure(g.load_library_footprint(FOOTPRINT))["pads"][0]
        self.assertIsNone(pad["net"])
        self.assertIsNone(pad["pin_function"])

    def test_symbol_numbering_fails(self):
        rows = g.check_pins(self.measure("D1"), g.parse_pins(DATASHEET_PINS))
        self.assertEqual([r["status"] for r in rows], ["mismatch"] * 4)
        self.assertEqual((rows[0]["datasheet"], rows[0]["pin_function"]), ("VDD", "VSS"))
        self.assertFalse(g.pins_ok(rows))
        self.assertIn("FAIL", g.format_pin_check(rows))

    def test_datasheet_numbering_passes_ignoring_case(self):
        rows = g.check_pins(self.measure("D2"), g.parse_pins(DATASHEET_PINS))
        self.assertEqual([r["status"] for r in rows], ["ok"] * 4)
        self.assertTrue(g.pins_ok(rows))
        self.assertIn("OK", g.format_pin_check(rows))

    def test_without_pin_functions_only_numbers_are_checked(self):
        m = g.measure(g.load_library_footprint(FOOTPRINT))
        rows = g.check_pins(m, g.parse_pins(DATASHEET_PINS))
        self.assertEqual([r["status"] for r in rows], ["unchecked"] * 4)
        self.assertTrue(g.pins_ok(rows))
        self.assertIn("not checked by name", g.format_pin_check(rows))

    def test_missing_and_extra_pads(self):
        m = g.measure(g.load_library_footprint(REVERSE_MOUNT))  # pads 1 and 4 only
        rows = g.check_pins(m, g.parse_pins("1=VDD 2=DOUT 3=GND"))
        self.assertEqual([(r["pad"], r["status"]) for r in rows],
                         [("1", "unchecked"), ("2", "missing"), ("3", "missing"), ("4", "extra")])
        self.assertFalse(g.pins_ok(rows))

    def test_stackup_pad_suffix_is_ignored(self):
        # Stackup's sync writes pin functions as <name>_<pad>: VSS_1, DIN_2.
        board = (SYMBOL_NUMBERED.replace('"VSS"', '"VSS_1"').replace('"vdd"', '"VDD_1"')
                 .replace('(pinfunction "GND")', '(pinfunction "GND_3")'))
        d1 = g.check_pins(g.measure(*g.load_board_footprint(board, "D1")), g.parse_pins(DATASHEET_PINS))
        self.assertEqual((d1[0]["pin_function"], d1[0]["status"]), ("VSS", "mismatch"))
        d2 = g.check_pins(g.measure(*g.load_board_footprint(board, "D2")), g.parse_pins(DATASHEET_PINS))
        self.assertEqual({r["status"] for r in d2}, {"ok"})

    def test_pin_name(self):
        self.assertEqual(g.pin_name("GND_3", "3"), "GND")
        self.assertEqual(g.pin_name("GND_3", "1"), "GND_3")  # another pad's number stays
        self.assertEqual(g.pin_name("_1", "1"), "_1")

    def test_parse_pins(self):
        self.assertEqual(g.parse_pins("1=VDD, 2=DOUT A1=GND"), {"1": "VDD", "2": "DOUT", "A1": "GND"})
        for bad in ("1VDD", "=VDD", "1=", "1=VDD,1=GND"):
            with self.assertRaises(ValueError):
                g.parse_pins(bad)


class MainTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = g.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_path_and_board(self):
        with tempfile.TemporaryDirectory() as d:
            mod = os.path.join(d, "LED4.kicad_mod")
            pcb = os.path.join(d, "b.kicad_pcb")
            open(mod, "w").write(FOOTPRINT)
            open(pcb, "w").write(BOARD)
            code, out, _ = self.run_main([mod])
            self.assertEqual(code, 0)
            self.assertIn("Test:LED4", out)
            code, out, _ = self.run_main(["--pcb", pcb, "--ref", "D1", "--json"])
            self.assertEqual(code, 0)
            self.assertIn('"pad_count": 2', out)
            code, _, err = self.run_main(["--pcb", pcb, "--ref", "U9"])
            self.assertEqual(code, 1)
            self.assertIn("U9", err)

    def test_whole_board(self):
        with tempfile.TemporaryDirectory() as d:
            pcb = os.path.join(d, "b.kicad_pcb")
            with open(pcb, "w") as f:
                f.write(BOARD)
            code, out, _ = self.run_main(["--pcb", pcb])
            self.assertEqual(code, 0)
            self.assertIn("Reference: D1", out)
            self.assertIn("Reference: R1", out)
            code, out, _ = self.run_main(["--pcb", pcb, "--json"])
            self.assertEqual([m["properties"]["Reference"] for m in json.loads(out)], ["D1", "R1"])


    def test_pins_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            pcb = os.path.join(d, "b.kicad_pcb")
            with open(pcb, "w") as f:
                f.write(SYMBOL_NUMBERED)
            code, out, _ = self.run_main(["--pcb", pcb, "--ref", "D1", "--pins", DATASHEET_PINS])
            self.assertEqual(code, 3)
            self.assertIn("FAIL", out)
            self.assertIn("VSS", out)  # the pad table shows each pad's pin function and net
            code, out, _ = self.run_main(["--pcb", pcb, "--ref", "D2", "--pins", DATASHEET_PINS, "--json"])
            self.assertEqual(code, 0)
            self.assertEqual({r["status"] for r in json.loads(out)["pin_check"]}, {"ok"})
            code, _, err = self.run_main(["--pcb", pcb, "--ref", "D2", "--pins", "1VDD"])
            self.assertEqual(code, 1)
            self.assertIn("number=name", err)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                g.main(["--pcb", pcb, "--pins", DATASHEET_PINS])

if __name__ == "__main__":
    unittest.main()
