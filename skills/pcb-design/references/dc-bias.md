# DC bias check

Do this before picking or accepting any part, value, or topology, and again before calling a change
done. Work it out by hand or with a short script, not by assumption, and show the numbers so they can
be checked.

## Procedure

1. **List the supply states.** Every rail's range, not only nominal: a 1S Li-ion is ~3.0-4.2 V (and
   ~4.5 V when USB feeds VSYS through a charger), plus off, idle, charging, and "MCU unpowered while
   the battery is connected". Include insertion and brown-out if the circuit is on a power path.
2. **Compute every touched node** in every state: the voltage, and the current through each path.
   Include diode drops at the real current (a Schottky or 1N4148 at a few µA drops far less than its
   headline Vf; use the datasheet's Vf-If curve), transistor Vbe/Vce(sat), and FET Rds(on) at the
   gate drive it will actually see.
3. **Compare against worst-case limits** from the manufacturer datasheet's electrical
   characteristics table:
   - a MOSFET is "on" only if Vgs exceeds **max** Vgs(th) with margin, and enhancement at the drive
     you have (Rds(on) is specified at a stated Vgs; below it, extrapolate cautiously);
   - a MOSFET is "off" only if Vgs stays comfortably under **min** Vgs(th);
   - a logic input is high only above **VIH(min)**, low only below **VIL(max)**, at that supply;
   - an enable pin (a buck's EN, an LDO's EN) has its own thresholds; use them.
4. **Hunt for hidden dividers and shared nodes.** Any two resistors meeting at a gate or input form a
   divider; compute it. Any new load on a node that something else reads (an MCU pin, a sense line,
   a feedback node) changes that node. Recompute the existing reader's levels with the new load.
5. **Check absolute maximums** on every pin against every rail that can drive it, in every state.
   An input may not exceed VDD+0.3 V (or the stated limit). When the MCU is unpowered, a signal from a
   live rail forward-biases the clamp diode and back-feeds the dead rail; find and fix those paths
   (series resistor sized to the injection-current limit, a Schottky, or a different topology).
6. **Give every enable/reset/control input a defined rest state** in both states of its driver. Read
   the pin description for "do not leave floating"; do not assume an internal pull unless the
   datasheet states it with a value. Stackup's `net.rest` check covers declared straps; apply the
   same thinking to every EN/RESET/CE/nSLEEP pin.
7. **Size pull resistors for both jobs:** strong enough to reach the needed level against leakage and
   loads, weak enough that idle current is acceptable (a 10 kΩ pull-up held low at 4.2 V burns 420 µA
   continuously, which matters on a battery device). State the trade-off when they conflict.
8. **Record where every number came from:** datasheet name, table or figure, min/typ/max. If a value
   could not be confirmed from the manufacturer's document (only from a distributor page or a
   summary), say so.

## Battery and power-path checks

For anything powered from a battery or USB, also check and record:

- **Reverse polarity**: can the battery be connected backwards (unkeyed connector, or a cell or pack
  wired by someone else)? Does the charger or power path survive it? If not, add protection (a
  reverse-blocking PMOS costs almost no voltage; a series diode costs 0.3-0.7 V of headroom) or record
  why it's acceptable (keyed connector, controlled battery source).
- **Battery temperature**: if the charger has a thermistor (TS/NTC) input, either wire a real NTC
  from the pack or record why it's fixed with a resistor (e.g. a swappable cell with no thermistor
  lead). A fixed resistor disables hot/cold charge protection.
- **Charge current against the cell**: set current as a fraction of capacity (C-rate) within the
  cell's datasheet limits; lower is gentler when there's no thermistor.
- **Firmware shutdown against hardware cutoffs**: firmware's "low battery, shut down gracefully"
  threshold must sit clearly above the charger's or protection circuit's undervoltage lockout,
  including voltage sag under load. A 60 mV gap (3.06 V firmware threshold against a 3.0 V hardware
  cutoff) lets the hardware cut power before a graceful shutdown finishes.
- **USB input**: VBUS range and transients, ESD protection on the connector, CC resistors for USB-C
  sinks, and what happens when USB and battery are both present.

## Presenting it

A small table per changed node works well:

| Node | State | VSYS 3.0 V | VSYS 4.2 V | VSYS 4.5 V | Limit (source) | OK? |
|---|---|---|---|---|---|---|
| `PWR_LATCH_G` | button held | _x_ V | _y_ V | _z_ V | > 1.45 V max Vgs(th) (AO3400A datasheet, electrical characteristics) | ? |
| `PWR_LATCH_G` | off, idle | _x_ V | _y_ V | _z_ V | < 0.65 V min Vgs(th) (same table) | ? |

For anything nonlinear or time-dependent (a latch, an RC on an enable pin, insertion transients), the
hand calculation sets expectations and the simulation in [spice.md](spice.md) confirms them.

## Worked examples (a battery-powered soft power latch)

- **Divider starved a gate:** a 10 kΩ latch-gate pull-down formed an unintended divider with a
  100 kΩ pull-up across an OR diode, leaving ~0.3 V at the FET gate on a press. Fix: raise the
  pull-down to 1 MΩ rather than shrink the pull-up, which would have turned the idle state into a
  continuous mA drain.
- **No margin at low battery:** with the real diode drop the gate reached ~2.4 V at 3.0 V supply,
  against a 2N7002's 2.5 V worst-case Vgs(th). Fix: AO3400A (1.45 V max), same SOT-23 pinout.
- **A shared sense node loaded down:** a transistor inverter's base resistor shared current with the
  button pull-up and sagged the MCU's button read to ~1 V. Fix: give the inverter its own pull-up and
  isolate it from the sense node with a Schottky.
- **Floating enable:** a buck's EN pin was connected only to a PMOS drain, which floats when the PMOS
  is off; the datasheet says not to leave EN floating. Fix: 100 kΩ pull-down.
- **GPIO above its rail:** a button pull-up to the battery rail (up to ~4.5 V on USB) exceeded the
  pin's VDD+0.3 V (~3.6 V) limit and back-fed the dead 3.3 V rail through the clamp diode when the MCU
  was off. A divider couldn't work across 3.0-4.5 V (it must read ≥ 2.5 V yet never exceed 3.6 V).
  Fix: pull up to 3.3 V.
