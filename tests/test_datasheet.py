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


class BatchTests(unittest.TestCase):
    def test_fetch_targets(self):
        self.assertEqual(ds.fetch_targets(["https://x/a.pdf"], name="A"), [("A", "https://x/a.pdf")])
        self.assertEqual(ds.fetch_targets(["A=https://x/a.pdf", "B=http://y/b.pdf"]),
                         [("A", "https://x/a.pdf"), ("B", "http://y/b.pdf")])
        with self.assertRaises(ValueError):
            ds.fetch_targets(["https://x/a.pdf", "https://x/b.pdf"], name="A")
        with self.assertRaises(ValueError):
            ds.fetch_targets(["no-equals"])
        with self.assertRaises(ValueError):
            ds.fetch_targets(["A=ftp://x"])

    def test_resolve_names(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ("B.pdf", "B.txt", "A.txt", ".hidden.txt", "manifest.json"):
                open(os.path.join(d, f), "w").close()
            self.assertEqual(ds.resolve_names("all", d), ["A", "B"])
            self.assertEqual(ds.resolve_names("A, B", d), ["A", "B"])
            empty = os.path.join(d, "empty")
            os.makedirs(empty)
            with self.assertRaises(FileNotFoundError):
                ds.resolve_names("all", empty)

    def test_grep_all_skips_unreadable_and_labels_hits(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "X.txt"), "w").write(TEXT)
            open(os.path.join(d, "Y.txt"), "w").write("Electrical Characteristics\nVIH EN high 1.1 V\n")
            open(os.path.join(d, "BAD.pdf"), "wb").write(b"not a pdf")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ds.main(["--dir", d, "grep", "all", "EN high"])
            self.assertEqual(code, 0)
            self.assertIn("--- X page 4", out.getvalue())
            self.assertIn("--- Y page 1", out.getvalue())
            self.assertIn("BAD: skipped", err.getvalue())

    def test_fetch_reports_each_failure(self):
        with tempfile.TemporaryDirectory() as d:
            def fail(url, dest):
                raise RuntimeError(f"{url} did not return a PDF")
            original = ds.download
            ds.download = fail
            try:
                err = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    code = ds.main(["--dir", d, "fetch", "A=https://x/a", "B=https://x/b"])
            finally:
                ds.download = original
            self.assertEqual(code, 1)
            self.assertIn("A: failed", err.getvalue())
            self.assertIn("B: failed", err.getvalue())


GUIDE_HTML = b"""<!DOCTYPE html><html><head><title>Guide</title><style>p {color: red}</style>
<script>var x = "RC delay in a script";</script></head>
<body><nav>Home | Next</nav><h2>Chip Power-up and Reset Timing</h2>
<p>The recommended setting for the RC delay circuit is usually R = 10&nbsp;k&Omega; and C = 1 &mu;F.</p>
<table><tr><th>Parameter</th><th>Min</th></tr><tr><td>t<sub>STBL</sub></td><td>50 &mu;s</td></tr></table>
</body></html>"""


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(body):
    """Stand-in for urllib.request.urlopen that returns `body`."""
    return lambda request, timeout=None: _Response(body)


class HtmlTests(unittest.TestCase):
    def setUp(self):
        self.original = ds.urllib.request.urlopen

    def tearDown(self):
        ds.urllib.request.urlopen = self.original

    def test_html_to_text_keeps_content_and_drops_scripts(self):
        text = ds.html_to_text(GUIDE_HTML.decode())
        self.assertIn("R = 10 kΩ and C = 1 μF.", text)
        self.assertIn("Chip Power-up and Reset Timing", text)
        self.assertIn("tSTBL", text)
        self.assertNotIn("in a script", text)
        self.assertNotIn("color: red", text)
        self.assertNotIn("Home | Next", text)

    def test_looks_like_html(self):
        self.assertTrue(ds.looks_like_html(b"  <!doctype html><html>"))
        self.assertTrue(ds.looks_like_html(b'<?xml version="1.0"?><html xmlns="x">'))
        self.assertFalse(ds.looks_like_html(b"%PDF-1.4"))
        self.assertFalse(ds.looks_like_html(b"\x89PNG"))

    def test_download_kinds(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "A.pdf")
            ds.urllib.request.urlopen = _serve(b"%PDF-1.4 body")
            self.assertEqual(ds.download("https://x/a.pdf", dest), "pdf")
            self.assertTrue(os.path.exists(dest))
            dest = os.path.join(d, "B.pdf")
            ds.urllib.request.urlopen = _serve(GUIDE_HTML)
            self.assertEqual(ds.download("https://x/guide", dest), "html")
            self.assertFalse(os.path.exists(dest))
            self.assertTrue(os.path.exists(os.path.join(d, "B.html")))
            self.assertIn("RC delay", open(os.path.join(d, "B.txt")).read())
            ds.urllib.request.urlopen = _serve(b"\x89PNG image")
            with self.assertRaises(RuntimeError):
                ds.download("https://x/c.png", os.path.join(d, "C.pdf"))

    def test_fetch_html_then_grep_with_dir_after_command(self):
        with tempfile.TemporaryDirectory() as d:
            ds.urllib.request.urlopen = _serve(GUIDE_HTML)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ds.main(["fetch", "HW=https://x/guide", "--dir", d]), 0)
            self.assertIn("from an HTML page, not a PDF", out.getvalue())
            manifest = json.load(open(os.path.join(d, "manifest.json")))
            self.assertEqual(manifest["HW"]["file"], "HW.html")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ds.main(["grep", "HW", "RC delay", "--dir", d]), 0)
            self.assertIn("--- page 1", out.getvalue())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(ds.main(["page", "HW", "1", "--dir", d]), 1)
            self.assertIn("HTML page", err.getvalue())

    def test_dir_before_command_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "X.txt"), "w").write(TEXT)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(ds.main(["--dir", d, "grep", "X", "EN high"]), 0)
            self.assertIn("page 4", out.getvalue())


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
