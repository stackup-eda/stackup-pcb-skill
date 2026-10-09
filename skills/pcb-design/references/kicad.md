# KiCad layout

KiCad is where the board is placed, routed, checked and exported. It is **not** where the circuit is
defined: that is Stackup. Never add nets or change connectivity in the PCB editor by hand. Change
`board.kdl`, run `stackup check`, and sync.

## Paths on this Mac

- App: `/Applications/KiCad/KiCad.app`
- Bundled Python (for `pcbnew` scripts and headless Stackup sync):
  `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/<ver>/bin/python3`
- ngspice library: `/Applications/KiCad/KiCad.app/Contents/PlugIns/sim/libngspice.dylib`
- `kicad-cli` (DRC, gerbers, drill, positions, STEP): `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`

## Layout practice

- **Layer stackup**: for a 4-layer board, signal / GND / power / signal, or signal / power / GND / signal.
  Keep a solid ground plane under anything fast or switching.
- **Switching regulators**: follow the datasheet's layout example. Keep the hot loop (input cap →
  switch → ground) tiny, the SW node small, feedback routed away from the SW node and inductor, and
  the output cap close. A written layout diagram per power circuit (`PCB/diagrams/`), checked against
  the datasheet's layout guidance, is worth writing before routing.
- **Chargers and thermal pads**: via the exposed pad into a copper pour, and check the thermal
  estimate against max junction temperature.
- **Decoupling**: each cap beside the pin it serves, with a short return. Stackup's `anchor=`
  records which pin that is.
- **RF modules** (ESP32 WROOM, XBee): respect the antenna keep-out on every layer; model it as a rule
  area rather than an oversized courtyard.
- **Return paths**: when a signal changes layers, put a GND stitching via next to the transition.
  Avoid routing across plane splits.
- **Test points** on every rail (VBUS, VBAT, VSYS, 3V3, GND) and key debug nets (EN, BOOT, UART,
  I2C, SPI) before production.
- **Edge-mounted parts** (buttons, connectors) that intentionally overhang: record the DRC
  exception and the reason instead of silently ignoring the warning.
- **Fiducials**: at least one per populated side for assembly; three per side is better.

## Footprints

A footprint can be plain wrong for the part: the right family name on the wrong body. An addressable
LED was once assigned a 5 × 5 mm PLCC4 footprint when the part was a 3.2 × 2.8 mm reverse-mount
package. The name looked plausible, every check passed, and the assembler rejected the board. The
footprint had also gone stale: the design had been corrected, but the board still carried the old
assignment. Check the geometry of every footprint against the part:

1. **Take the numbers from the manufacturer's package drawing** and recommended land pattern: body
   length and width, pad count and pin numbering, pad size, pitch, the center-to-center span between
   pad rows or columns, the outer pad extent, pin 1 location, mounting style (a reverse-mount LED
   needs a board cutout, a right-angle connector overhangs), and any polarity or orientation mark.
   Note which view each drawing is (top or bottom) and which way up the part will sit on this
   board; see "Drawing view and mounting direction" below.
2. **Measure the footprint actually on the board,** not the one you think is assigned:
   ```sh
   python3 <skill>/scripts/footprint_geometry.py --pcb PCB/<board>.kicad_pcb          # every footprint
   python3 <skill>/scripts/footprint_geometry.py --pcb PCB/<board>.kicad_pcb --ref D1
   python3 <skill>/scripts/footprint_geometry.py LED_SMD:<Name>        # a library candidate
   ```
   It prints the footprint's fields (value, manufacturer, MPN, whatever the board carries), pad
   count and numbering, pad positions and sizes, each pad's pin function and net on a board,
   pitch, pad spans, the body (Fab layer), the courtyard, and any cutout the footprint puts on
   Edge.Cuts with its smallest gap to a pad, all in the footprint's own unrotated frame, like the
   drawing's top view. It warns when the footprint's name, description or tags say reverse-mount
   but it has no cutout. Identify the part from those fields; don't report a board as missing MPNs
   without looking at them.
3. **Compare in a table** (drawing vs footprint) and show it. Pad count and numbering must match
   exactly (see "Pad numbers are the datasheet's pin numbers" below). Body size must match the
   drawing. Pitch and spans should be within about 0.05 mm, and pad sizes close to the recommended
   land pattern. A body whose size differs by millimetres means a different package, whatever the
   name says.
4. **Look at the 3D view** with the part's model: the body should sit on the pads with the leads
   landing on them, and pin 1 should match the silkscreen mark.
5. **Repeat after any part or footprint change,** after syncing the PCB, since the fab uses the
   footprint on the board.

Also:

- **Don't trust a footprint because of its name,** including KiCad's stock library. Compare pad size,
  pitch, span and pin numbering against the manufacturer's recommended land pattern. KiCad's stock
  SK6812 reverse-mount footprint, for one, was larger than the OPSCO datasheet's land pattern.
- **Draw a custom footprint from the datasheet's dimensions**, and record the datasheet revision in
  the footprint's description.
- **Community or third-party footprints** (from a GitHub project, SnapMagic, a vendor's EDA export)
  are a starting point. Check them against the datasheet and follow their license: CC-BY-SA
  footprints need attribution in the repo.
- **Parts with no real datasheet** (OEM repair parts, salvaged modules): measure the physical part
  with calipers and check pin functions with a continuity tester before sending the board to fab.
  Mark the footprint unverified until then.
- **Pad numbers are the datasheet's pin numbers.** Pad N carries the datasheet's pin N and sits
  where the datasheet's drawing puts pin N. A footprint numbered some other way (after a KiCad
  symbol's pin order, another vendor's part, or whatever the footprint's author picked) can still
  connect every net correctly, because the part's pin-to-pad map absorbs the difference, and pass
  every check. But the assembler compares the board's pad numbers, your screenshots and the
  datasheet, and when they disagree they stop and ask, or guess. An addressable LED whose datasheet
  reads 1 VDD, 2 DOUT, 3 GND, 4 DIN was laid out with pads numbered 1 VSS, 2 DIN, 3 VDD, 4 DOUT,
  and the fab couldn't confirm its orientation. Check it from the board after syncing:
  ```sh
  python3 <skill>/scripts/footprint_geometry.py --pcb PCB/<board>.kicad_pcb --ref D1 \
      --pins 1=VDD,2=DOUT,3=GND,4=DIN        # the datasheet's pin table, number=name
  ```
  It compares each pad's number and pin function with the table and exits 3 on any difference.
  Pads with no pin function are checked by number only; compare their position and net with the
  pinout drawing. Pass the pin names the part definition uses (the datasheet's, if the part
  follows the rule in [stackup.md](stackup.md#4-parts-and-library-blocks)). To fix a mismatch,
  renumber the footprint's pads to the datasheet and change the part's pin-to-pad map in the same
  commit, then sync; changing only one of them swaps nets. A library part with the wrong map is
  fixed in the library (or overridden by a project part) and reported upstream.
- **Pin 1 and rotation**: check that the footprint's pad 1 matches the datasheet's pin 1 and that the
  silkscreen's pin-1 mark sits where an assembler will look for it.
- **Drawing view and mounting direction.** A land pattern is only right for one way up. Seen from
  the side it's soldered on, a part shows its bottom when it sits face-down (a reverse-mount LED
  shining through a hole in the board) and its top when it sits face-up. The two views are
  mirror images, so a footprint drawn from the wrong one puts pins on the wrong pads, and no
  rotation fixes a mirror. Before trusting a land pattern:

  - say which way the part faces on this board (lens up or down, toward which side of the board);
  - find which view the drawing used. Datasheets label it ("TOP VIEW", "BOTTOM VIEW") or show it by
    where the polarity mark or chamfered corner falls. Don't assume a "recommended PCB pattern" is
    drawn from the component side: a reverse-mount LED's datasheet can draw it in the top view's
    orientation although the part sits face-down;
  - match them: face-up wants the top view, face-down the bottom view. Then check pin 1's position
    against that view, not just its number.

  Reverse-mount packages usually have leads coming out partway up the body, so they need a body
  cutout whichever way up they are mounted; check the side view. A reverse-mount footprint without
  one is usually unusable either way up; `footprint_geometry.py` warns about it. If the part is meant to face up, a
  top-mount version of the same LED or IC (a different package) is usually simpler than a cutout.
- **Cutouts in a footprint** (reverse-mount LEDs, slots) are board edges. Compare the reported
  cutout-to-pad gap with the fab's minimum copper-to-edge clearance and make sure DRC checks it.
  Router-bit relief arcs at a cutout's inside corners bulge toward the pads, so the smallest gap can
  be at a corner rather than along a straight side.

## Board outline and cost

Fab pricing jumps at size and layer-count thresholds (for example, many fabs have a cheaper tier
for boards up to 100 × 100 mm). Check the fab's thresholds before fixing the outline, and consider
whether a few millimetres or a layer count change would move the board into a cheaper tier.

## Checks before ordering

1. `stackup check --locked` clean (or every note explained).
2. The PCB is in sync with Stackup (plugin or CI check reports no changes).
3. The fab's design rules are loaded in Board Setup (minimum track/space, drill, annular ring, via,
   solder-mask sliver), and the stackup (layers, thickness, copper weight) matches what you'll order.
4. Zones refilled, then DRC: zero errors and zero unrouted nets; each remaining warning documented
   with a reason. Edge.Cuts is one closed outline.
5. Footprints match the manufacturer package drawing (see Footprints above), pad numbers match the
   datasheet's pin numbers, and 3D models are present for the STEP export.
6. Silkscreen: board name, revision and date updated before export; designators off the pads; pin-1
   and polarity marks where the assembler will look.
7. BOM and position files regenerated (see [bom-and-fab.md](bom-and-fab.md)); the designators in the
   BOM and the placement (CPL) file match each other and the board, excluding DNP parts.
8. Stock re-checked for every BOM line on the day of the order (`jlc_parts.py` with every MPN in one
   call, `--exact --best`), with a second source ready for anything short. Stock found at design
   time doesn't count ([parts-sourcing.md](parts-sourcing.md#availability-checks)).
9. Gerbers opened in a viewer: every layer present, drills on pads, paste only on SMD pads.
10. The DC-bias and SPICE results for changed circuits are recorded, and the bench checklist is
    written.
11. Tag the commit the fab files came from (e.g. `<board>-rev<X>`), so an order traces to its source.

## kicad-cli commands (verified on KiCad 10.0.5)

Use these rather than writing flags from memory; if the installed version differs, check
`kicad-cli <command> --help` before relying on a flag.

```sh
K=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
B=PCB/<board>.kicad_pcb

# DRC: refills zones in memory (the file isn't saved unless you add --save-board).
# Don't pass --schematic-parity: it's an off-by-default switch, and a Stackup board has no schematic.
$K pcb drc --refill-zones --severity-all --exit-code-violations --format report -o fab/drc.rpt $B

$K pcb export gerbers --board-plot-params -o fab/gerbers/ $B          # the board's saved plot settings
$K pcb export drill --excellon-separate-th --generate-map --map-format gerberx2 -o fab/gerbers/ $B
$K pcb export pos --format csv --units mm --side both --exclude-dnp -o fab/<board>-pos.csv $B
$K pcb export step -o fab/<board>.step $B
```

With `--exit-code-violations`, DRC exits non-zero (5 on KiCad 10) when anything is reported, and
`--severity-all` includes warnings, so a board with documented, accepted warnings still exits 5: read
the report rather than treating the exit code alone as pass/fail. Tested on a real 4-layer board:
the export commands produce the Gerber set, PTH/NPTH drill files with maps, a mm CSV placement file
and a STEP, and DRC with `--refill-zones` leaves the board file byte-identical.

`pcb export pos` defaults to inches (`--units in`), so pass `--units mm`. Drill output defaults to
millimetres. There is no PCB-side BOM export in kicad-cli: use `stackup bom` (see
[bom-and-fab.md](bom-and-fab.md)), or the Fabrication Toolkit plugin for JLCPCB's format.

## Scripting

`pcbnew` from KiCad's bundled Python can read and edit boards headlessly. Close the board in KiCad
first (or reload it after), because the editor will overwrite external changes on save. Prefer
`kicad-cli` for exports.
