---
name: pcb-design
description: Design, change, review, and validate printed circuit boards with KiCad for layout, Stackup (KDL) as the electrical source of truth instead of KiCad schematics, ngspice simulations, and common, well-stocked parts (JLCPCB Basic library first). Use this skill whenever the work touches hardware - picking a component or resistor value, adding or fixing a circuit (power latch, regulator, charger, level shifter, sensor, button, LED), editing a board.kdl/parts.kdl or .kicad_pcb, checking voltages or thresholds, writing a SPICE test, sourcing parts or LCSC numbers, preparing a BOM or fab/assembly order, or reviewing a board before ordering - even if the user never says "PCB" or names a tool.
compatibility: Any agent harness that supports Agent Skills (SKILL.md). Scripts need Python 3 (standard library only). Uses KiCad, the Stackup CLI, and KiCad's bundled libngspice when installed.
---

# PCB design

Paths below (`references/`, `scripts/`) are relative to this skill's directory. Run the scripts with
`python3`; they need only the standard library.

The lesson behind most of this skill: a board can pass every ERC/DRC/netlist check while its analog
behavior is still wrong. A divider starves a MOSFET gate, a new load drags down a shared sense node,
an enable pin has no rest state, a GPIO sits above its rail. Connectivity checks prove the wiring;
they say nothing about voltages. So every change is judged by its DC operating point and, where it
matters, a simulation, not by a clean check.

## Toolchain

| Job | Tool | Notes |
|---|---|---|
| Electrical design (the "schematic") | **Stackup** KDL (`board.kdl`, `parts.kdl`) | Source of truth. No KiCad schematics. |
| Design checks | `stackup check <board.kdl>` | Requirements, assertions, strap rest levels, nc pins |
| Layout, routing, DRC, gerbers | **KiCad** (currently 10) PCB editor | Linked to the KDL by a `.stackup_sch` file; synced with the Stackup plugin |
| Purchasing BOM | `stackup bom <board.kdl> --locked` | Separate manufacturer / MPN / distributor columns |
| Circuit simulation | **ngspice** via KiCad's bundled `libngspice` | Python + ctypes; see `scripts/ngspice_harness.py` |
| Part availability | JLCPCB parts search, then Mouser / DigiKey / Adafruit stock | See `scripts/jlc_parts.py` |

Read [references/stackup.md](references/stackup.md) before writing or editing KDL. The language is
young and specific: values are stated, facts are derived, and it never picks a part for you.

## Workflow for a new circuit or a change

Work through these in order. Skipping ahead to layout is how bad boards get made.

1. **Pin down the requirement.** Supply range (a 1S LiPo is ~3.0-4.2 V, ~4.5 V on USB), loads, what
   drives each input, and every power state (off, idle, on, charging, MCU unpowered).
2. **Choose parts** by the sourcing order in [references/parts-sourcing.md](references/parts-sourcing.md):
   a widely made part first, JLCPCB Basic before Extended, confirmed in stock, reusing part numbers
   already on the board, and with standard stocked values. Get the
   manufacturer's datasheet and verify the part's requirements against it (see the datasheet rule
   below) before designing around it. For an MCU or module, classify its pins before assigning
   any ([references/mcu-pins.md](references/mcu-pins.md)).
3. **Work out the DC bias by hand or script** before accepting a value or topology. Follow
   [references/dc-bias.md](references/dc-bias.md), and show the numbers. For battery or USB power,
   include its power-path checks (reverse polarity, thermistor, charge rate, firmware vs hardware
   cutoffs).
4. **Write it in Stackup.** Prefer a library block (`@stackup/...`) over hand-wiring when one exists.
   Give every placement its full purchasing identity (MPN, manufacturer, value, package,
   description, special details; see [references/bom-and-fab.md](references/bom-and-fab.md)), `nc`
   every deliberately unused or reserved pin, and give each `ignore`/`without` a `reason=` or a
   comment saying why.
5. **Simulate** any power, latch, sense, enable, reset, or timing circuit that is new or changed.
   Follow [references/spice.md](references/spice.md). Keep the harness in the repo (`scripts/spice/`)
   so it reruns.
6. **Check:** `stackup check PCB/stackup/board.kdl` (use `--locked` as CI does). Treat every finding
   and every "holds only for what is stated" note as something to explain or fix.
7. **Sync and lay out in KiCad.** Sync with the Stackup plugin, never by hand-editing footprints'
   nets. Layout rules and DRC are in [references/kicad.md](references/kicad.md).
8. **BOM and fab files.** Follow [references/bom-and-fab.md](references/bom-and-fab.md). The fab
   must be able to buy the exact part from what they see.
9. **Write the bench checklist:** what the first real board must confirm that the simulation and
   checks could not (scope this node on battery insertion, confirm a press latches at 3.0 V, and so on).
   Bring the first board up in stages: current-limited bench supply first, check every rail and the
   idle current before fitting or powering modules, then check each enable/reset/strap level at
   power-up before loading full firmware. Inspect assembled boards for orientation and substitutions.

For a small change (swap a resistor value, change a part), steps 3, 6 and 8 still apply, and step 5
applies if the part sits on a power, latch, sense, or enable node.

## Rules that are easy to get wrong

Each of these catches a real class of bug. The references explain them.

- **Worst case, not typical.** Check against max Vgs(th), VIH/VIL limits, and the diode drop at the
  real (often µA) current, across the whole supply range.
- **Every enable/reset/control input has a defined rest state** in both states of whatever drives it,
  including when the MCU is unpowered. Don't assume an internal pull exists; read the pin table.
- **No pin above its rail.** An input may not sit above VDD+0.3 V (or its stated limit) in any
  supply state. Clamp diodes back-feed a dead rail.
- **New loads on shared nodes.** Adding anything to a node something else reads (a sense line, an
  MCU pin) changes that node. Look for unintended dividers.
- **Verify every component requirement against the manufacturer's datasheet, never assumptions.**
  Supply range, absolute maximums, thresholds, pinout, required external parts, pin rest states,
  decoupling and layout guidance all come from the manufacturer's own datasheet (and errata or app
  notes), not from memory, a similar part, a distributor page, or a library definition. That
  includes Stackup library parts: check their pins and requirements against the datasheet too. Cite
  the table or figure for each number, and if something could not be confirmed from the primary
  source, say so explicitly. Details are in
  [references/parts-sourcing.md](references/parts-sourcing.md#datasheets).
- **Every footprint's geometry matches the part's package drawing.** Body size, pad count and
  numbering, pitch, pad spans and pin 1, measured from the footprint actually on the board
  (`scripts/footprint_geometry.py`) and compared with the manufacturer's drawing. A plausible
  footprint name proves nothing: a footprint for the wrong body size has passed every check and
  been rejected by the assembler. See [references/kicad.md](references/kicad.md#footprints).
- **Every component is fully specified for the BOM:** MPN, manufacturer, value, package,
  description, and any specific details a buyer could get wrong (orientation, variant, polarity,
  voltage rating, dielectric, tolerance). The exported BOM must be complete with no room for
  confusion. See [references/bom-and-fab.md](references/bom-and-fab.md).
- **Check MCU and module pin restrictions before assigning any pin.** Many MCUs and modules (ESP32
  modules especially, and radio modules too) have pins that are used internally for flash or PSRAM,
  sampled at boot (strapping), input-only, dedicated to USB/debug/crystal, or not bonded out.
  Classify every pin from the manufacturer's datasheet for the exact chip and module variant, check
  every load on a strap pin at reset, and record it in a GPIO table. Any pull that matters at
  power-up is a resistor on the board, not a firmware-enabled internal pull-up, and off-board
  connector pinouts are checked against the real module. See
  [references/mcu-pins.md](references/mcu-pins.md).
- **Fix with small standard parts before swapping in a specialized one.** When a part falls short,
  first look for a cheap, common addition that keeps the existing part, footprint and user-facing
  behavior (a transistor inverter, a diode, a resistor) rather than replacing it with a niche part
  (a two-pole switch, a special-function IC). Say so if the specialized part really is simpler.
- **Common parts win.** A part name that means one package to every distributor beats a slightly
  better niche part. Before a board exists a swap is cheap; after, it costs a respin, so weigh it
  honestly.
- **A clean ERC/DRC/`stackup check` is necessary, not sufficient.**

## Reporting a design change

When proposing or finishing hardware work, give the user:

- the numbers: node voltages across the supply range, thresholds with their datasheet source, currents;
- what the simulation showed, including surprises, and which models were generic;
- part choices with manufacturer, MPN, package, JLCPCB tier and stock, and at least one second
  source for anything that isn't generic;
- what is unverified, and the bench checklist.

Findings from outside tools (a design-review analyzer, another person's checker, an AI review) are
leads, not facts. Re-derive each one from the design and the datasheets before acting: they can be
wrong as stated yet point at a real problem, and their assumptions (a diode drop, a threshold) are
often off.

Record decisions so they don't get re-litigated or lost: accepted checker findings and false
positives (with the reason), deliberately deferred risks (with the reasoning and what would change
the call), and datasheet limits knowingly exceeded (with the evidence). Keep them in the PCB README
or a design-review file, and in Stackup `ignore … reason=` where it applies.

## Repo conventions

Hardware repos keep the design under `PCB/`: `PCB/stackup/board.kdl`, `PCB/stackup/parts.kdl`,
the KiCad project beside them, `PCB/datasheets/` for manufacturer PDFs, and `scripts/spice/` for
simulations. The Stackup CLI is pinned through a Cargo-locked crate (`ci/stackup/`) so CI and local
runs use the same version, and the parts library is pinned by commit in `manifest.kdl`. Follow what an
existing repo already does over this layout. Git workflow (feature branch, PR, never push to `main`)
follows the user's global instructions.

Common failure patterns and the check that catches each, worth skimming before a power or latch
design: [references/failure-patterns.md](references/failure-patterns.md).
