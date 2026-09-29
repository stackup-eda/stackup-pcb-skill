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

**Start from the template instead of writing a simulation from scratch.** Copy these three files
into the project's `scripts/spice/`, so it reruns without the skill installed:

- [../scripts/spice_template.py](../scripts/spice_template.py): a complete power-latch simulation
  with insertion, press and shutdown scenarios over supply and threshold corners, plus a flag that
  removes the fix. Edit only its marked sections: component values, limits (with their datasheet
  source), the netlist, and the checks.
- [../scripts/spice_lib.py](../scripts/spice_lib.py): generic models (`nmos`/`pmos` with a threshold
  argument for datasheet corners, `diode("1N4148"|"BAT54")`, `npn("2N3904")`, a button switch),
  stimulus (`ramp`, `press`, `pwl`), measurements (`peak`, `first_below`, `time_between`), standard
  corners (`LIION_1S`, `LIION_1S_USB`, `INSERTION_RISE_TIMES`), and `run_matrix`, which runs a
  netlist builder over `corners(...)` and turns each result into a pass/fail row.
- [../scripts/ngspice_harness.py](../scripts/ngspice_harness.py): loads libngspice and runs netlists.

The template runs in a few seconds; as shipped it passes, and `--no-gate-cap` makes the insertion
checks fail, which shows the checks can see the transient. For a circuit that isn't a latch, keep
the structure (values, limits, `netlist()`, one function per scenario using `run_matrix`) and
replace the contents.

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
