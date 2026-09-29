#!/usr/bin/env python3
"""Template: SPICE checks for a soft power latch. Copy it with ngspice_harness.py and spice_lib.py
into the project's scripts/spice/, then edit only the marked sections: the values, the limits, the
netlist, and the checks.

The example circuit: a momentary button (to GND, pulled up to 3V3) drives an NPN inverter whose
collector feeds a diode-OR into the gate of an N-FET latch; the MCU can hold the same gate through
the second diode. The N-FET pulls down a P-FET's gate, and the P-FET's drain drives a buck's EN pin,
which has a pull-down.

    python3 spice_template.py                      # every scenario, exit 1 on any failure
    python3 spice_template.py --scenario press
    python3 spice_template.py --no-gate-cap        # show what the gate capacitor is doing

Scenarios: battery insertion with the board off, a press at worst-case corners, shutdown.
"""
import argparse
import sys

from ngspice_harness import NgSpice, first_above, report, time_above
from spice_lib import (INSERTION_RISE_TIMES, LIION_1S_USB, corners, diode, nmos, npn, peak, pmos,
                       press, ramp, run_matrix, switch_model)

# ---- EDIT: component values (mirror the design; keep in sync with board.kdl) ---------------------
VALUES = dict(R_BTN_PU="100k", C_DBNC="100n", R_INV_BASE="100k", R_INV_PU="100k",
              R_LATCH_G="1Meg", C_LATCH_G="100n", R_GATE="100k", R_EN_PD="100k")

# ---- EDIT: limits, with their datasheet source ----------------------------------------------------
EN_HIGH = 1.2            # buck EN VIH max (regulator datasheet, electrical characteristics)
LATCH_VTH = (0.65, 1.45) # latch N-FET Vgs(th) min, max (FET datasheet)
POWER_VTH = (0.5, 1.3)   # power P-FET |Vgs(th)| min, max
MAX_GATE_OFF = 0.5       # latch gate must stay below this when the board should be off (< min Vth)
MAX_BLIP_MS = 0.1        # EN may not exceed EN_HIGH for longer than this on insertion
MAX_PRESS_MS = 20.0      # press to EN on


# ---- EDIT: netlist -------------------------------------------------------------------------------
def netlist(vsys, rise="1m", vth_latch=1.05, vth_power=0.9, button="PWL(0 0 10 0)",
            v3v3="PWL(0 0 10 0)", gate_cap=True, tstop="300m", tstep="10u", ic=""):
    v = VALUES
    cap = f"Clg latchg 0 {v['C_LATCH_G']}" if gate_cap else "* gate capacitor removed"
    return f"""* soft power latch
{nmos('NLATCH', vth_latch)}
{pmos('PPWR', vth_power)}
{npn('QINV')}
{diode('DOR', '1N4148')}
{diode('DISO', 'BAT54')}
{switch_model('SWM')}
Vsys vsys 0 {ramp(vsys, rise)}
V3 v3src 0 {v3v3}
R3 v3src v3v3 1k
C3 v3v3 0 10u
Rbtn v3v3 sense {v['R_BTN_PU']}
Cdb sense 0 {v['C_DBNC']}
Ssw sense 0 swc 0 SWM
Vsw swc 0 {button}
Rib vsys base {v['R_INV_BASE']}
Diso base sense DISO
Q1 trig base 0 QINV
Rip vsys trig {v['R_INV_PU']}
Dor1 trig latchg DOR
Dor2 hold latchg DOR
Vhold hold 0 0
Rlg latchg 0 {v['R_LATCH_G']}
{cap}
Mlatch pgate latchg 0 0 NLATCH W=1 L=1
Cgs1 latchg 0 550p
Rgate vsys pgate {v['R_GATE']}
Mpwr en pgate vsys vsys PPWR W=1 L=1
Cgs2 pgate vsys 500p
Rpd en 0 {v['R_EN_PD']}
Cen en 0 20p
{ic}
.tran {tstep} {tstop} uic
.end
"""


NODES = ["en", "latchg", "sense", "pgate"]


# ---- EDIT: scenarios -----------------------------------------------------------------------------
def insertion(sim, gate_cap):
    """Battery inserted with the board off: EN must not blip, the latch gate must stay off."""
    def build(vsys, rise, vth):
        return netlist(vsys, rise=rise, vth_latch=vth, gate_cap=gate_cap)

    def check(tr, c):
        blip = time_above(tr.time, tr["en"], EN_HIGH) * 1e3
        gate = peak(tr.time, tr["latchg"])
        ok = blip <= MAX_BLIP_MS and gate < MAX_GATE_OFF
        return ok, f"EN>{EN_HIGH}V {blip:.2f} ms, gate peak {gate:.2f} V"
    return run_matrix(sim, "insert", build,
                      corners(vsys=LIION_1S_USB, rise=INSERTION_RISE_TIMES, vth=LATCH_VTH[:1]),
                      NODES, check)


def button_press(sim, gate_cap):
    """A held press turns EN on quickly, at the lowest supply with the worst-case thresholds."""
    def build(vsys, vth):
        return netlist(vsys, vth_latch=vth, vth_power=POWER_VTH[1], gate_cap=gate_cap,
                       button=press(0.1, 0.4), tstop="600m", tstep="20u")

    def check(tr, c):
        on = first_above(tr.time, tr["en"], EN_HIGH, after=0.1)
        if on is None:
            return False, "EN never came on"
        ms = (on - 0.1) * 1e3
        return ms <= MAX_PRESS_MS, f"EN on {ms:.1f} ms after press"
    return run_matrix(sim, "press", build, corners(vsys=(3.0, 4.2), vth=LATCH_VTH), NODES, check)


def shutdown(sim, gate_cap):
    """The 3V3 rail collapsing after shutdown must not re-trigger the latch."""
    def build(vsys):
        ic = f".ic v(sense)=3.3 v(pgate)={vsys} v(latchg)=0 v(en)=0"
        return netlist(vsys, rise="1u", v3v3="PWL(0 3.3 10m 3.3 110m 0 10 0)", gate_cap=gate_cap,
                       ic=ic, tstop="400m", tstep="20u")

    def check(tr, c):
        gate, en = peak(tr.time, tr["latchg"]), peak(tr.time, tr["en"])
        return gate < MAX_GATE_OFF and en < EN_HIGH, f"gate peak {gate:.2f} V, EN peak {en:.2f} V"
    return run_matrix(sim, "shutdown", build, corners(vsys=(3.7, 4.2)), NODES, check)


SCENARIOS = {"insert": insertion, "press": button_press, "shutdown": shutdown}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    parser.add_argument("--no-gate-cap", action="store_true", help="remove the latch gate capacitor")
    args = parser.parse_args(argv)
    sim = NgSpice()
    names = SCENARIOS if args.scenario == "all" else [args.scenario]
    rows = [row for n in names for row in SCENARIOS[n](sim, not args.no_gate_cap)]
    return report(rows)


if __name__ == "__main__":
    sys.exit(main())
