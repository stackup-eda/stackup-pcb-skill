import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import jlc_parts as j  # noqa: E402


def listing(code, model, brand, library="expand", preferred=False, stock=0, package="SOT-23"):
    return {
        "componentCode": code, "componentModelEn": model, "componentBrandEn": brand,
        "componentLibraryType": library, "preferredComponentFlag": preferred,
        "stockCount": stock, "componentSpecificationEn": package,
    }


class TierTests(unittest.TestCase):
    def test_base_is_basic(self):
        self.assertEqual(j.tier(listing("C1", "X", "A", library="base")), j.BASIC)

    def test_preferred_extended(self):
        self.assertEqual(j.tier(listing("C1", "X", "A", preferred=True)), j.PREFERRED)

    def test_plain_extended(self):
        self.assertEqual(j.tier(listing("C1", "X", "A")), j.EXTENDED)

    def test_missing_fields_default_to_extended(self):
        self.assertEqual(j.tier({}), j.EXTENDED)


class SelectTests(unittest.TestCase):
    FOUND = [
        listing("C3", "AO3401A", "UMW", stock=600000),
        listing("C2", "AO3401A", "BORN", preferred=True, stock=50),
        listing("C1", "AO3401A", "Alpha & Omega Semicon", library="base", stock=800000),
        listing("C9", "AO3401A", "JLCPCB Assembly", library="base", stock=0),
        listing("C4", "AO3401AL", "Other", stock=10**7),
    ]

    def test_sorted_by_tier_then_stock_and_placeholder_dropped(self):
        codes = [p["lcsc"] for p in j.select(self.FOUND)]
        self.assertEqual(codes, ["C1", "C2", "C4", "C3"])

    def test_exact_mpn_ignores_punctuation_and_case(self):
        codes = [p["lcsc"] for p in j.select(self.FOUND, mpn="ao3401-a")]
        self.assertEqual(codes, ["C1", "C2", "C3"])

    def test_basic_only(self):
        codes = [p["lcsc"] for p in j.select(self.FOUND, basic_only=True)]
        self.assertEqual(codes, ["C1"])

    def test_summary_stock_is_int(self):
        part = j.summarize({"stockCount": None})
        self.assertEqual(part["stock"], 0)


class FormatTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(j.format_table([]), "no matching listings")

    def test_row_contents(self):
        table = j.format_table(j.select([listing("C15127", "AO3401A", "AOS", library="base", stock=5)]))
        self.assertIn("C15127", table)
        self.assertIn("Basic", table)
        self.assertIn("AO3401A", table)


class MainTests(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with mock.patch.object(j, "search", return_value=[
                listing("C1", "AO3401A", "AOS", library="base", stock=5)]) as search, \
                contextlib.redirect_stdout(out):
            code = j.main(argv)
        return code, search, out.getvalue()

    def test_default_page_size(self):
        code, search, out = self.run_main(["AO3401A"])
        self.assertEqual(code, 0)
        search.assert_called_once_with("AO3401A", page_size=50)
        self.assertIn("C1", out)

    def test_page_size_flag(self):
        _, search, _ = self.run_main(["AO3401A", "--page-size", "100"])
        search.assert_called_once_with("AO3401A", page_size=100)

    def test_lookup_failure_returns_1(self):
        out = io.StringIO()
        with mock.patch.object(j, "search", side_effect=RuntimeError("down")), \
                contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
            self.assertEqual(j.main(["X"]), 1)
        self.assertIn("lookup failed: down", out.getvalue())


class BatchTests(unittest.TestCase):
    FOUND = {
        "AO3400A": [listing("C20917", "AO3400A", "AOS", library="base", stock=9),
                    listing("C2", "AO3400A", "UMW", stock=5)],
        "NOPE": [],
    }

    def fake_search(self, query, page_size=50):
        if query == "BROKEN":
            raise RuntimeError("JLC search returned code 500")
        return self.FOUND.get(query, [])

    def test_lookup_all_keeps_order_and_errors(self):
        results = j.lookup_all(["AO3400A", "NOPE", "BROKEN"], exact=True, delay=0,
                               search_fn=self.fake_search)
        self.assertEqual([q for q, _, _ in results], ["AO3400A", "NOPE", "BROKEN"])
        self.assertEqual(results[0][1][0]["lcsc"], "C20917")
        self.assertEqual(results[1][1], [])
        self.assertIn("500", results[2][2])

    def test_format_best(self):
        text = j.format_best(j.lookup_all(["AO3400A", "NOPE", "BROKEN"], delay=0,
                                          search_fn=self.fake_search))
        lines = text.splitlines()
        self.assertIn("C20917", lines[1])
        self.assertIn("(+1 more)", lines[1])
        self.assertIn("no matching listings", lines[2])
        self.assertIn("lookup failed", lines[3])

    def test_main_multiple_best_and_json(self):
        with mock.patch.object(j, "search", side_effect=self.fake_search):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = j.main(["AO3400A", "NOPE", "--best", "--delay", "0"])
            self.assertEqual(code, 0)
            self.assertIn("C20917", out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = j.main(["AO3400A", "BROKEN", "--json", "--delay", "0"])
            self.assertEqual(code, 1)
            data = json.loads(out.getvalue())
            self.assertEqual(data["AO3400A"][0]["lcsc"], "C20917")
            self.assertIn("error", data["BROKEN"])

    def test_main_multiple_sections(self):
        with mock.patch.object(j, "search", side_effect=self.fake_search):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = j.main(["AO3400A", "BROKEN", "--delay", "0"])
        self.assertEqual(code, 1)
        self.assertIn("== AO3400A", out.getvalue())
        self.assertIn("lookup failed", out.getvalue())


if __name__ == "__main__":
    unittest.main()
