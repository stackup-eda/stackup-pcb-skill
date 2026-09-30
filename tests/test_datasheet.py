import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pcb-design", "scripts"))

import datasheet as ds  # noqa: E402

TEXT = "\f".join([
    "Contents\nPin Configuration 3\nAbsolute Maximum Ratings 3\nRecommended Operating Conditions 3\n"
    "Electrical Characteristics 4\nPackage Outline 9\nLand Pattern 10\n",
    "Title page\nFeatures\n",
    "Pin Configuration and Functions\nEN  1  Enable input. Do not leave floating.\n"
    "Absolute Maximum Ratings\nVIN -0.3 6 V\n",
    "Electrical Characteristics\nVIH EN high threshold 0.95 1.2 V\nVIL EN low threshold 0.4 V\n",
    "Package Outline\n",
    "Land Pattern\n",
]) + "\f"


class PageTests(unittest.TestCase):
    def test_pages_split_on_form_feed(self):
        pages = ds.pages_of(TEXT)
        self.assertEqual(len(pages), 6)
        self.assertTrue(pages[3].startswith("Electrical"))

    def test_sections_skip_contents_page(self):
        found = ds.find_sections(ds.pages_of(TEXT))
        self.assertEqual(found["contents"], [1])
        self.assertEqual(found["pin configuration"], [3])
        self.assertEqual(found["electrical characteristics"], [4])
        self.assertEqual(found["package / outline"], [5])
        self.assertEqual(found["land pattern"], [6])

    def test_contents_page_kept_when_only_hit(self):
        pages = ds.pages_of("Pin Configuration\nAbsolute Maximum\nRecommended Operating\n"
                            "Electrical Characteristics\nOrdering Information\n")
        self.assertEqual(ds.find_sections(pages)["ordering"], [1])

    def test_grep_with_context_and_pages(self):
        hits = ds.grep(ds.pages_of(TEXT), r"EN (high|low)", context=1)
        self.assertEqual([(p, n) for p, n, _ in hits], [(4, 2), (4, 3)])
        self.assertIn("Electrical Characteristics", hits[0][2][0])
        self.assertEqual(ds.grep(ds.pages_of(TEXT), "nothing here"), [])


class ManifestTests(unittest.TestCase):
    def test_update_manifest_records_hash_and_keeps_others(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "A.pdf")
            open(pdf, "wb").write(b"%PDF-1.4 test")
            manifest = os.path.join(d, "manifest.json")
            json.dump({"B": {"url": "x"}}, open(manifest, "w"))
            entry = ds.update_manifest(manifest, "A", "https://example.com/a.pdf", pdf)
            self.assertEqual(len(entry["sha256"]), 64)
            data = json.load(open(manifest))
            self.assertEqual(set(data), {"A", "B"})
            self.assertEqual(data["A"]["url"], "https://example.com/a.pdf")


class LoadTests(unittest.TestCase):
    def test_missing_pdf_message(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError) as e:
                ds.load_pages("NOPE", d)
            self.assertIn("datasheet.py fetch", str(e.exception))

    def test_uses_existing_text(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "X.txt"), "w").write(TEXT)
            self.assertEqual(len(ds.load_pages("X", d)), 6)

    def test_main_grep_and_sections(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "X.txt"), "w").write(TEXT)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ds.main(["--dir", d, "grep", "X", "floating"]), 0)
                self.assertEqual(ds.main(["--dir", d, "grep", "X", "zzz"]), 1)
                self.assertEqual(ds.main(["--dir", d, "sections", "X"]), 0)
            self.assertIn("--- page 3", out.getvalue())
            self.assertIn("land pattern: pages 6", out.getvalue())


@unittest.skipUnless(shutil.which("pdftotext") and shutil.which("pdftoppm"), "poppler not installed")
class PopplerTests(unittest.TestCase):
    """Round-trip a real (generated) PDF through extract_text and the page renderer."""

    def test_extract_and_render(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = os.path.join(d, "T.pdf")
            with open(pdf, "wb") as f:
                f.write(MINIMAL_PDF)
            txt = os.path.join(d, "T.txt")
            ds.extract_text(pdf, txt)
            self.assertIn("Electrical Characteristics", open(txt).read())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(ds.main(["--dir", d, "page", "T", "1", "--dpi", "30"]), 0)
            self.assertTrue(os.path.exists(out.getvalue().strip()))


def _pdf(text):
    """Build a one-page PDF containing `text` (Helvetica), with a correct xref table."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


MINIMAL_PDF = _pdf("Electrical Characteristics")


if __name__ == "__main__":
    unittest.main()
