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
2. **Measure the footprint actually on the board,** not the one you think is assigned:
   ```sh
   python3 <skill>/scripts/footprint_geometry.py --pcb PCB/<board>.kicad_pcb --ref D1
   python3 <skill>/scripts/footprint_geometry.py LED_SMD:<Name>        # a library candidate
   ```
   It prints pad count and numbering, pad positions and sizes, pitch, pad spans, the body (Fab
   layer) and the courtyard, in the footprint's own unrotated frame, like the drawing's top view.
3. **Compare in a table** (drawing vs footprint) and show it. Pad count and numbering must match
   exactly. Body size must match the drawing. Pitch and spans should be within about 0.05 mm, and pad
   sizes close to the recommended land pattern. A body whose size differs by millimetres means a
   different package, whatever the name says.
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
- **Pin 1 and rotation**: check that the footprint's pad 1 matches the datasheet's pin 1 and that the
  silkscreen's pin-1 mark sits where an assembler will look for it.

## Board outline and cost

Fab pricing jumps at size and layer-count thresholds (for example, many fabs have a cheaper tier
for boards up to 100 × 100 mm). Check the fab's thresholds before fixing the outline, and consider
whether a few millimetres or a layer count change would move the board into a cheaper tier.

## Checks before ordering

1. `stackup check --locked` clean (or every note explained).
2. The PCB is in sync with Stackup (plugin or CI check reports no changes).
3. DRC: zero errors; each remaining warning documented with a reason.
4. Unrouted nets: zero.
5. Footprints match the manufacturer package drawing (pad size, pitch, pin 1, orientation) for every
   non-standard part, and 3D models are present for the STEP export.
6. BOM and position files regenerated; see [bom-and-fab.md](bom-and-fab.md).
7. The DC-bias and SPICE results for changed circuits are recorded, and the bench checklist is written.

## Scripting

`pcbnew` from KiCad's bundled Python can read and edit boards headlessly. Close the board in KiCad
first (or reload it after), because the editor will overwrite external changes on save. Prefer
`kicad-cli` for exports.
