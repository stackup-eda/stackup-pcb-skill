import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import ngspice_harness as h  # noqa: E402
import spice_lib as s  # noqa: E402


class ModelTests(unittest.TestCase):
    def test_mos_models_carry_threshold_and_sign(self):
        self.assertIn("NMOS(LEVEL=1 VTO=1.45", s.nmos("N1", 1.45))
        self.assertIn("VTO=-0.9 ", s.pmos("P1", 0.9))
        self.assertIn("VTO=-0.9 ", s.pmos("P1", -0.9))

    def test_diode_and_bjt(self):
        self.assertTrue(s.diode("D1", "BAT54").startswith(".model D1 D("))
        self.assertTrue(s.npn("Q1").startswith(".model Q1 NPN("))
        with self.assertRaises(KeyError):
            s.diode("D2", "nonexistent")


class StimulusTests(unittest.TestCase):
    def test_pwl(self):
        self.assertEqual(s.pwl((0, 0), ("1m", 3.3)), "PWL(0 0 1m 3.3)")
        with self.assertRaises(ValueError):
            s.pwl()

    def test_ramp_from_zero_and_delayed(self):
        self.assertEqual(s.ramp(4.2, "100u"), "PWL(0 0 0.0001 4.2 10 4.2)")
        self.assertEqual(s.ramp(3.0, "1m", start="2m"), "PWL(0 0 0.002 0 0.003 3 10 3)")

    def test_press(self):
        self.assertEqual(s.press(0.1, 0.4, edge=0.001),
                         "PWL(0 0 0.1 0 0.101 1 0.5 1 0.501 0 10 0)")

    def test_num_units(self):
        self.assertAlmostEqual(s._num("10u"), 1e-5)
        self.assertAlmostEqual(s._num("2Meg"), 2e6)
        self.assertEqual(s._num(3), 3)


class MeasureTests(unittest.TestCase):
    T = [0.0, 1.0, 2.0, 3.0, 4.0]
    V = [0.0, 2.0, 0.8, 0.5, 2.0]

    def test_peak_windows(self):
        self.assertEqual(s.peak(self.T, self.V), 2.0)
        self.assertEqual(s.peak(self.T, self.V, start=1.5, stop=3.5), 0.8)
        with self.assertRaises(ValueError):
            s.peak(self.T, self.V, start=10)

    def test_first_below(self):
        self.assertEqual(s.first_below(self.T, self.V, 1.0, after=1.0), 2.0)
        self.assertIsNone(s.first_below(self.T, self.V, -1))

    def test_time_between(self):
        self.assertEqual(s.time_between(self.T, self.V, 0.4, 1.0), 1.0)


class MatrixTests(unittest.TestCase):
    def test_corners(self):
        self.assertEqual(s.corners(), [{}])
        c = s.corners(v=(3.0, 4.2), vth=(0.65, 1.45))
        self.assertEqual(len(c), 4)
        self.assertEqual(c[0], {"v": 3.0, "vth": 0.65})
        self.assertEqual(s.label(c[3]), "v=4.2 vth=1.45")

    def test_run_matrix_reports_errors_as_failures(self):
        class FakeSim:
            def run(self, netlist, nodes):
                if "bad" in netlist:
                    raise h.NgSpiceError("netlist rejected:\nmore")
                return h.Trace([0, 1], {"n": [0, 1]})

        rows = s.run_matrix(FakeSim(), "scn", lambda mode: mode, s.corners(mode=("good", "bad")),
                            ["n"], lambda tr, c: (tr["n"][-1] == 1, "ok"))
        self.assertEqual(rows[0], ("scn mode=good", True, "ok"))
        self.assertFalse(rows[1][1])
        self.assertEqual(rows[1][2], "simulation error: netlist rejected:")


def _sim_or_none():
    try:
        return h.NgSpice()
    except h.NgSpiceError:
        return None


SIM = _sim_or_none()


@unittest.skipIf(SIM is None, "libngspice not available")
class TemplateTests(unittest.TestCase):
    """The template's example latch must pass as designed and fail without its gate capacitor,
    which proves the models and scenarios can see the insertion transient."""

    @classmethod
    def setUpClass(cls):
        import spice_template
        cls.t = spice_template

    def run_template(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self.t.main(list(argv))
        return code, out.getvalue()

    def test_passes_as_designed(self):
        code, out = self.run_template()
        self.assertEqual(code, 0, out)

    def test_insertion_fails_without_gate_cap(self):
        code, out = self.run_template("--scenario", "insert", "--no-gate-cap")
        self.assertEqual(code, 1)
        self.assertIn("FAIL  insert vsys=4.5", out)


if __name__ == "__main__":
    unittest.main()
