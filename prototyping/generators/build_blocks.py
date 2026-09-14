#!/usr/bin/env python3
"""
Analyse block pages, v3.  Every block page follows one pattern:

    toolbar   source chip  +  "< back to the full chain"  +  primary action
    ribbon    the whole chain, the selected block highlighted
    body      that block's settings and that block's output

Page 1 is the chain itself (where you build it, or import a template); clicking
a block's settings icon opens its page. Nothing else is a "page".

Chains covered:

  detection      Source > Baseline > Encoding > Noise floor > Detection
  interrogation  Library family > Resolve spans > Aggregate
  training       Source > Sliding windows > Window matrix > Cluster > Encode > Model

Run:  python build_blocks.py  ->  UI_analyse_discovery_v3.pen
"""

import math

from pen_kit import (C, MONO, SANS, nid, frame, rect, ellipse, text, rtext,
                     ctext, chip, button, tw, write_doc, _rng)
from pen_widgets import (SYM, SYM_ORDER, HEAT, MAGMA, ONSET, dashes, vdashes,
                         wander, sawtooth_drops, baseline_overlay, ensemble,
                         symbol_strip, slope_bars, heat_grid, dendrogram,
                         slider, selectbox, seg_control, toggle, stat, _poly)

NAV = ["Explore", "Analyse", "Discovery", "Review", "Library"]
X, W = 88, 1328

# diverging ramp for z-scored feature matrices
DIVERGE = ["#2166AC", "#4393C3", "#92C5DE", "#D1E5F0", "#F7F7F7",
           "#FDDBC7", "#F4A582", "#D6604D", "#B2182B"]
CLASS_COLS = ["#E4574C", "#3E8FD6", "#E8963C", "#4FAE6A", "#9B6BD6", "#3FB5A8"]

DETECT = [("●", "Source"), ("01", "Baseline"), ("02", "Encoding"),
          ("03", "Noise floor"), ("04", "Detection")]
INTERR = [("●", "Library family"), ("01", "Resolve spans"),
          ("02", "Aggregate")]
TRAIN = [("●", "Source"), ("01", "Sliding windows"), ("02", "Window matrix"),
         ("03", "Cluster"), ("04", "Encode"), ("05", "Model")]


# ---------------------------------------------------------------- chrome
def nav(active=1, h=900):
    kids = [rect(18, 18, 28, 28, C["blue"], radius=8)]
    for i in range(len(NAV)):
        kids.append(rect(21, 170 + i * 46, 22, 22,
                         C["blue"] if i == active else C["muted"], radius=6))
    return frame("sidebar", 0, 0, 64, h, C["white"], children=kids)


def head(workspace, label, right=None, w=1376):
    kids = [rect(0, 43, w, 1, C["border"]),
            text("Signal", 24, 14, 15, bold=True),
            text(workspace, 92, 16, 13, C["grey"]),
            text(label, 92 + tw(workspace, 13) + 20, 17, 11, C["muted"], MONO)]
    if right:
        kids.append(rtext(right, w - 24, 17, 11, C["grey"], MONO))
    return frame("header", 64, 0, w, 44, C["white"], children=kids)


def sliders_icon(x, y, col=None):
    col = col or C["grey"]
    return [rect(x, y, 20, 20, C["page"], radius=5),
            rect(x + 4, y + 6, 12, 1.6, col), ellipse(x + 12, y + 4, 5, 5, col),
            rect(x + 4, y + 13, 12, 1.6, col), ellipse(x + 5, y + 11, 5, 5, col)]


def status_badge(x, y, state):
    col = {"cached": C["gink"], "stale": "#9A6206", "new": C["muted"]}[state]
    bg = {"cached": C["gtint"], "stale": "#FDF0D5", "new": C["page"]}[state]
    w = tw(state, 9, MONO) + 16
    return [rect(x, y, w, 17, bg, radius=5),
            text(state, x + 8, y + 4, 9, col, MONO)], w


def toolbar(source, back=True, actions=(), note=None):
    k = [text("source", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip(source, 70, 12, True)
    k += p
    if note:
        k.append(text(note, 80 + cw, 20, 10, C["muted"], MONO))
    bx = 1376 - 24
    for label, primary in reversed(actions):
        p, bw = button(label, 0, 11, primary=primary, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        k += p
        bx -= 12
    if back:
        k.append(text("‹ back to the full chain", 24, 38, 10, C["blue"], MONO))
    return frame("toolbar", 64, 44, 1376, 56, C["page"], children=k)


def ribbon(blocks, active, y=108, h=60):
    k = [text("chain", 16, h / 2 - 6, 9, C["muted"], MONO)]
    cx = 62
    for idx, name in blocks:
        on = idx == active
        src = idx == "●"
        bw = tw(name, 10, MONO) + 32
        k += [rect(cx, 12, bw, h - 24, C["tint"] if on else
                   (C["gtint"] if src else C["page"]), radius=7,
                   stroke=C["blue"] if on else C["border"]),
              text(idx, cx + 11, 19, 9, C["muted"], MONO),
              text(name, cx + 11, 32, 10, C["blue"] if on else C["black"], MONO)]
        cx += bw
        if (idx, name) != blocks[-1]:
            k.append(text("›", cx + 6, h / 2 - 8, 12, C["muted"]))
            cx += 20
    k.append(rtext("click any block to open it", W - 16, h / 2 - 6, 9,
                   C["muted"], MONO))
    return frame("chain-ribbon", X, y, W, h, C["white"], radius=10,
                 stroke=C["border"], children=k)


def card(name, x, y, w, h, kids, fill=None, stroke=None):
    return frame(name, x, y, w, h, fill or C["white"], radius=10,
                 stroke=stroke or C["border"], children=kids)


def page(name, workspace, label, right, source, blocks, active, body,
         actions=(), note=None, back=True):
    k = [nav(1), head(workspace, label, right),
         toolbar(source, back, actions, note), ribbon(blocks, active)]
    k += body
    return frame(name, 0, 0, 1440, 900, C["page"], children=k)


# ---------------------------------------------------------------- charts
def noisy_step(x, y, w, h, seed, col, step=0.42, sw=1.0, pts=200):
    r = _rng(seed)
    P = []
    for i in range(pts):
        t = i / (pts - 1)
        base = 0.72 if t < step else (0.30 if t < step + 0.22 else 0.46)
        P.append((t * w, h * (1 - base) + (r() - 0.5) * h * 0.22))
    return _poly(x, y, w, h, P, col, sw)


def rose(x, y, R, items, spokes=(-15, -30, -45, -60, -75)):
    out = []
    P = [(R * math.cos(math.radians(-90 * t)), R * math.sin(math.radians(90 * t)))
         for t in [i / 60 for i in range(61)]]
    out.append(_poly(x, y, R, R, P, C["black"], 1.4))
    for a in spokes:
        r = math.radians(-a)
        out.append(_poly(x, y, R, R, [(0, 0), (R * math.cos(r), R * math.sin(r))],
                         C["border"], 1))
        out.append(text("%d°" % a, x + (R + 8) * math.cos(r) - 4,
                        y + (R + 8) * math.sin(r) - 6, 9, C["muted"], MONO))
    out += [text("0° flat", x + R + 8, y - 6, 9, C["muted"], MONO),
            text("−90°", x - 14, y + R + 8, 9, C["muted"], MONO)]
    for i, (ang, ramp_pos, ringed) in enumerate(items):
        r = math.radians(-ang)
        rad = R * (0.30 + 0.62 * (i / max(1, len(items) - 1)))
        px, py = x + rad * math.cos(r) - 5, y + rad * math.sin(r) - 5
        col = ONSET[min(len(ONSET) - 1, int(ramp_pos * len(ONSET)))]
        if ringed:
            out += [ellipse(px - 5, py - 5, 20, 20, C["purple"]),
                    ellipse(px - 2, py - 2, 14, 14, C["white"])]
        out.append(ellipse(px, py, 10, 10, col))
    return out


def bars(x, y, w, h, vals, cols, labels=None, maxv=None, size=9, gap=6):
    out = []
    maxv = maxv or max(vals)
    bw = w / len(vals)
    for i, v in enumerate(vals):
        bh = max(2, v / maxv * h)
        col = cols[i] if isinstance(cols, list) else cols
        out.append(rect(x + i * bw + gap / 2, y + h - bh, bw - gap, bh, col,
                        radius=3))
        if labels:
            out.append(text(labels[i], x + i * bw + gap / 2, y + h + 5, size,
                            C["muted"], MONO))
    return out


def matrix_heat(x, y, w, rows, ncol, seed=5, rh=13, gap=1):
    """z-scored feature matrix; rows = [(group, feature, collapsed)]"""
    out = []
    cw = w / ncol
    r = _rng(seed)
    for j, (grp, feat, coll) in enumerate(rows):
        yy = y + j * (rh + gap)
        for i in range(ncol):
            u, v = i / ncol, j / max(1, len(rows))
            val = (math.sin(u * 9 + j * 1.7) * math.cos(v * 5 + u * 11)
                   + (r() - 0.5) * 1.1)
            if 0.55 < u < 0.62:
                val += 1.6
            k = int((val + 2.4) / 4.8 * (len(DIVERGE) - 1))
            out.append(rect(x + i * cw, yy, cw + 0.4, rh,
                            DIVERGE[max(0, min(len(DIVERGE) - 1, k))]))
    return out


# ================================================================ 1  CHAIN
def p_chain():
    k = [nav(1), head("Analyse", "Chain  ·  build it here, open a block to tune it",
                      "drop_motifs9 · unsaved")]
    tk = [text("source", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("Signal span  ·  CH4_A2  ·  825–875 s", 70, 12, True)
    tk += p
    tk += toggle(430, 15, "surrogate control", True)
    tk.append(text("est. 1.8 s  ·  local", 620, 19, 10, C["muted"], MONO))
    bx = 1376 - 24
    for lab, pri in [("Run chain", True), ("Save as template", False),
                     ("Import template", False)]:
        p, bw = button(lab, 0, 11, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        tk += p
        bx -= 12
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    ROWS = [
        ("●", "Source", "signal span, loaded from Explore",
         "swap for a Library family to interrogate events instead",
         "— → Signal", "cached", 96, "src"),
        ("01", "Baseline removal", "subtract a 7 s rolling median",
         "gradients below are measured on the blue trace",
         "Signal → Signal", "cached", 120, "base"),
        ("02", "Symbolic encoding", "each 0.2 s segment becomes a letter",
         "dSAX k=3, then D and U split by the noise floor",
         "Signal → Encoding", "cached", 96, "sym"),
        ("03", "Noise floor", "the cut is physical, not statistical",
         "σ of slope noise = 0.00958 mV/s, so d starts at 8σ",
         "Encoding → Scores", "stale", 96, "slope"),
        ("04", "Drop detection", "23 raw detections, 6 kept after dedupe",
         "shaded span runs onset → trough",
         "Scores → SpanSet", "stale", 114, "det"),
    ]
    y = 108
    for i, (idx, name, c1, c2, tp, state, h, plot) in enumerate(ROWS):
        kids = [text(idx, 14, 14, 10, C["muted"], MONO),
                text(name, 40, 12, 12, C["black"], SANS, True),
                text(c1, 14, 36, 9, C["grey"], MONO),
                text(c2, 14, 50, 9, C["muted"], MONO),
                text(tp, 14, h - 24, 9, C["muted"], MONO)]
        p, _ = status_badge(120, 12, state)
        kids += p
        kids += sliders_icon(196, 11)
        px, pw = 232, W - 232 - 14
        ph = h - 28
        if plot == "src":
            kids += [rect(px, 14, pw, ph, C["dark"], radius=4),
                     wander(px, 14, pw, ph, 9137, pts=300, amp=0.30, drift=0.20,
                            wobble=17, ripple=0.035, sw=1.3)]
        elif plot == "base":
            kids.append(rect(px, 14, pw, ph, C["white"], radius=4, stroke=C["border"]))
            kids += baseline_overlay(px + 4, 18, pw - 8, ph - 8, 9137)
        elif plot == "sym":
            sh = (ph - 8) / 2
            kids += symbol_strip(px, 14, pw, sh, 21, n=120, five=True)
            kids += symbol_strip(px, 14 + sh + 8, pw, sh, 21, n=120, five=False)
        elif plot == "slope":
            kids.append(rect(px, 14, pw, ph, C["white"], radius=4, stroke=C["border"]))
            kids += slope_bars(px + 6, 20, pw - 12, ph - 12, 33, n=100)
        else:
            kids.append(rect(px, 14, pw, ph, C["dark"], radius=4))
            for mx, mw, col in [(0.11, 0.02, "#3A3A3C"), (0.40, 0.022, "#3A3A3C"),
                                (0.545, 0.034, "#4A2B6B"), (0.845, 0.030, "#16544B")]:
                kids.append(rect(px + pw * mx, 14, pw * mw, ph, col))
            kids.append(wander(px, 14, pw, ph, 9137, pts=280, amp=0.30, drift=0.20,
                               wobble=17, ripple=0.035, sw=1.3))
        k.append(frame("stage/" + name, X, y, W, h,
                       "#FBFDFB" if idx == "●" else C["white"],
                       radius=10, stroke=C["border"], children=kids))
        y += h
        if i < len(ROWS) - 1:
            lab = "+  insert a stage"
            lw = tw(lab, 10, MONO) + 28
            k += [rect(X, y + 9, W, 1, C["border"]),
                  rect(X + (W - lw) / 2, y, lw, 20, C["white"], radius=10,
                       stroke=C["border"]),
                  text(lab, X + (W - lw) / 2 + 14, y + 5, 10, C["grey"], MONO)]
            y += 20

    k.append(card("terminal", X, 738, W, 62, [
        text("This chain ends in SpanSet, so it saves as a detection template "
             "and appears in Discovery's algorithm picker.", 18, 14, 11,
             C["gink"], MONO),
        text("End it in Model and it is a training chain; end it in features "
             "over a SpanSet and it is an interrogation. Same builder, "
             "different terminal type.", 18, 34, 10, C["gink"], MONO)],
        fill=C["gtint"], stroke=C["gtint"]))

    fk = [text("6 detections kept", 20, 18, 13, C["black"], SANS, True),
          text("from 23 raw  ·  surrogate 2  ·  6.1× above chance",
               172, 20, 11, C["grey"], MONO)]
    bx = W - 20
    for lab, pri in [("Pass 6 to Review  →", True),
                     ("Analyse events  →", False), ("Export run", False)]:
        p, bw = button(lab, 0, 11, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        fk += p
        bx -= 10
    k.append(card("footer", X, 812, W, 52, fk))
    return frame("analyse-1-chain", 0, 0, 1440, 900, C["page"], children=k)


# ================================================================ 2  ENCODING
def p_encoding():
    vk = [text("02  Symbolic encoding", 18, 14, 14, C["black"], SANS, True),
          rtext("Signal → Encoding", 782, 19, 10, C["muted"], MONO),
          text("5 bands  (d D S U u)", 18, 44, 9, C["muted"], MONO)]
    vk += symbol_strip(18, 60, 764, 30, 21, n=130, five=True)
    vk.append(text("dSAX k=3  (D S U)", 18, 100, 9, C["muted"], MONO))
    vk += symbol_strip(18, 116, 764, 30, 21, n=130, five=False)
    vk.append(text("segment slope, mV/s", 18, 156, 9, C["muted"], MONO))
    vk.append(rect(18, 170, 764, 92, C["white"], radius=4, stroke=C["border"]))
    vk += slope_bars(24, 176, 752, 80, 33, n=104)
    lx = 18
    for s in SYM_ORDER:
        lab = {"d": "fast down", "D": "down", "S": "same", "U": "up",
               "u": "fast up"}[s]
        vk += [rect(lx, 272, 9, 9, SYM[s]), text(lab, lx + 13, 271, 9,
                                                 C["muted"], MONO)]
        lx += 13 + tw(lab, 9, MONO) + 16

    pk = [text("Parameters", 18, 14, 12),
          rtext("generated from the adapter spec", 490, 17, 9, C["muted"], MONO)]
    p, _ = seg_control(18, 44, "alphabet size  k", [3, 4, 5], 3)
    pk += p
    pk += slider(190, 44, 130, "segment length", "0.2 s", 0.20)
    pk += slider(340, 44, 130, "same_fraction", "0.60", 0.60)
    pk += slider(18, 104, 130, "noise floor", "8 σ", 0.55)
    pk += selectbox(190, 100, 130, "split", "d/D, U/u")
    pk += selectbox(340, 100, 130, "edges", "reflect")
    pk += [rect(18, 164, 470, 1, C["border"]),
           text("At these settings", 18, 176, 11, C["black"], MONO),
           text("60 % of segments land in SAME, which is what", 18, 198, 10,
                C["grey"], MONO),
           text("same_fraction asks for. The 8 σ cut puts 'd' at", 18, 214, 10,
                C["grey"], MONO),
           text("−0.0767 mV/s — falling faster than the noise", 18, 230, 10,
                C["grey"], MONO),
           text("can explain.", 18, 246, 10, C["grey"], MONO)]
    for i, (lab, val, col) in enumerate([("segments", "250", None),
                                         ("qualify as d", "23", SYM["d"]),
                                         ("qualify as u", "31", SYM["u"])]):
        pk += stat(18 + i * 160, 268, lab, val, col)

    sk = [text("This parameter against the null", 18, 14, 12),
          text("every variant runs its own surrogate", 260, 17, 9, C["muted"], MONO),
          rtext("the knee, not the peak", W - 18, 17, 9, C["blue"], MONO)]
    vals = [("2σ", 148, 96), ("4σ", 92, 41), ("6σ", 48, 17),
            ("8σ", 23, 2), ("10σ", 14, 1), ("12σ", 9, 1),
            ("16σ", 4, 0), ("20σ", 1, 0)]
    for i, (lab, det, sur) in enumerate(vals):
        bx = 60 + i * 156
        on = lab == "8σ"
        hd, hs = det / 148 * 80, sur / 148 * 80
        if on:
            sk.append(rect(bx - 6, 40, 92, 100, C["tint"], radius=6))
        sk += [rect(bx, 46 + 80 - hd, 36, hd, C["blue"] if on else "#9CC4F0",
                    radius=3),
               rect(bx + 42, 46 + 80 - max(2, hs), 36, max(2, hs),
                    C["muted"] if on else C["border"], radius=3),
               text(lab, bx + 20, 132, 9, C["blue"] if on else C["muted"], MONO)]
    sk += dashes(52, 126, 1180, C["border"], 6, 6)

    ak = [text("Changes are not applied until you rerun", 20, 20, 11,
               C["muted"], MONO),
          text("stages before this one are cached, so retuning costs 0.4 s — "
               "03 and 04 will recompute", 20, 38, 9, C["gink"], MONO)]
    bx = W - 20
    for lab, pri in [("Apply and rerun from 02  →", True),
                     ("Revert to recommended", False)]:
        p, bw = button(lab, 0, 14, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        ak += p
        bx -= 12

    body = [card("stage-view", X, 180, 800, 296, vk),
            card("parameters", 904, 180, 508, 296, pk),
            card("surrogate-sweep", X, 492, W, 156, sk),
            card("apply", X, 664, W, 62, ak)]
    return page("analyse-2-encoding-block", "Analyse",
                "Block 02 open  ·  symbolic encoding",
                "drop_motifs9 · unsaved",
                "Signal span  ·  CH4_A2  ·  825–875 s", DETECT, "02", body)


# ================================================================ 3  DETECTION
def p_detection():
    dk = [text("04  Drop detection", 18, 14, 14, C["black"], SANS, True),
          rtext("Scores → SpanSet", 782, 19, 10, C["muted"], MONO),
          rect(18, 44, 764, 160, C["dark"], radius=5)]
    for mx, mw, col in [(0.08, 0.018, "#3A3A3C"), (0.19, 0.016, "#3A3A3C"),
                        (0.33, 0.02, "#3A3A3C"), (0.455, 0.030, "#4A2B6B"),
                        (0.60, 0.018, "#3A3A3C"), (0.74, 0.026, "#16544B"),
                        (0.88, 0.016, "#3A3A3C")]:
        dk.append(rect(18 + 764 * mx, 44, 764 * mw, 160, col))
    dk.append(wander(18, 44, 764, 160, 9137, pts=300, amp=0.28, drift=0.18,
                     wobble=17, ripple=0.03, sw=1.3))
    dk.append(text("shaded span runs onset → trough  ·  fill colour is the "
                   "pooled shape family", 18, 214, 9, C["muted"], MONO))
    for i, (lab, val, col) in enumerate([("raw", "23", None),
                                         ("kept", "6", None),
                                         ("surrogate", "2", C["muted"]),
                                         ("above chance", "6.1×", C["gink"])]):
        dk += stat(18 + i * 190, 240, lab, val, col)

    pk = [text("Parameters", 18, 14, 12)]
    pk += slider(18, 44, 200, "minimum depth", "0.10 mV", 0.28,
                 "the instrument floor")
    pk += slider(258, 44, 200, "minimum duration", "0.6 s", 0.18)
    pk += slider(18, 104, 200, "merge window", "2.0 s", 0.34,
                 "adjacent falls closer than this become one")
    pk += slider(258, 104, 200, "trough tolerance", "0.5 σ", 0.22)
    pk += selectbox(18, 164, 200, "dedupe", "keep best-framed")
    pk += selectbox(258, 164, 200, "onset rule", "walk back from steepest")
    pk += [rect(18, 216, 470, 1, C["border"]),
           text("17 of 23 raw detections were dropped: 11 duplicates of a "
                "better-framed copy in another window, 4 below the instrument "
                "floor, 2 shorter than the minimum.", 18, 228, 10,
                C["grey"], MONO),
           text("Dedupe is the parameter that most changes the count — it is "
                "worth looking at what it removed before trusting the number.",
                18, 272, 10, C["blue"], MONO)]

    ck = [text("Each kept detection", 18, 12, 12),
          rtext("click one to centre it above", W - 18, 15, 9, C["muted"], MONO)]
    for i in range(6):
        cx = 18 + i * 218
        on = i == 3
        ck += [rect(cx, 34, 204, 112, C["tint"] if on else C["page"], radius=8,
                    stroke=C["blue"] if on else C["border"]),
               text("M%02d" % (12 + i), cx + 12, 42, 10, C["black"], MONO),
               rtext("%.2f" % (0.91 - i * 0.04), cx + 192, 42, 10, C["grey"], MONO),
               rect(cx + 12, 60, 180, 52, C["dark"], radius=4)]
        ck.append(wander(cx + 12, 60, 180, 52, 800 + i * 73, pts=60, amp=0.34,
                         drift=0.30, col=C["blue"] if on else C["trace"],
                         sw=1.2, wobble=5))
        ck.append(text("unadjudicated", cx + 12, 120, 9, C["muted"], MONO))

    tk = [text("Save this chain as a detection template", 18, 14, 12),
          text("name", 18, 44, 9, C["muted"], MONO),
          rect(58, 40, 290, 26, C["page"], radius=6, stroke=C["border"]),
          text("drop_motifs9 + refine9", 68, 47, 10, C["black"], MONO),
          text("kind", 366, 44, 9, C["muted"], MONO),
          rect(402, 40, 210, 26, C["gtint"], radius=6),
          text("detection  (from terminal type)", 412, 47, 9, C["gink"], MONO),
          text("Templates strip the recording and span, so this runs on a "
               "channel it has never seen.", 18, 78, 10, C["muted"], MONO)]
    bx = W - 18
    for lab, pri in [("Pass 6 to Review  →", True),
                     ("Analyse events  →", False), ("Save template", False)]:
        p, bw = button(lab, 0, 38, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        tk += p
        bx -= 10
    tk.append(rtext("send the 6 spans straight into a new chain as a SpanSet "
                    "source", W - 18, 78, 9, C["muted"], MONO))

    body = [card("stage-view", X, 180, 800, 296, dk),
            card("parameters", 904, 180, 508, 296, pk),
            card("detection-cards", X, 492, W, 158, ck),
            card("save-and-hand-off", X, 666, W, 114, tk)]
    return page("analyse-3-detection-block", "Analyse",
                "Block 04 open  ·  drop detection",
                "drop_motifs9 · run 128",
                "Signal span  ·  CH4_A2  ·  825–875 s", DETECT, "04", body)


# ================================================================ 4a  FAMILY
def p_family():
    mk = [text("●  Library family", 18, 14, 14, C["black"], SANS, True),
          rtext("— → SpanSet", 782, 19, 10, C["muted"], MONO),
          text("F-03  ·  sharkfin  ·  17 members  ·  3 recordings  ·  "
               "2 channels", 18, 42, 10, C["grey"], MONO)]
    for i in range(10):
        cx, cy = 18 + (i % 5) * 154, 66 + (i // 5) * 104
        inc = i not in (7,)
        mk += [rect(cx, cy, 142, 92, C["white"] if inc else C["page"], radius=6,
                    stroke=C["blue"] if inc else C["border"]),
               rect(cx + 8, cy + 22, 126, 44, C["dark"], radius=4)]
        mk.append(sawtooth_drops(cx + 9, cy + 24, 124, 40, 300 + i * 37, n=1,
                                 col=C["orange"] if inc else "#5A5A5E", sw=1.2))
        mk += [rect(cx + 8, cy + 6, 12, 12, C["blue"] if inc else C["white"],
                    radius=3, stroke=None if inc else C["border"]),
               text("s-%04d" % (341 + i), cx + 26, cy + 7, 9, C["black"], MONO),
               text("%.1f h" % (336.9 + i * 0.44), cx + 8, cy + 72, 9,
                    C["muted"], MONO)]
        if not inc:
            mk.append(rtext("excluded", cx + 134, cy + 72, 9, C["red"], MONO))
    mk.append(text("+ 7 more members", 18, 276, 10, C["blue"], MONO))

    pk = [text("Source settings", 18, 14, 12)]
    pk += selectbox(18, 44, 220, "members", "all except excluded  (16)")
    pk += selectbox(258, 44, 220, "resolve from", "original recording")
    pk += slider(18, 104, 220, "context padding", "± 0.5 × span", 0.5,
                 "how much signal either side comes with each member")
    pk += selectbox(258, 100, 220, "on missing source", "fail the run")
    pk += [rect(18, 164, 470, 1, C["border"]),
           text("Members keep their identity", 18, 178, 11, C["black"], MONO),
           text("Span identity is content-based — source file, channel and "
                "sample range — so measurements written downstream land back "
                "on the right member, and re-running the same recipe is "
                "idempotent rather than accumulating orphans.",
                18, 200, 10, C["grey"], MONO),
           rect(18, 262, 470, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("members in", "16", None),
                                         ("excluded", "1", C["red"]),
                                         ("total samples", "1.4 M", None)]):
        pk += stat(18 + i * 160, 274, lab, val, col)

    ok = [text("Where this family came from", 18, 16, 12),
          text("promoted from run 114 on 2 Sept  ·  seeded by exemplar E-014  "
               "·  edges carry the scale-invariant distance", 18, 42, 10,
               C["grey"], MONO),
          text("Excluding a member here does not change the Library entry — it "
               "only scopes this analysis. The exclusion is recorded on the run "
               "so the measurement stays reproducible.", 18, 64, 10,
               C["muted"], MONO)]
    bx = W - 18
    for lab, pri in [("Run measurement  →", True), ("Open in Library", False)]:
        p, bw = button(lab, 0, 40, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        ok += p
        bx -= 10

    body = [card("members", X, 180, 800, 302, mk),
            card("source-settings", 904, 180, 508, 302, pk),
            card("provenance", X, 498, W, 104, ok)]
    return page("analyse-4a-family-block", "Analyse",
                "Block ● open  ·  the family being analysed",
                "F-03 sharkfin · n = 17",
                "Library family  ·  F-03 sharkfin", INTERR, "●", body,
                note="arrived via ‘Analyse events’")


# ================================================================ 4b  SLOPE
def p_slope():
    ak = [text("01  Resolve spans — slope analysis", 18, 14, 14,
               C["black"], SANS, True),
          text("every quantity on the rose comes from three points on each "
               "event", 18, 38, 9, C["muted"], MONO),
          rect(18, 56, 584, 196, C["white"], radius=5, stroke=C["border"])]
    ak.append(rect(196, 58, 210, 192, "#FBEBDC"))
    P = []
    for i in range(120):
        t = i / 119
        if t < 0.30:
            v = 0.62 + 0.22 * math.sin(t * 9)
        elif t < 0.62:
            u = (t - 0.30) / 0.32
            v = 0.84 - 0.78 * u ** 1.15
        else:
            u = (t - 0.62) / 0.38
            v = 0.06 + 0.34 * (1 - math.exp(-u * 3))
        P.append((t * 580, 246 - v * 186))
    ak.append(_poly(20, 58, 580, 192, P, C["black"], 1.6))
    ak += [_poly(196, 58, 212, 192, [(0, 36), (210, 184)], "#C2185B", 1.3),
           _poly(240, 58, 130, 174, [(0, 28), (120, 164)], "#6B6BD6", 1.8),
           ellipse(190, 88, 11, 11, "#1E8E7E"),
           ellipse(400, 236, 11, 11, "#B0245C"),
           rect(286, 150, 16, 16, C["white"], stroke="#6B6BD6", sw=1.6),
           _poly(404, 92, 2, 148, [(0, 0), (0, 146)], "#1E8E7E", 2),
           text("ONSET", 150, 74, 8, "#1E8E7E", MONO),
           text("TROUGH", 386, 250, 8, "#B0245C", MONO),
           text("STEEPEST", 250, 136, 8, "#6B6BD6", MONO),
           text("DEPTH", 414, 158, 8, "#1E8E7E", MONO),
           text("depth 0.378 mV  ·  max slope −0.725 mV/s (−35.9°)  ·  "
                "mean −0.378  ·  peakedness 1.92", 18, 258, 9, C["grey"], MONO)]
    ak += [text("‹", 18, 278, 13, C["grey"]),
           text("event 4 / 16", 40, 280, 10, C["black"], MONO),
           text("›", 120, 278, 13, C["grey"]),
           rtext("peakedness is max ÷ mean — 1.0 is a straight fall",
                 602, 281, 9, C["muted"], MONO)]

    rk = [text("Each fall becomes one angle", 18, 14, 12),
          text("45° = a fall of exactly 1 mV/s — stated, not implied",
               18, 36, 9, C["muted"], MONO),
          text("radius is spacing only; colour is drop height", 18, 50, 9,
               C["muted"], MONO)]
    items = [(-6, 0.05, False), (-11, 0.14, False), (-17, 0.24, False),
             (-22, 0.33, False), (-27, 0.45, False), (-33, 0.56, False),
             (-24, 0.72, False), (-29, 0.80, False), (-31, 0.90, False),
             (-35.9, 0.97, True)]
    rk += rose(44, 86, 178, items)
    rk.append(text("the ringed marker is the event on the left, at −35.9°",
                   18, 292, 9, C["purple"], MONO))

    pk = [text("Parameters", 18, 14, 12),
          rtext("these three rules define every number above", W - 18, 17, 9,
                C["muted"], MONO)]
    pk += selectbox(18, 44, 280, "onset rule",
                    "walk back from steepest while descending")
    pk += selectbox(318, 44, 280, "trough rule",
                    "first run of 3 exceeding +0.5 σ")
    pk += slider(618, 44, 220, "steepest window", "3 samples", 0.25)
    pk += slider(878, 44, 220, "slope noise σ", "MAD", 0.5,
                 "0.00958 mV/s on this family")
    pk += [text("Change the onset rule and every depth, angle and peakedness "
                "above changes with it — which is why measurements are stored "
                "against the recipe hash rather than on the Library row.",
                18, 108, 10, C["blue"], MONO)]

    tk = [text("Per-event output", 18, 14, 12),
          text("one row per member, written to the derived-features table as "
               "(span, recipe_hash)", 138, 17, 9, C["muted"], MONO),
          rtext("16 rows", W - 18, 17, 10, C["black"], MONO)]
    cols = ["span", "onset (h)", "depth mV", "max slope", "angle",
            "peakedness", "duration"]
    cxs = [18, 160, 300, 430, 570, 690, 830]
    tk.append(rect(18, 40, W - 36, 1, C["border"]))
    for c, cx in zip(cols, cxs):
        tk.append(text(c, cx, 46, 9, C["muted"], MONO))
    rows = [("s-0341", "336.94", "0.141", "−0.512", "−16°", "1.31", "0.9 s"),
            ("s-0342", "337.36", "0.193", "−0.604", "−24°", "1.54", "1.1 s"),
            ("s-0343", "337.75", "0.326", "−0.688", "−40°", "1.77", "0.7 s"),
            ("s-0344", "338.19", "0.378", "−0.725", "−36°", "1.92", "1.0 s")]
    for i, r in enumerate(rows):
        yy = 64 + i * 24
        if i % 2 == 0:
            tk.append(rect(14, yy - 5, W - 28, 24, C["page"], radius=4))
        for v, cx in zip(r, cxs):
            tk.append(text(v, cx, yy, 10, C["black"], MONO))
    tk.append(text("+ 12 more", 18, 164, 10, C["blue"], MONO))

    body = [card("anatomy", X, 180, 620, 302, ak),
            card("rose", 736, 180, 676, 302, rk),
            card("parameters", X, 498, W, 136, pk),
            card("rows", X, 650, W, 190, tk)]
    return page("analyse-4b-slope-block", "Analyse",
                "Block 01 open  ·  slope analysis",
                "F-03 sharkfin · n = 16",
                "Library family  ·  F-03 sharkfin", INTERR, "01", body)


# ================================================================ 4c  AGGREGATE
def p_aggregate():
    def hist(title, sub, vals, cols, labels, note=None):
        k = [text(title, 18, 14, 12), text(sub, 18, 36, 9, C["muted"], MONO)]
        k += bars(18, 56, 384, 130, vals, cols, labels)
        if note:
            k.append(text(note, 18, 206, 9, C["muted"], MONO))
        return k

    d1 = hist("Drop depth", "mV  ·  16 events",
              [1, 3, 5, 9, 12, 8, 4, 2], C["blue"],
              ["", "0.1", "", "0.2", "", "0.3", "", "0.4"],
              "bimodal — worth asking whether this is one family")
    d2 = hist("Inter-event interval", "hours between consecutive onsets",
              [1, 4, 11, 14, 7, 3, 1, 1], C["purple"],
              ["", "0.2", "", "0.4", "", "0.6", "", "0.8"],
              "mean 0.44 h  ·  CV 0.31 — more regular than Poisson")
    d3 = hist("Max slope", "mV/s  ·  the rose, as a distribution",
              [2, 3, 6, 10, 13, 9, 5, 2], "#E4646C",
              ["", "0.4", "", "0.6", "", "0.7", "", "0.8"],
              "tightly unimodal — the shape is consistent")

    tk = [text("When the events happened", 18, 14, 12),
          text("onset times across the family, with amplitude as height",
               210, 17, 9, C["muted"], MONO),
          rect(18, 44, W - 36, 62, C["page"], radius=5)]
    for i in range(16):
        t = 0.04 + i * 0.058 + (0.01 if i % 3 else 0)
        h = 14 + i * 2.6
        col = ONSET[min(len(ONSET) - 1, int(i / 16 * len(ONSET)))]
        tk.append(rect(18 + (W - 36) * t, 100 - h, 5, h, col, radius=2))
    tk += [text("336 h", 18, 110, 9, C["muted"], MONO),
           rtext("346 h", W - 18, 110, 9, C["muted"], MONO),
           text("amplitude modulation increasing, frequency modulation "
                "decreasing — the pattern the catalogue entry records",
                18, 130, 10, C["grey"], MONO)]

    pk = [text("Parameters", 18, 14, 12)]
    pk += selectbox(18, 44, 200, "binning", "Freedman–Diaconis")
    pk += selectbox(238, 44, 200, "interval defined as", "onset → onset")
    pk += selectbox(18, 104, 200, "outliers", "kept, flagged")
    pk += selectbox(238, 104, 200, "purity check", "one fall per window")
    pk += [rect(18, 160, 420, 1, C["border"]),
           text("Aggregates are views", 18, 174, 11, C["black"], MONO),
           text("Nothing on this page is stored. Every chart recomputes from "
                "the per-event rows, so changing the onset rule upstream "
                "changes these immediately rather than leaving a stale copy "
                "behind.", 18, 196, 10, C["grey"], MONO)]

    sk = [text("Summary", 18, 14, 12)]
    for i, (lab, val, col) in enumerate([("events", "16", None),
                                         ("mean interval", "0.44 h", None),
                                         ("interval CV", "0.31", None),
                                         ("mean depth", "0.29 mV", None),
                                         ("mean angle", "−28°", None),
                                         ("one fall per window", "100 %",
                                          C["gink"])]):
        pk2 = stat(18 + (i % 2) * 230, 44 + (i // 2) * 44, lab, val, col)
        sk += pk2
    sk += [rect(18, 172, 430, 1, C["border"]),
           text("The purity figure is the honest check: if some windows held "
                "two falls, the family would be a sequence, not an event.",
                18, 186, 10, C["muted"], MONO)]
    bx = 468 - 18
    for lab, pri in [("Export CSV", False)]:
        p, bw = button(lab, 0, 232, primary=pri, h=28)
        bx -= bw
        for n in p:
            n["x"] += bx
        sk += p

    body = [card("depth", X, 180, 420, 232, d1),
            card("interval", 540, 180, 420, 232, d2),
            card("slope", 992, 180, 420, 232, d3),
            card("timeline", X, 428, W, 158, tk),
            card("parameters", X, 602, 800, 278, pk),
            card("summary", 904, 602, 508, 278, sk)]
    return page("analyse-4c-aggregate-block", "Analyse",
                "Block 02 open  ·  aggregate",
                "F-03 sharkfin · n = 16",
                "Library family  ·  F-03 sharkfin", INTERR, "02", body)


# ================================================================ 5a  MATRIX
def p_matrix():
    ROWS = [("CNN (base)", "interesting", False), ("", "not_interesting", False),
            ("CNN (GASF)", "GASF_interesting", False), ("", "GASF_not", False),
            ("CNN (GADF)", "GADF_interesting", False), ("", "GADF_not", False),
            ("CNN (recur.)", "recurrence_interesting", False),
            ("", "recurrence_not", False),
            ("Random Forest", "interesting", False), ("", "not_interesting", False),
            ("Entropy", "sample entropy", False), ("", "shannon entropy", False),
            ("", "permutation entropy", False), ("", "svd entropy", False),
            ("", "spectral entropy", False), ("", "approximate entropy", False),
            ("Catch22", "22 features  ·  collapsed", True)]
    mk = [text("02  Window matrix", 18, 14, 14, C["black"], SANS, True),
          text("z-scored, clipped ± 3 σ  ·  10 min windows, 5 min stride",
               230, 20, 9, C["muted"], MONO),
          rtext("Signal → WindowSet", 992, 19, 10, C["muted"], MONO)]
    gx, gy, gw, ncol = 128, 44, 720, 38
    mk += matrix_heat(gx, gy, gw, ROWS, ncol, seed=5)
    for j, (grp, feat, coll) in enumerate(ROWS):
        yy = gy + j * 14
        if grp:
            mk.append(rtext(grp, gx - 8, yy + 2, 8, C["black"], MONO))
        mk.append(text(feat, gx + gw + 8, yy + 2, 8, C["muted"], MONO))
        if coll:
            mk.append(text("›", gx - 120, yy + 1, 10, C["blue"]))
    for i, col in enumerate(DIVERGE):
        mk.append(rect(gx + gw + 116, gy + i * 12, 12, 12, col))
    mk += [text("+3", gx + gw + 132, gy - 2, 8, C["muted"], MONO),
           text("−3", gx + gw + 132, gy + 100, 8, C["muted"], MONO),
           text("0 h", gx, gy + len(ROWS) * 14 + 6, 8, C["muted"], MONO),
           rtext("45.2 h", gx + gw, gy + len(ROWS) * 14 + 6, 8, C["muted"], MONO),
           text("groups collapse — Catch22's 22 rows are one line until you "
                "open them", 18, 300, 9, C["blue"], MONO)]

    sk = [text("the signal underneath", 18, 12, 10, C["muted"], MONO),
          rect(18, 30, 964, 58, C["white"], radius=4, stroke=C["border"])]
    sk.append(wander(22, 34, 956, 50, 4711, pts=340, amp=0.34, drift=0.16,
                     wobble=29, col="#3E8FD6", sw=1.2))
    sk.append(text("the vertical band at 29 h is a regime change, and it is "
                   "visible in every feature group at once — that is what the "
                   "matrix is for", 18, 96, 9, C["grey"], MONO))

    ck = [text("Compute", 18, 12, 12)]
    ck += [rect(18, 36, 264, 42, C["gtint"], radius=6),
           text("computed  ·  cached", 30, 43, 10, C["gink"], MONO),
           text("14 min on the cluster, 2 Sept", 30, 59, 9, C["gink"], MONO)]
    ck += slider(18, 94, 264, "window length", "10 min", 0.35)
    ck += slider(18, 148, 264, "stride", "5 min", 0.22,
                 "543 windows over 45.2 h")
    ck += [rect(18, 208, 264, 1, C["border"]),
           text("feature groups", 18, 218, 9, C["muted"], MONO)]
    for i, (g, on) in enumerate([("Catch22", True), ("Entropy", True),
                                 ("CNN scores", True), ("Random Forest", True),
                                 ("Wavelet energy", False)]):
        yy = 234 + i * 22
        ck += [rect(18, yy, 14, 14, C["blue"] if on else C["white"], radius=4,
                    stroke=None if on else C["border"]),
               text(g, 40, yy + 1, 10, C["black"] if on else C["grey"], MONO)]
    ck += [rect(18, 350, 264, 1, C["border"]),
           text("a whole channel at this stride is ~3 h", 18, 360, 9,
                "#9A6206", MONO)]
    by = 380
    for lab in ["Create SLURM script", "Upload a computed matrix"]:
        p, bw = button(lab, 18, by, primary=False, h=28)
        ck += p
        by += 34
    ck.append(text("uploading skips the compute if this span", 18, 448, 9,
                   C["muted"], MONO))

    body = [card("matrix", X, 180, 1010, 322, mk),
            card("signal", X, 514, 1010, 120, sk),
            card("compute", 1112, 180, 300, 454, ck)]
    return page("analyse-5a-matrix-block", "Analyse",
                "Block 02 open  ·  window matrix",
                "CH4_A2 · 45.2 h",
                "Signal  ·  CH4_A2  ·  whole channel", TRAIN, "02", body)


# ================================================================ 5b  CLUSTER
def p_cluster():
    dk = [text("03  Cluster", 18, 14, 14, C["black"], SANS, True),
          text("z-normalised Euclidean distance  ·  average linkage",
               140, 20, 9, C["muted"], MONO),
          rtext("WindowSet → Grouping", 1290, 19, 10, C["muted"], MONO)]
    dk += dendrogram(30, 42, 1264, 122, nleaves=34, seed=9,
                     groups=[(6, CLASS_COLS[0]), (4, CLASS_COLS[1]),
                             (8, CLASS_COLS[2]), (6, CLASS_COLS[3]),
                             (5, CLASS_COLS[4]), (5, CLASS_COLS[5])])
    dk += dashes(30, 92, 1264, C["amber"], 9, 6)
    dk += [rect(24, 86, 12, 12, C["amber"], radius=3),
           text("drag the cutline — 6 classes at this height", 30, 204, 9,
                C["amber"], MONO),
           rtext("linkage distance 10.1", 1294, 204, 9, C["muted"], MONO)]

    mk = [text("What each class looks like", 18, 12, 12),
          text("medoid on top — a real member, not an average", 240, 15, 9,
               C["muted"], MONO)]
    for i in range(6):
        cx = 18 + i * 218
        col = CLASS_COLS[i]
        mk += [rect(cx, 34, 204, 142, C["page"], radius=8, stroke=C["border"]),
               ellipse(cx + 10, 42, 8, 8, col),
               text("C%d" % (i + 1), cx + 24, 40, 10, C["black"], MONO),
               rtext(["%d windows" % n for n in
                      (142, 98, 51, 32, 13, 7)][i], cx + 194, 41, 9,
                     C["muted"], MONO)]
        for j in range(3):
            yy = 58 + j * 38
            mk.append(rect(cx + 10, yy, 184, 34, C["darker"], radius=3))
            mk.append(noisy_step(cx + 11, yy + 1, 182, 32, 400 + i * 31 + j,
                                 col, step=0.30 + i * 0.07 + j * 0.03))

    pk = [text("Parameters", 18, 14, 12)]
    pk += selectbox(18, 44, 200, "distance", "z-normalised Euclidean")
    pk += selectbox(238, 44, 200, "linkage", "average")
    pk += slider(458, 44, 200, "cut height", "10.1", 0.55, "6 classes")
    pk += [rect(18, 104, 640, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("silhouette", "0.238", None),
                                         ("cophenetic r", "0.91", C["gink"]),
                                         ("classes", "6", None)]):
        pk += stat(18 + i * 210, 118, lab, val, col)
    pk.append(text("Ward gives silhouette 0.238 at k=5 but cophenetic r 0.52; "
                   "average gives r 0.91 and suggests k=2. State the selection "
                   "criterion before reporting any cluster-derived labels — "
                   "otherwise the choice of k is the finding.",
                   18, 166, 10, "#9A6206", MONO))

    bk = [text("Windows per class", 18, 14, 12),
          rtext("543 windows", 430, 17, 10, C["black"], MONO)]
    bk += bars(18, 44, 412, 110, [142, 98, 51, 32, 13, 7], CLASS_COLS,
               ["C1", "C2", "C3", "C4", "C5", "C6"])
    bk += [text("C5 and C6 are too small to train on \u2014 merge them,",
                18, 176, 10, "#9A6206", MONO),
           text("or raise the cut.", 18, 192, 10, "#9A6206", MONO),
           rect(18, 212, 584, 1, C["border"]),
           text("Save as a custom grouping", 18, 222, 11, C["black"], MONO),
           text("scope", 18, 246, 9, C["muted"], MONO)]
    cx2 = 62
    for lab, on in [("whole channel", True), ("this section only", False)]:
        parts, cwid = chip(lab, cx2, 240, on)
        bk += parts
        cx2 += cwid + 6
    p2, bw2 = button("Save grouping  \u2192", 452, 238, h=26)
    bk += p2
    bk.append(text("a section-scoped grouping leaves members outside it",
                   18, 274, 9, C["muted"], MONO))
    bk.append(text("unassigned in the Library", 18, 288, 9, C["muted"], MONO))

    body = [card("dendrogram", X, 180, 1328, 192, dk),
            card("medoids", X, 392, W, 190, mk),
            card("parameters", X, 594, 680, 250, pk),
            card("balance", 792, 594, 620, 300, bk)]
    return page("analyse-5b-cluster-block", "Analyse",
                "Block 03 open  ·  cluster",
                "CH4_A2 · 543 windows",
                "Signal  ·  CH4_A2  ·  whole channel", TRAIN, "03", body)


# ================================================================ 5c  ENCODE
def p_encode():
    bk = [text("04  Encode", 18, 12, 14, C["black"], SANS, True),
          text("browse the windows to get a feel for what the classifier sees",
               160, 18, 9, C["muted"], MONO),
          rtext("WindowSet → Encoding", 1290, 17, 10, C["muted"], MONO)]
    bk += [rect(18, 40, 26, 26, C["white"], radius=6, stroke=C["border"]),
           text("‹", 28, 45, 13, C["grey"]),
           text("window 118 / 543", 54, 47, 10, C["black"], MONO),
           rect(168, 40, 26, 26, C["white"], radius=6, stroke=C["border"]),
           text("›", 178, 45, 13, C["grey"])]
    for i in range(9):
        cx = 216 + i * 118
        on = i == 3
        bk += [rect(cx, 38, 106, 32, C["tint"] if on else C["page"], radius=5,
                    stroke=C["blue"] if on else C["border"])]
        bk.append(noisy_step(cx + 4, 41, 98, 26, 700 + i * 23,
                             C["blue"] if on else C["muted"],
                             step=0.28 + i * 0.05))
    bk.append(rtext("class C2  ·  t = 19.8 h", 1294, 47, 9, C["muted"], MONO))

    ek = [text("The four encodings of this window", 18, 14, 12),
          rtext("one window, four representations — the model is trained on "
                "whichever you tick", W - 18, 17, 9, C["muted"], MONO)]
    for i, (lab, diag) in enumerate([("GASF", False), ("GADF", False),
                                     ("Recurrence", True), ("Fusion RGB", False)]):
        gx = 20 + i * 328
        ek += heat_grid(gx, 40, 250, 250, nx=20, ny=20, seed=3 + i * 2, diag=diag)
        ek += [text(lab, gx, 298, 10, C["black"], MONO),
               rect(gx + 280, 40, 14, 250, C["white"])]
        for j, col in enumerate(HEAT):
            ek.append(rect(gx + 280, 40 + j * 27.8, 14, 27.8, col))
        ek += [rect(gx + 258, 40, 14, 14, C["blue"] if i != 3 else C["white"],
                    radius=4, stroke=None if i != 3 else C["border"])]
    ek.append(text("the signal for this window", 1310, 44, 9, C["muted"], MONO))

    pk = [text("Parameters", 18, 14, 12)]
    pk += selectbox(18, 44, 190, "image size", "224 × 224")
    pk += selectbox(228, 44, 190, "paa reduction", "none")
    pk += selectbox(438, 44, 190, "fusion channels", "GASF / GADF / RP")
    pk += slider(648, 44, 190, "recurrence ε", "0.20", 0.20)
    pk += [text("3,420 images will be written  ·  1.2 GB  ·  ~6 min",
                18, 108, 10, C["grey"], MONO),
           rtext("existing encoders are kept — substituting a library risks a "
                 "silent encoding mismatch with the trained models",
                 W - 18, 108, 9, C["blue"], MONO)]

    body = [card("browse", X, 180, W, 82, bk),
            card("encodings", X, 274, W, 326, ek),
            card("parameters", X, 612, W, 140, pk)]
    return page("analyse-5c-encode-block", "Analyse",
                "Block 04 open  ·  encode",
                "CH4_A2 · 543 windows",
                "Signal  ·  CH4_A2  ·  whole channel", TRAIN, "04", body)


# ================================================================ 5d  MODEL
def p_model():
    jk = [text("05  Model — build the job", 18, 14, 14, C["black"], SANS, True),
          text("tick the stages this job should run; cached stages can be "
               "skipped", 250, 20, 9, C["muted"], MONO),
          rtext("Encoding → Model", 782, 19, 10, C["muted"], MONO)]
    stages = [("01", "Sliding windows", "cached", "—", False),
              ("02", "Window matrix", "cached", "14 min", False),
              ("03", "Cluster", "cached", "40 s", True),
              ("04", "Encode", "stale", "6 min", True),
              ("05", "Train model", "new", "2 h 40", True)]
    for i, (idx, name, state, cost, inc) in enumerate(stages):
        yy = 48 + i * 40
        jk += [rect(18, yy, 746, 34, C["tint"] if inc else C["page"], radius=7,
                    stroke=C["blue"] if inc else C["border"]),
               rect(30, yy + 10, 14, 14, C["blue"] if inc else C["white"],
                    radius=4, stroke=None if inc else C["border"]),
               text(idx, 56, yy + 11, 9, C["muted"], MONO),
               text(name, 82, yy + 10, 11, C["black"], MONO)]
        p, bw = status_badge(300, yy + 9, state)
        jk += p
        jk += [rtext(cost, 470, yy + 11, 10, C["grey"], MONO),
               rtext("skipped — reuses the cached artifact" if not inc
                     else "included", 752, yy + 11, 9,
                     C["muted"] if not inc else C["blue"], MONO)]
    jk.append(text("The window matrix is already computed, so this job starts "
                   "at clustering — 3 h of compute that does not have to happen "
                   "twice.", 18, 254, 10, C["gink"], MONO))

    pk = [text("Model", 18, 14, 12)]
    pk += selectbox(18, 44, 220, "architecture", "EfficientNet-B0")
    pk += selectbox(258, 44, 220, "labels from", "cluster classes (6)")
    pk += slider(18, 104, 220, "train / val split", "80 / 20", 0.8)
    pk += selectbox(258, 100, 220, "held-out recording", "M4  ·  locked")
    pk += [rect(18, 160, 470, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("images", "3,420", "#9A6206"),
                                         ("classes", "6", None),
                                         ("est. wall time", "2 h 40", None)]):
        pk += stat(18 + i * 160, 174, lab, val, col)
    pk.append(text("3,420 is under the ~10,000 a CNN on Gramian images wants, "
                   "and two classes sit under 20. Consider a random forest on "
                   "Catch22, or merge C5 and C6.", 18, 218, 10, "#9A6206", MONO))
    pk.append(text("M4 stays locked — the runner refuses it without an "
                   "explicit unlock, so the holdout is true by construction.",
                   18, 268, 10, C["gink"], MONO))

    sk = [text("Generated job", 18, 14, 12),
          rtext("stages 03 → 05  ·  one array task", W - 18, 17, 10,
                C["muted"], MONO),
          rect(18, 40, W - 36, 132, "#15161A", radius=6),
          text("#!/bin/bash", 32, 50, 9, "#7FB8EE", MONO),
          text("#SBATCH --job-name=ub_train_run131", 32, 66, 9, "#9CC4F0", MONO),
          text("#SBATCH --gres=gpu:1  --time=04:00:00  --mem=32G", 32, 82, 9,
               "#9CC4F0", MONO),
          text("python -m pipeline.run --recipe a7f3…9c \\", 32, 106, 9,
               C["trace"], MONO),
          text("    --from-stage 03 --to-stage 05 \\", 32, 122, 9, C["trace"], MONO),
          text("    --artifacts ./artifacts --manifest out/manifest.json",
               32, 138, 9, C["trace"], MONO),
          text("# stages 01-02 resolved from cache by recipe prefix hash",
               32, 156, 9, "#6E6E73", MONO)]
    bx = W - 18
    for lab, pri in [("Download job  →", True), ("Copy script", False)]:
        p, bw = button(lab, 0, 182, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        sk += p
        bx -= 10
    sk.append(text("Results come back through Admin's import action. The "
                   "trained model then appears as a Model artifact any "
                   "detection chain or Discovery algorithm can reference.",
                   18, 190, 10, C["muted"], MONO))

    body = [card("job-builder", X, 180, 800, 292, jk),
            card("model", 904, 180, 508, 292, pk),
            card("script", X, 488, W, 232, sk)]
    return page("analyse-5d-model-block", "Analyse",
                "Block 05 open  ·  model",
                "CH4_A2 · 6 classes",
                "Signal  ·  CH4_A2  ·  whole channel", TRAIN, "05", body)


# ================================================================ 6  INSERT
def _thumb(kind, x, y, w, h):
    """Tiny glyph standing in for what a block does."""
    if kind == "sym":
        return symbol_strip(x, y + h * 0.3, w, h * 0.4, 21, n=16, five=True)
    if kind == "slope":
        return [rect(x, y, w, h, C["white"], radius=3, stroke=C["border"])] + \
               slope_bars(x + 3, y + 3, w - 6, h - 6, 33, n=14)
    if kind == "trace":
        return [rect(x, y, w, h, C["dark"], radius=3),
                wander(x, y, w, h, 91, pts=40, amp=0.32, drift=0.30, sw=1.1,
                       wobble=5)]
    if kind == "overlay":
        return [rect(x, y, w, h, C["white"], radius=3, stroke=C["border"])] + \
               baseline_overlay(x + 2, y + 2, w - 4, h - 4, 77)
    if kind == "heat":
        return heat_grid(x, y, w, h, nx=7, ny=5, seed=4)
    if kind == "dendro":
        return [rect(x, y, w, h, C["white"], radius=3, stroke=C["border"])] + \
               dendrogram(x + 4, y + 4, w - 8, h - 8, nleaves=8, seed=3,
                          groups=[(4, C["blue"]), (4, C["green"])], sw=1)
    if kind == "marks":
        out = [rect(x, y, w, h, C["dark"], radius=3)]
        for mx in (0.3, 0.62):
            out.append(rect(x + w * mx, y, w * 0.06, h, "#4A2B6B"))
        out.append(wander(x, y, w, h, 55, pts=40, amp=0.30, drift=0.28, sw=1.1,
                          wobble=5))
        return out
    if kind == "runs":
        out = []
        cw = w / 6
        for i, col in enumerate([SYM["d"], SYM["S"], SYM["U"], SYM["S"],
                                 SYM["u"], SYM["S"]]):
            out.append(rect(x + i * cw, y + h * 0.3, cw - 1, h * 0.4, col))
        return out
    return [rect(x, y, w, h, C["page"], radius=3)]


BLOCKS = [
    ("Symbol smoothing", "majority filter over the symbol stream, so a single "
     "stray letter cannot start a run", "Encoding → Encoding", "runs", True, ""),
    ("Run-length collapse", "collapse repeated letters to runs, which is what "
     "most downstream detectors actually want", "Encoding → Encoding", "sym",
     True, ""),
    ("Alphabet remap", "merge or split bands after the fact — 5 letters back "
     "to 3, or the reverse", "Encoding → Encoding", "sym", True, ""),
    ("Word filter", "keep only the stretches containing a named symbol word",
     "Encoding → Encoding", "runs", True, ""),
    ("Baseline removal", "subtract a rolling statistic", "Signal → Signal",
     "overlay", False, "needs Signal · this point carries Encoding"),
    ("Matrix profile", "all-pairs self join, one score per timepoint",
     "Signal → Scores", "trace", False,
     "needs Signal · this point carries Encoding"),
    ("Threshold to spans", "cut a score profile into regions of interest",
     "Scores → SpanSet", "slope", False,
     "emits SpanSet · stage 03 requires Encoding"),
    ("Gramian encoding", "windows into images a classifier can read",
     "WindowSet → Encoding", "heat", False,
     "needs WindowSet · this point carries Encoding"),
    ("Hierarchical cluster", "group windows by shape", "WindowSet → Grouping",
     "dendro", False, "needs WindowSet · and emits Grouping"),
]


def p_insert():
    # --- the chain behind, drawn as if dimmed (no alpha in .pen)
    dim, dimb, dimt = "#FAFAFB", "#EDEDF0", "#C6C6CC"
    k = [nav(1),
         frame("header", 64, 0, 1376, 44, C["white"], children=[
             rect(0, 43, 1376, 1, dimb),
             text("Signal", 24, 14, 15, dimt, SANS, True),
             text("Analyse", 92, 16, 13, dimt),
             text("Chain  ·  inserting a stage", 152, 17, 11, dimt, MONO)]),
         frame("toolbar-dim", 64, 44, 1376, 56, C["page"], children=[
             text("source", 24, 20, 9, dimt, MONO),
             rect(70, 12, 260, 24, C["white"], radius=6, stroke=dimb),
             text("Signal span  ·  CH4_A2", 80, 18, 11, dimt, MONO)])]
    y = 108
    for idx, name, h in [("●", "Source", 70), ("01", "Baseline removal", 70),
                         ("02", "Symbolic encoding", 70), ("03", "Noise floor", 70),
                         ("04", "Drop detection", 70)]:
        k.append(frame("dim/" + name, X, y, W, h, dim, radius=10, stroke=dimb,
                       children=[text(idx, 14, 14, 10, dimt, MONO),
                                 text(name, 40, 12, 12, dimt, SANS, True),
                                 rect(232, 14, W - 246, h - 28, "#F2F2F5",
                                      radius=4)]))
        y += h + 20

    # --- the modal
    MX, MY, MW, MH = 170, 88, 1100, 724
    k.append(rect(MX + 3, MY + 4, MW, MH, "#DFDFE4", radius=14))
    mk = [text("Insert a stage", 24, 20, 16, C["black"], SANS, True),
          text("between 02 Symbolic encoding and 03 Noise floor", 190, 26, 11,
               C["grey"], MONO),
          rtext("×", MW - 24, 18, 18, C["grey"]),
          rect(0, 56, MW, 1, C["border"])]

    # type contract
    ck = [text("the stage you insert must fit here", 0, 0, 9, C["muted"], MONO)]
    pills = [("02 Symbolic encoding", "outputs", "Encoding", C["blue"]),
             ("new stage", "must accept", "Encoding", C["amber"]),
             ("03 Noise floor", "requires", "Encoding", C["blue"])]
    px = 0
    for i, (who, verb, ty, col) in enumerate(pills):
        pw = max(tw(who, 10, MONO), tw(ty, 11, MONO) + 4) + 34
        ck += [rect(px, 18, pw, 48, C["page"] if i != 1 else "#FDF0D5", radius=7,
                    stroke=C["border"] if i != 1 else C["amber"]),
               text(who, px + 12, 26, 10, C["black"], MONO),
               text(verb, px + 12, 42, 8, C["muted"], MONO),
               text(ty, px + 12 + tw(verb, 8, MONO) + 8, 41, 10, col, MONO)]
        px += pw
        if i < 2:
            ck += [text("→", px + 8, 34, 13, C["muted"])]
            px += 30
    ck.append(rtext("4 of 21 blocks fit. The rest stay visible with the reason "
                    "— the type system is easier to learn by being refused "
                    "than by being hidden from.", MW - 48, 30, 10, C["muted"],
                    MONO))
    mk.append(frame("contract", 24, 74, MW - 48, 74, C["white"], children=ck))

    # filter row
    fk = [rect(0, 0, 300, 28, C["page"], radius=6, stroke=C["border"]),
          text("search blocks", 12, 7, 10, C["muted"], MONO)]
    fx = 316
    for lab, on in [("all", True), ("preprocess", False), ("encode", False),
                    ("detect", False), ("cluster", False), ("model", False),
                    ("control", False)]:
        bw = tw(lab, 10, MONO) + 22
        fk += [rect(fx, 0, bw, 28, C["tint"] if on else C["white"], radius=6,
                    stroke=C["blue"] if on else C["border"]),
               text(lab, fx + 11, 7, 10, C["blue"] if on else C["grey"], MONO)]
        fx += bw + 6
    fk += toggle(MW - 48 - 210, 5, "show incompatible", True)
    mk.append(frame("filters", 24, 160, MW - 48, 28, C["white"], children=fk))

    # grid
    gk = []
    for i, (name, desc, ty, kind, ok, why) in enumerate(BLOCKS):
        cx, cy = (i % 3) * 230, (i // 3) * 160
        sel = i == 1
        gk += [rect(cx, cy, 220, 150, C["tint"] if sel else
                    (C["white"] if ok else C["page"]), radius=9,
                    stroke=C["blue"] if sel else (C["border"] if ok else C["border"]))]
        gk += _thumb(kind, cx + 14, cy + 14, 78, 44)
        gk += [text(name, cx + 104, cy + 16, 11,
                    C["black"] if ok else C["muted"], MONO),
               text(ty, cx + 104, cy + 32, 8,
                    C["blue"] if ok else C["muted"], MONO)]
        words = desc.split()
        line, ly = "", cy + 68
        for wd in words:
            if tw(line + " " + wd, 9, MONO) > 190:
                gk.append(text(line, cx + 14, ly, 9,
                               C["grey"] if ok else C["muted"], MONO))
                line, ly = wd, ly + 13
            else:
                line = (line + " " + wd).strip()
        gk.append(text(line, cx + 14, ly, 9, C["grey"] if ok else C["muted"], MONO))
        if not ok:
            gk += [rect(cx + 14, cy + 124, 192, 16, "#F6DADA", radius=4),
                   text(why, cx + 20, cy + 128, 8, "#A33", MONO)]
        else:
            gk.append(text("✓  fits here", cx + 14, cy + 128, 9,
                           C["gink"], MONO))
    mk.append(frame("grid", 24, 204, 700, 470, C["white"], children=gk))

    # detail panel
    dk = [text("Run-length collapse", 16, 14, 13, C["black"], SANS, True),
          text("Encoding → Encoding", 16, 36, 9, C["blue"], MONO)]
    dk += _thumb("sym", 16, 56, 296, 52)
    dk += [text("Collapses repeated letters into runs, so DDDDSSUU becomes "
                "D×4 S×2 U×2. Most downstream detectors care about run "
                "length rather than sample count, and collapsing first makes "
                "the noise floor comparable across segment lengths.",
                16, 120, 10, C["grey"], MONO),
           rect(16, 216, 296, 1, C["border"]),
           text("defaults", 16, 228, 9, C["muted"], MONO)]
    for i, (lab, val) in enumerate([("minimum run", "2 segments"),
                                    ("keep SAME runs", "yes"),
                                    ("emit", "run lengths + letters")]):
        dk += [text(lab, 16, 246 + i * 20, 10, C["grey"], MONO),
               rtext(val, 312, 246 + i * 20, 10, C["black"], MONO)]
    dk += [rect(16, 314, 296, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("est. cost", "0.2 s", None),
                                         ("has a null", "yes", C["gink"])]):
        dk += stat(16 + i * 150, 326, lab, val, col)
    dk += [rect(16, 372, 296, 1, C["border"]),
           text("Inserting here makes stages 03 and 04 stale. 00–02 stay "
                "cached.", 16, 384, 9, "#9A6206", MONO),
           text("Inserting at the END of a chain has only one constraint, and "
                "changes the chain's terminal type — which changes what kind "
                "of template it saves as.", 16, 414, 9, C["muted"], MONO)]
    mk.append(frame("detail", 748, 204, 328, 470, C["white"], radius=9,
                    stroke=C["border"], children=dk))

    # footer
    fk2 = [rect(0, 0, MW, 1, C["border"]),
           text("21 blocks in the registry  ·  adding a technique is one "
                "adapter file", 24, 22, 10, C["muted"], MONO)]
    bx = MW - 24
    for lab, pri in [("Insert and open settings  →", True), ("Insert", False),
                     ("Cancel", False)]:
        p, bw = button(lab, 0, 16, primary=pri, h=32)
        bx -= bw
        for n in p:
            n["x"] += bx
        fk2 += p
        bx -= 10
    mk.append(frame("footer", 0, MH - 64, MW, 64, C["white"], children=fk2))

    k.append(frame("insert-modal", MX, MY, MW, MH, C["white"], radius=14,
                   stroke=C["border"], children=mk))
    return frame("analyse-6-insert-stage", 0, 0, 1440, 900, C["page"], children=k)


# ================================================================ 7  COMPARE
A_COL, B_COL = C["blue"], C["purple"]
A_SEG = [(20, 70), (150, 48), (300, 96), (470, 60), (600, 84), (790, 52),
         (900, 44)]
B_SEG = [(24, 64), (218, 70), (302, 92), (540, 66), (604, 78), (700, 58),
         (860, 50)]
BOTH = [(24, 60), (302, 88), (604, 74)]
ONLY_A = [(150, 48), (470, 60), (790, 52), (900, 44)]
ONLY_B = [(218, 70), (540, 66), (700, 58), (860, 50)]


def _compare_toolbar():
    tk = [text("section", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("112 – 286 h  ·  174 h", 74, 12, True)
    tk += p
    tk.append(text("‹ back to all algorithms", 24, 38, 10, C["blue"], MONO))
    bx = 1376 - 24
    for lab in ["Rerun both", "Swap A / B"]:
        p, bw = button(lab, 0, 11, primary=False, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        tk += p
        bx -= 12
    return frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk)


def p_compare():
    PX, PW = 150, 1160
    S = PW / 1050.0
    k = [nav(2), head("Discovery", "Compare  ·  two algorithms, same section",
                      "run 128 vs run 131"), _compare_toolbar()]

    dk = [text("What differs", 18, 14, 12),
          text("comparing detections means comparing recipes — the stages that "
               "differ are the explanation", 128, 17, 9, C["muted"], MONO)]
    chains = [("A", "drop_motifs9", A_COL, "run 128",
               [("●", "Source", True), ("01", "Baseline", True),
                ("02", "Encoding", True), ("03", "Noise floor  8σ", False),
                ("04", "Detection", True)]),
              ("B", "sharkfin_v2", B_COL, "run 131",
               [("●", "Source", True), ("bp", "Bandpass  0.001–0.01 Hz", False),
                ("02", "Encoding", True), ("03", "Noise floor  6σ", False),
                ("04", "Detection", True)])]
    for r, (tag, nm, col, run, blocks) in enumerate(chains):
        yy = 40 + r * 44
        dk += [ellipse(18, yy + 10, 10, 10, col),
               text(tag, 34, yy + 6, 12, C["black"], SANS, True),
               text(nm, 50, yy + 8, 11, C["black"], MONO),
               text(run, 50 + tw(nm, 11, MONO) + 14, yy + 9, 9, C["muted"], MONO)]
        cx = 330
        for idx, bn, same in blocks:
            bw = tw(bn, 9, MONO) + 26
            dk += [rect(cx, yy, bw, 30, C["page"] if same else "#FDF0D5",
                        radius=6, stroke=C["border"] if same else C["amber"]),
                   text(idx, cx + 9, yy + 4, 8, C["muted"], MONO),
                   text(bn, cx + 9, yy + 16, 9,
                        C["grey"] if same else "#9A6206", MONO)]
            cx += bw + 8
    dk.append(text("B bandpasses first and cuts at 6σ rather than 8σ — two "
                   "changes, so a difference in output cannot be attributed to "
                   "either one alone.", 18, 124, 10, C["amber"], MONO))
    k.append(card("recipe-diff", X, 108, W, 144, dk))

    trk = [text("The section, and where each algorithm fires", 18, 14, 12),
           text("one time axis for all of it — a fire only means something next "
                "to the signal it fired on", 320, 17, 9, C["muted"], MONO),
           rtext("CH4_A2", W - 18, 17, 9, C["muted"], MONO),
           text("signal", 18, 62, 9, C["black"], MONO),
           text("112 – 286 h", 18, 78, 8, C["muted"], MONO),
           rect(PX, 40, PW, 84, C["dark"], radius=5)]
    trk.append(wander(PX, 40, PW, 84, 4711, pts=420, amp=0.34, drift=0.16,
                      wobble=27, sw=1.2))
    for x0, wd in A_SEG:
        trk.append(rect(PX + x0 * S, 40, max(2, wd * S * 0.22), 8, A_COL))
    for x0, wd in B_SEG:
        trk.append(rect(PX + x0 * S, 116, max(2, wd * S * 0.22), 8, B_COL))
    trk += [text("A", PX + 6, 44, 8, A_COL, MONO),
            text("B", PX + 6, 106, 8, B_COL, MONO),
            rect(18, 138, W - 36, 1, C["border"])]
    for i, (nm, segs, col) in enumerate([("A  drop_motifs9", A_SEG, A_COL),
                                         ("B  sharkfin_v2", B_SEG, B_COL),
                                         ("both", BOTH, C["muted"]),
                                         ("only A", ONLY_A, A_COL),
                                         ("only B", ONLY_B, B_COL)]):
        yy = 150 + i * 24
        trk.append(text(nm, 18, yy + 2, 9,
                        C["black"] if i < 2 else C["grey"], MONO))
        for x0, wd in segs:
            trk.append(rect(PX + x0 * S, yy, wd * S, 14, col, radius=3))
    trk += [text("112 h", PX, 274, 8, C["muted"], MONO),
            text("199 h", PX + PW / 2 - 16, 274, 8, C["muted"], MONO),
            rtext("286 h", PX + PW, 274, 8, C["muted"], MONO)]
    k.append(card("signal-and-tracks", X, 260, W, 288, trk))

    ok = [text("Set overlap", 18, 14, 12),
          text("matched at IoU ≥ 0.5, onset tolerance scaled to duration",
               118, 17, 9, C["muted"], MONO)]
    bx = 18
    for lab, n, col in [("only A", 42, A_COL), ("both", 118, C["muted"]),
                        ("only B", 27, B_COL)]:
        wseg = (W - 36) * n / 187
        ok += [rect(bx, 38, wseg, 26, col, radius=4),
               text(str(n), bx + 10, 44, 12, C["white"], MONO),
               text(lab, bx, 70, 9, C["grey"], MONO)]
        bx += wseg + 4
    for i, (lab, val, col) in enumerate([("A found", "160", A_COL),
                                         ("A surrogate", "26", C["muted"]),
                                         ("B found", "145", B_COL),
                                         ("B surrogate", "19", C["muted"]),
                                         ("A precision", "24 %", None),
                                         ("B precision", "not yet scored",
                                          C["muted"])]):
        ok += stat(18 + i * 220, 92, lab, val, col)
    k.append(card("overlap", X, 556, W, 132, ok))

    bk = [text("Step through the disagreements", 18, 12, 12),
          text("69 spans where exactly one of them fired", 250, 15, 10,
               C["grey"], MONO),
          rtext("browse only — judgement happens in Review", W - 18, 15, 9,
                C["muted"], MONO),
          rect(18, 32, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("‹", 28, 37, 13, C["grey"]),
          text("7 / 69", 54, 39, 11, C["black"], MONO),
          rect(108, 32, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("›", 118, 37, 13, C["grey"]),
          text("192.4 h  ·  only A fired here", 150, 39, 10, A_COL, MONO)]
    for i, (tag, col, fires) in enumerate([("A  drop_motifs9", A_COL, True),
                                           ("B  sharkfin_v2", B_COL, False)]):
        cx = 18 + i * 654
        bk += [ellipse(cx, 66, 9, 9, col),
               text(tag, cx + 16, 62, 10, C["black"], MONO),
               rtext("detection at 192.42 h" if fires else "nothing here",
                     cx + 636, 63, 9, col if fires else C["muted"], MONO),
               rect(cx, 82, 636, 72, C["dark"], radius=5)]
        if fires:
            bk.append(rect(cx + 636 * 0.44, 82, 636 * 0.07, 72, "#12365E",
                           stroke=col))
        bk.append(wander(cx, 82, 636, 72, 4433, pts=220, amp=0.30, drift=0.22,
                         wobble=13, ripple=0.03,
                         col=C["trace"] if fires else "#7A7A80", sw=1.3))
    bk += [rect(18, 164, W - 36, 30, C["tint"], radius=7, stroke=C["blue"]),
           text("⌄", 30, 169, 13, C["blue"]),
           text("compare every stage for this window", 50, 172, 10, C["blue"],
                MONO),
           rtext("see where the two chains actually diverge", W - 30, 173, 9,
                 C["muted"], MONO)]
    k.append(card("browse", X, 696, W, 200, bk))
    return frame("discovery-3-compare", 0, 0, 1440, 900, C["page"], children=k)


# ---- the scrolled state: stage-by-stage, same window, both chains
def _strip_plot(kind, x, y, w, h, col):
    if kind == "raw":
        return [rect(x, y, w, h, C["dark"], radius=4),
                wander(x, y, w, h, 4433, pts=220, amp=0.30, drift=0.22,
                       wobble=13, ripple=0.035, sw=1.3)]
    if kind == "baseline":
        return [rect(x, y, w, h, C["white"], radius=4, stroke=C["border"])] + \
               baseline_overlay(x + 4, y + 4, w - 8, h - 8, 4433)
    if kind == "bandpass":
        out = [rect(x, y, w, h, C["dark"], radius=4),
               wander(x, y, w, h, 4433, pts=220, amp=0.30, drift=0.22,
                      wobble=13, ripple=0.02, col="#4A4A50", sw=1)]
        out.append(wander(x, y, w, h, 8821, pts=260, amp=0.10, drift=0.30,
                          wobble=3, col=col, sw=1.4))
        return out
    if kind == "symA":
        sh = (h - 8) / 2
        return (symbol_strip(x, y, w, sh, 21, n=90, five=True) +
                symbol_strip(x, y + sh + 8, w, sh, 21, n=90, five=False))
    if kind == "symB":
        sh = (h - 8) / 2
        return (symbol_strip(x, y, w, sh, 64, n=90, five=True) +
                symbol_strip(x, y + sh + 8, w, sh, 64, n=90, five=False))
    if kind == "slopeA":
        return [rect(x, y, w, h, C["white"], radius=4, stroke=C["border"])] + \
               slope_bars(x + 6, y + 6, w - 12, h - 12, 33, n=64, sigma=0.30)
    if kind == "slopeB":
        return [rect(x, y, w, h, C["white"], radius=4, stroke=C["border"])] + \
               slope_bars(x + 6, y + 6, w - 12, h - 12, 91, n=64, sigma=0.86)
    if kind == "detA":
        return [rect(x, y, w, h, C["dark"], radius=4),
                rect(x + w * 0.44, y, w * 0.07, h, "#12365E", stroke=A_COL),
                wander(x, y, w, h, 4433, pts=200, amp=0.30, drift=0.22,
                       wobble=13, ripple=0.035, sw=1.3),
                ellipse(x + w * 0.462, y + h * 0.22, 10, 10, A_COL)]
    return [rect(x, y, w, h, C["dark"], radius=4),
            wander(x, y, w, h, 8821, pts=200, amp=0.10, drift=0.30, wobble=3,
                   col="#6E6E73", sw=1.2)]


def p_compare_window():
    k = [nav(2), head("Discovery", "Compare  ·  stage by stage, one window",
                      "192.38 – 192.45 h  ·  40 s"), _compare_toolbar()]

    sk = [rect(18, 14, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("‹", 28, 19, 13, C["grey"]),
          text("7 / 69", 54, 21, 11, C["black"], MONO),
          rect(108, 14, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("›", 118, 19, 13, C["grey"]),
          text("192.4 h", 150, 21, 12, C["black"], SANS, True),
          text("only A fired here", 216, 22, 10, A_COL, MONO),
          rtext("⌃ back to the overview", W - 18, 22, 10, C["blue"], MONO),
          text("the same 40 s pushed through both chains — rows are aligned, so "
               "the row where the pictures stop matching is the row that "
               "explains the disagreement", 330, 22, 9, C["muted"], MONO)]
    k.append(card("stepper", X, 108, W, 54, sk))

    CW = 654
    AX, BX = X, X + CW + 20
    for cx, tag, nm, col, run in [(AX, "A", "drop_motifs9", A_COL, "run 128"),
                                  (BX, "B", "sharkfin_v2", B_COL, "run 131")]:
        k.append(frame("head/" + tag, cx, 172, CW, 30, C["page"], radius=7,
                       children=[ellipse(12, 10, 10, 10, col),
                                 text(tag, 30, 6, 12, C["black"], SANS, True),
                                 text(nm, 48, 8, 11, C["black"], MONO),
                                 rtext(run, CW - 12, 9, 9, C["muted"], MONO)]))

    ROWS = [
        ("●", "Source", "raw", "raw", "identical", 88,
         "the same 40 s, both chains", "the same 40 s, both chains"),
        ("01", "Baseline / Bandpass", "baseline", "bandpass", "differs", 112,
         "rolling median removed · the slow rise survives",
         "0.001–0.01 Hz · the slow rise is gone"),
        ("02", "Encoding", "symA", "symB", "same block, different input", 84,
         "one long d run at the fall", "no d run — the fall is not in band"),
        ("03", "Noise floor", "slopeA", "slopeB", "differs", 100,
         "σ 0.00958 · cut ±0.0767 · min slope −0.725 → 8 segments qualify",
         "σ 0.00614 · cut ±0.0368 · min slope −0.031 → 0 qualify"),
        ("04", "Detection", "detA", "detB", "differs", 100,
         "1 detection · depth 0.378 mV · score 0.88",
         "no detection in this window"),
    ]
    y = 210
    for idx, name, ka, kb, badge, h, na, nb in ROWS:
        same = badge == "identical"
        for cx, kind, note, col in [(AX, ka, na, A_COL), (BX, kb, nb, B_COL)]:
            kids = [text(idx, 12, 10, 9, C["muted"], MONO),
                    text(name, 32, 9, 10, C["black"], MONO)]
            bw = tw(badge, 8, MONO) + 14
            kids += [rect(CW - 12 - bw, 8, bw, 16,
                          C["page"] if same else "#FDF0D5", radius=4),
                     text(badge, CW - 12 - bw + 7, 11, 8,
                          C["muted"] if same else "#9A6206", MONO)]
            kids += _strip_plot(kind, 12, 30, CW - 24, h - 50, col)
            kids.append(text(note, 12, h - 16, 9,
                             C["grey"] if same else C["black"], MONO))
            k.append(frame("row/%s/%s" % (idx, "A" if cx == AX else "B"),
                           cx, y, CW, h, C["white"], radius=9,
                           stroke=C["border"] if same else C["amber"],
                           children=kids))
        y += h + 10

    vk = [text("Where they diverge", 18, 16, 12),
          text("row 01 — and everything after it follows from there",
               172, 19, 10, C["amber"], MONO)]
    for i, (lab, va, vb) in enumerate([
            ("min slope in window", "−0.725 mV/s", "−0.031 mV/s"),
            ("slope noise σ", "0.00958", "0.00614"),
            ("cut at", "±0.0767", "±0.0368"),
            ("segments qualifying", "8", "0")]):
        xx = 18 + i * 330
        vk += [text(lab, xx, 46, 9, C["muted"], MONO),
               ellipse(xx, 64, 7, 7, A_COL),
               text(va, xx + 14, 61, 11, C["black"], MONO),
               ellipse(xx, 84, 7, 7, B_COL),
               text(vb, xx + 14, 81, 11, C["black"], MONO)]
    k.append(card("divergence", X, y + 4, W, 110, vk))
    return frame("discovery-3b-compare-window", 0, 0, 1440, 900, C["page"],
                 children=k)
