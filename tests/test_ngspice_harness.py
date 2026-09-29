import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import ngspice_harness as h  # noqa: E402


class HelperTests(unittest.TestCase):
    T = [0.0, 1.0, 2.0, 3.0, 4.0]
    V = [0.0, 2.0, 2.0, 0.5, 2.0]

    def test_time_above_counts_only_intervals_with_both_ends_above(self):
        self.assertEqual(h.time_above(self.T, self.V, 1.0), 1.0)

    def test_time_above_zero_when_never_above(self):
        self.assertEqual(h.time_above(self.T, self.V, 5.0), 0.0)

    def test_first_above(self):
        self.assertEqual(h.first_above(self.T, self.V, 1.0), 1.0)
        self.assertEqual(h.first_above(self.T, self.V, 1.0, after=2.5), 4.0)
        self.assertIsNone(h.first_above(self.T, self.V, 5.0))

    def test_value_at_interpolates_and_clamps(self):
        self.assertAlmostEqual(h.value_at(self.T, self.V, 0.5), 1.0)
        self.assertEqual(h.value_at(self.T, self.V, -1.0), 0.0)
        self.assertEqual(h.value_at(self.T, self.V, 10.0), 2.0)

    def test_report_exit_code_and_summary(self):
        out = io.StringIO()
        self.assertEqual(h.report([("a", True, "fine")], out), 0)
        self.assertIn("all checks passed", out.getvalue())
        out = io.StringIO()
        self.assertEqual(h.report([("a", True, ""), ("b", False, "bad")], out), 1)
        self.assertIn("FAIL  b", out.getvalue())
        self.assertIn("1 check(s) failed", out.getvalue())


class ParseWrdataTests(unittest.TestCase):
    def test_pairs_of_columns_per_vector(self):
        rows = [" 0.0 1.0 0.0 2.0", "", " 1e-3 1.5 1e-3 2.5"]
        time, values = h.parse_wrdata(rows, 2)
        self.assertEqual(time, [0.0, 1e-3])
        self.assertEqual(values, [[1.0, 1.5], [2.0, 2.5]])

    def test_short_row_is_an_error(self):
        with self.assertRaises(h.NgSpiceError):
            h.parse_wrdata(["0.0 1.0"], 2)


class LibraryCandidateTests(unittest.TestCase):
    def test_env_override_comes_first(self):
        paths = h.library_candidates({"NGSPICE_LIB": "/x/libngspice.dylib"})
        self.assertEqual(paths[0], "/x/libngspice.dylib")
        self.assertEqual(paths[1:], h.LIB_CANDIDATES)

    def test_no_override(self):
        self.assertEqual(h.library_candidates({}), h.LIB_CANDIDATES)


def _ngspice_or_none():
    try:
        return h.NgSpice()
    except h.NgSpiceError:
        return None


SIM = _ngspice_or_none()


@unittest.skipIf(SIM is None, "libngspice not available")
class SimulationTests(unittest.TestCase):
    def test_selftest_rc_matches_analytic(self):
        for label, ok, detail in h.selftest(SIM):
            self.assertTrue(ok, f"{label}: {detail}")

    def test_divider_operating_point(self):
        tr = SIM.run("""* divider
V1 in 0 3.3
R1 in mid 100k
R2 mid 0 200k
.tran 1u 10u
.end
""", ["mid", "in"])
        self.assertAlmostEqual(tr["mid"][-1], 2.2, places=3)
        self.assertAlmostEqual(tr["in"][-1], 3.3, places=3)

    def test_bad_netlist_raises(self):
        with self.assertRaises(h.NgSpiceError):
            SIM.run("* broken\nR1 a\n.tran 1u 10u\n.end\n", ["a"])


if __name__ == "__main__":
    unittest.main()
