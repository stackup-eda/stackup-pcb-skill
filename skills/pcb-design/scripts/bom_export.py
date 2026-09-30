#!/usr/bin/env python3
"""Turn a `stackup bom` export into the files a fab needs, with an unambiguous description on
every line.

Stackup keeps `value=` readable (and requires a plain quantity such as "100nF" on resistors and
capacitors), and its CSV has no package or description column. This builds, for each line,

    <value> | <MPN> | <manufacturer> | <package>

(dropping a part that repeats the one before it, with no commas, semicolons or quotes) and writes:

- `--jlc FILE`: JLCPCB's upload format (Comment, Designator, Footprint, LCSC Part #), with the
  long form as the Comment. Hand-installed and DNP lines are left out.
- `--value-only FILE`: Designator, Footprint, Quantity, Value (long form), for fabs that read only
  those columns. DNP lines are marked DNP.
- `--purchasing FILE`: the full Stackup columns plus Package and LongValue.

    bom_export.py --stackup PCB/stackup/board.kdl --jlc fab/jlc-bom.csv --purchasing fab/bom.csv
    bom_export.py board-bom.csv --value-only fab/bom.csv --package L1=4x4x1.8mm

The package comes from the footprint name (an 0402/SOT-23/... code, or the footprint's own name for
part-specific footprints); override it with --package REF=TEXT. The export stops if bom_check.py
finds a problem (--fab jlc applies its LCSC rule), unless --force is given.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bom_check  # noqa: E402

UNSAFE = re.compile(r'[,;"]')


def clean(text):
    """Text safe inside a CSV cell without quoting."""
    return re.sub(r"\s+", " ", UNSAFE.sub(" ", text or "")).strip()


# Standard package and size codes, which name a body by themselves. Connector family words (JST,
# USB, PinHeader) don't, so those footprints keep their full name.
PACKAGE_CODE = re.compile(
    r"(?<![0-9])(0201|0402|0603|0805|1206|1210|1812|2010|2512)(?![0-9])|"
    r"SOT-?\d+(-\d+)?|SOD-?\d+|SC-?\d+|SOIC-?\d*|SSOP-?\d*|TSSOP-?\d*|MSOP-?\d*|QFN-?\d*|DFN-?\d*|"
    r"TO-?\d+|SMA|SMB|SMC", re.IGNORECASE)


def package_of(row, overrides=None):
    """Override, else a standard package code from the footprint, else the footprint's name."""
    for ref in (r.strip() for r in (row.get("Refs") or "").split(",")):
        if overrides and ref in overrides:
            return overrides[ref]
    footprint = (row.get("Footprint") or "").split(":")[-1]
    m = PACKAGE_CODE.search(footprint)
    if m and not bom_check.footprint_names_part(row.get("Footprint") or "", row.get("MPN") or ""):
        return m.group(0).upper()
    return footprint


def long_value(row, package):
    """<value> | <MPN> | <manufacturer> | <package>, skipping a part that repeats the previous one."""
    parts = []
    for text in (row.get("Value"), row.get("MPN"), row.get("MF"), package):
        text = clean(text)
        if text and (not parts or bom_check.normalize(text) != bom_check.normalize(parts[-1])):
            parts.append(text)
    return " | ".join(parts)


def expand(rows, overrides=None):
    out = []
    for row in rows:
        package = package_of(row, overrides)
        out.append({**row, "Package": package, "LongValue": long_value(row, package)})
    return out


def is_off_board(row):
    return bom_check.flag(row, "Hand") or bom_check.flag(row, "DNP")


def write_jlc(rows, f):
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    for row in rows:
        if is_off_board(row):
            continue
        w.writerow([row["LongValue"], row["Refs"].replace(" ", ""),
                    (row.get("Footprint") or "").split(":")[-1], row.get("LCSC", "")])


def write_value_only(rows, f):
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["Designator", "Footprint", "Quantity", "Value"])
    for row in rows:
        value = row["LongValue"] + (" | DNP" if is_off_board(row) else "")
        w.writerow([row["Refs"].replace(" ", ""), (row.get("Footprint") or "").split(":")[-1],
                    row.get("Quantity", ""), value])


def write_purchasing(rows, f):
    fields = list(rows[0].keys())
    w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)


def parse_overrides(items):
    overrides = {}
    for item in items:
        ref, sep, text = item.partition("=")
        if not sep or not ref or not text:
            raise ValueError(f"expected REF=PACKAGE, got {item!r}")
        overrides[ref.strip()] = clean(text)
    return overrides


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", nargs="?", help="BOM CSV from `stackup bom`")
    parser.add_argument("--stackup", metavar="BOARD_KDL", help="run `stackup bom` on this design")
    parser.add_argument("--jlc", help="write JLCPCB's upload format here")
    parser.add_argument("--value-only", help="write Designator/Footprint/Quantity/Value here")
    parser.add_argument("--purchasing", help="write the full BOM plus Package and LongValue here")
    parser.add_argument("--package", action="append", default=[], metavar="REF=TEXT",
                        help="package text for a reference (repeatable)")
    parser.add_argument("--fab", choices=["jlc"], help="check this assembler's rules before export")
    parser.add_argument("--allow-no-mpn", default="", help="references deliberately without MPN")
    parser.add_argument("--force", action="store_true", help="export even if bom_check finds problems")
    args = parser.parse_args(argv)

    if not (args.jlc or args.value_only or args.purchasing):
        parser.error("choose at least one of --jlc, --value-only, --purchasing")
    try:
        if args.stackup:
            text = bom_check.stackup_bom(args.stackup)
        elif args.csv:
            with open(args.csv, newline="") as f:
                text = f.read()
        else:
            parser.error("give a BOM CSV or --stackup BOARD_KDL")
        rows = bom_check.read_csv(text)
        overrides = parse_overrides(args.package)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    fab = args.fab or ("jlc" if args.jlc else None)
    problems = [(refs, problem) for refs, problem in
                bom_check.check_rows(rows, fab=fab, allow_no_mpn=args.allow_no_mpn.split(","))
                if not (problem.startswith("package not evident")
                        and {r.strip() for r in refs.split(",")} <= set(overrides))]
    for refs, problem in problems:
        print(f"{refs}: {problem}", file=sys.stderr)
    if problems and not args.force:
        print(f"{len(problems)} problem(s); fix them or pass --force", file=sys.stderr)
        return 1

    rows = expand(rows, overrides)
    for path, writer in ((args.jlc, write_jlc), (args.value_only, write_value_only),
                         (args.purchasing, write_purchasing)):
        if path:
            with open(path, "w", newline="") as f:
                writer(rows, f)
            print(f"wrote {path}")
    for row in rows:
        print(f"  {row['Refs']}: {row['LongValue']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
