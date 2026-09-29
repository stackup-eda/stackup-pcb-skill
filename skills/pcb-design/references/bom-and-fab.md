# BOM, values, and fab output

The fab or assembler must be able to buy exactly the right part from what they see. A bare "BAT54W"
is not enough: it is SOT-323 from most makers and SOD-123 from a few, and fabs flag orders on
exactly that ambiguity.

## Every component is complete

Ensure every component has all of these, so the exported BOM is complete with no potential for
confusion:

| Field | What it holds | Example |
|---|---|---|
| MPN | the exact orderable part number, including packaging/suffix | `CL05B104KO5NNNC`, `BAT54W-7-F` |
| Manufacturer | who makes that MPN | `Samsung Electro-Mechanics`, `Diodes Incorporated` |
| Value | the human value or part name | `100nF`, `10kΩ`, `BAT54W-7-F` |
| Package | confirmed from the manufacturer's package drawing | `0402`, `SOT-323`, `SOT-23-5` |
| Description | what the part is, with the ratings that matter for it | `100nF 16V X7R ±10% MLCC`, `30V 200mA Schottky diode` |
| Specific details | anything a buyer or assembler could get wrong | `RIGHT-ANGLE HORIZONTAL`, `vertical`, `pin 1 = anode`, `N8 flash variant` |

Passives need their ratings in the description: a capacitor's voltage rating, dielectric and
tolerance; a resistor's tolerance and power where it matters. "100nF" alone can be bought wrong.
A connector needs its orientation and mating series; an LED its color and polarity; a module its
variant.

A part that genuinely has no MPN (a custom or salvaged module, a hand-sourced part) still gets a
value, package, description and source, and is marked as having no MPN on purpose, with a comment
on the placement and a note in the PCB README. A gap is never silent.

Before exporting, check the BOM row by row: no blank MPN, manufacturer or value, a package that
names exactly one body, and a description on every part.

## In Stackup

Every placement that gets bought carries its purchasing identity:

```kdl
place bat54w "D1" footprint="Package_TO_SOT_SMD:SOT-323_SC-70" \
    manufacturer="Diodes Incorporated" mpn="BAT54W-7-F" lcsc="C134417" value="BAT54W-7-F"
```

- `value=` is human-readable (`100kΩ`, `10µF`, the part name), unless the fab path below needs
  the long form.
- `manufacturer=`, `mpn=`, `lcsc=` (and other distributor fields) state the exact purchase. Library
  parts can supply defaults, but review what the BOM actually contains.
- `hand=#true` keeps a hand-installed part in the purchasing BOM and marks it DNP for the assembler.
- A part with no MPN is handled as described above.
- Description lives on the part (`description "…"` in the library or `parts.kdl`, or per package
  when a body changes it). Board-specific details go in `note=` on the placement.

Export the purchasing BOM with separate columns:

```sh
stackup bom PCB/stackup/board.kdl --locked -o <board>-bom.csv
```

As of Stackup 0.1.3 the CSV columns are `Refs, Quantity, Value, Footprint, MF, MPN, LCSC, Mouser,
DigiKey, Hand, DNP`. There is **no Package or Description column**, and part descriptions and
placement notes are not exported. Until the pinned version adds them, a BOM built only from that CSV
is missing information. Check the header of the version in use, then get package, description and
details into what the fab receives one of two ways:

- carry them in the value, as below (`<label> | <MPN> | <manufacturer> | <package> | <details>`), or
- post-process the CSV with a project script that adds Package and Description columns from the
  design, and check in CI that no row is blank.

## What each fab sees

- **JLCPCB assembly** matches on the **LCSC part number**, so every assembled part needs `lcsc=`.
  The KiCad Fabrication Toolkit plugin writes JLCPCB's BOM (Comment = Value, Designator, Footprint,
  LCSC) from the PCB.
- **Fabs that read only Designator, Footprint, Quantity and Value** (many do) never see
  MF, MPN or LCSC columns from a KiCad export. Send them the `stackup bom` CSV, which has manufacturer
  and MPN columns. If their BOM must come from the KiCad Value field instead, make that field
  unambiguous: `<label> | <MPN> | <manufacturer> | <package> | <details>`, with the label dropped when it repeats
  the MPN, the human value (`100kΩ`, `10µF`) as the label for passives, and no commas, semicolons or
  quotes so the CSV never needs quoting.
- Either way, add anything a fab could get wrong: connector orientation (right-angle vs vertical),
  variant, polarity.

Prefer a script that builds and checks these fields over editing them by hand, and run it in CI.
Read the BOM through `stackup bom --locked` (so library defaults are included) rather than parsing
the KDL, use [../scripts/jlc_parts.py](../scripts/jlc_parts.py) to find LCSC numbers and
Basic-library alternatives, and have a human review matches before writing them into the KDL.

## After any part change

1. Update the placement in `board.kdl` and run `stackup check --locked`.
2. Sync the PCB from Stackup, because fab tools read the `.kicad_pcb`, not the KDL. Confirm the
   PCB's Value, MPN and LCSC match the design (CI's sync check fails if they don't).
3. Re-run DRC, regenerate production files (gerbers, drill, placement, BOM), and re-check the
   footprint on the board against the part's package drawing with `scripts/footprint_geometry.py`
   (see [kicad.md](kicad.md#footprints)), plus the 3D model.
4. Update anything else that names the part: layout diagrams, README hardware tables, GPIO tables.
   Docs go stale easily after a part swap.

## Assembly errors happen even with a correct BOM

An assembler can mount a correct part wrongly: a right-angle connector has been fitted vertically
from a BOM that correctly specified the right-angle part. To make this less likely and catch it:
- put orientation and variant in the description and value (`RIGHT-ANGLE HORIZONTAL`), not only in
  the MPN;
- review the assembler's placement preview and answer their engineering queries carefully, since
  their questions often reveal an ambiguity in the BOM;
- inspect the first assembled boards before powering them, against the placement drawing and BOM.

If the design and BOM were right, report it to the assembler as a QC issue rather than changing the
design.

## Production file review

Before ordering, look at the whole diff: a regenerated KiCad board, gerbers, and BOM make large diffs,
which is normal, but confirm the change is what was intended. Check the assembler's placement preview
for rotation and polarity (diodes, LEDs, electrolytics, ICs with pin-1 marks). Footprint rotation and
LED pin-order mismatches are common assembly failures.
