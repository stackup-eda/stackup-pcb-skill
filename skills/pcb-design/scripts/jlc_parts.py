#!/usr/bin/env python3
"""Look up parts in the JLCPCB assembly library: LCSC number, library tier, stock, package.

Uses the unauthenticated component search that jlcpcb.com/parts itself calls (no API key).
Results are sorted by tier (Basic, then Preferred Extended, then Extended) and then by stock.

    python3 jlc_parts.py AO3401A                 # everything the search returns
    python3 jlc_parts.py AO3401A --exact         # only listings whose model is exactly AO3401A
    python3 jlc_parts.py "100nF 0402" --basic    # Basic-library parts only
    python3 jlc_parts.py C15127 --json           # machine-readable

Stock numbers change daily. Quote them with the date checked. The search is keyword-based and
returns a limited window (--page-size), so re-check each hit's value/package/MPN, and widen the
window before concluding a part isn't listed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

SEARCH_URL = ("https://jlcpcb.com/api/overseas-pcb-order/v1/"
              "shoppingCart/smtGood/selectSmtComponentList/v2")

BASIC, PREFERRED, EXTENDED = "Basic", "Preferred Extended", "Extended"
TIER_RANK = {BASIC: 0, PREFERRED: 1, EXTENDED: 2}

# JLC lists its own zero-stock placeholder SKUs under this brand; they are not real manufacturers.
PLACEHOLDER_BRAND = "JLCPCBASSEMBLY"


def normalize(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def tier(component):
    """Map JLC's library fields onto the three tiers that decide the loading fee."""
    if (component.get("componentLibraryType") or "").lower() == "base":
        return BASIC
    if component.get("preferredComponentFlag"):
        return PREFERRED
    return EXTENDED


def summarize(component):
    return {
        "lcsc": component.get("componentCode", ""),
        "mpn": component.get("componentModelEn", ""),
        "manufacturer": component.get("componentBrandEn", ""),
        "package": component.get("componentSpecificationEn", ""),
        "tier": tier(component),
        "stock": int(component.get("stockCount") or 0),
        "description": component.get("describe", ""),
        "datasheet": component.get("dataManualUrl", ""),
        "url": component.get("lcscGoodsUrl", ""),
    }


def select(components, mpn=None, basic_only=False):
    """Drop placeholders, optionally filter, and sort best-first."""
    parts = [summarize(c) for c in components
             if normalize(c.get("componentBrandEn")) != PLACEHOLDER_BRAND]
    if mpn:
        parts = [p for p in parts if normalize(p["mpn"]) == normalize(mpn)]
    if basic_only:
        parts = [p for p in parts if p["tier"] == BASIC]
    return sorted(parts, key=lambda p: (TIER_RANK[p["tier"]], -p["stock"]))


def search(keyword, page_size=50, timeout=20):
    payload = {
        "currentPage": 1, "pageSize": page_size, "keyword": keyword,
        "searchSource": "search", "searchType": 2,
        "componentBrandList": [], "componentSpecificationList": [],
        "componentAttributeList": [], "paramList": [],
    }
    request = urllib.request.Request(
        SEARCH_URL, data=json.dumps(payload).encode(), method="POST",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://jlcpcb.com/parts",
            "User-Agent": "Mozilla/5.0 (compatible; pcb-design-skill/1.0)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    if data.get("code") != 200:
        raise RuntimeError(f"JLC search returned code {data.get('code')}: {data.get('message')}")
    return (data.get("data") or {}).get("componentPageInfo", {}).get("list") or []


def format_table(parts):
    if not parts:
        return "no matching listings"
    header = f"{'LCSC':10} {'Tier':19} {'Stock':>9}  {'Package':14} {'Manufacturer':28} MPN"
    rows = [f"{p['lcsc']:10} {p['tier']:19} {p['stock']:>9}  {p['package'][:14]:14} "
            f"{p['manufacturer'][:28]:28} {p['mpn']}" for p in parts]
    return "\n".join([header, *rows])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("keyword", help="MPN, LCSC number, or search words (e.g. '100nF 0402')")
    parser.add_argument("--exact", action="store_true", help="keep only exact MPN matches")
    parser.add_argument("--basic", action="store_true", help="keep only Basic-library parts")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--page-size", type=int, default=50,
                        help="how many search results to fetch (default %(default)s)")
    args = parser.parse_args(argv)

    try:
        found = search(args.keyword, page_size=args.page_size)
    except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
        print(f"lookup failed: {e}", file=sys.stderr)
        return 1
    parts = select(found, mpn=args.keyword if args.exact else None, basic_only=args.basic)
    print(json.dumps(parts, indent=2) if args.json else format_table(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
