#!/usr/bin/env python3
"""
Generate Pencil (.pen) drafts for the Underground Brains Review workspace.

Four screens, laid out left to right on one canvas:
    review-A-focus          single candidate, keyboard-first, max throughput
    review-B-contactsheet   grid triage with batch verdicts
    review-C-inspector      queue + context + evidence, three columns
    review-C2-inspector-rev revised C: collapsed rails, verdict + annotation
                            rows, cluster-aware, family-affinity signals

Run:  python build_pen.py  ->  UI_frontend_prototype_v2.pen

Schema notes (derived from a hand-made probe file, Pencil v2.17):
  frame     x y width height fill clip layout children
  text      x y fill content fontFamily fontSize fontWeight   (auto-sized)
  rectangle x y width height fill [cornerRadius stroke strokeWidth strokeAlignment]
  ellipse   x y width height fill
  path      x y width height geometry stroke strokeWidth      (geometry in LOCAL coords)

Two deliberate conservatisms, both one-line changes at the top of this file:
  * fontWeight uses only "normal" and "bold" -- the only values the probe
    confirmed. Hierarchy is carried by size and colour instead.
  * Text nodes have no width in .pen, so right-aligned text is positioned with
    an estimated advance width (see `tw`). Nudge CHAR_W if it looks off.
"""

import json
import string

SANS = "Inter"
MONO = "Geist Mono"      # if Pencil lacks it, swap to "JetBrains Mono" or "monospace"
CHAR_W = {SANS: 0.52, MONO: 0.60}   # advance width as a fraction of font size

# ---------------------------------------------------------------- palette
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
    "trace":  "#D9D9DE",
    "ghost":  "#3A3A3C",
    "red":    "#FF4545",
    "green":  "#30D158",
    "gtint":  "#E2F9E9",
    "gink":   "#1E7E34",
    "amber":  "#F59E0B",
    "purple": "#AF52DE",
}

_ids = iter("".join(p) for p in __import__("itertools").product(
    string.ascii_letters, repeat=3))


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
    """Right-aligned text, positioned by estimated width."""
    return text(s, right - tw(s, size, family), y, size, fill, family, bold)


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
    """A signal-like polyline as a .pen path node. Geometry is local."""
    import math
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


# ---------------------------------------------------------------- chrome
def sidebar(active=2):
    kids = [rect(18, 18, 28, 28, C["blue"], radius=8)]
    for i in range(4):
        kids.append(rect(21, 190 + i * 46, 22, 22,
                         C["blue"] if i == active else C["muted"], radius=6))
    return frame("sidebar", 0, 0, 64, 900, C["white"], children=kids)


def header(label, right=None):
    kids = [
        rect(0, 43, 1376, 1, C["border"]),
        text("Signal", 24, 14, 15, bold=True),
        text("Review", 92, 16, 13, C["grey"]),
        text(label, 152, 17, 11, C["muted"], MONO),
    ]
    if right:
        kids.append(rtext(right, 1352, 17, 11, C["grey"], MONO))
    return frame("header", 64, 0, 1376, 44, C["white"], children=kids)


def chip(label, x, y, active=False, family=MONO, size=11):
    w = tw(label, size, family) + 20
    return [rect(x, y, w, 24, C["tint"] if active else C["white"],
                 radius=6, stroke=C["border"]),
            text(label, x + 10, y + 6, size,
                 C["blue"] if active else C["grey"], family)]


def keycap(x, y, key, label, w=232, h=56):
    return [
        rect(x, y, w, h, C["page"], radius=8, stroke=C["border"]),
        rect(x + 14, y + 14, 28, 28, C["white"], radius=6, stroke=C["border"]),
        text(key, x + 14 + (28 - tw(key, 12, MONO)) / 2, y + 22, 12, C["black"], MONO),
        text(label, x + 52, y + 33 - 14, 13),
    ]


VERDICTS = [("S", "seed"), ("I", "interesting"), ("N", "not interesting"),
            ("A", "artifact"), ("U", "unsure")]


# ================================================================ SCREEN A
def screen_a(ox):
    k = [sidebar(), header("Focus  ·  one candidate, keyboard-first",
                           "342 / 1284 adjudicated")]

    bar = []
    cx = 24
    for lab, act in [("Matrix Profile", True), ("CH4_A2", False),
                     ("score ≥ 0.72", False), ("unadjudicated", False)]:
        bar += chip(lab, cx, 12, act)
        cx += tw(lab, 11, MONO) + 28
    bar += [rect(1000, 24, 240, 3, C["border"], radius=2),
            rect(1000, 24, 64, 3, C["blue"], radius=2)]
    k.append(frame("filter-bar", 64, 44, 1376, 52, C["page"], children=bar))

    plot = [rect(531, 0, 210, 208, C["tint"], stroke=C["blue"]),
            trace(0, 0, 1272, 208, 9137),
            trace(531, 0, 210, 208, 4421, pts=120, amp=0.34, drift=0.24,
                  col=C["red"], sw=1.6)]
    k.append(frame("candidate-context", 88, 124, 1312, 318, C["white"],
                   radius=10, stroke=C["border"], children=[
        text("Candidate 343", 20, 18, 14, bold=True),
        text("CH4_A2   ·   14:22:06 → 14:22:41   ·   35.0 s   ·   ±120 s context",
             20, 42, 11, C["grey"], MONO),
        rtext("0.84", 1292, 16, 22, C["black"], SANS, True),
        rtext("matrix profile", 1292, 44, 10, C["muted"], MONO),
        frame("plot", 20, 86, 1272, 208, C["dark"], radius=6, children=plot),
    ]))

    zp = [trace(0, 0, 604, 142, 300 + i * 77, pts=90, amp=0.26, drift=0.20,
                col=C["ghost"], sw=1) for i in range(6)]
    zp.append(trace(0, 0, 604, 142, 911, pts=90, amp=0.26, drift=0.20,
                    col=C["blue"], sw=2))
    k.append(frame("znorm-overlay", 88, 466, 644, 224, C["white"],
                   radius=10, stroke=C["border"], children=[
        text("Matched members, z-normalised", 20, 16, 13, bold=True),
        text("7 members  ·  shared relative-time axis", 20, 38, 10, C["grey"], MONO),
        frame("plot", 20, 62, 604, 142, C["dark"], radius=6, children=zp),
    ]))

    ev = [text("Against the null", 20, 16, 13, bold=True),
          text("phase-randomised surrogate  ·  seed 20260913", 20, 38, 10, C["grey"], MONO)]
    for i, (lab, n, frac, col) in enumerate([
            ("detections, real", 1284, 1.0, C["blue"]),
            ("detections, surrogate", 212, 0.165, C["muted"])]):
        y = 74 + i * 34
        ev += [text(lab, 20, y, 11, C["grey"]),
               rect(180, y + 1, 380, 10, C["border"], radius=5),
               rect(180, y + 1, max(6, 380 * frac), 10, col, radius=5),
               rtext(str(n), 624, y, 11, C["black"], MONO)]
    ev += [rect(20, 148, tw("6.1× above chance", 11, MONO) + 20, 24,
                C["gtint"], radius=6),
           text("6.1× above chance", 30, 154, 11, C["gink"], MONO),
           text("nearest library exemplar   E-014  ·  d = 0.31  ·  scale-invariant",
                20, 192, 10, C["muted"], MONO)]
    k.append(frame("evidence", 756, 466, 644, 224, C["white"],
                   radius=10, stroke=C["border"], children=ev))

    vb = [text("Verdict", 20, 16, 11, C["muted"], MONO),
          rtext("←  undo last verdict", 1292, 18, 11, C["grey"], MONO),
          rtext("auto-advance on", 1292, 104, 10, C["muted"], MONO)]
    for i, (key, lab) in enumerate(VERDICTS):
        vb += keycap(20 + i * 250, 44, key, lab)
    k.append(frame("verdict-bar", 88, 714, 1312, 122, C["white"],
                   radius=10, stroke=C["border"], children=vb))

    return frame("review-A-focus", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ SCREEN B
def screen_b(ox):
    k = [sidebar(), header("Contact Sheet  ·  grid triage, batch verdicts")]

    bar = []
    cx = 24
    for lab, act in [("Matrix Profile", True), ("CH4_A2", False),
                     ("unadjudicated", False)]:
        bar += chip(lab, cx, 12, act)
        cx += tw(lab, 11, MONO) + 28
    bar.append(rtext("sort  score ↓      group  none", 1352, 19, 11, C["grey"], MONO))
    k.append(frame("filter-bar", 64, 44, 1376, 52, C["page"], children=bar))

    bb = [text("4 selected", 16, 14, 12, C["blue"], SANS, True),
          text("mark all as", 100, 15, 11, C["grey"], MONO),
          rtext("clear selection", 1312, 15, 11, C["grey"], MONO)]
    bx = 180
    for lab in ["seed", "interesting", "not interesting", "artifact", "unsure"]:
        w = tw(lab, 11) + 24
        bb += [rect(bx, 9, w, 26, C["white"], radius=6, stroke=C["border"]),
               text(lab, bx + 12, 15, 11)]
        bx += w + 8
    k.append(frame("batch-bar", 88, 100, 1328, 44, C["tint"], radius=8, children=bb))

    grid = [("c-0341", "0.91", "sel"), ("c-0342", "0.88", "sel"), ("c-0343", "0.84", ""),
            ("c-0344", "0.81", "seed"), ("c-0345", "0.79", ""), ("c-0346", "0.78", "artifact"),
            ("c-0347", "0.77", "sel"), ("c-0348", "0.76", ""), ("c-0349", "0.74", "interesting"),
            ("c-0350", "0.73", "sel"), ("c-0351", "0.72", "not"), ("c-0352", "0.72", ""),
            ("c-0353", "0.71", ""), ("c-0354", "0.70", "artifact"), ("c-0355", "0.69", ""),
            ("c-0356", "0.68", ""), ("c-0357", "0.67", "interesting"), ("c-0358", "0.66", "")]
    badge = {"seed": ("seed", C["blue"]), "artifact": ("artifact", C["red"]),
             "interesting": ("interesting", C["green"]), "not": ("not interesting", C["muted"])}

    for i, (cid, score, state) in enumerate(grid):
        col, row = i % 6, i // 6
        sel = state == "sel"
        kids = [text(cid, 14, 13, 10, C["grey"], MONO),
                rtext(score, 194, 13, 10, C["black"], MONO),
                frame("thumb", 14, 36, 180, 92, C["dark"], radius=5, children=[
                    trace(0, 0, 180, 92, 1000 + i * 137, pts=70, amp=0.30,
                          drift=0.26, col=C["blue"] if sel else C["trace"],
                          sw=1.3, wobble=7)])]
        if state in badge:
            lab, bc = badge[state]
            kids += [ellipse(14, 145, 6, 6, bc),
                     text(lab, 26, 140, 10, C["grey"], MONO)]
        elif sel:
            kids.append(text("selected", 14, 140, 10, C["blue"], MONO))
        else:
            kids.append(text("unadjudicated", 14, 140, 10, C["muted"], MONO))
        k.append(frame("candidate/" + cid, 88 + col * 224, 160 + row * 196,
                       208, 180, C["tint"] if sel else C["white"], radius=10,
                       stroke=C["blue"] if sel else C["border"], children=kids))

    k.append(frame("queue-footer", 88, 764, 1328, 56, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("showing 18 of 1284", 16, 20, 12, C["black"], SANS, True),
        text("342 adjudicated  ·  942 remaining  ·  ~1.9 s / candidate this session",
             180, 21, 11, C["grey"], MONO),
        rtext("load next 18  →", 1312, 21, 11, C["blue"], MONO)]))

    return frame("review-B-contactsheet", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ SCREEN C
def screen_c(ox):
    k = [sidebar(), header("Inspector  ·  queue + context + evidence")]

    q = [rect(299, 0, 1, 856, C["border"]),
         text("Queue", 20, 20, 14, C["black"], SANS, True),
         text("942 unadjudicated", 20, 44, 11, C["grey"], MONO)]
    fy = 78
    for key, val in [("method", "Matrix Profile"), ("channel", "CH4_A2"),
                     ("score", "≥ 0.66"), ("status", "unadjudicated")]:
        q += [rect(20, fy, 260, 28, C["page"], radius=6),
              text(key, 30, fy + 8, 10, C["muted"], MONO),
              rtext(val, 270, fy + 7, 11, C["black"], MONO)]
        fy += 34
    q.append(rect(20, fy + 8, 260, 1, C["border"]))

    rows = [("c-0341", "0.91", None), ("c-0342", "0.88", None), ("c-0343", "0.84", "active"),
            ("c-0344", "0.81", "seed"), ("c-0345", "0.79", None), ("c-0346", "0.78", "artifact"),
            ("c-0347", "0.77", None), ("c-0348", "0.76", None), ("c-0349", "0.74", "interesting"),
            ("c-0350", "0.73", None), ("c-0351", "0.72", "not")]
    dots = {"seed": C["blue"], "artifact": C["red"],
            "interesting": C["green"], "not": C["muted"]}
    ry = fy + 24
    for cid, score, st in rows:
        act = st == "active"
        q += [rect(20, ry, 260, 52, C["tint"] if act else C["white"], radius=8,
                   stroke=C["blue"] if act else None),
              text(cid, 30, ry + 9, 11, C["blue"] if act else C["black"], MONO),
              rtext(score, 270, ry + 10, 10, C["grey"], MONO),
              frame("spark", 30, ry + 28, 240, 18, C["dark"], radius=3, children=[
                  trace(0, 0, 240, 18, 500 + ry, pts=48, amp=0.32, drift=0.30,
                        col=C["blue"] if act else C["trace"], sw=1, wobble=5)])]
        if st and not act:
            q.append(ellipse(264, ry + 32, 6, 6, dots[st]))
        ry += 56
    k.append(frame("queue-panel", 64, 44, 300, 856, C["white"], children=q))

    X, W = 388, 728
    k += [text("Candidate 343", X, 62, 16, C["black"], SANS, True),
          text("CH4_A2   ·   14:22:06 → 14:22:41   ·   35.0 s   ·   run mp_CH4_w36",
               X, 88, 11, C["grey"], MONO)]

    k.append(frame("candidate-context", X, 112, W, 268, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("In context", 18, 16, 12),
        rtext("±120 s  ·  drag to extend", 710, 18, 10, C["muted"], MONO),
        frame("plot", 18, 44, 692, 206, C["dark"], radius=6, children=[
            rect(287, 0, 118, 206, C["tint"], stroke=C["blue"]),
            trace(0, 0, 692, 206, 3311),
            trace(287, 0, 118, 206, 8822, pts=80, amp=0.34, drift=0.26,
                  col=C["red"], sw=1.6)])]))

    zp = [trace(0, 0, 692, 150, 2200 + i * 91, pts=80, amp=0.26, drift=0.22,
                col=C["ghost"], sw=1) for i in range(6)]
    zp.append(trace(0, 0, 692, 150, 777, pts=80, amp=0.26, drift=0.22,
                    col=C["blue"], sw=2))
    k.append(frame("znorm-overlay", X, 396, W, 212, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("Members, z-normalised", 18, 16, 12),
        rtext("7 members  ·  shared relative-time axis", 710, 18, 10, C["muted"], MONO),
        frame("plot", 18, 44, 692, 150, C["dark"], radius=6, children=zp)]))

    xc = [text("Cross-channel members", 18, 16, 12),
          rtext("lag from cross-correlation peak", 710, 18, 10, C["muted"], MONO),
          text("2 artifact-binned members excluded from library counts",
               18, 166, 10, C["red"], MONO)]
    for i, (name, desc, n, col) in enumerate([
            ("artifact", "near-zero lag, identical waveform", "2", C["red"]),
            ("propagation", "small consistent lag, waveform varies", "4", C["amber"]),
            ("independent recurrence", "lag scattered", "1", C["green"])]):
        y = 52 + i * 32
        xc += [ellipse(18, y + 5, 8, 8, col), text(name, 36, y, 12),
               text(desc, 260, y + 2, 10, C["grey"], MONO),
               rtext(n, 710, y, 12, C["black"], MONO)]
    k.append(frame("cross-channel", X, 624, W, 200, C["white"], radius=10,
                   stroke=C["border"], children=xc))

    ev = [rect(0, 0, 1, 856, C["border"]),
          text("Evidence", 20, 20, 14, C["black"], SANS, True),
          text("0.84", 20, 48, 30, C["black"], SANS, True),
          text("matrix profile distance", 20, 88, 10, C["grey"], MONO),
          rect(20, 116, 260, 1, C["border"]),
          text("AGAINST THE NULL", 20, 130, 10, C["muted"], MONO)]
    for i, (nm, n, frac, col) in enumerate([("real", 1284, 1.0, C["blue"]),
                                            ("surrogate", 212, 0.165, C["muted"])]):
        y = 154 + i * 28
        ev += [text(nm, 20, y, 11, C["grey"]),
               rect(98, y + 3, 130, 8, C["border"], radius=4),
               rect(98, y + 3, max(5, 130 * frac), 8, col, radius=4),
               rtext(str(n), 280, y + 1, 10, C["black"], MONO)]
    ev += [rect(20, 214, tw("6.1× above chance", 10, MONO) + 18, 22, C["gtint"], radius=6),
           text("6.1× above chance", 29, 219, 10, C["gink"], MONO),
           rect(20, 248, 260, 1, C["border"]),
           text("NEAREST EXEMPLARS", 20, 262, 10, C["muted"], MONO)]
    for i, (eid, d, kind) in enumerate([("E-014", "0.31", "scale-inv"),
                                        ("E-007", "0.44", "symbolic"),
                                        ("E-022", "0.58", "native")]):
        y = 284 + i * 50
        ev += [rect(20, y, 260, 44, C["page"], radius=6),
               frame("thumb", 28, y + 10, 56, 24, C["dark"], radius=3, children=[
                   trace(0, 0, 56, 24, 60 + y, pts=44, amp=0.32, drift=0.30,
                         col=C["trace"], sw=1, wobble=5)]),
               text(eid, 94, y + 8, 11, C["black"], MONO),
               text(kind, 94, y + 24, 9, C["muted"], MONO),
               rtext("d " + d, 272, y + 16, 10, C["grey"], MONO)]
    ev += [rect(20, 440, 260, 1, C["border"]),
           text("MORPHOLOGY TAGS", 20, 454, 10, C["muted"], MONO)]
    tx, ty = 20, 476
    for tag, on in [("spike-train", True), ("slow-drift", False), ("burst", True),
                    ("plateau", False), ("biphasic", False)]:
        w = tw(tag, 10, MONO) + 18
        if tx + w > 280:
            tx, ty = 20, ty + 30
        ev += [rect(tx, ty, w, 22, C["tint"] if on else C["page"], radius=6,
                    stroke=C["blue"] if on else None),
               text(tag, tx + 9, ty + 5, 10, C["blue"] if on else C["grey"], MONO)]
        tx += w + 6
    ev += [rect(20, 556, 260, 1, C["border"]),
           text("VERDICT", 20, 570, 10, C["muted"], MONO),
           rtext("← undo", 280, 570, 10, C["grey"], MONO)]
    for i, (key, lab) in enumerate(VERDICTS):
        y = 592 + i * 50
        ev += [rect(20, y, 260, 44, C["page"], radius=8, stroke=C["border"]),
               rect(30, y + 10, 24, 24, C["white"], radius=5, stroke=C["border"]),
               text(key, 30 + (24 - tw(key, 11, MONO)) / 2, y + 17, 11, C["black"], MONO),
               text(lab, 64, y + 14, 12)]
    k.append(frame("evidence-panel", 1140, 44, 300, 856, C["white"], children=ev))

    return frame("review-C-inspector", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ SCREEN C2
def screen_c2(ox):
    """Revised inspector: rails collapsed, verdict + annotation rows below,
    cluster-aware batch verdict, family-affinity signalling."""
    k = [sidebar(), header("Inspector rev  ·  rails collapsed, cluster-aware",
                           "342 / 1284  ·  ~1.9 s / candidate")]

    # --- collapsed queue rail -------------------------------------------
    qr = [rect(55, 0, 1, 856, C["border"]),
          text("›", 24, 12, 15, C["grey"]),
          text("48", (56 - tw("48", 11, MONO)) / 2, 40, 11, C["black"], MONO),
          text("clusters", (56 - tw("clusters", 8, MONO)) / 2, 56, 8, C["muted"], MONO)]
    for i in range(14):
        on = i == 4
        qr.append(frame("q%d" % i, 10, 84 + i * 38, 36, 30,
                        C["tint"] if on else C["page"], radius=5,
                        stroke=C["blue"] if on else None, children=[
            trace(0, 0, 36, 30, 180 + i * 53, pts=26, amp=0.30, drift=0.34,
                  col=C["blue"] if on else C["muted"], sw=1, wobble=4)]))
    k.append(frame("queue-rail (collapsed)", 64, 44, 56, 856, C["white"], children=qr))

    # --- collapsed evidence rail ----------------------------------------
    er = [rect(0, 0, 1, 856, C["border"]), text("‹", 24, 12, 15, C["grey"])]
    for i, (v, col) in enumerate([("0.84", C["black"]), ("6.1×", C["green"]),
                                  ("d.19", C["purple"]), ("7", C["blue"])]):
        er.append(text(v, (56 - tw(v, 10, MONO)) / 2, 44 + i * 26, 10, col, MONO))
    k.append(frame("evidence-rail (collapsed)", 1384, 44, 56, 856, C["white"], children=er))

    X, W = 144, 1216

    # --- title + the three always-visible signals ------------------------
    k += [text("Cluster 12", X, 60, 16, C["black"], SANS, True),
          text("7 members", X + 104, 66, 11, C["grey"], MONO),
          text("CH4_A2  ·  exemplar c-0343  ·  14:22:06 → 14:22:41  ·  35.0 s",
               X, 88, 11, C["grey"], MONO)]
    sx = X + 560
    for key, val, col in [("verdict", "unadjudicated", C["muted"]),
                          ("family affinity", "F-03  d 0.19", C["purple"]),
                          ("member cohesion", "mean d 0.24", C["blue"])]:
        w = 30 + tw(key, 10, MONO) + tw(val, 11, MONO) + 20
        k += [rect(sx, 62, w, 30, C["white"], radius=7, stroke=C["border"]),
              ellipse(sx + 10, 73, 7, 7, col),
              text(key, sx + 25, 69, 10, C["muted"], MONO),
              text(val, sx + 25 + tw(key, 10, MONO) + 8, 68, 11, col, MONO)]
        sx += w + 10

    # --- wide context ----------------------------------------------------
    k.append(frame("candidate-context", X, 116, W, 288, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("Exemplar in context", 18, 16, 12),
        rtext("±120 s  ·  drag to extend  ·  ⌥ scroll to zoom",
              1198, 18, 10, C["muted"], MONO),
        frame("plot", 18, 44, 1180, 226, C["dark"], radius=6, children=[
            rect(492, 0, 196, 226, C["tint"], stroke=C["blue"]),
            trace(0, 0, 1180, 226, 3311),
            trace(492, 0, 196, 226, 8822, pts=110, amp=0.34, drift=0.26,
                  col=C["red"], sw=1.6)])]))

    # --- members + nearest families -------------------------------------
    zp = [trace(0, 0, 560, 118, 2200 + i * 91, pts=80, amp=0.26, drift=0.22,
                col=C["ghost"], sw=1) for i in range(6)]
    zp.append(trace(0, 0, 560, 118, 777, pts=80, amp=0.26, drift=0.22,
                    col=C["blue"], sw=2))
    k.append(frame("member-overlay", X, 416, 596, 180, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("Members, z-normalised", 18, 14, 12),
        rtext("7  ·  mean d 0.24", 578, 16, 10, C["muted"], MONO),
        frame("plot", 18, 42, 560, 118, C["dark"], radius=6, children=zp)]))

    fam = [text("Nearest families", 18, 14, 12),
           rtext("low distance ≠ interesting", 578, 16, 10, C["muted"], MONO)]
    for i, (fid, d, tag, col) in enumerate([
            ("F-03", "0.19", "spike-train", C["purple"]),
            ("F-11", "0.37", "burst", C["muted"]),
            ("F-07", "0.52", "slow-drift", C["muted"])]):
        y = 44 + i * 44
        fam += [rect(18, y, 560, 38, C["page"], radius=6),
                ellipse(28, y + 16, 7, 7, col),
                text(fid, 46, y + 12, 11, C["black"], MONO),
                text(tag, 108, y + 13, 10, C["grey"], MONO),
                rect(258, y + 16, 180, 6, C["border"], radius=3),
                rect(258, y + 16, max(6, 180 * (1 - float(d))), 6, col, radius=3),
                rtext("d " + d, 568, y + 13, 10, C["grey"], MONO)]
    k.append(frame("family-affinity", X + 620, 416, 596, 180, C["white"],
                   radius=10, stroke=C["border"], children=fam))

    # --- verdict row (moved out of the evidence column) ------------------
    vb = [text("Verdict", 20, 16, 11, C["muted"], MONO),
          # backward navigation: revisit and change a prior verdict
          rect(20, 40, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("‹", 30, 45, 13, C["grey"]),
          rect(52, 40, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("›", 62, 45, 13, C["grey"]),
          text("c-0342 was marked interesting", 88, 47, 10, C["muted"], MONO),
          # batch verdict across a clustered queue entry
          rect(760, 14, 16, 16, C["white"], radius=4, stroke=C["border"]),
          text("Verdict for all 7 members", 784, 15, 11, C["black"], MONO),
          rtext("← undo  (reverses the whole cluster)", 1196, 16, 10, C["grey"], MONO)]
    for i, (key, lab) in enumerate(VERDICTS):
        vb += keycap(20 + i * 236, 76, key, lab, w=220, h=52)
    k.append(frame("verdict-row", X, 616, W, 148, C["white"], radius=10,
                   stroke=C["border"], children=vb))

    # --- annotation row: tags, class, notes ------------------------------
    an = [text("Annotate", 20, 14, 11, C["muted"], MONO),
          text("optional — only for motifs worth the time", 92, 15, 10, C["muted"], MONO),
          text("morphology tags", 20, 40, 10, C["grey"], MONO)]
    tx = 20
    for tag, on in [("spike-train", True), ("slow-drift", False), ("burst", True),
                    ("plateau", False), ("biphasic", False), ("+ new", False)]:
        w = tw(tag, 10, MONO) + 18
        an += [rect(tx, 60, w, 24, C["tint"] if on else C["page"], radius=6,
                    stroke=C["blue"] if on else C["border"]),
               text(tag, tx + 9, 66, 10, C["blue"] if on else C["grey"], MONO)]
        tx += w + 6
    an += [text("class", 480, 40, 10, C["grey"], MONO),
           rect(480, 60, 220, 24, C["page"], radius=6, stroke=C["border"]),
           text("unassigned", 490, 66, 10, C["grey"], MONO),
           rtext("⌄", 692, 64, 11, C["grey"], MONO),
           text("notes", 724, 40, 10, C["grey"], MONO),
           rect(724, 60, 472, 24, C["page"], radius=6, stroke=C["border"]),
           text("shape recurs on CH2 at ~0.5× duration — check scale invariance",
                734, 66, 10, C["muted"], MONO)]
    k.append(frame("annotation-row", X, 776, W, 104, C["white"], radius=10,
                   stroke=C["border"], children=an))

    return frame("review-C2-inspector-rev", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ output
doc = {
    "version": "2.17",
    "children": [screen_a(0), screen_b(1560), screen_c(3120), screen_c2(4680)],
    "fileToken": "8f3c1d52-0b47-4e19-9a6d-7c2e5b810f44",
}

with open("UI_frontend_prototype_v2.pen", "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, ensure_ascii=False)


def count(n):
    return 1 + sum(count(c) for c in n.get("children", []))


print("screens :", [c["name"] for c in doc["children"]])
print("nodes   :", sum(count(c) for c in doc["children"]))
