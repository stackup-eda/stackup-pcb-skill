import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import distributor_stock as d  # noqa: E402

KEYS = {"MOUSER_API_KEY": "mouser-secret-123", "DIGIKEY_CLIENT_ID": "dk-id-456",
        "DIGIKEY_CLIENT_SECRET": "dk-secret-789"}


# Trimmed from real Search API / Product Information v4 responses.
def mouser_response(mpn="TCAN1044AVDRQ1", stock="4714", on_order=None, price="$1.05"):
    return {"Errors": [], "SearchResults": {"NumberOfResult": 1, "Parts": [{
        "ManufacturerPartNumber": mpn, "MouserPartNumber": "595-" + mpn,
        "Manufacturer": "Texas Instruments", "AvailabilityInStock": stock,
        "AvailabilityOnOrder": on_order or [{"Quantity": 37500, "Date": "2026-11-26T00:00:00"}],
        "PriceBreaks": [{"Quantity": 10, "Price": "$0.755", "Currency": "USD"},
                        {"Quantity": 1, "Price": price, "Currency": "USD"}],
        "LeadTime": "140 Days", "LifecycleStatus": None,
        "ProductDetailUrl": "https://www.mouser.com/ProductDetail/x"}]}}


def digikey_response(mpn="TCAN1044AVDRQ1", quantity=None, discontinued=False):
    return {"Product": {
        "ManufacturerProductNumber": mpn, "Manufacturer": {"Id": 296, "Name": "Texas Instruments"},
        "QuantityAvailable": quantity, "UnitPrice": 1.05, "ManufacturerLeadWeeks": "16",
        "ProductStatus": {"Id": 0, "Status": "Active"}, "Discontinued": discontinued, "EndOfLife": False,
        "ProductUrl": "https://www.digikey.com/x",
        "ProductVariations": [
            {"DigiKeyProductNumber": "296-" + mpn + "TR-ND", "PackageType": {"Name": "Tape & Reel (TR)"},
             "QuantityAvailableforPackageType": 0},
            {"DigiKeyProductNumber": "296-" + mpn + "CT-ND", "PackageType": {"Name": "Cut Tape (CT)"},
             "QuantityAvailableforPackageType": 0},
        ]}}


def jlc_listing(code="C3234993", model="TCAN1044AVDRQ1", stock=2060):
    return {"componentCode": code, "componentModelEn": model, "componentBrandEn": "Texas Instruments",
            "componentLibraryType": "expand", "preferredComponentFlag": False, "stockCount": stock,
            "componentSpecificationEn": "SOIC-8"}


# Trimmed from a real wmsc.lcsc.com product-detail response.
def lcsc_response(code="C3234993", model="TCAN1044AVDRQ1", stock=1830, cycle="normal"):
    return {"code": 200, "msg": None, "ok": True, "result": {
        "productCode": code, "productModel": model, "brandNameEn": "TI", "encapStandard": "SOIC-8",
        "minBuyNumber": 5, "stockNumber": stock, "productCycle": cycle,
        "productPriceList": [{"ladder": 50, "usdPrice": 0.61}, {"ladder": 5, "usdPrice": 0.72}]}}


def lcsc_http(responses):
    """A fake LCSC endpoint: {code: response}; unknown codes get LCSC's empty result."""
    calls = []

    def http(url, data=None, headers=None):
        code = url.rsplit("=", 1)[1]
        calls.append(code)
        return responses.get(code, {"code": 200, "msg": None, "ok": True, "result": None})
    http.calls = calls
    return http


class KeyTests(unittest.TestCase):
    def test_parse_key_file(self):
        text = "# comment\n\nexport MOUSER_API_KEY='abc'\nDIGIKEY_CLIENT_ID = \"id\"\nJUNK\n"
        self.assertEqual(d.parse_key_file(text), {"MOUSER_API_KEY": "abc", "DIGIKEY_CLIENT_ID": "id"})

    def test_environment_wins_over_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("MOUSER_API_KEY=from-file\nDIGIKEY_CLIENT_ID=file-id\n")
        try:
            keys = d.load_keys(f.name, environ={"MOUSER_API_KEY": "from-env"})
        finally:
            os.unlink(f.name)
        self.assertEqual(keys, {"MOUSER_API_KEY": "from-env", "DIGIKEY_CLIENT_ID": "file-id"})

    def test_key_file_from_environment_variable(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("DIGIKEY_CLIENT_SECRET=s\n")
        try:
            keys = d.load_keys(environ={"PCB_DESIGN_KEYS": f.name})
        finally:
            os.unlink(f.name)
        self.assertEqual(keys, {"DIGIKEY_CLIENT_SECRET": "s"})

    def test_missing_file_means_no_keys(self):
        self.assertEqual(d.load_keys("/nonexistent/keys.env", environ={}), {})

    def test_redact(self):
        self.assertEqual(d.redact("bad key mouser-secret-123 here", KEYS), "bad key <redacted> here")


class MouserTests(unittest.TestCase):
    def test_parse_exact_listing(self):
        listing = d.mouser_parse(mouser_response(), "tcan1044avdrq1")
        self.assertEqual(listing["sku"], "595-TCAN1044AVDRQ1")
        self.assertEqual(listing["stock"], 4714)
        self.assertEqual(listing["price"], 1.05)  # the quantity-1 break, not the first listed
        self.assertEqual(listing["on_order"], [{"quantity": 37500, "date": "2026-11-26"}])

    def test_other_mpn_is_not_listed(self):
        self.assertIsNone(d.mouser_parse(mouser_response(mpn="TCAN1044VDRQ1"), "TCAN1044AVDRQ1"))

    def test_no_stock_is_zero(self):
        self.assertEqual(d.mouser_parse(mouser_response(stock=None), "TCAN1044AVDRQ1")["stock"], 0)

    def test_price_with_thousands(self):
        self.assertEqual(d.mouser_parse(mouser_response(price="$1,234.50"), "TCAN1044AVDRQ1")["price"], 1234.5)

    def test_fetch_sends_exact_search_and_raises_on_errors(self):
        calls = []

        def http(url, data=None, headers=None):
            calls.append((url, json.loads(data)))
            return {"Errors": [{"Message": "Invalid unique identifier."}]}
        with self.assertRaisesRegex(d.DistributorError, "Invalid unique identifier"):
            d.mouser_fetch("AO3401A", KEYS, http)
        self.assertIn("apiKey=mouser-secret-123", calls[0][0])
        self.assertEqual(calls[0][1]["SearchByPartRequest"],
                         {"mouserPartNumber": "AO3401A", "partSearchOptions": "Exact"})


class DigiKeyTests(unittest.TestCase):
    def test_null_quantity_is_zero_not_an_error(self):
        listing = d.digikey_parse(digikey_response(quantity=None), "TCAN1044AVDRQ1")
        self.assertEqual(listing["stock"], 0)
        self.assertEqual(listing["sku"], "296-TCAN1044AVDRQ1CT-ND")  # cut tape preferred
        self.assertEqual(listing["lead_time"], "16 weeks")
        self.assertEqual(listing["status"], "Active")

    def test_in_stock(self):
        self.assertEqual(d.digikey_parse(digikey_response(quantity=2540), "TCAN1044AVDRQ1")["stock"], 2540)

    def test_discontinued_status(self):
        listing = d.digikey_parse(digikey_response(quantity=5, discontinued=True), "TCAN1044AVDRQ1")
        self.assertEqual(listing["status"], "Discontinued")

    def test_not_found_or_other_mpn(self):
        self.assertIsNone(d.digikey_parse(None, "X"))
        self.assertIsNone(d.digikey_parse(digikey_response(mpn="OTHER"), "TCAN1044AVDRQ1"))

    def test_token_fetched_once_and_refreshed_after_expiry(self):
        now = [1000.0]
        token_calls = []

        def http(url, data=None, headers=None):
            if url == d.DIGIKEY_TOKEN_URL:
                token_calls.append(data)
                return {"access_token": f"tok{len(token_calls)}", "expires_in": 600}
            self.assertEqual(headers["X-DIGIKEY-Client-Id"], "dk-id-456")
            return {"auth": headers["Authorization"]}
        dk = d.DigiKey(KEYS, http=http, clock=lambda: now[0])
        self.assertEqual(dk.fetch("A")["auth"], "Bearer tok1")
        self.assertEqual(dk.fetch("B")["auth"], "Bearer tok1")
        now[0] += 600
        self.assertEqual(dk.fetch("C")["auth"], "Bearer tok2")
        self.assertEqual(len(token_calls), 2)
        self.assertIn(b"grant_type=client_credentials", token_calls[0])

    def test_mpn_is_url_quoted(self):
        urls = []

        def http(url, data=None, headers=None):
            if url == d.DIGIKEY_TOKEN_URL:
                return {"access_token": "t", "expires_in": 600}
            urls.append(url)
            return None
        d.DigiKey(KEYS, http=http).fetch("MMBT3904(RANGE:100-300)/X")
        self.assertIn("MMBT3904%28RANGE%3A100-300%29%2FX", urls[0])


class LcscTests(unittest.TestCase):
    def test_parse_exact_listing(self):
        listing = d.lcsc_parse(lcsc_response()["result"], "tcan1044avdrq1")
        self.assertEqual(listing["sku"], "C3234993")
        self.assertEqual(listing["stock"], 1830)
        self.assertEqual(listing["price"], 0.72)  # the smallest break, not the first listed
        self.assertEqual(listing["min_order"], 5)
        self.assertEqual(listing["status"], "")
        self.assertEqual(listing["url"], "https://www.lcsc.com/product-detail/C3234993.html")

    def test_other_mpn_or_missing_is_not_listed(self):
        self.assertIsNone(d.lcsc_parse(None, "X"))
        self.assertIsNone(d.lcsc_parse(lcsc_response(model="TCAN1044VDRQ1")["result"], "TCAN1044AVDRQ1"))

    def test_no_stock_is_zero_and_lifecycle_is_shown(self):
        listing = d.lcsc_parse(lcsc_response(stock=None, cycle="discontinued")["result"], "TCAN1044AVDRQ1")
        self.assertEqual(listing["stock"], 0)
        self.assertEqual(listing["status"], "discontinued")

    def test_fetch_raises_on_error_code_and_sends_client_name(self):
        seen = []

        def http(url, data=None, headers=None):
            seen.append((url, headers))
            return {"code": 500, "msg": "busy"}
        with self.assertRaisesRegex(d.DistributorError, "LCSC returned code 500: busy"):
            d.lcsc_fetch("C15127", http)
        self.assertTrue(seen[0][0].endswith("productCode=C15127"))
        self.assertIn("pcb-design-skill", seen[0][1]["User-Agent"])

    def test_lookup_picks_most_stock_and_caps_requests(self):
        matches = [{"lcsc": f"C{i}"} for i in range(1, 6)]
        http = lcsc_http({"C1": lcsc_response("C1", stock=10), "C2": lcsc_response("C2", stock=500),
                          "C3": lcsc_response("C3", model="OTHER", stock=9999)})
        listing = d.lcsc_lookup("TCAN1044AVDRQ1", matches, http)
        self.assertEqual(listing["sku"], "C2")
        self.assertEqual(http.calls, ["C1", "C2", "C3"])

    def test_lookup_with_no_lcsc_numbers_is_not_listed(self):
        http = lcsc_http({})
        self.assertIsNone(d.lcsc_lookup("X", [], http))
        self.assertEqual(http.calls, [])


class BatchTests(unittest.TestCase):
    def fake_digikey(self, quantity=None, error=None):
        dk = mock.Mock()
        if error:
            dk.fetch.side_effect = d.DistributorError(error)
        else:
            dk.fetch.side_effect = lambda mpn: digikey_response(mpn, quantity)
        return dk

    def test_all_sources(self):
        searches = []

        def jlc_search(mpn):
            searches.append(mpn)
            return [jlc_listing()]
        results = d.lookup_all(["TCAN1044AVDRQ1"], KEYS, delay=0,
                               mouser_http=lambda url, data=None, headers=None: mouser_response(),
                               digikey=self.fake_digikey(), jlc_search=jlc_search,
                               lcsc_http=lcsc_http({"C3234993": lcsc_response()}))
        row = results["TCAN1044AVDRQ1"]
        self.assertEqual(list(row), ["mouser", "digikey", "lcsc", "jlc"])
        self.assertEqual(row["jlc"]["sku"], "C3234993")
        self.assertEqual(row["jlc"]["stock"], 2060)  # JLCPCB's assembly stock...
        self.assertEqual(row["lcsc"]["stock"], 1830)  # ...is not LCSC's store stock
        self.assertEqual(row["mouser"]["stock"], 4714)
        self.assertEqual(row["digikey"]["stock"], 0)
        self.assertEqual(searches, ["TCAN1044AVDRQ1"])  # one JLCPCB search serves both columns

    def test_lcsc_works_without_any_keys(self):
        results = d.lookup_all(["TCAN1044AVDRQ1"], {}, delay=0, jlc_search=lambda mpn: [jlc_listing()],
                               lcsc_http=lcsc_http({"C3234993": lcsc_response()}))
        row = results["TCAN1044AVDRQ1"]
        self.assertEqual(row["mouser"], {"skipped": "no key"})
        self.assertEqual(row["digikey"], {"skipped": "no key"})
        self.assertEqual(row["lcsc"]["stock"], 1830)
        self.assertEqual(row["jlc"]["stock"], 2060)

    def test_failed_jlc_search_fails_lcsc_too_without_stopping_others(self):
        def jlc_search(mpn):
            raise RuntimeError("JLC search returned code 500: down")
        results = d.lookup_all(["X"], {"MOUSER_API_KEY": "k"}, sources=("mouser", "lcsc", "jlc"), delay=0,
                               mouser_http=lambda url, data=None, headers=None: mouser_response(mpn="X"),
                               jlc_search=jlc_search, lcsc_http=lcsc_http({}))
        self.assertEqual(results["X"]["mouser"]["stock"], 4714)
        self.assertIn("error", results["X"]["lcsc"])
        self.assertIn("error", results["X"]["jlc"])

    def test_missing_keys_are_skipped_not_failed(self):
        results = d.lookup_all(["X"], {}, sources=("mouser", "digikey"), delay=0)
        self.assertEqual(results["X"], {"mouser": {"skipped": "no key"}, "digikey": {"skipped": "no key"}})

    def test_errors_are_redacted_and_do_not_stop_other_sources(self):
        def http(url, data=None, headers=None):
            raise d.DistributorError("rejected key mouser-secret-123")
        results = d.lookup_all(["X"], KEYS, sources=("mouser", "digikey"), delay=0, mouser_http=http,
                               digikey=self.fake_digikey(quantity=3))
        self.assertEqual(results["X"]["mouser"], {"error": "rejected key <redacted>"})
        self.assertEqual(results["X"]["digikey"]["stock"], 3)

    def test_format_table(self):
        results = d.lookup_all(["TCAN1044AVDRQ1", "NOPE"], KEYS, delay=0,
                               mouser_http=lambda url, data=None, headers=None:
                                   mouser_response() if "TCAN" in json.loads(data)["SearchByPartRequest"]["mouserPartNumber"] else {"Errors": [], "SearchResults": {"Parts": []}},
                               digikey=self.fake_digikey(quantity=2540),
                               jlc_search=lambda mpn: [jlc_listing()] if mpn.startswith("TCAN") else [],
                               lcsc_http=lcsc_http({"C3234993": lcsc_response()}))
        results["NOPE"]["digikey"] = None
        lines = d.format_table(results).splitlines()
        self.assertEqual(lines[0].split()[:5], ["MPN", "Mouser", "DigiKey", "LCSC", "JLCPCB"])
        self.assertIn("C3234993 2,060 (Extended)", lines[1])
        self.assertIn("4,714 @ $1.05", lines[1])
        self.assertIn("2,540 @ $1.05", lines[1])
        self.assertIn("1,830 @ $0.72", lines[1])
        self.assertIn("Mouser 37,500 on order 2026-11-26", lines[1])
        self.assertEqual(lines[2].split()[1:], ["not", "listed"] * 4)
        self.assertEqual(lines[2], lines[2].rstrip())


class MainTests(unittest.TestCase):
    def run_main(self, argv, results):
        out = io.StringIO()
        with mock.patch.object(d, "load_keys", return_value={}), \
                mock.patch.object(d, "lookup_all", return_value=results) as lookup, \
                contextlib.redirect_stdout(out):
            code = d.main(argv)
        return code, lookup, out.getvalue()

    def test_json_and_sources(self):
        code, lookup, out = self.run_main(["A", "--json", "--sources", "mouser,digikey"],
                                          {"A": {"mouser": None, "digikey": None}})
        self.assertEqual(code, 0)
        self.assertEqual(lookup.call_args.kwargs["sources"], ("mouser", "digikey"))
        self.assertEqual(json.loads(out), {"A": {"mouser": None, "digikey": None}})

    def test_failure_exit_code(self):
        code, _, out = self.run_main(["A"], {"A": {"jlc": {"error": "down"}, "mouser": None, "digikey": None}})
        self.assertEqual(code, 1)
        self.assertIn("failed: down", out)

    def test_unknown_source_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            d.main(["A", "--sources", "octopart"])


if __name__ == "__main__":
    unittest.main()
