#!/usr/bin/env python3
"""Run ngspice transient simulations from Python through libngspice (no packages needed).

KiCad bundles libngspice (on macOS there is no ngspice CLI). This module loads it with ctypes,
runs a netlist, and returns the requested node voltages, plus small helpers for pass/fail checks.
Copy it next to a project's simulation scripts (e.g. scripts/spice/) so they rerun anywhere.

    from ngspice_harness import NgSpice, time_above, first_above, report
    sim = NgSpice()
    tr = sim.run(netlist_text, ["en", "gate"])
    blip = time_above(tr.time, tr["en"], 1.2)

    python3 ngspice_harness.py --selftest    # RC step response vs. the analytic answer

Set NGSPICE_LIB to use a specific libngspice.
"""
from __future__ import annotations

import ctypes
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field

LIB_CANDIDATES = [
    "/Applications/KiCad/KiCad.app/Contents/PlugIns/sim/libngspice.dylib",
    "/opt/homebrew/lib/libngspice.dylib",
    "/usr/local/lib/libngspice.dylib",
    "/usr/lib/x86_64-linux-gnu/libngspice.so.0",
    "libngspice.so",
    "libngspice.so.0",
]


class NgSpiceError(RuntimeError):
    pass


def library_candidates(env=None):
    """Paths to try, NGSPICE_LIB first."""
    env = os.environ if env is None else env
    override = env.get("NGSPICE_LIB")
    return ([override] if override else []) + LIB_CANDIDATES


@dataclass
class Trace:
    """One transient result: a time axis and a voltage list per requested node."""
    time: list[float]
    nodes: dict[str, list[float]] = field(default_factory=dict)

    def __getitem__(self, node: str) -> list[float]:
        return self.nodes[node]


def parse_wrdata(lines, count):
    """Parse ngspice `wrdata` output for `count` vectors.

    wrdata writes a (time, value) column pair per vector on each row.
    """
    time, values = [], [[] for _ in range(count)]
    for line in lines:
        cols = line.split()
        if not cols:
            continue
        if len(cols) < 2 * count:
            raise NgSpiceError(f"wrdata row has {len(cols)} columns, expected {2 * count}: {line!r}")
        row = [float(c) for c in cols]
        time.append(row[0])
        for i in range(count):
            values[i].append(row[2 * i + 1])
    return time, values


class NgSpice:
    """A loaded libngspice. Keep one per process; runs are sequential."""

    def __init__(self, lib_path: str | None = None):
        self.output: list[str] = []
        self._lib = self._load(lib_path)

    def _load(self, lib_path):
        lib = None
        tried = [lib_path] if lib_path else library_candidates()
        for path in tried:
            try:
                lib = ctypes.CDLL(path)
                break
            except OSError:
                continue
        if lib is None:
            raise NgSpiceError("libngspice not found; install KiCad or set NGSPICE_LIB. Tried: "
                               + ", ".join(tried))
        send_char = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        send_stat = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        controlled_exit = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool,
                                           ctypes.c_int, ctypes.c_void_p)
        send_data = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_void_p)
        send_init = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
        bg_running = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)

        def on_char(text, _id, _user):
            self.output.append(text.decode(errors="replace"))
            return 0

        # Keep the callbacks referenced for the library's lifetime.
        self._callbacks = [
            send_char(on_char),
            send_stat(lambda *_: 0),
            controlled_exit(lambda *_: 0),
            send_data(lambda *_: 0),
            send_init(lambda *_: 0),
            bg_running(lambda *_: 0),
        ]
        lib.ngSpice_Init(*self._callbacks[:5], self._callbacks[5], None)
        return lib

    def command(self, cmd: str) -> int:
        return self._lib.ngSpice_Command(cmd.encode())

    def run(self, netlist: str, nodes: list[str]) -> Trace:
        """Load `netlist` (must include its analysis line and .end), run it, return `nodes`.

        Node names are plain (`"en"`); they are read as v(<node>).
        """
        self.output.clear()
        self.command("destroy all")
        lines = [line.encode() for line in netlist.strip().splitlines()] + [None]
        array = (ctypes.c_char_p * len(lines))(*lines)
        if self._lib.ngSpice_Circ(array) != 0:
            raise NgSpiceError("netlist rejected:\n" + "\n".join(self.output[-20:]))
        if self.command("run") != 0:
            raise NgSpiceError("simulation failed:\n" + "\n".join(self.output[-20:]))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.txt")
            self.command(f"wrdata {out} " + " ".join(f"v({n})" for n in nodes))
            if not os.path.exists(out):
                raise NgSpiceError("no data written:\n" + "\n".join(self.output[-20:]))
            with open(out) as f:
                time, values = parse_wrdata(f, len(nodes))
        if not time:
            raise NgSpiceError("simulation produced no points:\n" + "\n".join(self.output[-20:]))
        return Trace(time, dict(zip(nodes, values)))


def time_above(t, v, threshold):
    """Total time `v` spends above `threshold` (both ends of a step above counts)."""
    return sum(t[i] - t[i - 1] for i in range(1, len(t)) if v[i] > threshold and v[i - 1] > threshold)


def first_above(t, v, threshold, after=0.0):
    """First time at or after `after` when `v` exceeds `threshold`, or None."""
    return next((t[i] for i in range(len(t)) if t[i] >= after and v[i] > threshold), None)


def value_at(t, v, when):
    """`v` linearly interpolated at time `when` (clamped to the ends)."""
    if when <= t[0]:
        return v[0]
    for i in range(1, len(t)):
        if t[i] >= when:
            span = t[i] - t[i - 1]
            frac = 0.0 if span == 0 else (when - t[i - 1]) / span
            return v[i - 1] + frac * (v[i] - v[i - 1])
    return v[-1]


def report(results, out=sys.stdout):
    """Print (label, ok, detail) rows; return a process exit code (1 if anything failed)."""
    failed = 0
    for label, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label:36s} {detail}", file=out)
        failed += not ok
    print(f"\n{failed} check(s) failed" if failed else "\nall checks passed", file=out)
    return 1 if failed else 0


SELFTEST_NETLIST = """* RC step: 10k / 100n, tau = 1 ms
V1 in 0 PWL(0 0 1u 1 10m 1)
R1 in out 10k
C1 out 0 100n
.tran 5u 10m
.end
"""


def selftest(sim=None):
    """Check the library against an RC step response: v(tau) = 1 - 1/e, v(5 tau) ~ 1."""
    sim = sim or NgSpice()
    tr = sim.run(SELFTEST_NETLIST, ["out"])
    at_tau = value_at(tr.time, tr["out"], 1e-3 + 1e-6)
    at_5tau = value_at(tr.time, tr["out"], 5e-3 + 1e-6)
    expected = 1 - math.exp(-1)
    return [
        ("RC at 1 tau", abs(at_tau - expected) < 0.01, f"{at_tau:.4f} V (expected {expected:.4f} V)"),
        ("RC at 5 tau", abs(at_5tau - (1 - math.exp(-5))) < 0.01, f"{at_5tau:.4f} V"),
    ]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--selftest"]:
        print(__doc__)
        return 2
    return report(selftest())


if __name__ == "__main__":
    sys.exit(main())
