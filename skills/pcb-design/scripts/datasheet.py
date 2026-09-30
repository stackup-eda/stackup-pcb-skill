#!/usr/bin/env python3
"""Fetch a manufacturer datasheet once, then read it as text and look at only the pages you need.

Reading a datasheet page as an image costs far more than reading its text. Use text for tables
(thresholds, ratings, pin tables) and render a page only for drawings (pinout, package outline,
land pattern).

    datasheet.py fetch <url> --name AO3400A [--dir PCB/datasheets]   # PDF + text + manifest entry
    datasheet.py sections AO3400A                   # which pages hold pinout, ratings, package...
    datasheet.py grep AO3400A "V.?GS\\(th\\)|Gate Threshold" [-C 1]  # matching lines, with page numbers
    datasheet.py page AO3400A 1 [--dpi 90]          # render one page to PNG for a drawing

Files live in --dir (default PCB/datasheets): <name>.pdf, <name>.txt (pages split by form feeds),
and manifest.json with the source URL, date and SHA-256, so a later review reads the same revision.
Needs poppler's pdftotext/pdftoppm (macOS: brew install poppler; Debian: apt install poppler-utils).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

DEFAULT_DIR = "PCB/datasheets"
USER_AGENT = "Mozilla/5.0 (compatible; pcb-design-skill/1.0)"

# Headings worth finding. Each maps a label to a pattern matched against a page's text.
SECTIONS = {
    "pin configuration": r"pin (configuration|assignment|description|functions?|out)|pinout|terminal functions",
    "absolute maximum": r"absolute maximum",
    "recommended operating": r"recommended operating",
    "electrical characteristics": r"electrical characteristics",
    "typical characteristics": r"typical (performance )?characteristics",
    "application / layout": r"layout (guidelines|example|recommendations)|application information",
    "package / outline": r"package (outline|dimensions|information|drawing)|mechanical data|outline dimensions",
    "land pattern": r"land pattern|recommended (footprint|pad|solder pad)|pcb layout pattern",
    "ordering": r"ordering information|order(ing)? codes?|part number(ing)? (system|guide)",
}


def paths(name, directory):
    base = os.path.join(directory, name)
    return base + ".pdf", base + ".txt", os.path.join(directory, "manifest.json")


def require(tool):
    if not shutil.which(tool):
        raise RuntimeError(f"{tool} not found; install poppler (brew install poppler / "
                           "apt install poppler-utils)")


def extract_text(pdf, txt):
    require("pdftotext")
    subprocess.run(["pdftotext", "-layout", pdf, txt], check=True, capture_output=True)


def pages_of(text):
    """Split pdftotext output into pages (form-feed separated); page numbers start at 1."""
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


CONTENTS_THRESHOLD = 5  # a page naming this many sections is a table of contents, not content


def find_sections(pages):
    """{label: [page numbers]} for the headings in SECTIONS. A contents page (one that names most
    sections) is left out of a label's pages unless it is the only hit, and reported as "contents"."""
    raw = {label: [i + 1 for i, page in enumerate(pages) if re.search(pattern, page, re.IGNORECASE)]
           for label, pattern in SECTIONS.items()}
    per_page = {}
    for hits in raw.values():
        for p in hits:
            per_page[p] = per_page.get(p, 0) + 1
    contents = sorted(p for p, n in per_page.items() if n >= CONTENTS_THRESHOLD)
    found = {"contents": contents} if contents else {}
    for label, hits in raw.items():
        kept = [p for p in hits if p not in contents] or hits
        if kept:
            found[label] = kept
    return found


def grep(pages, pattern, context=0):
    """[(page, line_number, [lines])] for lines matching `pattern`, with `context` lines around."""
    rx = re.compile(pattern, re.IGNORECASE)
    results = []
    for p, page in enumerate(pages, 1):
        lines = page.splitlines()
        for i, line in enumerate(lines):
            if rx.search(line):
                lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                results.append((p, i + 1, lines[lo:hi]))
    return results


def update_manifest(manifest, name, url, pdf):
    data = {}
    if os.path.exists(manifest):
        with open(manifest) as f:
            data = json.load(f)
    with open(pdf, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    data[name] = {"url": url, "file": os.path.basename(pdf), "sha256": digest,
                  "fetched": datetime.date.today().isoformat()}
    with open(manifest, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return data[name]


def download(url, dest):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"{url} did not return a PDF (got {body[:40]!r}); find the direct PDF link")
    with open(dest, "wb") as f:
        f.write(body)


def load_pages(name, directory):
    pdf, txt, _ = paths(name, directory)
    if not os.path.exists(txt):
        if not os.path.exists(pdf):
            raise FileNotFoundError(f"no {pdf}; run: datasheet.py fetch <url> --name {name}")
        extract_text(pdf, txt)
    with open(txt, errors="replace") as f:
        return pages_of(f.read())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=DEFAULT_DIR, help=f"datasheet folder (default {DEFAULT_DIR})")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download a PDF, extract its text, record it in the manifest")
    f.add_argument("url")
    f.add_argument("--name", required=True, help="short file name, e.g. the MPN")
    s = sub.add_parser("sections", help="list the pages holding the usual datasheet sections")
    s.add_argument("name")
    g = sub.add_parser("grep", help="print matching lines with page numbers")
    g.add_argument("name")
    g.add_argument("pattern")
    g.add_argument("-C", "--context", type=int, default=0)
    p = sub.add_parser("page", help="render one page to PNG (for drawings only)")
    p.add_argument("name")
    p.add_argument("number", type=int)
    p.add_argument("--dpi", type=int, default=90)
    args = parser.parse_args(argv)

    try:
        if args.command == "fetch":
            os.makedirs(args.dir, exist_ok=True)
            pdf, txt, manifest = paths(args.name, args.dir)
            download(args.url, pdf)
            extract_text(pdf, txt)
            entry = update_manifest(manifest, args.name, args.url, pdf)
            with open(txt, errors="replace") as fh:
                count = len(pages_of(fh.read()))
            print(f"saved {pdf} ({count} pages), {txt}; sha256 {entry['sha256'][:12]}")
            for label, hits in find_sections(load_pages(args.name, args.dir)).items():
                print(f"  {label}: pages {', '.join(map(str, hits))}")
        elif args.command == "sections":
            pages = load_pages(args.name, args.dir)
            print(f"{args.name}: {len(pages)} pages")
            for label, hits in find_sections(pages).items():
                print(f"  {label}: pages {', '.join(map(str, hits))}")
        elif args.command == "grep":
            hits = grep(load_pages(args.name, args.dir), args.pattern, args.context)
            for page, line, lines in hits:
                print(f"--- page {page}, line {line}")
                print("\n".join(lines))
            if not hits:
                print("no matches")
                return 1
        elif args.command == "page":
            require("pdftoppm")
            pdf, _, _ = paths(args.name, args.dir)
            out = os.path.join(args.dir, f"{args.name}-p{args.number}")
            subprocess.run(["pdftoppm", "-png", "-r", str(args.dpi), "-f", str(args.number),
                            "-l", str(args.number), "-singlefile", pdf, out],
                           check=True, capture_output=True)
            print(out + ".png")
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
