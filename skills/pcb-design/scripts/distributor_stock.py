#!/usr/bin/env python3
"""Check JLCPCB, Mouser and DigiKey stock and price for one or more exact MPNs, one line each.

    python3 distributor_stock.py TCAN1044AVDRQ1                    # all three distributors
    python3 distributor_stock.py AO3400A AO3401A TLV62569DBVR      # a whole BOM, one line each
    python3 distributor_stock.py AO3401A --sources mouser,digikey  # skip some distributors
    python3 distributor_stock.py AO3401A --json                    # every field, machine-readable

JLCPCB needs no key (it uses jlc_parts.py). Mouser and DigiKey need free API credentials, read from
environment variables first and then from a key file (default ~/.config/pcb-design/api-keys.env,
or the path in PCB_DESIGN_KEYS / --keys), one KEY=value per line:

    MOUSER_API_KEY=...         # Mouser API Hub -> Search API (https://www.mouser.com/api-hub/)
    DIGIKEY_CLIENT_ID=...      # developer.digikey.com -> Production app with Product Information v4
    DIGIKEY_CLIENT_SECRET=...

Keep that file outside every repository and readable only by you (chmod 600). A distributor with no
credentials is reported as "no key" and skipped; it is not a failure.

Read the numbers carefully:
- Out of stock is 0, not an error. DigiKey reports a part it lists but has none of with a null
  quantity; that is real, not an access problem. When every part looks out of stock, check a part
  that is surely stocked before suspecting the lookup.
- "on order" is the distributor's incoming quantity and date, not a promise.
- Prices are the quantity-1 price in USD. Stock moves daily: quote it with the date checked.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jlc_parts  # noqa: E402

DEFAULT_KEY_FILE = Path.home() / ".config" / "pcb-design" / "api-keys.env"
KEY_NAMES = ("MOUSER_API_KEY", "DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET")
SOURCES = ("jlc", "mouser", "digikey")

MOUSER_URL = "https://api.mouser.com/api/v1/search/partnumber"
DIGIKEY_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_DETAILS_URL = "https://api.digikey.com/products/v4/search/{}/productdetails"


class DistributorError(Exception):
    """A lookup that failed (network, auth, bad response), as opposed to a part with no stock."""


# Credentials

def parse_key_file(text):
    """KEY=value lines; ignores blanks and comments, tolerates `export` and quotes."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        values[key] = value.strip().strip('"').strip("'")
    return values


def load_keys(path=None, environ=None):
    """Credentials from the environment, then the key file. Missing ones are absent, not empty."""
    environ = os.environ if environ is None else environ
    path = Path(path or environ.get("PCB_DESIGN_KEYS") or DEFAULT_KEY_FILE).expanduser()
    from_file = parse_key_file(path.read_text()) if path.is_file() else {}
    keys = {}
    for name in KEY_NAMES:
        value = environ.get(name) or from_file.get(name)
        if value:
            keys[name] = value
    return keys


def redact(message, keys):
    """Remove every credential from a message before it is printed."""
    for value in keys.values():
        if value:
            message = message.replace(value, "<redacted>")
    return message


# HTTP

def _request(url, data=None, headers=None, timeout=20):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise DistributorError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise DistributorError(f"network: {getattr(e, 'reason', e)}") from None
    except json.JSONDecodeError:
        raise DistributorError("response was not JSON") from None


def _price(text):
    """'$1,234.50' -> 1234.5; None when there is no number."""
    try:
        return float(str(text).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


# Mouser

def mouser_fetch(mpn, keys, http=_request):
    body = json.dumps({"SearchByPartRequest": {"mouserPartNumber": mpn,
                                               "partSearchOptions": "Exact"}}).encode()
    url = MOUSER_URL + "?apiKey=" + urllib.parse.quote(keys["MOUSER_API_KEY"])
    data = http(url, data=body, headers={"Content-Type": "application/json",
                                         "Accept": "application/json"})
    if data is None:
        raise DistributorError("HTTP 404")
    errors = data.get("Errors") or []
    if errors:
        raise DistributorError("; ".join(e.get("Message", str(e)) for e in errors))
    return data


def mouser_parse(data, mpn):
    """The exact-MPN listing with the most stock, or None if Mouser doesn't list the part."""
    parts = ((data or {}).get("SearchResults") or {}).get("Parts") or []
    exact = [p for p in parts
             if jlc_parts.normalize(p.get("ManufacturerPartNumber")) == jlc_parts.normalize(mpn)]
    if not exact:
        return None
    rows = []
    for p in exact:
        breaks = sorted(p.get("PriceBreaks") or [], key=lambda b: b.get("Quantity") or 0)
        on_order = [{"quantity": o.get("Quantity"), "date": (o.get("Date") or "")[:10]}
                    for o in p.get("AvailabilityOnOrder") or []]
        rows.append({
            "sku": p.get("MouserPartNumber", ""),
            "mpn": p.get("ManufacturerPartNumber", ""),
            "manufacturer": p.get("Manufacturer", ""),
            "stock": int(p.get("AvailabilityInStock") or 0),
            "price": _price(breaks[0].get("Price")) if breaks else None,
            "on_order": on_order,
            "lead_time": p.get("LeadTime") or "",
            "status": p.get("LifecycleStatus") or ("Discontinued" if p.get("IsDiscontinued") == "true" else ""),
            "url": p.get("ProductDetailUrl", ""),
        })
    return max(rows, key=lambda r: r["stock"])


# DigiKey

class DigiKey:
    """Client-credentials token, fetched once and reused until it expires."""

    def __init__(self, keys, http=_request, clock=time.time):
        self.keys, self.http, self.clock = keys, http, clock
        self.token, self.expires = None, 0.0

    def _token(self):
        if self.token and self.clock() < self.expires - 30:
            return self.token
        body = urllib.parse.urlencode({
            "client_id": self.keys["DIGIKEY_CLIENT_ID"],
            "client_secret": self.keys["DIGIKEY_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        }).encode()
        data = self.http(DIGIKEY_TOKEN_URL, data=body,
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        if not data or "access_token" not in data:
            raise DistributorError("DigiKey token request failed")
        self.token = data["access_token"]
        self.expires = self.clock() + float(data.get("expires_in") or 0)
        return self.token

    def fetch(self, mpn):
        headers = {
            "Authorization": "Bearer " + self._token(),
            "X-DIGIKEY-Client-Id": self.keys["DIGIKEY_CLIENT_ID"],
            "X-DIGIKEY-Locale-Site": "US",
            "X-DIGIKEY-Locale-Currency": "USD",
            "Accept": "application/json",
        }
        return self.http(DIGIKEY_DETAILS_URL.format(urllib.parse.quote(mpn, safe="")),
                         headers=headers)


def digikey_parse(data, mpn):
    """The listing for an exact MPN, or None if DigiKey doesn't list it. A null quantity is 0."""
    product = (data or {}).get("Product")
    if not product or jlc_parts.normalize(product.get("ManufacturerProductNumber")) != jlc_parts.normalize(mpn):
        return None
    variations = product.get("ProductVariations") or []
    # Cut tape is what a small order buys; fall back to whichever packaging comes first.
    cut = next((v for v in variations if "cut tape" in ((v.get("PackageType") or {}).get("Name") or "").lower()),
               variations[0] if variations else {})
    status = (product.get("ProductStatus") or {}).get("Status") or ""
    if product.get("Discontinued"):
        status = "Discontinued"
    elif product.get("EndOfLife"):
        status = "End of life"
    lead = product.get("ManufacturerLeadWeeks")
    return {
        "sku": cut.get("DigiKeyProductNumber", ""),
        "mpn": product.get("ManufacturerProductNumber", ""),
        "manufacturer": (product.get("Manufacturer") or {}).get("Name", ""),
        "stock": int(product.get("QuantityAvailable") or 0),
        "price": product.get("UnitPrice"),
        "on_order": [],
        "lead_time": f"{lead} weeks" if lead else "",
        "status": status,
        "url": product.get("ProductUrl", ""),
    }


# JLCPCB

def jlc_lookup(mpn, search_fn=None):
    parts = jlc_parts.select((search_fn or jlc_parts.search)(mpn), mpn=mpn)
    if not parts:
        return None
    p = parts[0]
    return {"sku": p["lcsc"], "mpn": p["mpn"], "manufacturer": p["manufacturer"], "stock": p["stock"],
            "price": None, "on_order": [], "lead_time": "", "status": p["tier"], "url": p["url"]}


# Batch lookup

def lookup_all(mpns, keys, sources=SOURCES, delay=0.3, mouser_http=_request, digikey=None,
               jlc_search=None):
    """{mpn: {source: listing | None | {"error": ...} | {"skipped": ...}}} in query order."""
    if "digikey" in sources and digikey is None and {"DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET"} <= keys.keys():
        digikey = DigiKey(keys)
    results = {}
    for i, mpn in enumerate(mpns):
        if i and delay:
            time.sleep(delay)
        row = {}
        for source in sources:
            try:
                if source == "jlc":
                    row[source] = jlc_lookup(mpn, jlc_search)
                elif source == "mouser":
                    if "MOUSER_API_KEY" not in keys:
                        row[source] = {"skipped": "no key"}
                        continue
                    row[source] = mouser_parse(mouser_fetch(mpn, keys, mouser_http), mpn)
                elif source == "digikey":
                    if digikey is None:
                        row[source] = {"skipped": "no key"}
                        continue
                    row[source] = digikey_parse(digikey.fetch(mpn), mpn)
            except (DistributorError, RuntimeError, urllib.error.URLError, TimeoutError) as e:
                row[source] = {"error": redact(str(e), keys)}
        results[mpn] = row
    return results


def _cell(listing):
    if listing is None:
        return "not listed"
    if "skipped" in listing:
        return listing["skipped"]
    if "error" in listing:
        return "failed: " + listing["error"]
    text = f"{listing['stock']:,}"
    if listing.get("price") is not None:
        text += f" @ ${listing['price']:.2f}"
    if listing.get("status") and listing["status"] not in ("Active",):
        text += f" ({listing['status']})"
    return text


def format_table(results, sources=SOURCES):
    names = {"jlc": "JLCPCB", "mouser": "Mouser", "digikey": "DigiKey"}
    widths = {"jlc": 38, "mouser": 22, "digikey": 22}
    header = (f"{'MPN':22} " + " ".join(f"{names[s]:{widths[s]}}" for s in sources) + " Notes").rstrip()
    rows = [header]
    for mpn, row in results.items():
        cells = []
        for s in sources:
            listing = row.get(s)
            cell = _cell(listing)
            if s == "jlc" and listing and "stock" in listing:
                cell = f"{listing['sku']} {listing['stock']:,} ({listing['status']})"
            cells.append(f"{cell[:widths[s]]:{widths[s]}}")
        notes = []
        for s in sources:
            listing = row.get(s) or {}
            for o in listing.get("on_order") or []:
                notes.append(f"{names[s]} {o['quantity']:,} on order {o['date']}".strip())
        rows.append((f"{mpn[:22]:22} " + " ".join(cells) + (" " + "; ".join(notes) if notes else "")).rstrip())
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mpns", nargs="+", metavar="MPN", help="exact manufacturer part numbers")
    parser.add_argument("--sources", default=",".join(SOURCES),
                        help="comma-separated subset of %(default)s")
    parser.add_argument("--keys", help=f"key file (default $PCB_DESIGN_KEYS or {DEFAULT_KEY_FILE})")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="seconds between parts when looking up several")
    args = parser.parse_args(argv)

    sources = tuple(s.strip().lower() for s in args.sources.split(",") if s.strip())
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        parser.error(f"unknown source(s) {', '.join(unknown)}; choose from {', '.join(SOURCES)}")

    keys = load_keys(args.keys)
    results = lookup_all(args.mpns, keys, sources=sources, delay=args.delay)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_table(results, sources))
    failed = any("error" in (listing or {}) for row in results.values() for listing in row.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
