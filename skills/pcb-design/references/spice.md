# SPICE simulation

Simulate any new circuit or non-trivial change on a power, latch, sense, enable, reset or timing
path before calling it done. The goal is a first prototype that works, so a second board spin isn't
needed.

## Running ngspice here

KiCad bundles libngspice; on macOS there is no ngspice CLI:

```
/Applications/KiCad/KiCad.app/Contents/PlugIns/sim/libngspice.dylib
```

Use the bundled harness, [../scripts/ngspice_harness.py](../scripts/ngspice_harness.py). It loads
the library with ctypes (`ngSpice_Init`, `ngSpice_Circ`, `ngSpice_Command("run")`, `wrdata`), runs a
netlist, and returns node voltages, plus helpers for pass/fail checks. It needs no Python packages.
`NGSPICE_LIB` overrides the library path.

```sh
python3 <skill>/scripts/ngspice_harness.py --selftest   # RC step: proves the library and harness work
```

Copy the harness into the project (`scripts/spice/ngspice_harness.py`) next to the circuit's
simulation script, so the project reruns without the skill installed. A circuit script looks like:

```python
from ngspice_harness import NgSpice, time_above, first_above, report

NET = """* buck EN rest state
Vsys vsys 0 PWL(0 0 {rise} {vsys})
Rpd en 0 100k
Cen en 0 20p
.tran 5u 50m uic
.end
"""

def insertion(sim):
    results = []
    for vsys, rise in ((3.0, "1m"), (4.2, "100u"), (4.5, "10u")):
        tr = sim.run(NET.format(vsys=vsys, rise=rise), ["en"])
        blip_ms = time_above(tr.time, tr["en"], 1.2) * 1e3
        results.append((f"insert VSYS={vsys}V", blip_ms <= 0.1, f"EN above 1.2V for {blip_ms:.2f} ms"))
    return results

if __name__ == "__main__":
    raise SystemExit(report(insertion(NgSpice())))
```

(BSD `sed -i` on macOS needs `-i ''` if a script edits netlists in place.)

## What to cover

Pick the scenarios that break this kind of circuit. For a power latch or power path, all of these:

| Scenario | What to assert |
|---|---|
| Power-up / battery insertion with the board off | enable lines stay below their threshold, no latch, ends off; several rise times (10 µs-1 ms) and supply levels |
| Off / idle | every gate and enable at a safe level; quiescent current |
| The intended action (button press, MCU hold, USB attach) | turns on within a time bound, at the **lowest** supply with worst-case thresholds |
| Shutdown / decay | collapsing rails do not re-trigger anything |
| Worst-case corners | min/max supply × min/typ/max FET thresholds (Level-1 models with `VTO` swept) |
| Faults and edges | MCU unpowered, button held through insertion, brown-out, reverse or hot-plug where relevant |

For a fix, run the previous design and the new one through the same scenarios (a `--cap 0` style
flag works well), so the result shows the change helped.

## Models

- Use vendor SPICE models when available (TI, onsemi, Diodes, Nexperia and AOS publish many).
- Generic stand-ins (a 2N3904-family model for an MMBT3904, Level-1 MOSFETs with `VTO` at the
  datasheet min/typ/max Vgs(th), fitted diodes) are acceptable. Say so plainly and treat the result as
  evidence, not proof.
- Model what the node actually sees: pin capacitance on enables, gate capacitances (Cgs, Cgd), the
  debounce cap. Leave out what you can't justify.

## Sanity-check the simulation

A result that surprises you may be a model bug. Once, an arbitrary 1 µF on an EN pin produced a fake
100 ms glitch. Before trusting a run:

- run the harness self-test;
- check a hand-calculated operating point (a divider ratio, an RC time constant) in the same netlist;
- confirm initial conditions (`uic`, `.ic`) match the physical starting state;
- make the timestep small against the fastest edge you care about.

## Reporting

- Pass/fail per scenario with the measured numbers, surprises, and any mitigation with its cost
  (a part added, idle current, slower turn-on).
- What was **not** modeled: ideal supplies (no battery impedance or bounce), MCU boot behavior,
  loads, parasitics, temperature, tolerance.
- The bench checklist for the first real board (which node to scope, under which condition).
- A `scripts/spice/README.md` table of scenarios and what each asserts, plus "keeping it in sync":
  the netlist mirrors `board.kdl` by hand, so update it whenever those values or that topology change.
