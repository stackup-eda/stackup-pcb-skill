#!/usr/bin/env python3
"""Measure a KiCad footprint so it can be compared against the part's package drawing.

Reports the footprint's properties (value, manufacturer, MPN and other fields), pad count and
numbering, each pad's position, size, net and pin function (on a board), pad pitch, the span of the pads, the body outline (Fab
layer), the courtyard, and any board cutout the footprint carries on Edge.Cuts with its smallest
gap to a pad. Compare those numbers with the manufacturer's package drawing and recommended land
pattern; a name that looks right proves nothing.

    footprint_geometry.py LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount
    footprint_geometry.py path/to/Part.kicad_mod
    footprint_geometry.py --pcb PCB/board.kicad_pcb --ref D1     # what is actually on the board
    footprint_geometry.py --pcb PCB/board.kicad_pcb              # every footprint on the board
    footprint_geometry.py --pcb PCB/board.kicad_pcb --ref D1 --pins 1=VDD,2=DOUT,3=GND,4=DIN
    footprint_geometry.py ... --json

--pins takes the datasheet's pin table (number=name) and checks that pad N is the datasheet's
pin N: the same pad numbers, and on a board, the same pin function on each pad. It exits 3 when
they differ.

`Lib:Name` is looked up as <dir>/<Lib>.pretty/<Name>.kicad_mod in each --lib-dir, then in
KICAD_FOOTPRINT_DIR, then in the standard KiCad install locations. Coordinates are in mm in the
footprint's own frame (unrotated), matching a package drawing's top view.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass

DEFAULT_FOOTPRINT_DIRS = [
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
    "/usr/share/kicad/footprints",
    "/usr/local/share/kicad/footprints",
]

ROUND = 4  # decimal places used when grouping pads into rows/columns
ARC_STEPS = 16  # straight segments used to approximate an arc or circle on Edge.Cuts


# --- S-expression parsing -------------------------------------------------------------------

def tokenize(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "()":
            yield c
            i += 1
        elif c.isspace():
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 1
                buf.append(text[j])
                j += 1
            yield ("str", "".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield text[i:j]
            i = j


def parse(text):
    """Parse KiCad S-expression text into nested lists. Quoted strings stay strings."""
    stack = [[]]
    for tok in tokenize(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            if len(stack) < 2:
                raise ValueError("unbalanced ')'")
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(tok[1] if isinstance(tok, tuple) else tok)
    if len(stack) != 1:
        raise ValueError("unbalanced '('")
    return stack[0]


def children(node, name):
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == name]


def child(node, name):
    found = children(node, name)
    return found[0] if found else None


def numbers(node, count):
    return [float(v) for v in node[1:1 + count]]


# --- Geometry --------------------------------------------------------------------------------

@dataclass
class Pad:
    number: str
    kind: str
    shape: str
    x: float
    y: float
    width: float
    height: float
    drill: float | None = None
    corner_radius: float = 0.0
    net: str | None = None
    pin_function: str | None = None


@dataclass
class Box:
    width: float
    height: float
    min_x: float
    min_y: float
    max_x: float
    max_y: float


def box_of(points):
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Box(round(max(xs) - min(xs), ROUND), round(max(ys) - min(ys), ROUND),
               min(xs), min(ys), max(xs), max(ys))


def graphic_points(item):
    """Points that bound one fp_* graphic item."""
    kind = item[0]
    if kind in ("fp_line", "fp_rect"):
        return [numbers(child(item, "start"), 2), numbers(child(item, "end"), 2)]
    if kind == "fp_circle":
        cx, cy = numbers(child(item, "center"), 2)
        ex, ey = numbers(child(item, "end"), 2)
        r = math.hypot(ex - cx, ey - cy)
        return [[cx - r, cy - r], [cx + r, cy + r]]
    if kind == "fp_arc":
        return [numbers(child(item, k), 2) for k in ("start", "mid", "end") if child(item, k)]
    if kind == "fp_poly":
        pts = child(item, "pts")
        return [numbers(xy, 2) for xy in children(pts, "xy")] if pts else []
    return []


def layer_box(footprint, layer_suffix):
    """Bounding box of all graphics on F.<suffix> (or B.<suffix> if the front has none)."""
    for side in ("F.", "B."):
        points = []
        for item in footprint[1:]:
            if isinstance(item, list) and item and item[0] in (
                    "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
                layer = child(item, "layer")
                if layer and layer[1] == side + layer_suffix:
                    points.extend(graphic_points(item))
        if points:
            return box_of(points)
    return None


def arc_points(start, mid, end, steps=ARC_STEPS):
    """Points along the circular arc through start, mid and end (a straight line if collinear)."""
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [list(start), list(end)]
    ux = ((ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)) / d
    uy = ((ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0, am, a1 = (math.atan2(y - uy, x - ux) for x, y in (start, mid, end))
    sweep = (a1 - a0) % (2 * math.pi)
    if (am - a0) % (2 * math.pi) > sweep:  # mid lies on the other way round
        sweep -= 2 * math.pi
    return [[ux + r * math.cos(a0 + sweep * i / steps), uy + r * math.sin(a0 + sweep * i / steps)]
            for i in range(steps + 1)]


def graphic_segments(item):
    """One fp_* graphic item as straight segments ((x1, y1), (x2, y2))."""
    kind = item[0]
    if kind == "fp_line":
        return [(numbers(child(item, "start"), 2), numbers(child(item, "end"), 2))]
    if kind == "fp_rect":
        (x1, y1), (x2, y2) = numbers(child(item, "start"), 2), numbers(child(item, "end"), 2)
        corners = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        return list(zip(corners, corners[1:] + corners[:1]))
    if kind == "fp_arc":
        pts = arc_points(*(numbers(child(item, k), 2) for k in ("start", "mid", "end")))
        return list(zip(pts, pts[1:]))
    if kind == "fp_circle":
        cx, cy = numbers(child(item, "center"), 2)
        r = math.hypot(*(a - b for a, b in zip(numbers(child(item, "end"), 2), (cx, cy))))
        pts = [[cx + r * math.cos(2 * math.pi * i / ARC_STEPS), cy + r * math.sin(2 * math.pi * i / ARC_STEPS)]
               for i in range(ARC_STEPS)]
        return list(zip(pts, pts[1:] + pts[:1]))
    if kind == "fp_poly":
        pts = graphic_points(item)
        return list(zip(pts, pts[1:] + pts[:1])) if len(pts) > 1 else []
    return []


def edge_cut_segments(footprint):
    """Segments of every graphic the footprint puts on Edge.Cuts (a board cutout or slot)."""
    segments = []
    for item in footprint[1:]:
        if isinstance(item, list) and item and item[0] in (
                "fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
            layer = child(item, "layer")
            if layer and layer[1] == "Edge.Cuts":
                segments.extend(graphic_segments(item))
    return segments


def _segment_distance(p1, p2, q1, q2):
    """Shortest distance between segments p1-p2 and q1-q2 (0 if they cross)."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1, d2, d3, d4 = cross(q1, q2, p1), cross(q1, q2, p2), cross(p1, p2, q1), cross(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4):
        return 0.0

    def point_segment(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
        return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
    return min(point_segment(p1, q1, q2), point_segment(p2, q1, q2),
               point_segment(q1, p1, p2), point_segment(q2, p1, p2))


def pad_clearance(segments, pads):
    """Smallest gap from any segment to any pad's copper outline, with rounded corners (roundrect,
    oval and circle pads) taken into account. Returns (gap_mm, pad_number), or None when either
    list is empty."""
    best = None
    for pad in pads:
        # A pad with corner radius r is the set of points within r of its rectangle shrunk by r.
        r = pad.corner_radius
        x1, y1 = pad.x - pad.width / 2 + r, pad.y - pad.height / 2 + r
        x2, y2 = pad.x + pad.width / 2 - r, pad.y + pad.height / 2 - r
        corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        for a, b in segments:
            if any(x1 <= p[0] <= x2 and y1 <= p[1] <= y2 for p in (a, b)):
                gap = 0.0
            else:
                gap = max(0.0, min(_segment_distance(a, b, c, d)
                                   for c, d in zip(corners, corners[1:] + corners[:1])) - r)
            if best is None or gap < best[0]:
                best = (gap, pad.number)
    return (round(best[0], ROUND), best[1]) if best else None


def properties_of(footprint):
    """The footprint's non-empty fields (Reference, Value, manufacturer, MPN and so on)."""
    props = {}
    for prop in children(footprint, "property"):
        if len(prop) > 2 and isinstance(prop[1], str) and isinstance(prop[2], str) and prop[2]:
            props[prop[1]] = prop[2]
    return props


def _last_text(node):
    """The name in a (net 3 "GND"), (net "GND") or (pinfunction "VDD") node, or None."""
    return str(node[-1]) if node and len(node) > 1 and str(node[-1]) else None


def pad_sort_key(number):
    return (len(number), number)


def read_pads(footprint, footprint_angle=0.0):
    """Pads in the footprint's own frame. In a .kicad_pcb, a pad's angle includes the footprint's
    rotation, so it is subtracted to recover the pad's own orientation."""
    pads = []
    for pad in children(footprint, "pad"):
        at = child(pad, "at")
        x, y = float(at[1]), float(at[2])
        angle = (float(at[3]) if len(at) > 3 else 0.0) - footprint_angle
        w, h = numbers(child(pad, "size"), 2)
        if round(angle / 90) % 2:
            w, h = h, w
        drill_node = child(pad, "drill")
        drill = None
        if drill_node:
            values = [v for v in drill_node[1:] if not isinstance(v, list) and v != "oval"]
            drill = float(values[0]) if values else None
        shape = str(pad[3])
        if shape in ("circle", "oval"):
            radius = min(w, h) / 2
        elif shape == "roundrect":
            ratio = child(pad, "roundrect_rratio")
            radius = min(w, h) * (float(ratio[1]) if ratio else 0.25)
        else:
            radius = 0.0
        pads.append(Pad(str(pad[1]), str(pad[2]), shape, x, y, w, h, drill, radius,
                        _last_text(child(pad, "net")), _last_text(child(pad, "pinfunction"))))
    return pads


def pitches(pads):
    """Distinct center-to-center spacings between neighbouring pads in each row and column."""
    found = set()
    for axis, other in ((0, 1), (1, 0)):
        lines = {}
        for p in pads:
            key = round((p.x, p.y)[other], ROUND)
            lines.setdefault(key, []).append((p.x, p.y)[axis])
        for coords in lines.values():
            coords = sorted(set(round(c, ROUND) for c in coords))
            found.update(round(b - a, ROUND) for a, b in zip(coords, coords[1:]))
    return sorted(found)


def measure(footprint, footprint_angle=0.0):
    pads = read_pads(footprint, footprint_angle)
    attr = child(footprint, "attr")
    centers = box_of([(p.x, p.y) for p in pads])
    extent = box_of([pt for p in pads for pt in
                     ((p.x - p.width / 2, p.y - p.height / 2), (p.x + p.width / 2, p.y + p.height / 2))])
    cuts = edge_cut_segments(footprint)
    clearance = pad_clearance(cuts, pads)
    return {
        "name": footprint[1],
        "properties": properties_of(footprint),
        "type": attr[1] if attr else "unspecified",
        "pad_count": len(pads),
        "pad_numbers": sorted({p.number for p in pads}, key=pad_sort_key),
        "pads": [asdict(p) for p in pads],
        "pitches": pitches(pads),
        "pad_center_span": asdict(centers) if centers else None,
        "pad_outer_extent": asdict(extent) if extent else None,
        "body_fab": asdict(b) if (b := layer_box(footprint, "Fab")) else None,
        "courtyard": asdict(b) if (b := layer_box(footprint, "CrtYd")) else None,
        "edge_cuts": asdict(b) if (b := box_of([pt for seg in cuts for pt in seg])) else None,
        "edge_cuts_pad_clearance": {"gap": clearance[0], "pad": clearance[1]} if clearance else None,
    }


# --- Pin numbering against the datasheet ------------------------------------------------------

def parse_pins(text):
    """'1=VDD,2=DOUT' (commas or spaces) as {"1": "VDD", "2": "DOUT"}."""
    pins = {}
    for item in text.replace(",", " ").split():
        number, sep, name = item.partition("=")
        if not sep or not number or not name:
            raise ValueError(f"expected number=name in --pins, got {item!r}")
        if number in pins:
            raise ValueError(f"pin {number} given twice in --pins")
        pins[number] = name
    return pins


def pin_name(pin_function, pad_number):
    """A pad's pin function without the "_<pad number>" suffix Stackup's sync adds (VSS_1 -> VSS)."""
    suffix = "_" + pad_number
    if pin_function.endswith(suffix) and len(pin_function) > len(suffix):
        return pin_function[:-len(suffix)]
    return pin_function


def check_pins(m, pins):
    """Compare a measured footprint with the datasheet's pin table {number: name}.

    Each pad N must exist for datasheet pin N and, where the board records a pin function, carry
    pin N's name (case-insensitive). Returns one row per pin or pad, with status "ok", "mismatch",
    "missing" (no such pad), "extra" (a pad the datasheet doesn't list) or "unchecked" (no pin
    function on the pad, so only its number could be compared). A "_<pad number>" suffix on the pin
    function, as Stackup's sync writes it, is ignored."""
    by_number = {}
    for p in m["pads"]:
        by_number.setdefault(p["number"], []).append(p)
    rows = []
    for number in sorted(set(pins) | set(by_number), key=pad_sort_key):
        expected, pads = pins.get(number), by_number.get(number, [])
        functions = sorted({pin_name(p["pin_function"], number) for p in pads if p["pin_function"]})
        nets = sorted({p["net"] for p in pads if p["net"]})
        if expected is None:
            status = "extra"
        elif not pads:
            status = "missing"
        elif not functions:
            status = "unchecked"
        elif all(f.casefold() == expected.casefold() for f in functions):
            status = "ok"
        else:
            status = "mismatch"
        rows.append({"pad": number, "datasheet": expected, "pin_function": ", ".join(functions) or None,
                     "net": ", ".join(nets) or None, "status": status})
    return rows


def format_pin_check(rows):
    lines = ["", "Datasheet pin numbering:",
             f"{'Pad':>4}  {'datasheet':12} {'pad function':12} {'net':16} result"]
    for r in rows:
        lines.append(f"{r['pad']:>4}  {r['datasheet'] or '-':12} {r['pin_function'] or '-':12} "
                     f"{r['net'] or '-':16} {r['status']}")
    bad = [r for r in rows if r["status"] in ("mismatch", "missing", "extra")]
    if bad:
        lines.append("FAIL: pad numbers don't follow the datasheet's pin numbers. Renumber the "
                     "footprint's pads and the part's pin-to-pad map together.")
    elif any(r["status"] == "unchecked" for r in rows):
        lines.append("Pad numbers match; pads without a pin function were not checked by name: "
                     "compare their position and net with the datasheet's pinout drawing.")
    else:
        lines.append("OK: every pad carries the datasheet's pin of the same number.")
    return "\n".join(lines)


def pins_ok(rows):
    return not any(r["status"] in ("mismatch", "missing", "extra") for r in rows)


# --- Finding the footprint -------------------------------------------------------------------

def find_library_file(lib_name, lib_dirs, env=None):
    env = os.environ if env is None else env
    lib, _, name = lib_name.partition(":")
    if not name:
        raise ValueError(f"expected Lib:Name, got {lib_name!r}")
    dirs = list(lib_dirs) + ([env["KICAD_FOOTPRINT_DIR"]] if env.get("KICAD_FOOTPRINT_DIR") else [])
    dirs += DEFAULT_FOOTPRINT_DIRS
    for d in dirs:
        path = os.path.join(d, f"{lib}.pretty", f"{name}.kicad_mod")
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(f"{lib_name} not found in: " + ", ".join(dirs))


def load_library_footprint(text):
    root = parse(text)
    for node in root:
        if isinstance(node, list) and node and node[0] in ("footprint", "module"):
            return node
    raise ValueError("no footprint in file")


def reference_of(footprint):
    for prop in children(footprint, "property"):
        if len(prop) > 2 and prop[1] == "Reference":
            return prop[2]
    text = [t for t in children(footprint, "fp_text") if len(t) > 2 and t[1] == "reference"]
    return text[0][2] if text else None


def board_footprints(text):
    """Every footprint on a .kicad_pcb as (reference, footprint, rotation on the board)."""
    root = parse(text)
    board = root[0] if root and isinstance(root[0], list) else root
    found = []
    for fp in children(board, "footprint"):
        at = child(fp, "at")
        found.append((reference_of(fp), fp, float(at[3]) if at and len(at) > 3 else 0.0))
    return found


def load_board_footprint(text, ref):
    """The footprint placed as `ref` in a .kicad_pcb, and its rotation on the board."""
    for found_ref, fp, angle in board_footprints(text):
        if found_ref == ref:
            return fp, angle
    raise LookupError(f"no footprint with reference {ref!r} on the board")


# --- Output ----------------------------------------------------------------------------------

def fmt(v):
    return f"{v:.3f}"


def format_report(m):
    lines = [f"Footprint: {m['name']}"]
    lines += [f"  {k}: {v}" for k, v in m["properties"].items()]
    connected = any(p["net"] or p["pin_function"] for p in m["pads"])
    lines += [f"Type: {m['type']}   Pads: {m['pad_count']} (numbers {', '.join(m['pad_numbers'])})",
             "", f"{'Pad':>4} {'X':>8} {'Y':>8} {'W':>7} {'H':>7}  {'shape':10} {'drill':6}" +
             (f" {'function':12} net" if connected else "")]
    for p in sorted(m["pads"], key=lambda p: (*pad_sort_key(p["number"]), p["x"], p["y"])):
        drill = fmt(p["drill"]) if p["drill"] else "-"
        line = (f"{p['number']:>4} {fmt(p['x']):>8} {fmt(p['y']):>8} {fmt(p['width']):>7} "
                f"{fmt(p['height']):>7}  {p['shape']:10} {drill:6}")
        if connected:
            line += f" {p['pin_function'] or '-':12} {p['net'] or '-'}"
        lines.append(line.rstrip())
    lines.append("")
    lines.append("Pitch (neighbouring pad centers): " +
                 (", ".join(fmt(v) for v in m["pitches"]) or "-"))
    for label, key in (("Pad center span", "pad_center_span"), ("Pad outer extent", "pad_outer_extent"),
                       ("Body (Fab layer)", "body_fab"), ("Courtyard", "courtyard")):
        b = m[key]
        lines.append(f"{label + ':':18} " + (f"{fmt(b['width'])} x {fmt(b['height'])}" if b else "none"))
    b, c = m["edge_cuts"], m["edge_cuts_pad_clearance"]
    lines.append(f"{'Edge.Cuts cutout:':18} " + (
        f"{fmt(b['width'])} x {fmt(b['height'])}, closest pad {c['pad']} at {fmt(c['gap'])} mm "
        "(compare with the fab's copper-to-edge minimum)" if b and c else
        f"{fmt(b['width'])} x {fmt(b['height'])}" if b else "none"))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("footprint", nargs="?", help="Lib:Name or a .kicad_mod path")
    parser.add_argument("--pcb", help="read the footprints placed on this .kicad_pcb instead")
    parser.add_argument("--ref", help="reference designator to read from --pcb (default: all)")
    parser.add_argument("--lib-dir", action="append", default=[],
                        help="extra directory containing <Lib>.pretty folders (repeatable)")
    parser.add_argument("--pins", help="datasheet pin table, e.g. 1=VDD,2=DOUT,3=GND,4=DIN: check "
                        "that pad N is pin N (needs one footprint: a Lib:Name, a path or --ref)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.pins and args.pcb and not args.ref:
        parser.error("--pins checks one footprint: add --ref")

    try:
        if args.pcb:
            with open(args.pcb) as f:
                text = f.read()
            if args.ref:
                found = [(args.ref, *load_board_footprint(text, args.ref))]
            else:
                found = board_footprints(text)
        elif args.footprint:
            path = args.footprint if args.footprint.endswith(".kicad_mod") else \
                find_library_file(args.footprint, args.lib_dir)
            with open(path) as f:
                found = [(None, load_library_footprint(f.read()), 0.0)]
        else:
            parser.error("give a footprint (Lib:Name or path) or --pcb")
    except (OSError, ValueError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        pins = parse_pins(args.pins) if args.pins else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    results = [measure(fp, angle) for _, fp, angle in found]
    rows = check_pins(results[0], pins) if pins else None
    if args.json:
        out = results if args.pcb and not args.ref else results[0]
        if rows is not None:
            out = dict(out, pin_check=rows)
        print(json.dumps(out, indent=2))
    else:
        report = "\n\n".join(format_report(m) for m in results)
        print(report + ("\n" + format_pin_check(rows) if rows is not None else ""))
    return 3 if rows is not None and not pins_ok(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
