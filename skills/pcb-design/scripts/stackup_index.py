#!/usr/bin/env python3
"""List what a Stackup parts library offers: each part (with its packages, orderable MPN and
optional features) and each application block (with its parameters and defaults).

Use it instead of reading library files one by one to find the right part or block.

    stackup_index.py                          # library pinned by ./manifest.kdl (or a parent's)
    stackup_index.py buck                     # only entries whose path, name or description match
    stackup_index.py --lib ../stackup-library # a local library checkout
    stackup_index.py --manifest PCB/stackup   # find manifest.kdl from this directory upward

The pinned library comes from Stackup's download cache (.stackup/cache next to the manifest). If
it isn't there yet, run `stackup check` on the design once.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

LIB_DECL = re.compile(r'library\s+(\S+)\s+git="([^"]+)"\s+rev="([0-9a-f]+)"')
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')


def find_manifest(start):
    d = os.path.abspath(start)
    while True:
        path = os.path.join(d, "manifest.kdl")
        if os.path.isfile(path):
            return path
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def cached_library(manifest, name="stackup"):
    """Path of the pinned library in Stackup's cache next to `manifest`, or None."""
    with open(manifest) as f:
        text = f.read()
    for lib, url, rev in LIB_DECL.findall(text):
        if lib != name:
            continue
        cache = os.path.join(os.path.dirname(manifest), ".stackup", "cache",
                             url.encode().hex(), "commits", rev)
        return cache if os.path.isdir(cache) else None
    return None


def braces(line):
    """Net brace depth change of a line, ignoring braces inside strings and // comments."""
    code = QUOTED.sub('""', line.split("//")[0])
    return code.count("{") - code.count("}")


def first_string(line):
    m = QUOTED.search(line)
    return m.group(0)[1:-1] if m else ""


def parse_file(text):
    """Top-level parts and blocks in one library file."""
    entries, current, depth, feature = [], None, 0, None
    for raw in text.splitlines():
        line = raw.strip()
        if depth == 0:
            m = re.match(r"(part|block)\s+(\S+)\s*\{", line)
            if m:
                current = {"kind": m.group(1), "name": m.group(2), "description": "",
                           "packages": [], "mpn": "", "params": [], "features": []}
                entries.append(current)
        elif current is not None:
            if depth == 1:
                if line.startswith("description "):
                    current["description"] = first_string(line)
                elif line.startswith("package "):
                    current["packages"].append(line.split()[1])
                elif line.startswith("order ") and "mpn=" in line:
                    current["mpn"] = re.search(r"mpn=(\"[^\"]*\"|\S+)", line).group(1).strip('"')
                elif line.startswith("param "):
                    parts = line.split()
                    default = re.search(r"default=(\"[^\"]*\"|\S+)", line)
                    current["params"].append(
                        parts[1] + ("=" + default.group(1).strip('"') if default else ""))
                else:
                    m = re.match(r"block\s+(\S+)\s*\{(.*)", line)
                    if m:
                        inline = m.group(2)  # one-line form: block x { when "…"; default; }
                        when = re.search(r'when\s+("(?:[^"\\]|\\.)*")', inline)
                        feature = {"name": m.group(1),
                                   "default": bool(re.search(r"(^|[;\s])default([;\s}]|$)", inline)),
                                   "when": first_string(when.group(1)) if when else ""}
                        current["features"].append(feature)
            elif depth == 2 and feature is not None:
                if line == "default" or line.startswith("default "):
                    feature["default"] = True
                elif line.startswith("when "):
                    feature["when"] = first_string(line)
        depth += braces(raw)
        if depth <= 1:
            feature = None
        if depth == 0:
            current = None
    return entries


def index(lib_dir):
    """[(import path, entry)] for every .kdl file under lib_dir (examples excluded)."""
    rows = []
    for root, dirs, files in os.walk(lib_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "examples")
        for name in sorted(files):
            if not name.endswith(".kdl") or name == "manifest.kdl":
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, lib_dir)[:-4]
            with open(path, errors="replace") as f:
                for entry in parse_file(f.read()):
                    rows.append(("@stackup/" + rel, entry))
    return rows


def describe(entry):
    if entry["kind"] == "part":
        bits = []
        if entry["packages"]:
            bits.append("packages " + "/".join(entry["packages"]))
        if entry["mpn"]:
            bits.append("mpn " + entry["mpn"])
        feats = [f["name"] + ("*" if f["default"] else "") for f in entry["features"] if not f["when"]]
        if feats:
            bits.append("features " + ", ".join(feats))
        desc = entry["description"][:90]
        return f"part {entry['name']}" + (f" — {desc}" if desc else "") + (
            f"  [{'; '.join(bits)}]" if bits else "")
    return f"block {entry['name']}(" + ", ".join(entry["params"]) + ")"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("filter", nargs="?", default="", help="case-insensitive text to match")
    parser.add_argument("--lib", help="library directory (overrides the manifest)")
    parser.add_argument("--manifest", default=".", help="directory to search upward for manifest.kdl")
    args = parser.parse_args(argv)

    lib = args.lib
    if not lib:
        manifest = find_manifest(args.manifest)
        if not manifest:
            print("error: no manifest.kdl found; pass --lib", file=sys.stderr)
            return 1
        lib = cached_library(manifest)
        if not lib:
            print(f"error: the pinned library isn't in the cache next to {manifest}; run "
                  "`stackup check` on the design once, or pass --lib", file=sys.stderr)
            return 1

    needle = args.filter.lower()
    last = None
    count = 0
    for path, entry in index(lib):
        text = f"{path} {entry['name']} {entry['description']}".lower()
        if needle and needle not in text:
            continue
        if path != last:
            print(path)
            last = path
        print("  " + describe(entry))
        count += 1
    print(f"({count} entries; * = default feature, turn off with `without`)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
