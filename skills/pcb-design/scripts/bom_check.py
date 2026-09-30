#!/usr/bin/env python3
"""Check a purchasing BOM for gaps before it goes to a fab: blank manufacturer/MPN/value, missing
LCSC numbers for JLCPCB assembly, and ambiguous or missing package information.

Reads the CSV that `stackup bom` writes (Refs, Quantity, Value, Footprint, MF, MPN, LCSC, Mouser,
DigiKey, Hand, DNP), from a file or by running Stackup:

    bom_check.py board-bom.csv
    bom_check.py --stackup PCB/stackup/board.kdl            # runs `stackup bom <file> --locked`
    bom_check.py board-bom.csv --fab jlc                     # also require LCSC on assembled lines
    bom_check.py board-bom.csv --allow-no-mpn J3,U7
    bom_check.py board-bom.csv --long-values                 # Value must carry MPN and package

Hand-installed and DNP lines are still checked for MPN (they are still bought) but not for LCSC.
Exit status 1 if any problem is found.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys

REQUIRED_COLUMNS = ("Refs", "Value", "Footprint", "MF", "MPN")
YES = {"yes", "y", "true", "1", "dnp"}

# Footprint names that carry a size code or package name, so the package is readable from them.
PACKAGE_HINT = re.compile(
    r"(0201|0402|0603|0805|1206|1210|1812|2010|2512|SOT-?\d+|SOD-?\d+|SOIC|SSOP|TSSOP|MSOP|QFN|DFN|"
    r"LGA|BGA|TO-?\d+|SMA|SMB|SMC|PLCC|JST|USB|Pin(Header|Socket)|\d+(\.\d+)?x\d+(\.\d+)?mm)",
    re.IGNORECASE)


def normalize(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def footprint_names_part(footprint, mpn):
    """True when the footprint is drawn for this specific part: its name shares a distinctive token
    (5+ characters) with the MPN, e.g. 'L_Bourns-SRN4018' for SRN4018-2R2M."""
    mpn_n = normalize(mpn)
    if not mpn_n:
        return False
    name = footprint.split(":")[-1]
    if normalize(name) and (normalize(name) in mpn_n or mpn_n in normalize(name)):
        return True
    return any(len(t) >= 5 and t in mpn_n for t in map(normalize, re.split(r"[_\-\s.]+", name)))


def flag(row, name):
    return (row.get(name) or "").strip().lower() in YES


def check_rows(rows, fab=None, allow_no_mpn=(), long_values=False):
    """Return a list of (refs, problem) for every gap found."""
    allow = {r.strip() for r in allow_no_mpn if r.strip()}
    problems = []
    for row in rows:
        refs = (row.get("Refs") or "").strip() or "?"
        ref_set = {r.strip() for r in refs.split(",")}
        value = (row.get("Value") or "").strip()
        mf = (row.get("MF") or "").strip()
        mpn = (row.get("MPN") or "").strip()
        footprint = (row.get("Footprint") or "").strip()
        bought_by_assembler = not (flag(row, "Hand") or flag(row, "DNP"))
        exempt = ref_set <= allow

        if not value:
            problems.append((refs, "blank value"))
        if not footprint:
            problems.append((refs, "blank footprint"))
        elif not (PACKAGE_HINT.search(footprint) or PACKAGE_HINT.search(value)
                  or footprint_names_part(footprint, mpn)):
            problems.append((refs, f"package not evident from footprint {footprint!r} or value; "
                                   "state it in the value or description"))
        if not exempt:
            if not mf:
                problems.append((refs, "blank manufacturer"))
            if not mpn:
                problems.append((refs, "blank MPN"))
            elif long_values and mpn.lower() not in value.lower():
                problems.append((refs, f"value {value!r} does not contain the MPN {mpn!r}"))
        if fab == "jlc" and bought_by_assembler and not (row.get("LCSC") or "").strip():
            problems.append((refs, "no LCSC number (JLCPCB assembly matches on it)"))
        for bad in (",", ";", '"'):
            if bad in value:
                problems.append((refs, f"value contains {bad!r}, which forces CSV quoting"))
                break
    return problems


def read_csv(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("the BOM has no rows")
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise ValueError("BOM is missing columns: " + ", ".join(missing))
    return rows


def stackup_bom(design, binary=None):
    binary = binary or os.environ.get("STACKUP_BIN", "stackup")
    result = subprocess.run([binary, "bom", design, "--locked"], capture_output=True, text=True,
                            check=False, cwd=os.path.dirname(os.path.abspath(design)) or ".")
    # `stackup bom` exits 1 when a part has no MPN but still writes the CSV; check_rows reports
    # those parts too, so only a run that produced no CSV is a failure.
    if result.returncode and not result.stdout.startswith("Refs,"):
        raise RuntimeError(f"stackup bom failed:\n{result.stderr or result.stdout}")
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", nargs="?", help="BOM CSV from `stackup bom`")
    parser.add_argument("--stackup", metavar="BOARD_KDL", help="run `stackup bom` on this design")
    parser.add_argument("--fab", choices=["jlc"], help="also apply this assembler's requirements")
    parser.add_argument("--allow-no-mpn", default="",
                        help="comma-separated references deliberately without MPN (hand-sourced)")
    parser.add_argument("--long-values", action="store_true",
                        help="require each Value to contain its MPN (fabs that read only Value)")
    args = parser.parse_args(argv)

    try:
        if args.stackup:
            text = stackup_bom(args.stackup)
        elif args.csv:
            with open(args.csv, newline="") as f:
                text = f.read()
        else:
            parser.error("give a BOM CSV or --stackup BOARD_KDL")
        rows = read_csv(text)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    problems = check_rows(rows, fab=args.fab, allow_no_mpn=args.allow_no_mpn.split(","),
                          long_values=args.long_values)
    for refs, problem in problems:
        print(f"{refs}: {problem}")
    print(f"{len(rows)} lines, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
