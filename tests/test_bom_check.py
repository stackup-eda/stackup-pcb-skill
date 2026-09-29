import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import bom_check as b  # noqa: E402

HEADER = "Refs,Quantity,Value,Footprint,MF,MPN,LCSC,Mouser,DigiKey,Hand,DNP\n"
GOOD = ('"R1,R2","2","100kΩ","Resistor_SMD:R_0402_1005Metric","UNI-ROYAL","0402WGF1003TCE",'
        '"C25741","","","",""\n')


def rows(*lines):
    return b.read_csv(HEADER + "".join(lines))


class CheckTests(unittest.TestCase):
    def test_clean_line(self):
        self.assertEqual(b.check_rows(rows(GOOD), fab="jlc"), [])

    def test_blank_fields(self):
        problems = b.check_rows(rows('"C1","1","","Capacitor_SMD:C_0402_1005Metric","","","","","","",""\n'))
        self.assertEqual([p for _, p in problems], ["blank value", "blank manufacturer", "blank MPN"])

    def test_jlc_requires_lcsc_except_hand_and_dnp(self):
        line = '"{r}","1","10µF","Capacitor_SMD:C_0805_2012Metric","Samsung","CL21A106KAYNNNE","","","","{h}","{d}"\n'
        self.assertEqual(b.check_rows(rows(line.format(r="C1", h="", d="")), fab="jlc"),
                         [("C1", "no LCSC number (JLCPCB assembly matches on it)")])
        self.assertEqual(b.check_rows(rows(line.format(r="C2", h="Yes", d="Yes")), fab="jlc"), [])
        self.assertEqual(b.check_rows(rows(line.format(r="C3", h="", d="")), fab=None), [])

    def test_allow_no_mpn_only_for_listed_refs(self):
        line = '"J1","1","Thumbstick","Custom:Stick_0603","","","","","","Yes","Yes"\n'
        self.assertEqual(b.check_rows(rows(line), allow_no_mpn=["J1"]), [])
        self.assertEqual(len(b.check_rows(rows(line), allow_no_mpn=["J2"])), 2)

    def test_package_evident_from_footprint_value_or_part_specific_name(self):
        vague = '"U1","1","Widget","Custom:Thing","Acme","WX-1","","","","",""\n'
        self.assertIn("package not evident", b.check_rows(rows(vague))[0][1])
        named = '"L1","1","2.2µH","Inductor_SMD:L_Bourns-SRN4018","Bourns","SRN4018-2R2M","","","","",""\n'
        self.assertEqual(b.check_rows(rows(named)), [])
        module = '"U2","1","ESP32","Espressif:ESP32-S3-WROOM-1","Espressif","ESP32-S3-WROOM-1-N8","","","","",""\n'
        self.assertEqual(b.check_rows(rows(module)), [])
        in_value = '"U3","1","Widget SOT-23","Custom:Thing","Acme","WX-1","","","","",""\n'
        self.assertEqual(b.check_rows(rows(in_value)), [])

    def test_long_values(self):
        short = b.check_rows(rows(GOOD), long_values=True)
        self.assertEqual(short, [("R1,R2", "value '100kΩ' does not contain the MPN '0402WGF1003TCE'")])
        good = '"R1","1","100kΩ | 0402WGF1003TCE | UNI-ROYAL | 0402","Resistor_SMD:R_0402_1005Metric","UNI-ROYAL","0402WGF1003TCE","","","","",""\n'
        self.assertEqual(b.check_rows(rows(good), long_values=True), [])

    def test_value_with_comma(self):
        line = '"R1","1","10k, 1%","Resistor_SMD:R_0402_1005Metric","Yageo","RC0402FR-0710KL","","","","",""\n'
        self.assertIn("forces CSV quoting", b.check_rows(rows(line))[0][1])

    def test_footprint_names_part(self):
        self.assertTrue(b.footprint_names_part("Xbee3:XB324Z8UTJ", "XB3-24Z8UT-J"))
        self.assertTrue(b.footprint_names_part("Button_Switch_SMD:SW_SPST_EVQP2_ShortPushTravel", "EVQP2T02M"))
        self.assertFalse(b.footprint_names_part("Custom:GuliKit_HallStick", ""))
        self.assertFalse(b.footprint_names_part("Custom:Thing", "WX-1"))


class ReadTests(unittest.TestCase):
    def test_missing_columns_and_empty(self):
        with self.assertRaises(ValueError):
            b.read_csv("Refs,Value\nR1,1k\n")
        with self.assertRaises(ValueError):
            b.read_csv(HEADER)


class MainTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = b.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_file_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.csv")
            open(good, "w").write(HEADER + GOOD)
            code, out, _ = self.run_main([good, "--fab", "jlc"])
            self.assertEqual(code, 0)
            self.assertIn("1 lines, 0 problem(s)", out)
            bad = os.path.join(d, "bad.csv")
            open(bad, "w").write(HEADER + '"C1","1","","X_0402","","","","","","",""\n')
            code, out, _ = self.run_main([bad])
            self.assertEqual(code, 1)
            code, _, err = self.run_main([os.path.join(d, "missing.csv")])
            self.assertEqual(code, 1)
            self.assertIn("error", err)

    def test_stackup_failure_is_reported(self):
        with mock_env("STACKUP_BIN", "/nonexistent/stackup"):
            code, _, err = self.run_main(["--stackup", "board.kdl"])
        self.assertEqual(code, 1)
        self.assertIn("error", err)


@contextlib.contextmanager
def mock_env(key, value):
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            del os.environ[key]
        else:
            os.environ[key] = old


if __name__ == "__main__":
    unittest.main()
