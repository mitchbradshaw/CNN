#!/usr/bin/env python3
"""
Shared primitives for generating Pencil (.pen) documents.

Schema confirmed against Pencil v2.17:
  frame     x y width height fill clip layout children [cornerRadius stroke strokeWidth strokeAlignment]
  text      x y fill content fontFamily fontSize fontWeight        (auto-sized, no width)
  rectangle x y width height fill [cornerRadius stroke strokeWidth strokeAlignment]
  ellipse   x y width height fill
  path      x y width height geometry stroke strokeWidth           (geometry in LOCAL coords)

Only "normal" and "bold" fontWeight values are used -- the only two the probe
confirmed. Hierarchy is carried by size and colour instead.
"""

import itertools
import math
import string

SANS = "Inter"
MONO = "Geist Mono"
CHAR_W = {SANS: 0.52, MONO: 0.60}

C = {
    "page":   "#F4F4F6",
    "white":  "#FFFFFF",
    "black":  "#000000",
    "grey":   "#8E8E93",
    "muted":  "#AEAEB2",
    "border": "#E5E5EA",
    "blue":   "#007AFF",
    "tint":   "#E0F0FF",
    "dark":   "#1C1C1E",
    "darker": "#121214",
    "trace":  "#D9D9DE",
    "ghost":  "#3A3A3C",
    "red":    "#FF4545",
    "green":  "#30D158",
    "gtint":  "#E2F9E9",
    "gink":   "#1E7E34",
    "amber":  "#F59E0B",
    "purple": "#AF52DE",
    "orange": "#FF9F0A",
    # on-dark overlay tints (no alpha channel available, so these are pre-mixed)
    "ov_seed":     "#10305A",
    "ov_interest": "#14402A",
    "ov_artifact": "#4A1F1F",
    "ov_span":     "#0F2E4D",
    "ov_motif":    "#4A3A14",
}

# light -> saturated ramp for density maps
RAMP = ["#F0F0F2", "#DCEAF9", "#B6D6F4", "#7FB8EE", "#3D93E4", "#007AFF"]

_ids = iter("".join(p) for p in itertools.product(string.ascii_letters, repeat=3))


def nid():
    return next(_ids)


def tw(s, size, family=SANS):
    """Estimated rendered width of a text node."""
    return len(s) * size * CHAR_W[family]


# ---------------------------------------------------------------- primitives
def frame(name, x, y, w, h, fill=C["white"], radius=None, stroke=None,
          clip=True, children=None):
    n = {"type": "frame", "id": nid(), "x": x, "y": y, "name": name,
         "clip": clip, "width": w, "height": h, "fill": fill,
         "layout": "none", "children": children if children is not None else []}
    if radius:
        n["cornerRadius"] = radius
    if stroke:
        n["stroke"] = stroke
        n["strokeWidth"] = 1
        n["strokeAlignment"] = "inner"
    return n


def rect(x, y, w, h, fill, radius=None, stroke=None, sw=1):
    n = {"type": "rectangle", "id": nid(), "x": x, "y": y,
         "fill": fill, "width": w, "height": h}
    if radius:
        n["cornerRadius"] = radius
    if stroke:
        n["stroke"] = stroke
        n["strokeWidth"] = sw
        n["strokeAlignment"] = "inner"
    return n


def ellipse(x, y, w, h, fill):
    return {"type": "ellipse", "id": nid(), "x": x, "y": y,
            "fill": fill, "width": w, "height": h}


def text(s, x, y, size=13, fill=C["black"], family=SANS, bold=False):
    return {"type": "text", "id": nid(), "x": x, "y": y, "fill": fill,
            "content": s, "fontFamily": family, "fontSize": size,
            "fontWeight": "bold" if bold else "normal"}


def rtext(s, right, y, size=13, fill=C["black"], family=SANS, bold=False):
    return text(s, right - tw(s, size, family), y, size, fill, family, bold)


def ctext(s, cx, y, size=13, fill=C["black"], family=SANS, bold=False):
    return text(s, cx - tw(s, size, family) / 2, y, size, fill, family, bold)


# ---------------------------------------------------------------- traces
def _rng(seed):
    a = seed & 0xFFFFFFFF

    def f():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = (a ^ (a >> 15)) * (1 | a) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t)) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return f


def trace(x, y, w, h, seed, pts=180, amp=0.30, drift=0.20,
          col=C["trace"], sw=1.2, wobble=13):
    """Signal-like polyline as a .pen path. Geometry is local to the node."""
    r = _rng(seed)
    v = d = 0.0
    out = []
    for i in range(pts):
        d = d * 0.96 + (r() - 0.5) * drift
        v = v * 0.86 + d
        px = (i / (pts - 1)) * w
        py = h / 2 - max(-1.0, min(1.0, v)) * h * amp - math.sin(i / wobble) * h * 0.08
        out.append(("L" if i else "M") + f"{px:.1f} {py:.1f}")
    return {"type": "path", "id": nid(), "x": x, "y": y,
            "width": w, "height": h, "geometry": " ".join(out),
            "stroke": col, "strokeWidth": sw}


def motif_trace(x, y, w, h, seed, cycles=3.0, col=C["orange"], sw=1.8, pts=140):
    """A smoother, more periodic shape -- reads as a resolved motif rather
    than raw signal. Used at the deepest zoom tier."""
    r = _rng(seed)
    jit = [(r() - 0.5) for _ in range(pts)]
    out = []
    for i in range(pts):
        t = i / (pts - 1)
        px = t * w
        env = math.sin(math.pi * t) ** 0.6
        py = h / 2 - math.sin(t * cycles * 2 * math.pi) * h * 0.32 * env \
            - jit[i] * h * 0.05
        out.append(("L" if i else "M") + f"{px:.1f} {py:.1f}")
    return {"type": "path", "id": nid(), "x": x, "y": y,
            "width": w, "height": h, "geometry": " ".join(out),
            "stroke": col, "strokeWidth": sw}


# ---------------------------------------------------------------- chrome
def sidebar(active=0, h=900):
    kids = [rect(18, 18, 28, 28, C["blue"], radius=8)]
    for i in range(4):
        kids.append(rect(21, 190 + i * 46, 22, 22,
                         C["blue"] if i == active else C["muted"], radius=6))
    return frame("sidebar", 0, 0, 64, h, C["white"], children=kids)


def header(workspace, label, right=None, w=1376):
    kids = [rect(0, 43, w, 1, C["border"]),
            text("Signal", 24, 14, 15, bold=True),
            text(workspace, 92, 16, 13, C["grey"]),
            text(label, 92 + tw(workspace, 13) + 20, 17, 11, C["muted"], MONO)]
    if right:
        kids.append(rtext(right, w - 24, 17, 11, C["grey"], MONO))
    return frame("header", 64, 0, w, 44, C["white"], children=kids)


def chip(label, x, y, active=False, family=MONO, size=11, h=24):
    w = tw(label, size, family) + 20
    return [rect(x, y, w, h, C["tint"] if active else C["white"],
                 radius=6, stroke=C["border"]),
            text(label, x + 10, y + (h - size) / 2 - 1, size,
                 C["blue"] if active else C["grey"], family)], w


def button(label, x, y, primary=False, size=11, h=28, family=MONO):
    w = tw(label, size, family) + 28
    return [rect(x, y, w, h, C["blue"] if primary else C["white"], radius=6,
                 stroke=None if primary else C["border"]),
            text(label, x + 14, y + (h - size) / 2 - 1, size,
                 C["white"] if primary else C["black"], family)], w


def keycap(x, y, key, label, w=220, h=52):
    return [rect(x, y, w, h, C["page"], radius=8, stroke=C["border"]),
            rect(x + 13, y + (h - 26) / 2, 26, 26, C["white"], radius=6, stroke=C["border"]),
            text(key, x + 13 + (26 - tw(key, 12, MONO)) / 2, y + h / 2 - 7, 12,
                 C["black"], MONO),
            text(label, x + 49, y + h / 2 - 7, 13)]


def count_nodes(n):
    return 1 + sum(count_nodes(c) for c in n.get("children", []))


def write_doc(path, screens, token="8f3c1d52-0b47-4e19-9a6d-7c2e5b810f44"):
    """Write a .pen document.

    A bare filename is written to the PARENT of the directory holding the
    generators, so `prototyping/generators/build_x.py` writes
    `prototyping/UI_x.pen`.  Pass an absolute path to override.
    """
    import json, os
    if not os.path.isabs(path) and os.sep not in path:
        here = os.path.dirname(os.path.abspath(__file__))
        if os.path.basename(here) == "generators":
            path = os.path.join(os.path.dirname(here), path)
    doc = {"version": "2.17", "children": screens, "fileToken": token}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    print("screens :", [s["name"] for s in screens if "name" in s])
    print("nodes   :", sum(count_nodes(s) for s in screens))
    return doc
