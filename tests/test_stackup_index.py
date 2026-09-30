import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import stackup_index as si  # noqa: E402

BUCK = '''// @stackup/power/buck/demo — a demo buck.
use "@stackup/passives"

part demo-buck {
    description "2A buck, SOT-23-5 {braces in a string}"
    order mpn=DEMO123 lcsc=C1
    pin EN input required {
        require net.rest not=float
    }
    package sot23-5 footprint="SOT-23-5" {
        pad EN 1
    }
    package dfn footprint="DFN-6" {
        pad EN 1
    }
    block supply {
        default
        place capacitor Cin value="10µF"
    }
    block ext-clock {
        place capacitor Cx value="1nF"
    }
    block fixed { when "package == dfn"; }
}

// An application block.
block demo-buck-app {
    param inductance inductance default="2.2µH"
    param vout voltage
    place demo-buck as=self
}
'''


def make_lib(root):
    os.makedirs(os.path.join(root, "power", "buck"))
    os.makedirs(os.path.join(root, "examples"))
    open(os.path.join(root, "power", "buck", "demo.kdl"), "w").write(BUCK)
    open(os.path.join(root, "examples", "ex.kdl"), "w").write("part hidden {\n}\n")
    open(os.path.join(root, "manifest.kdl"), "w").write('stackup "0.2"\n')


class ParseTests(unittest.TestCase):
    def test_part_details(self):
        part, block = si.parse_file(BUCK)
        self.assertEqual(part["name"], "demo-buck")
        self.assertEqual(part["packages"], ["sot23-5", "dfn"])
        self.assertEqual(part["mpn"], "DEMO123")
        self.assertIn("{braces in a string}", part["description"])
        feats = {f["name"]: f for f in part["features"]}
        self.assertTrue(feats["supply"]["default"])
        self.assertFalse(feats["ext-clock"]["default"])
        self.assertEqual(feats["fixed"]["when"], "package == dfn")

    def test_block_params(self):
        _, block = si.parse_file(BUCK)
        self.assertEqual(block["kind"], "block")
        self.assertEqual(block["params"], ["inductance=2.2µH", "vout"])

    def test_describe(self):
        part, block = si.parse_file(BUCK)
        text = si.describe(part)
        self.assertIn("packages sot23-5/dfn", text)
        self.assertIn("features supply*, ext-clock", text)
        self.assertNotIn("fixed", text)
        self.assertEqual(si.describe(block), "block demo-buck-app(inductance=2.2µH, vout)")


class IndexTests(unittest.TestCase):
    def test_index_skips_examples_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            make_lib(d)
            rows = si.index(d)
            self.assertEqual([(p, e["name"]) for p, e in rows],
                             [("@stackup/power/buck/demo", "demo-buck"),
                              ("@stackup/power/buck/demo", "demo-buck-app")])

    def test_cache_lookup_from_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            url = "https://github.com/stackup-eda/library"
            rev = "9120a03038a79a3fc05ed309dbb8858c06370739"
            open(os.path.join(d, "manifest.kdl"), "w").write(
                f'stackup "0.2"\nlibrary stackup git="{url}" rev="{rev}"\n')
            sub = os.path.join(d, "PCB", "stackup")
            os.makedirs(sub)
            manifest = si.find_manifest(sub)
            self.assertEqual(manifest, os.path.join(d, "manifest.kdl"))
            self.assertIsNone(si.cached_library(manifest))
            cache = os.path.join(d, ".stackup", "cache", url.encode().hex(), "commits", rev)
            os.makedirs(cache)
            self.assertEqual(si.cached_library(manifest), cache)

    def test_main_filter_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            make_lib(d)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(si.main(["app", "--lib", d]), 0)
            self.assertIn("block demo-buck-app", out.getvalue())
            self.assertNotIn("part demo-buck —", out.getvalue())
            self.assertIn("(1 entries", out.getvalue())
            empty = os.path.join(d, "empty")
            os.makedirs(empty)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(si.main(["--manifest", "/"]), 1)
            self.assertIn("manifest.kdl", err.getvalue())


if __name__ == "__main__":
    unittest.main()
