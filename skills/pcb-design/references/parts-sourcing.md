# Choosing and sourcing parts

Always prefer the commonly available part over the esoteric one. A part that several manufacturers
make in the same package, that every distributor stocks, and whose name maps to exactly one package is
worth more than a slightly better niche part. It survives shortages, it can be second-sourced, and a fab
cannot misread it.

## Order of preference

1. **JLCPCB Basic library** (`componentLibraryType: base`): no feeder-loading fee, and it's what
   JLCPCB keeps loaded.
2. **JLCPCB Preferred Extended** (`expand` with `preferredComponentFlag: true`): no feeder fee on
   Economic PCBA.
3. **JLCPCB Extended** (`expand`): about $3 per unique part in loading fees. Use only when nothing in
   the first two tiers fits, and say why.
4. **Not at JLCPCB**: hand-install (`hand=#true`) or consigned. Needs a stated reason and a source.

The tier only breaks ties among parts that are electrically right. A Basic part with the wrong
threshold is still the wrong part.

The tier order is about JLCPCB assembly cost. If a board is assembled elsewhere, the fee reason goes
away, but a Basic listing is still a good sign that a part is common. Check the repo's agent instructions
(AGENTS.md, CLAUDE.md, GEMINI.md or similar) or README for which fab a board targets.

## Cost is set by distinct parts and the assembler

- **Get real quotes before assuming a fab is cheapest.** At low quantity, assembly cost is driven by
  the number of distinct parts and their library tier more than by unit prices. One board quoted
  roughly $334 at JLCPCB against ~$190 elsewhere because every part was Extended. Compare complete
  assembly quotes (parts, setup and loading fees, stencil, shipping) from at least two assemblers.
- **Use fewer distinct parts.** Reuse one part number wherever a value allows it: one 100 kΩ, one
  10 kΩ, one 100 nF, one 10 µF across the board. Where a value has slack (an LED series resistor
  specified as 300-500 Ω), pick a value the board already uses or a Basic-library one.
- **Choose values that exist and are stocked.** Use standard E-series values (E24, or E96 for 1%
  parts): 600 Ω isn't stocked in 0402 at all, so it had to become 604 Ω. For dividers (regulator
  feedback, charger set resistors), compute from the datasheet formula and then search for a pair of
  stocked (ideally Basic) values that still meets the tolerance, rather than fixing exact odd values
  first. Keep values whose number is itself the standard (27 Ω USB series resistors, 5.1 kΩ USB-C
  CC pull-downs) even if they're Extended.

## Availability checks

For each non-generic part (anything but a jellybean resistor or capacitor), record:

- **JLCPCB / LCSC**: LCSC number, tier, stock. Use `scripts/jlc_parts.py`:

  ```sh
  python3 <skill>/scripts/jlc_parts.py AO3401A              # all listings, best tier first
  python3 <skill>/scripts/jlc_parts.py AO3401A --exact      # only exact MPN matches
  python3 <skill>/scripts/jlc_parts.py "100nF 0402" --basic # Basic-library alternatives
  ```

  It uses the same unauthenticated search the jlcpcb.com parts page uses. Know its traps:
  - it is keyword search, so a digit string can match the wrong value ("100" hits a 1001 = 1 kΩ
    code); re-check the actual value, package and MPN of any hit;
  - it returns a limited window (`--page-size`, default 50), so a real match can be missing, not just
    ranked low; widen the window or search by exact MPN before concluding a part isn't listed;
  - JLCPCB's own BOM tool sometimes shows quantity 0 with no price, which usually means its price
    lookup failed, not that stock is gone; confirm with a live search.
- **Tier cross-check**: confirm Basic/Extended status from a second source before stating it as fact.
  Fetching JLCPCB's web part pages has given contradictory answers for the same URL. The
  community-maintained `jlcpcb-parts-database` export
  (`https://cdfer.github.io/jlcpcb-parts-database/jlcpcb-components-basic-preferred.csv`, synced from
  JLCPCB's API, with `library_type` and `basic` columns) is a good independent check; a part absent
  from it is very likely plain Extended.
- **Mouser, DigiKey, Adafruit**: in-stock quantity and number of manufacturers listing the part.
  Their stock pages indicate broad availability even when the board is assembled at JLCPCB. These need API keys
  for scripted access, so check the product or search pages (with whatever web fetch or search tool is available) and quote the
  numbers with the date checked. Adafruit is a good signal that a part is maker-friendly and has
  breakout-board precedent.
- **Second sources**: other manufacturers making the same part in the same package (for AO3401A,
  several makers list it in SOT-23; for BAT54W, Diodes, Nexperia and others in SOT-323).

**Stock moves daily.** A part that matched fine last week can be short at order time. Re-check stock
for every line when ordering, not only when designing. When a part runs short, look for:
- the same part in another packaging (a reel-size suffix such as `-7` vs `-13` is often the only
  difference);
- a pin- and spec-compatible part from another maker in the same package (search by the existing
  MPN as a keyword), verified against its own datasheet;
- then, only if needed, a different part, which reopens the DC bias check.

Signals that a part is common: several manufacturers, tens of thousands in stock at more than one
distributor, a JLCPCB Basic or Preferred listing, a KiCad standard footprint, and use in reference
designs or Adafruit/SparkFun boards.

Signals to avoid: a single maker or a single sales channel, a non-standard or vendor-specific package
where a standard one exists (prefer SOT-323 over a vendor's SOD variant), a name that means different
packages at different makers, low or zero stock, "not recommended for new designs", or last-time-buy.

## Package certainty

Confirm the package from the **manufacturer's datasheet** (package drawing and ordering table), not
from the KiCad footprint name or a distributor listing. Suffixes matter: `BAT54W` is SOT-323 from
nearly every maker and SOD-123 from a few, and fabs do flag orders on exactly that. Confirm pin
numbering from the manufacturer's pinout drawing too.

## Datasheets

Verify every component requirement against the **manufacturer's** datasheet, never against
assumptions. Memory, a "similar" part, a distributor listing, a summary, a reference design, and a
Stackup library or KiCad symbol definition are all starting points, not evidence. Parts that share a
name across makers (AO3401A, BAT54W, 2N7002) can differ in thresholds, ratings and even pinout, so
read the datasheet from the maker of the exact MPN being bought.

Download it before designing around the part with
[../scripts/datasheet.py](../scripts/datasheet.py), which saves the PDF and its text under
`PCB/datasheets/` and records the source URL, date and hash in `manifest.json`, so later reviews use
the same document:

```sh
python3 <skill>/scripts/datasheet.py fetch <manufacturer PDF url> --name AO3400A
python3 <skill>/scripts/datasheet.py sections AO3400A        # pages for pinout, ratings, package...
python3 <skill>/scripts/datasheet.py grep AO3400A "Gate Threshold|VGS\(th\)" -C 1
python3 <skill>/scripts/datasheet.py page AO3400A 1          # render one page, for a drawing
```

Read tables (thresholds, ratings, pin tables) as text with `grep`; it is far cheaper than looking
at page images. Render a page only for drawings (pinout, package outline, land pattern), and only
the page `sections` points to. For a question-level task, grep the rows you need rather than
fetching every part's datasheet. LCSC's `dataManualUrl` is a mirror convenience. Get the document from the manufacturer's
site, and say when only a mirror was available.

For each part, confirm from the datasheet (and its errata and relevant app notes):

- **Pinout and package**: the pinout drawing and pin table for the exact package and MPN suffix,
  pin 1 location, and exposed-pad connection. Check the footprint and the Stackup part's pad
  mapping against it.
- **Operating conditions**: recommended supply range, and whether the part works across the board's
  whole supply range (not only nominal).
- **Absolute maximums** for every pin, including inputs when the part is unpowered.
- **Thresholds, min and max**: VIH/VIL, Vgs(th), EN/UVLO thresholds and hysteresis, reference
  voltage tolerance.
- **Pin requirements**: which pins must not float, internal pulls (only if stated, with their
  value), strap and boot pins, required power sequencing.
- **Required external parts**: input/output capacitance (type, value and ESR limits), feedback
  resistor ranges, inductor ratings, compensation, from the application section.
- **Layout guidance**: the recommended layout, thermal pad and via requirements, keep-outs.
- **Ratings that affect the choice**: current, power and thermal limits, derating, capacitor DC-bias
  derating for MLCCs.

Stackup library parts carry pin tables, requirements and default support blocks. Check them against
the datasheet too, and fix the library (or the local part) if they differ. A clean `stackup check`
only means the design meets the library's claims.

When reporting, cite the source for each number (datasheet, section, table or figure, min/typ/max).
If something could not be confirmed from the manufacturer's document, say so explicitly and list it
for bench confirmation, rather than filling the gap with a typical or assumed value.

## When a niche part is really needed

Say why (the function the common options can't meet), record alternate sources or a fallback part
and the layout cost of switching, and flag it in the design notes. Swapping is cheap before a board
exists and expensive after.
