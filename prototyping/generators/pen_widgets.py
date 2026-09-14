#!/usr/bin/env python3
"""
Chart and control widgets for Pencil (.pen) mockups.

Everything here returns a flat list of .pen nodes positioned in the
coordinate space of whatever frame you append them to. Built only from the
five primitives Pencil confirmed: frame, text, rectangle, ellipse, path.

Charts model the seven reference figures from the Underground Brains work:
line traces, baseline/detrend overlays, dSAX symbol strips, slope bars with
a physical threshold, dendrograms, encoding image grids, scalograms, and
onset-aligned ensemble overlays.
"""

import math

from pen_kit import C, MONO, SANS, nid, rect, ellipse, text, rtext, frame, tw, _rng

# symbol palette, matching the reference dSAX figure
SYM = {
    "d": "#8B2E1F",   # fast down
    "D": "#F59E0B",   # down
    "S": "#E5E5EA",   # same
    "U": "#9CB8E8",   # up
    "u": "#2B5BA8",   # fast up
}
SYM_ORDER = ["d", "D", "S", "U", "u"]

# heat ramp for encoding images (jet-ish, as in the GASF/GADF figures)
HEAT = ["#191F5C", "#1B4BA0", "#1E86C9", "#35BFA8", "#8FD44A",
        "#F2E23C", "#F29A2E", "#D6412B", "#8C1D14"]
# magma-ish ramp for scalograms
MAGMA = ["#0B0417", "#2C1152", "#6B1D6E", "#A62E62", "#D6503F",
         "#F0862B", "#F9C932"]
# perceptual ramp for onset-time colouring in ensembles
ONSET = ["#3B1F8F", "#6A2BA0", "#9B36A0", "#C7488B", "#E4646C",
         "#F58C50", "#F9BE3F"]


# ---------------------------------------------------------------- helpers
def dashes(x, y, w, col, dash=7, gap=5, th=1):
    """Fake a dashed rule -- Pencil strokes have no dash array."""
    out, cx = [], x
    while cx < x + w:
        out.append(rect(cx, y, min(dash, x + w - cx), th, col))
        cx += dash + gap
    return out


def vdashes(x, y, h, col, dash=6, gap=5, th=1):
    out, cy = [], y
    while cy < y + h:
        out.append(rect(x, cy, th, min(dash, y + h - cy), col))
        cy += dash + gap
    return out


def _poly(x, y, w, h, pts, col, sw):
    return {"type": "path", "id": nid(), "x": x, "y": y, "width": w, "height": h,
            "geometry": " ".join(("L" if i else "M") + f"{px:.1f} {py:.1f}"
                                 for i, (px, py) in enumerate(pts)),
            "stroke": col, "strokeWidth": sw}


# ---------------------------------------------------------------- traces
def wander(x, y, w, h, seed, pts=220, amp=0.30, drift=0.20, col=C["trace"],
           sw=1.2, wobble=13, ripple=0.0):
    """Slow-wandering signal, optionally with a fine ripple riding on it."""
    r = _rng(seed)
    v = d = 0.0
    P = []
    for i in range(pts):
        d = d * 0.96 + (r() - 0.5) * drift
        v = v * 0.86 + d
        px = (i / (pts - 1)) * w
        py = (h / 2 - max(-1.0, min(1.0, v)) * h * amp
              - math.sin(i / wobble) * h * 0.08
              - math.sin(i / 2.3) * h * ripple)
        P.append((px, py))
    return _poly(x, y, w, h, P, col, sw)


def sawtooth_drops(x, y, w, h, seed, n=6, col=C["trace"], sw=1.3, pts=300):
    """Slow rise, fast fall -- the sharkfin shape from the catalogue figure."""
    r = _rng(seed)
    edges = sorted(r() for _ in range(n - 1))
    edges = [0.0] + edges + [1.0]
    P = []
    for i in range(pts):
        t = i / (pts - 1)
        k = max(j for j in range(len(edges) - 1) if edges[j] <= t)
        span = max(1e-6, edges[k + 1] - edges[k])
        u = (t - edges[k]) / span
        val = u ** 0.85 if u < 0.86 else (1 - (u - 0.86) / 0.14) * 0.86
        P.append((t * w, h * 0.88 - val * h * 0.74))
    return _poly(x, y, w, h, P, col, sw)


def baseline_overlay(x, y, w, h, seed):
    """Raw + rolling baseline + detrended, as in STEP 2 of the reference."""
    out = [wander(x, y, w, h, seed, pts=260, amp=0.26, drift=0.18,
                  col="#C9C9CE", sw=1, ripple=0.03)]
    # the baseline: same walk, heavily smoothed
    r = _rng(seed)
    v = d = 0.0
    raw = []
    for i in range(260):
        d = d * 0.96 + (r() - 0.5) * 0.18
        v = v * 0.86 + d
        raw.append(max(-1.0, min(1.0, v)))
    k = 26
    sm = [sum(raw[max(0, i - k):i + k]) / len(raw[max(0, i - k):i + k])
          for i in range(260)]
    out.append(_poly(x, y, w, h,
                     [((i / 259) * w, h / 2 - s * h * 0.26) for i, s in enumerate(sm)],
                     "#E2551C", 1.8))
    out.append(_poly(x, y, w, h,
                     [((i / 259) * w, h * 0.62 - (raw[i] - sm[i]) * h * 0.55
                       - math.sin(i / 2.3) * h * 0.03) for i in range(260)],
                     "#1F6FB8", 1.4))
    return out


def ensemble(x, y, w, h, n=14, seed=11, onset=0.42, ramp=ONSET, sw=1.1):
    """Onset-aligned drops, coloured by position in the recording."""
    out = []
    r = _rng(seed)
    for j in range(n):
        f = j / max(1, n - 1)
        col = ramp[min(len(ramp) - 1, int(f * len(ramp)))]
        rise = 0.22 + 0.5 * f
        depth = 0.34 + 0.5 * f
        jitter = (r() - 0.5) * 0.05
        P = []
        for i in range(90):
            t = i / 89
            if t < onset:
                u = (t - (onset - rise)) / rise
                val = 0.0 if u < 0 else u ** 2.1
            else:
                u = (t - onset) / max(1e-6, 1 - onset)
                val = 1.0 - (1 - math.exp(-u * 5.2)) * (1 + depth) / (1 + depth)
                val = math.exp(-u * 4.4)
            P.append((t * w, h * 0.80 - val * h * 0.62 * (0.55 + f * 0.7) + jitter * h))
        out.append(_poly(x, y, w, h, P, col, sw))
    out += vdashes(x + w * onset, y, h, C["muted"], 5, 4)
    return out


# ---------------------------------------------------------------- encodings
def symbol_strip(x, y, w, h, seed, n=120, five=True):
    """dSAX band sequence. five=False collapses d/u back into D/U (k=3)."""
    out = []
    r = _rng(seed)
    v = 0.0
    cw = w / n
    for i in range(n):
        v = v * 0.62 + (r() - 0.5)
        a = abs(v)
        if a < 0.22:
            s = "S"
        elif v > 0:
            s = "u" if (five and a > 0.62) else "U"
        else:
            s = "d" if (five and a > 0.62) else "D"
        out.append(rect(x + i * cw, y, max(1.0, cw - 0.6), h, SYM[s]))
    return out


def slope_bars(x, y, w, h, seed, n=96, sigma=0.30):
    """Segment slope with a physical (noise-floor) cut, as in STEP 3b."""
    out = []
    mid = y + h * 0.52
    out.append(rect(x, mid, w, 1, C["border"]))
    r = _rng(seed)
    bw = w / n
    for i in range(n):
        v = (r() - 0.5) * 2
        v = v * (1 + 2.6 * (1 if r() > 0.94 else 0))
        bh = min(h * 0.46, abs(v) * h * 0.30)
        up = v > 0
        col = (SYM["u"] if abs(v) > sigma * 2.6 else SYM["U"]) if up else \
              (SYM["d"] if abs(v) > sigma * 2.6 else SYM["D"])
        if abs(v) < sigma * 0.8:
            col = C["border"]
        out.append(rect(x + i * bw, mid - bh if up else mid,
                        max(1.5, bw - 1.6), max(1.5, bh), col))
    out += dashes(x, mid - h * 0.20, w, SYM["u"], 7, 5)
    out += dashes(x, mid + h * 0.20, w, SYM["d"], 7, 5)
    return out


def heat_grid(x, y, w, h, nx=26, ny=26, seed=5, ramp=HEAT, diag=False):
    """GASF / GADF / recurrence-plot style encoding image."""
    out = []
    cw, ch = w / nx, h / ny
    for i in range(nx):
        for j in range(ny):
            u, v = i / nx, j / ny
            val = (math.sin(u * 7 + seed) * math.cos(v * 7 + seed * 0.7)
                   + math.sin((u + v) * 5.5) * 0.7)
            if diag:
                val -= 2.2 * math.exp(-((u - v) ** 2) / 0.002)
            k = int((val + 2) / 4 * (len(ramp) - 1))
            out.append(rect(x + i * cw, y + j * ch, cw + 0.5, ch + 0.5,
                            ramp[max(0, min(len(ramp) - 1, k))]))
    return out


def scalogram(x, y, w, h, seed=3, ncol=90, nrow=16):
    """Wavelet energy: dark field with bright vertical bursts."""
    out = [rect(x, y, w, h, MAGMA[0])]
    r = _rng(seed)
    cw, ch = w / ncol, h / nrow
    for i in range(ncol):
        burst = 1.0 if r() > 0.82 else 0.16
        for j in range(nrow):
            lo = 1 - j / nrow
            e = burst * (r() * 0.6 + 0.4) * (lo ** 1.6)
            k = int(e * (len(MAGMA) - 1))
            if k > 0:
                out.append(rect(x + i * cw, y + j * ch, cw + 0.5, ch + 0.5,
                                MAGMA[min(len(MAGMA) - 1, k)]))
    return out


# ---------------------------------------------------------------- clustering
def dendrogram(x, y, w, h, nleaves=22, seed=7, groups=None, sw=1.2):
    """Agglomerative merge tree. groups = list of (count, colour)."""
    if groups is None:
        groups = [(5, "#2E7D5B"), (7, "#2B5BA8"), (4, "#7B3FA0"), (6, "#1E8E7E")]
    cols = []
    for n, col in groups:
        cols += [col] * n
    cols = (cols + [C["muted"]] * nleaves)[:nleaves]

    step = w / max(1, nleaves)
    nodes = [{"x": x + step * (i + 0.5), "h": 0.0, "col": cols[i]}
             for i in range(nleaves)]
    out = []
    r = _rng(seed)
    lvl = 0.0
    while len(nodes) > 1:
        # merge the adjacent pair whose colours match first, else any
        idx = 0
        for i in range(len(nodes) - 1):
            if nodes[i]["col"] == nodes[i + 1]["col"]:
                idx = i
                break
        else:
            idx = int(r() * (len(nodes) - 1))
        a, b = nodes[idx], nodes[idx + 1]
        lvl += 0.06 + r() * 0.10
        hh = min(0.97, lvl)
        col = a["col"] if a["col"] == b["col"] else C["muted"]
        ay, by, my = y + h * (1 - a["h"]), y + h * (1 - b["h"]), y + h * (1 - hh)
        out += [rect(a["x"], my, max(1, b["x"] - a["x"]), sw, col),
                rect(a["x"], my, sw, max(1, ay - my), a["col"]),
                rect(b["x"], my, sw, max(1, by - my), b["col"])]
        nodes[idx:idx + 2] = [{"x": (a["x"] + b["x"]) / 2, "h": hh, "col": col}]
    return out


# ---------------------------------------------------------------- controls
def slider(x, y, w, label, value, frac, hint=None, size=10):
    out = [text(label, x, y, size, C["grey"], MONO),
           rtext(value, x + w, y, size, C["black"], MONO),
           rect(x, y + 20, w, 4, C["border"], radius=2),
           rect(x, y + 20, max(4, w * frac), 4, C["blue"], radius=2),
           ellipse(x + w * frac - 6, y + 16, 12, 12, C["blue"])]
    if hint:
        out.append(text(hint, x, y + 32, 9, C["muted"], MONO))
    return out


def selectbox(x, y, w, label, value, size=10):
    return [text(label, x, y, size, C["grey"], MONO),
            rect(x, y + 16, w, 26, C["page"], radius=6, stroke=C["border"]),
            text(value, x + 10, y + 23, size, C["black"], MONO),
            rtext("⌄", x + w - 10, y + 21, 11, C["grey"], MONO)]


def seg_control(x, y, label, items, active, size=10):
    out = [text(label, x, y, size, C["grey"], MONO)]
    widths = [tw(str(s), size, MONO) + 22 for s in items]
    total = sum(widths) + 6
    out.append(rect(x, y + 16, total, 26, C["page"], radius=6, stroke=C["border"]))
    cx = x + 3
    for s, wd in zip(items, widths):
        on = s == active
        if on:
            out.append(rect(cx, y + 19, wd, 20, C["white"], radius=4, stroke=C["border"]))
        out.append(text(str(s), cx + 11, y + 24, size,
                        C["black"] if on else C["grey"], MONO))
        cx += wd
    return out, total


def toggle(x, y, label, on, size=10):
    return [rect(x, y, 30, 18, C["blue"] if on else C["border"], radius=9),
            ellipse(x + (14 if on else 2), y + 2, 14, 14, C["white"]),
            text(label, x + 38, y + 3, size, C["black"], MONO)]


def stat(x, y, label, value, col=None, size=10):
    return [text(label, x, y, 9, C["muted"], MONO),
            text(value, x, y + 14, 13, col or C["black"], MONO)]
