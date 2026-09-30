#!/usr/bin/env python3
"""Look up parts in the JLCPCB assembly library: LCSC number, library tier, stock, package.

Uses the unauthenticated component search that jlcpcb.com/parts itself calls (no API key).
Results are sorted by tier (Basic, then Preferred Extended, then Extended) and then by stock.

    python3 jlc_parts.py AO3401A                 # everything the search returns
    python3 jlc_parts.py AO3401A --exact         # only listings whose model is exactly AO3401A
    python3 jlc_parts.py "100nF 0402" --basic    # Basic-library parts only
    python3 jlc_parts.py C15127 --json           # machine-readable
    python3 jlc_parts.py AO3400A AO3401A TLV62569DBVR --exact --best   # many parts, one line each

Stock numbers change daily. Quote them with the date checked. The search is keyword-based and
returns a limited window (--page-size), so re-check each hit's value/package/MPN, and widen the
window before concluding a part isn't listed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
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


def format_best(results):
    """One line per query: the best listing, or why there is none."""
    header = f"{'Query':22} {'LCSC':10} {'Tier':19} {'Stock':>9}  {'Package':14} MPN / manufacturer"
    rows = []
    for query, parts, error in results:
        if error:
            rows.append(f"{query[:22]:22} lookup failed: {error}")
        elif not parts:
            rows.append(f"{query[:22]:22} no matching listings")
        else:
            p = parts[0]
            more = f" (+{len(parts) - 1} more)" if len(parts) > 1 else ""
            rows.append(f"{query[:22]:22} {p['lcsc']:10} {p['tier']:19} {p['stock']:>9}  "
                        f"{p['package'][:14]:14} {p['mpn']} / {p['manufacturer']}{more}")
    return "\n".join([header, *rows])


def lookup_all(queries, exact=False, basic_only=False, page_size=50, delay=0.3, search_fn=None):
    """[(query, parts, error)] for each query, pausing `delay` seconds between requests."""
    search_fn = search_fn or search
    results = []
    for i, query in enumerate(queries):
        if i and delay:
            time.sleep(delay)
        try:
            found = search_fn(query, page_size=page_size)
            results.append((query, select(found, mpn=query if exact else None, basic_only=basic_only), ""))
        except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
            results.append((query, [], str(e)))
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("keywords", nargs="+", metavar="keyword",
                        help="MPN, LCSC number, or search words (e.g. '100nF 0402'); several allowed")
    parser.add_argument("--exact", action="store_true", help="keep only exact MPN matches")
    parser.add_argument("--basic", action="store_true", help="keep only Basic-library parts")
    parser.add_argument("--best", action="store_true", help="one line per keyword: the best listing")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--page-size", type=int, default=50,
                        help="how many search results to fetch (default %(default)s)")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="seconds between requests when looking up several parts")
    args = parser.parse_args(argv)

    results = lookup_all(args.keywords, exact=args.exact, basic_only=args.basic,
                         page_size=args.page_size, delay=args.delay)
    failed = [q for q, _, error in results if error]
    if args.json:
        data = {q: ({"error": error} if error else parts) for q, parts, error in results}
        print(json.dumps(data if len(results) > 1 else next(iter(data.values())), indent=2))
    elif args.best:
        print(format_best(results))
    else:
        for query, parts, error in results:
            if len(results) > 1:
                print(f"== {query}")
            print(f"lookup failed: {error}" if error else format_table(parts))
    if failed and not (args.best or args.json):
        print("lookup failed for: " + ", ".join(failed), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
