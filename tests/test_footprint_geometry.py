import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
