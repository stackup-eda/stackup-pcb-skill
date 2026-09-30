"""Reusable pieces for ngspice checks, so a circuit script only has to state its netlist and limits.

- Generic device models, with MOSFET thresholds taken from datasheet min/typ/max corners.
- Stimulus helpers for supply ramps and button presses (PWL sources).
- Waveform measurements (peak, time above/below, when a node crosses a level).
- A corner-matrix runner that turns (netlist builder, corners, check) into pass/fail rows.

Use it with ngspice_harness.py (copy both into the project's scripts/spice/). Start from
spice_template.py, which wires these together for a power-latch style circuit.

The models are generic: Level-1 MOSFETs, textbook diode/BJT fits. Say so when reporting, and prefer
a vendor model when one exists.
"""
from __future__ import annotations

from itertools import product

# --- Supply and timing corners that break power circuits ----------------------------------

LIION_1S = (3.0, 3.7, 4.2)            # single Li-ion cell: empty, nominal, full (V)
LIION_1S_USB = (3.0, 3.7, 4.2, 4.5)   # plus a charger's power path on USB
INSERTION_RISE_TIMES = ("10u", "100u", "1m")  # battery/connector insertion edges

# --- Models -------------------------------------------------------------------------------

DIODE_MODELS = {
    # Small-signal silicon diode (1N4148 / 1N4148W / 1N4148WS family).
    "1N4148": "D(IS=2.52n RS=0.568 N=1.752 CJO=4p M=0.4 TT=20n BV=100)",
    # Small Schottky (BAT54 family): low Vf at µA, higher leakage.
    "BAT54": "D(IS=1.4e-8 N=1.05 RS=3 CJO=10p M=0.4 VJ=0.5 BV=30)",
}

BJT_MODELS = {
    # 2N3904-family NPN, a stand-in for MMBT3904.
    "2N3904": ("NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259 ISE=6.734f IKF=66.78m "
               "XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 "
               "CJE=4.493p MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)"),
}


def diode(name, family="1N4148"):
    """`.model <name> D(...)` for a diode family in DIODE_MODELS."""
    return f".model {name} {DIODE_MODELS[family]}"


def npn(name, family="2N3904"):
    return f".model {name} {BJT_MODELS[family]}"


def nmos(name, vth, kp=5.0, lam=0.01):
    """Level-1 N-MOSFET with threshold `vth` volts. Sweep vth over the datasheet's
    min/typ/max Vgs(th): the max is the turn-on worst case, the min the stay-off worst case."""
    return f".model {name} NMOS(LEVEL=1 VTO={vth} KP={kp} LAMBDA={lam})"


def pmos(name, vth, kp=4.0, lam=0.01):
    """Level-1 P-MOSFET; pass the threshold magnitude (e.g. 0.9 for -0.9 V)."""
    return f".model {name} PMOS(LEVEL=1 VTO={-abs(vth)} KP={kp} LAMBDA={lam})"


def switch_model(name="SWM", ron=1, roff="1G", vt=0.5, vh=0.1):
    """Voltage-controlled switch for buttons: drive its control with press()."""
    return f".model {name} SW(RON={ron} ROFF={roff} VT={vt} VH={vh})"


# --- Stimulus -----------------------------------------------------------------------------

def pwl(*points):
    """PWL(...) from (time, value) pairs. Values may be numbers or SPICE strings ("1m")."""
    if not points:
        raise ValueError("pwl needs at least one point")
    return "PWL(" + " ".join(f"{_fmt(t)} {_fmt(v)}" for t, v in points) + ")"


def _fmt(value):
    """Numbers to 9 significant digits (so 1e-4 prints as 0.0001, not 9.999999999999999e-05)."""
    return f"{value:.9g}" if isinstance(value, float) else str(value)


def ramp(volts, rise, start=0, end=10):
    """0 V until `start`, rising linearly to `volts` over `rise`, then held until `end`.
    Times may be numbers (seconds) or SPICE strings such as "100u"."""
    t0, t1 = _num(start), _num(start) + _num(rise)
    points = [(0, 0)] + ([(t0, 0)] if t0 > 0 else []) + [(t1, volts), (_num(end), volts)]
    return pwl(*points)


def press(at, length, edge=1e-4, end="10"):
    """Switch-control PWL: 0 until `at` seconds, 1 for `length` seconds, then 0 (numbers only)."""
    return pwl((0, 0), (at, 0), (at + edge, 1), (at + length, 1), (at + length + edge, 0), (end, 0))


def _num(value):
    units = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6}
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().lower()
    for suffix in sorted(units, key=len, reverse=True):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * units[suffix]
    return float(text)


# --- Measurements -------------------------------------------------------------------------

def peak(t, v, start=None, stop=None):
    """Maximum of `v` within [start, stop] (whole trace by default)."""
    values = [x for ti, x in zip(t, v) if (start is None or ti >= start) and (stop is None or ti <= stop)]
    if not values:
        raise ValueError("no samples in the requested window")
    return max(values)


def first_below(t, v, threshold, after=0.0):
    """First time at or after `after` when `v` drops below `threshold`, or None."""
    return next((ti for ti, x in zip(t, v) if ti >= after and x < threshold), None)


def time_between(t, v, low, high):
    """Total time `v` spends strictly between `low` and `high` (e.g. an enable pin sitting in its
    undefined band), counting intervals whose both ends are inside."""
    inside = [low < x < high for x in v]
    return sum(t[i] - t[i - 1] for i in range(1, len(t)) if inside[i] and inside[i - 1])


# --- Corner matrix ------------------------------------------------------------------------

def corners(**axes):
    """Every combination of the given axes, as dicts: corners(vsys=(3.0, 4.2), vth=(0.65, 1.45))."""
    if not axes:
        return [{}]
    names = list(axes)
    return [dict(zip(names, values)) for values in product(*(axes[n] for n in names))]


def label(corner):
    return " ".join(f"{k}={v}" for k, v in corner.items())


def run_matrix(sim, scenario, build, corner_list, nodes, check):
    """Run `build(**corner)` for each corner and apply `check(trace, corner) -> (ok, detail)`.

    Returns (label, ok, detail) rows for ngspice_harness.report(). A simulation error becomes a
    failing row rather than stopping the whole matrix."""
    rows = []
    for corner in corner_list:
        name = f"{scenario} {label(corner)}".strip()
        try:
            trace = sim.run(build(**corner), nodes)
            ok, detail = check(trace, corner)
        except Exception as e:  # noqa: BLE001 - report every corner, including broken ones
            ok, detail = False, f"simulation error: {e}".splitlines()[0]
        rows.append((name, bool(ok), detail))
    return rows
