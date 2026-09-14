#!/usr/bin/env python3
"""
Analyse (merged, terminal-type surfaces) + Discovery, v2.

Settled in three grilling rounds:

  * No deadline. The PRD's cut-list constraints are advisory; the goal is a
    usable tool.
  * The three "modes" are not modes. A chain's TERMINAL TYPE decides what the
    surface looks like: SpanSet -> detection, features over a SpanSet ->
    interrogation, Model -> train. The names survive only as filters over
    saved templates.
  * A saved detection algorithm IS a template (PRD `templates` table), filtered
    by terminal type. No second store.
  * Chains start from a SOURCE BLOCK. One kind loads a signal span, another
    emits a SpanSet from a Library family or a prior run. The spine stays
    linear; chain validation is untouched. "Analyse events" is the universal
    verb that sends a SpanSet here from Discovery, Library or Review.
  * Interrogation writes per-event rows to a derived-features table keyed by
    (span, recipe_hash). Aggregates are views, never stored.
  * Explore's Agreement mode folds into Discovery as the n=2 case where one
    "algorithm" is the human annotation store.
  * Discovery BROWSES only. Per-candidate judgement happens in Review.
    `send all to Review` pushes the run to the top of the queue tagged with the
    run id; returning to Discovery refreshes the precision figure.
    `discard run` marks the run superseded and writes no adjudications.
  * Precision is labelled precision. Recall appears only where the section
    intersects human-reviewed coverage, scoped to that intersection.
  * Seed search is MASS at native length; the acceptance threshold is chosen
    against a surrogate distribution with the trivial-match zone drawn.

Run:  python build_analyse_discovery.py  ->  UI_analyse_discovery_v2.pen
"""

import math

from pen_kit import (C, MONO, SANS, nid, frame, rect, ellipse, text, rtext,
                     ctext, chip, button, tw, write_doc, _rng)
from pen_widgets import (SYM, SYM_ORDER, HEAT, MAGMA, ONSET, dashes, vdashes,
                         wander, sawtooth_drops, baseline_overlay, ensemble,
                         symbol_strip, slope_bars, heat_grid, dendrogram,
                         slider, selectbox, seg_control, toggle, stat, _poly)

NAV = ["Explore", "Analyse", "Discovery", "Review", "Library"]


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


def arrow_nav(x, y, cur, total, w=150):
    return [rect(x, y, 26, 26, C["white"], radius=6, stroke=C["border"]),
            text("‹", x + 10, y + 5, 13, C["grey"]),
            text("%d / %d" % (cur, total), x + 36, y + 8, 11, C["black"], MONO),
            rect(x + w - 26, y, 26, 26, C["white"], radius=6, stroke=C["border"]),
            text("›", x + w - 16, y + 5, 13, C["grey"])]


def section_slider(x, y, w, h, seed=4711, sel=(0.44, 0.10), label=None):
    """Channel overview with draggable section handles."""
    px, pw = x + w * sel[0], w * sel[1]
    out = [rect(x, y, w, h, C["dark"], radius=5),
           rect(px, y, pw, h, C["ov_span"], stroke=C["blue"]),
           wander(x, y, w, h, seed, pts=400, amp=0.34, drift=0.16, wobble=29)]
    for hx in (px - 5, px + pw - 5):
        out += [rect(hx, y + h / 2 - 14, 10, 28, C["blue"], radius=3),
                rect(hx + 4, y + h / 2 - 8, 1, 16, C["white"])]
    return out


def chain_ribbon(x, y, w, blocks, active=None, h=60):
    """Compact horizontal chain. blocks = [(idx, name, state)]"""
    out = [text("chain", 16, h / 2 - 6, 9, C["muted"], MONO)]
    cx = 62
    for idx, name, state in blocks:
        on = idx == active
        src = idx == "●"
        bw = tw(name, 10, MONO) + 32
        out += [rect(cx, 12, bw, h - 24, C["tint"] if on else
                     (C["gtint"] if src else C["page"]), radius=7,
                     stroke=C["blue"] if on else C["border"]),
                text(idx, cx + 11, 19, 9, C["muted"], MONO),
                text(name, cx + 11, 32, 10, C["blue"] if on else C["black"], MONO)]
        cx += bw
        if (idx, name, state) != blocks[-1]:
            out.append(text("›", cx + 6, h / 2 - 8, 12, C["muted"]))
            cx += 20
    return out


# ---------------------------------------------------------------- new charts
def rose(x, y, R, items, spokes=(-15, -30, -45, -60, -75)):
    """Quarter polar plot. items = [(angle_deg, ramp_pos, ringed)]"""
    out = []
    P = [(R * math.cos(math.radians(-90 * t)), R * math.sin(math.radians(90 * t)))
         for t in [i / 60 for i in range(61)]]
    out.append(_poly(x, y, R, R, P, C["black"], 1.4))
    for a in spokes:
        r = math.radians(-a)
        out.append(_poly(x, y, R, R,
                         [(0, 0), (R * math.cos(r), R * math.sin(r))],
                         C["border"], 1))
        out.append(text("%d°" % a, x + (R + 8) * math.cos(r) - 4,
                        y + (R + 8) * math.sin(r) - 6, 9, C["muted"], MONO))
    out += [text("0° flat", x + R + 8, y - 6, 9, C["muted"], MONO),
            text("−90°", x - 12, y + R + 8, 9, C["muted"], MONO)]
    for i, (ang, ramp_pos, ringed) in enumerate(items):
        r = math.radians(-ang)
        rad = R * (0.30 + 0.62 * (i / max(1, len(items) - 1)))
        px = x + rad * math.cos(r) - 5
        py = y + rad * math.sin(r) - 5
        col = ONSET[min(len(ONSET) - 1, int(ramp_pos * len(ONSET)))]
        if ringed:
            out.append(ellipse(px - 5, py - 5, 20, 20, C["purple"]))
            out.append(ellipse(px - 2, py - 2, 14, 14, C["white"]))
        out.append(ellipse(px, py, 10, 10, col))
    return out


def hist_overlay(x, y, w, h, seed=9, nbins=34, thresh=0.38, excl=0.10):
    """Match-distance histogram with the surrogate distribution behind it."""
    out = [rect(x, y, w, h, C["white"])]
    r = _rng(seed)
    bw = w / nbins
    real, surr = [], []
    for i in range(nbins):
        t = i / (nbins - 1)
        real.append(math.exp(-((t - 0.22) ** 2) / 0.012) * 0.9 +
                    math.exp(-((t - 0.62) ** 2) / 0.05) * 0.5 + r() * 0.05)
        surr.append(math.exp(-((t - 0.66) ** 2) / 0.045) * 0.75 + r() * 0.04)
    m = max(max(real), max(surr))
    for i in range(nbins):
        hs = surr[i] / m * h
        out.append(rect(x + i * bw, y + h - hs, bw - 1, hs, "#DDDDE2"))
    for i in range(nbins):
        hr = real[i] / m * h
        out.append(rect(x + i * bw, y + h - hr, bw - 1, hr, C["blue"]))
    out.append(rect(x, y, w * excl, h, "#F6DADA"))
    out += vdashes(x + w * excl, y, h, C["red"], 5, 4)
    out += [rect(x + w * thresh - 1, y - 6, 2, h + 12, C["black"]),
            rect(x + w * thresh - 7, y - 14, 14, 12, C["black"], radius=3)]
    return out


def bars(x, y, w, h, vals, cols, labels=None, maxv=None, size=9):
    out = []
    maxv = maxv or max(vals)
    bw = w / len(vals)
    for i, v in enumerate(vals):
        bh = max(2, v / maxv * h)
        col = cols[i] if isinstance(cols, list) else cols
        out.append(rect(x + i * bw + 3, y + h - bh, bw - 8, bh, col, radius=3))
        if labels:
            out.append(text(labels[i], x + i * bw + 3, y + h + 5, size,
                            C["muted"], MONO))
    return out


# ================================================================ 1
def chain_view(ox):
    """A + B merged: film strip with per-block status and a settings control."""
    k = [nav(1), head("Analyse", "Chain  ·  every stage visible, each one tunable",
                      "drop_motifs9 · unsaved")]
    tk = [text("source", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("Signal span  ·  CH4_A2  ·  825–875 s", 70, 12, True)
    tk += p
    tk += toggle(470, 15, "surrogate control", True)
    tk.append(text("est. 1.8 s  ·  runs locally", 660, 19, 10, C["muted"], MONO))
    p, bw = button("Save as template", 1376 - 24 - 300, 11, h=30)
    tk += p
    p, bw = button("Run chain", 1376 - 24 - 130, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    ROWS = [
        ("●", "Source", "signal span, loaded from Explore",
         "swap for a Library family to interrogate events instead",
         "— → Signal", "cached", 100, "src"),
        ("01", "Baseline removal", "subtract a 7 s rolling median",
         "gradients below are measured on the blue trace",
         "Signal → Signal", "cached", 124, "02"),
        ("02", "Symbolic encoding", "each 0.2 s segment becomes a letter",
         "dSAX k=3, then D and U split by the noise floor",
         "Signal → Encoding", "cached", 100, "03"),
        ("03", "Noise floor", "the cut is physical, not statistical",
         "σ of slope noise = 0.00958 mV/s, so d starts at 8σ",
         "Encoding → Scores", "stale", 100, "04"),
        ("04", "Drop detection", "23 raw detections, 6 kept after dedupe",
         "shaded span runs onset → trough",
         "Scores → SpanSet", "stale", 120, "05"),
    ]
    y = 108
    for i, (idx, name, c1, c2, tp, state, h, plot) in enumerate(ROWS):
        kids = [text(idx, 14, 14, 10, C["muted"], MONO),
                text(name, 40, 12, 12, C["black"], SANS, True),
                text(c1, 14, 36, 9, C["grey"], MONO),
                text(c2, 14, 50, 9, C["muted"], MONO),
                text(tp, 14, h - 24, 9, C["muted"], MONO)]
        p, bw2 = status_badge(120, 12, state)
        kids += p
        kids += sliders_icon(196, 11)
        px, pw = 232, W - 232 - 14
        if plot == "src":
            kids += [rect(px, 14, pw, h - 28, C["dark"], radius=4),
                     wander(px, 14, pw, h - 28, 9137, pts=300, amp=0.30,
                            drift=0.20, wobble=17, ripple=0.035, sw=1.3)]
        elif plot == "02":
            kids.append(rect(px, 14, pw, h - 28, C["white"], radius=4,
                             stroke=C["border"]))
            kids += baseline_overlay(px + 4, 18, pw - 8, h - 36, 9137)
        elif plot == "03":
            sh = (h - 38) / 2
            kids += symbol_strip(px, 14, pw, sh, 21, n=120, five=True)
            kids += symbol_strip(px, 14 + sh + 8, pw, sh, 21, n=120, five=False)
        elif plot == "04":
            kids.append(rect(px, 14, pw, h - 28, C["white"], radius=4,
                             stroke=C["border"]))
            kids += slope_bars(px + 6, 20, pw - 12, h - 40, 33, n=100)
        else:
            kids.append(rect(px, 14, pw, h - 28, C["dark"], radius=4))
            for mx, mw, col in [(0.11, 0.02, "#3A3A3C"), (0.40, 0.022, "#3A3A3C"),
                                (0.545, 0.034, "#4A2B6B"), (0.845, 0.030, "#16544B")]:
                kids.append(rect(px + pw * mx, 14, pw * mw, h - 28, col))
            kids.append(wander(px, 14, pw, h - 28, 9137, pts=280, amp=0.30,
                               drift=0.20, wobble=17, ripple=0.035, sw=1.3))
            for mx, col in [(0.554, C["purple"]), (0.856, "#1E8E7E")]:
                kids.append(ellipse(px + pw * mx - 4, 14 + (h - 28) * 0.24, 9, 9, col))
        k.append(frame("stage/" + name, X, y, W, h,
                       C["white"] if idx != "●" else "#FBFDFB",
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

    k.append(frame("terminal", X, 762, W, 56, C["gtint"], radius=10, children=[
        text("This chain ends in SpanSet, so it saves as a detection template "
             "and its results go to Review.", 18, 12, 11, C["gink"], MONO),
        text("End it in Model and it becomes a training chain; end it in "
             "features over a SpanSet and it becomes interrogation. Same "
             "builder, different terminal type.", 18, 30, 10, C["gink"], MONO)]))

    fk = [text("6 detections kept", 20, 18, 13, C["black"], SANS, True),
          text("from 23 raw  ·  surrogate 2  ·  6.1× above chance",
               172, 20, 11, C["grey"], MONO)]
    p, w1 = button("Export run", W - 20 - 340, 11, h=30)
    fk += p
    p, w2 = button("Pass 6 to Review  →", W - 20 - 216, 11, primary=True, h=30)
    fk += p
    k.append(frame("footer", X, 828, W, 52, C["white"], radius=10,
                   stroke=C["border"], children=fk))
    return frame("analyse-1-chain", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 2
def block_open(ox):
    """The settings control has been clicked: chain collapses, block opens."""
    k = [nav(1), head("Analyse", "Stage 02 open  ·  chain collapsed",
                      "drop_motifs9 · unsaved")]
    tk = [text("source", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("Signal span  ·  CH4_A2  ·  825–875 s", 70, 12, True)
    tk += p
    tk.append(rtext("‹ back to the full chain", 1352, 19, 11, C["blue"], MONO))
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    blocks = [("●", "Source", ""), ("01", "Baseline", ""),
              ("02", "Encoding", ""), ("03", "Noise floor", ""),
              ("04", "Detection", "")]
    k.append(frame("chain-ribbon", X, 108, W, 60, C["white"], radius=10,
                   stroke=C["border"],
                   children=chain_ribbon(0, 0, W, blocks, active="02")))

    # ---- the stage, large
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
    k.append(frame("stage-view", X, 180, 800, 296, C["white"], radius=10,
                   stroke=C["border"], children=vk))

    # ---- parameters
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
    k.append(frame("parameters", 904, 180, 508, 296, C["white"], radius=10,
                   stroke=C["border"], children=pk))

    # ---- surrogate comparison, folded into the settings
    sk = [text("This parameter against the null", 18, 14, 12),
          text("every variant runs its own surrogate, so the setting is chosen "
               "against chance rather than by counting detections", 260, 17, 9,
               C["muted"], MONO),
          rtext("the knee, not the peak", W - 18, 17, 9, C["blue"], MONO)]
    vals = [("2σ", 148, 96), ("4σ", 92, 41), ("6σ", 48, 17),
            ("8σ", 23, 2), ("10σ", 14, 1), ("12σ", 9, 1),
            ("16σ", 4, 0), ("20σ", 1, 0)]
    for i, (lab, det, sur) in enumerate(vals):
        bx = 60 + i * 156
        on = lab == "8σ"
        hd, hs = det / 148 * 86, sur / 148 * 86
        sk += [rect(bx, 46 + 86 - hd, 36, hd, C["blue"] if on else "#9CC4F0",
                    radius=3),
               rect(bx + 42, 46 + 86 - max(2, hs), 36, max(2, hs), C["border"],
                    radius=3),
               text(lab, bx + 20, 138, 9, C["blue"] if on else C["muted"], MONO)]
        if on:
            sk.append(rect(bx - 6, 40, 92, 106, C["tint"], radius=6))
            sk += [rect(bx, 46 + 86 - hd, 36, hd, C["blue"], radius=3),
                   rect(bx + 42, 46 + 86 - max(2, hs), 36, max(2, hs),
                        C["muted"], radius=3)]
    sk += dashes(52, 132, 1180, C["border"], 6, 6)
    k.append(frame("surrogate-sweep", X, 492, W, 162, C["white"], radius=10,
                   stroke=C["border"], children=sk))

    k.append(frame("cache", X, 670, W, 46, C["gtint"], radius=8, children=[
        text("Stages before this one are content-hashed and cached, so "
             "retuning costs 0.4 s. Stages 03–04 will recompute.",
             16, 16, 10, C["gink"], MONO)]))

    ak = [text("Changes are not applied until you rerun", 20, 20, 11,
               C["muted"], MONO)]
    p, w1 = button("Revert to recommended", W - 20 - 400, 12, h=30)
    ak += p
    p, w2 = button("Apply and rerun from 02  →", W - 20 - 224, 12,
                   primary=True, h=30)
    ak += p
    k.append(frame("apply", X, 732, W, 54, C["white"], radius=10,
                   stroke=C["border"], children=ak))
    return frame("analyse-2-block-open", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 3
def detection_surface(ox):
    k = [nav(1), head("Analyse", "Terminal type SpanSet  ·  a detection chain",
                      "drop_motifs9 · run 128")]
    tk = [text("this chain saves as a", 24, 20, 10, C["muted"], MONO)]
    p, cw = chip("detection template", 190, 12, True)
    tk += p
    tk.append(text("because it ends in SpanSet", 360, 20, 10, C["muted"], MONO))
    p, bw = button("Run chain", 1376 - 24 - 130, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    blocks = [("●", "Source", ""), ("01", "Baseline", ""),
              ("02", "Encoding", ""), ("03", "Noise floor", ""),
              ("04", "Detection", "")]
    k.append(frame("chain-ribbon", X, 108, W, 56, C["white"], radius=10,
                   stroke=C["border"],
                   children=chain_ribbon(0, 0, W, blocks, h=56)))

    dk = [text("Detections over the span", 18, 14, 12),
          rtext("shaded span runs onset → trough", W - 18, 17, 9,
                C["muted"], MONO),
          rect(18, 38, W - 36, 166, C["dark"], radius=5)]
    for mx, mw, col in [(0.08, 0.018, "#3A3A3C"), (0.19, 0.016, "#3A3A3C"),
                        (0.33, 0.02, "#3A3A3C"), (0.455, 0.030, "#4A2B6B"),
                        (0.60, 0.018, "#3A3A3C"), (0.74, 0.026, "#16544B"),
                        (0.88, 0.016, "#3A3A3C")]:
        dk.append(rect(18 + (W - 36) * mx, 38, (W - 36) * mw, 166, col))
    dk.append(wander(18, 38, W - 36, 166, 9137, pts=340, amp=0.28, drift=0.18,
                     wobble=17, ripple=0.03, sw=1.3))
    k.append(frame("detections", X, 176, W, 220, C["white"], radius=10,
                   stroke=C["border"], children=dk))

    ck = [text("Each detection", 18, 12, 12),
          rtext("click one to open it in the strip above", W - 18, 15, 9,
                C["muted"], MONO)]
    for i in range(6):
        cx = 18 + i * 218
        on = i == 3
        ck += [rect(cx, 36, 204, 118, C["tint"] if on else C["page"], radius=8,
                    stroke=C["blue"] if on else C["border"]),
               text("M%02d" % (12 + i), cx + 12, 44, 10, C["black"], MONO),
               rtext("%.2f" % (0.91 - i * 0.04), cx + 192, 44, 10, C["grey"], MONO),
               rect(cx + 12, 62, 180, 56, C["dark"], radius=4)]
        ck.append(wander(cx + 12, 62, 180, 56, 800 + i * 73, pts=60, amp=0.34,
                         drift=0.30, col=C["blue"] if on else C["trace"],
                         sw=1.2, wobble=5))
        ck.append(text("unadjudicated", cx + 12, 126, 9, C["muted"], MONO))
    k.append(frame("detection-cards", X, 408, W, 170, C["white"], radius=10,
                   stroke=C["border"], children=ck))

    sk = [text("Against the null", 18, 14, 12)]
    for i, (lab, val, col) in enumerate([("raw detections", "23", None),
                                         ("kept after dedupe", "6", None),
                                         ("surrogate", "2", C["muted"]),
                                         ("above chance", "6.1×", C["gink"]),
                                         ("recipe hash", "a7f3…9c", None)]):
        sk += stat(18 + i * 250, 46, lab, val, col)
    sk.append(text("the surrogate ran automatically — it is on by default, so a "
                   "missing null is impossible rather than merely unlikely",
                   18, 86, 10, C["muted"], MONO))
    k.append(frame("stats", X, 590, W, 116, C["white"], radius=10,
                   stroke=C["border"], children=sk))

    tk2 = [text("Save this chain as a detection template", 18, 16, 12),
           text("name", 18, 46, 9, C["muted"], MONO),
           rect(60, 42, 300, 26, C["page"], radius=6, stroke=C["border"]),
           text("drop_motifs9 + refine9", 70, 49, 10, C["black"], MONO),
           text("kind", 380, 46, 9, C["muted"], MONO),
           rect(416, 42, 160, 26, C["gtint"], radius=6),
           text("detection  (from terminal type)", 426, 49, 9, C["gink"], MONO),
           text("side-inputs", 600, 46, 9, C["muted"], MONO),
           rect(676, 42, 200, 26, C["page"], radius=6, stroke=C["border"]),
           text("none to rebind", 686, 49, 10, C["grey"], MONO),
           text("Templates strip the recording and span, so this runs on a "
                "channel it has never seen — and appears in Discovery's "
                "algorithm picker.", 18, 82, 10, C["muted"], MONO)]
    p, w1 = button("Save template", W - 18 - 380, 40, h=30)
    tk2 += p
    p, w2 = button("Pass 6 to Review  →", W - 18 - 216, 40, primary=True, h=30)
    tk2 += p
    k.append(frame("save-template", X, 718, W, 162, C["white"], radius=10,
                   stroke=C["border"], children=tk2))
    return frame("analyse-3-detection", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 4
def interrogation(ox):
    k = [nav(1), head("Analyse", "Terminal type features  ·  interrogating a family",
                      "F-03 sharkfin · n = 17")]
    tk = [text("source", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("Library family  ·  F-03 sharkfin  ·  17 members", 70, 12, True)
    tk += p
    tk.append(text("arrived via ‘Analyse events’ from the Library",
                   420, 20, 10, C["muted"], MONO))
    p, bw = button("Run measurement", 1376 - 24 - 170, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    blocks = [("●", "Library family", ""), ("01", "Resolve spans", ""),
              ("02", "Measure events", ""), ("03", "Aggregate", "")]
    k.append(frame("chain-ribbon", X, 108, W, 56, C["white"], radius=10,
                   stroke=C["border"],
                   children=chain_ribbon(0, 0, W, blocks, h=56)))

    # ---- anatomy of one event
    ak = [text("The anatomy of one event", 18, 14, 12),
          text("every quantity on the rose comes from these three points",
               200, 17, 9, C["muted"], MONO),
          rect(18, 38, 584, 214, C["white"], radius=5, stroke=C["border"])]
    ak.append(rect(196, 40, 210, 210, "#FBEBDC"))
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
        P.append((t * 580, 248 - v * 205))
    ak.append(_poly(20, 40, 580, 210, P, C["black"], 1.6))
    ak.append(_poly(196, 40, 212, 210,
                    [(0, 39), (210, 202)], "#C2185B", 1.3))
    ak.append(_poly(240, 40, 130, 190, [(0, 30), (120, 180)], "#6B6BD6", 1.8))
    ak += [ellipse(190, 74, 11, 11, "#1E8E7E"),
           ellipse(400, 238, 11, 11, "#B0245C"),
           rect(286, 140, 16, 16, C["white"], stroke="#6B6BD6", sw=1.6),
           _poly(404, 78, 2, 162, [(0, 0), (0, 160)], "#1E8E7E", 2)]
    ak += [text("ONSET", 148, 60, 8, "#1E8E7E", MONO),
           text("TROUGH", 386, 252, 8, "#B0245C", MONO),
           text("STEEPEST", 250, 126, 8, "#6B6BD6", MONO),
           text("DEPTH", 414, 150, 8, "#1E8E7E", MONO)]
    ak.append(text("depth 0.378 mV   ·   max slope −0.725 mV/s  (−35.9°)   "
                   "·   mean slope −0.378 mV/s   ·   peakedness 1.92",
                   18, 258, 10, C["grey"], MONO))
    k.append(frame("anatomy", X, 176, 620, 296, C["white"], radius=10,
                   stroke=C["border"], children=ak))

    # ---- the rose
    rk = [text("Each fall becomes one angle", 18, 14, 12),
          text("45° = a fall of exactly 1 mV/s — stated, not implied",
               18, 36, 9, C["muted"], MONO),
          text("radius is spacing only; colour is drop height", 18, 50, 9,
               C["muted"], MONO)]
    items = [(-6, 0.05, False), (-11, 0.14, False), (-17, 0.24, False),
             (-22, 0.33, False), (-27, 0.45, False), (-33, 0.56, False),
             (-24, 0.72, False), (-29, 0.80, False), (-31, 0.90, False),
             (-35.9, 0.97, True)]
    rk += rose(44, 84, 196, items)
    rk.append(text("the ringed marker is the event on the left, at −35.9°",
                   18, 316, 9, C["purple"], MONO))
    k.append(frame("rose", 736, 176, 676, 296, C["white"], radius=10,
                   stroke=C["border"], children=rk))

    # ---- per-event rows
    tk2 = [text("Measured events", 18, 14, 12),
           text("one row per event, keyed by (span, recipe_hash) — aggregates "
                "are views and are never stored", 160, 17, 9, C["muted"], MONO),
           rtext("export CSV", W - 18, 17, 10, C["blue"], MONO)]
    cols = ["span", "onset (h)", "depth mV", "max slope", "angle", "peakedness",
            "interval to next"]
    cxs = [18, 150, 290, 420, 560, 680, 830]
    tk2.append(rect(18, 38, W - 36, 1, C["border"]))
    for c, cx in zip(cols, cxs):
        tk2.append(text(c, cx, 44, 9, C["muted"], MONO))
    rows = [("s-0341", "336.94", "0.141", "−0.512", "−16°", "1.31", "0.42 h"),
            ("s-0342", "337.36", "0.193", "−0.604", "−24°", "1.54", "0.39 h"),
            ("s-0343", "337.75", "0.326", "−0.688", "−40°", "1.77", "0.44 h"),
            ("s-0344", "338.19", "0.378", "−0.725", "−36°", "1.92", "0.51 h"),
            ("s-0345", "338.70", "0.404", "−0.741", "−38°", "1.88", "—")]
    for i, r in enumerate(rows):
        yy = 62 + i * 24
        if i % 2 == 0:
            tk2.append(rect(14, yy - 5, W - 28, 24, C["page"], radius=4))
        for v, cx in zip(r, cxs):
            tk2.append(text(v, cx, yy, 10, C["black"], MONO))
    k.append(frame("events-table", X, 488, W, 196, C["white"], radius=10,
                   stroke=C["border"], children=tk2))

    # ---- distributions
    dk = [text("Aggregates", 18, 14, 12),
          text("recomputed from the rows above on demand", 110, 17, 9,
               C["muted"], MONO)]
    dk.append(text("drop depth, mV", 18, 42, 9, C["muted"], MONO))
    dk += bars(18, 58, 260, 80, [2, 5, 9, 14, 11, 6, 3, 1],
               C["blue"], ["0.1", "", "0.2", "", "0.3", "", "0.4", ""])
    dk.append(text("inter-event interval, h", 330, 42, 9, C["muted"], MONO))
    dk += bars(330, 58, 260, 80, [1, 4, 12, 15, 8, 4, 2, 1],
               C["purple"], ["0.2", "", "0.4", "", "0.6", "", "0.8", ""])
    dk.append(text("amplitude across the sequence", 642, 42, 9, C["muted"], MONO))
    dk += bars(642, 58, 300, 80, [4, 5, 6, 7, 8, 9, 11, 12, 13, 14],
               "#E4646C", None)
    dk.append(text("amplitude modulation increasing; frequency modulation "
                   "decreasing — the pattern the catalogue entry records",
                   642, 146, 9, C["muted"], MONO))
    dk += [text("events", 990, 42, 9, C["muted"], MONO),
           text("17", 990, 56, 16, C["black"], MONO),
           text("mean interval", 1090, 42, 9, C["muted"], MONO),
           text("0.44 h", 1090, 56, 16, C["black"], MONO),
           text("100 % of windows hold exactly one fall", 990, 92, 9,
                C["gink"], MONO),
           text("a purity check — it is how you know the family is one thing "
                "and not two", 990, 108, 9, C["muted"], MONO)]
    k.append(frame("aggregates", X, 700, W, 180, C["white"], radius=10,
                   stroke=C["border"], children=dk))
    return frame("analyse-4-interrogation", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 5
def train(ox):
    k = [nav(1), head("Analyse", "Terminal type Model  ·  a training chain",
                      "CH4_A2 · whole channel")]
    tk = [text("source", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("Signal  ·  CH4_A2  ·  whole channel  ·  720 h", 70, 12, True)
    tk += p
    tk.append(text("clustering runs statistically — no prior labels needed",
                   420, 20, 10, C["muted"], MONO))
    p, bw = button("Generate SLURM job", 1376 - 24 - 190, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    blocks = [("●", "Source", ""), ("01", "Sliding windows", ""),
              ("02", "Window matrix", ""), ("03", "Cluster", ""),
              ("04", "Encode", ""), ("05", "Model", "")]
    k.append(frame("chain-ribbon", X, 108, W, 56, C["white"], radius=10,
                   stroke=C["border"],
                   children=chain_ribbon(0, 0, W, blocks, active="03", h=56)))

    # ---- clustering
    ck = [text("03  Cluster", 18, 14, 12),
          text("Ward linkage over the window matrix", 110, 17, 9, C["muted"], MONO),
          rtext("Grouping", 602, 17, 9, C["muted"], MONO)]
    ck += dendrogram(24, 40, 572, 158, nleaves=24, seed=9,
                     groups=[(5, "#2E7D5B"), (7, "#2B5BA8"),
                             (4, "#7B3FA0"), (8, "#1E8E7E")])
    ck += dashes(24, 78, 572, C["grey"], 8, 6)
    ck.append(text("cut  —  6 classes", 24, 206, 9, C["muted"], MONO))
    ck.append(rtext("drag the cutline to change k", 596, 206, 9, C["blue"], MONO))
    ck += [rect(24, 226, 572, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("silhouette", "0.238", None),
                                         ("cophenetic r", "0.52", "#9A6206"),
                                         ("linkage", "Ward", None)]):
        ck += stat(24 + i * 190, 238, lab, val, col)
    ck.append(text("average linkage gives cophenetic r 0.91 but suggests k=2 — "
                   "state the selection criterion before reporting any "
                   "cluster-derived label set", 24, 276, 9, "#9A6206", MONO))
    k.append(frame("cluster", X, 176, 620, 316, C["white"], radius=10,
                   stroke=C["border"], children=ck))

    # ---- class balance / sufficiency gate
    bk = [text("Is there enough to train on?", 18, 14, 12),
          rtext("windows per class", 658, 17, 9, C["muted"], MONO)]
    counts = [1420, 980, 512, 318, 126, 64]
    cols = ["#2E7D5B", "#2B5BA8", "#7B3FA0", "#1E8E7E", C["amber"], C["red"]]
    bk += bars(18, 44, 640, 120, counts, cols,
               ["C1", "C2", "C3", "C4", "C5", "C6"])
    bk += [rect(18, 190, 640, 1, C["border"]),
           text("3,420 windows total", 18, 202, 12, C["black"], MONO),
           text("a CNN on Gramian images wants roughly 10,000. Two classes "
                "sit under 200, which will not train and will not be caught "
                "by overall accuracy.", 18, 224, 10, C["grey"], MONO)]
    bk += [rect(18, 258, 300, 26, "#FDF0D5", radius=6),
           text("random forest on Catch22 instead", 28, 265, 10, "#9A6206", MONO),
           rect(330, 258, 190, 26, "#FDF0D5", radius=6),
           text("or merge C5 and C6", 340, 265, 10, "#9A6206", MONO)]
    k.append(frame("balance", 736, 176, 676, 316, C["white"], radius=10,
                   stroke=C["border"], children=bk))

    # ---- encoding
    ek = [text("04  Encode", 18, 14, 12),
          text("what the classifier actually sees — one example per class",
               100, 17, 9, C["muted"], MONO),
          rtext("Encoding", 602, 17, 9, C["muted"], MONO)]
    for i in range(4):
        gx = 22 + i * 148
        ek += heat_grid(gx, 40, 128, 128, nx=14, ny=14, seed=3 + i * 2,
                        diag=(i == 2))
        ek.append(text(["C1 GASF", "C2 GASF", "C3 recurrence", "C4 fusion"][i],
                       gx, 174, 9, C["muted"], MONO))
    k.append(frame("encode", X, 508, 620, 208, C["white"], radius=10,
                   stroke=C["border"], children=ek))

    # ---- job export
    jk = [text("05  Model", 18, 14, 12),
          text("the site writes the job; the HPC runs it", 90, 17, 9,
               C["muted"], MONO),
          rtext("Model", 658, 17, 9, C["muted"], MONO)]
    for i, (lab, val, col) in enumerate([("architecture", "EfficientNet-B0", None),
                                         ("images", "3,420", "#9A6206"),
                                         ("est. wall time", "2 h 40", None)]):
        jk += stat(18 + i * 220, 44, lab, val, col)
    jk += [rect(18, 92, 640, 88, "#15161A", radius=6),
           text("#!/bin/bash", 30, 102, 9, "#7FB8EE", MONO),
           text("#SBATCH --gres=gpu:1  --time=04:00:00", 30, 118, 9,
                "#9CC4F0", MONO),
           text("#SBATCH --job-name=ub_cnn_run131", 30, 134, 9, "#9CC4F0", MONO),
           text("python -m pipeline.train --recipe a7f3…9c --manifest ...",
                30, 150, 9, C["trace"], MONO),
           text("The manifest comes back through Admin's import action, so "
                "the trained model lands as a Model artifact this chain can "
                "reference.", 18, 188, 10, C["muted"], MONO)]
    k.append(frame("job", 736, 508, 676, 208, C["white"], radius=10,
                   stroke=C["border"], children=jk))

    k.append(frame("note", X, 732, W, 148, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("A trained model becomes a block", 18, 16, 12),
        text("Once imported, this model is available as a step inside a "
             "detection chain in Analyse, or as an algorithm in Discovery — "
             "Model is one of the seven interchange types, so nothing special "
             "is needed to use it.", 18, 42, 10, C["grey"], MONO),
        text("If the source had been a Library family rather than a whole "
             "channel, the input would already be grouped and stage 03 would "
             "be skipped rather than optional — which is the sort of thing the "
             "source block makes visible instead of silently wrong.",
             18, 68, 10, C["grey"], MONO),
        text("Nothing here writes a verdict. A model that labels spans "
             "produces candidates, and candidates go to Review.",
             18, 110, 10, C["blue"], MONO)]))
    return frame("analyse-5-train", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 6
def discovery_algorithms(ox):
    k = [nav(2), head("Discovery", "Algorithms  ·  apply saved detectors at scale",
                      "M2_aug_concat_fs1.mat · CH4_A2")]
    tk = [text("section", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("112 – 286 h  ·  174 h of 720 h", 74, 12, True)
    tk += p
    tk.append(text("drag the handles above to change it", 330, 20, 10,
                   C["muted"], MONO))
    p, bw = button("Preview on a sample", 1376 - 24 - 320, 11, h=30)
    tk += p
    p, bw = button("Run 3 algorithms  →", 1376 - 24 - 170, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    sk = [text("CHANNEL", 16, 12, 9, C["muted"], MONO),
          text("CH4_A2  ·  0 – 720 h", 82, 12, 9, C["grey"], MONO),
          rtext("preview ran on 4 h · extrapolated 38 min · routes to cluster",
                W - 16, 12, 9, C["amber"], MONO)]
    sk += section_slider(16, 32, W - 32, 62, sel=(0.155, 0.24))
    k.append(frame("section", X, 108, W, 110, C["white"], radius=10,
                   stroke=C["border"], children=sk))

    # ---- n-way coverage ribbon, including the human store
    rk = [text("Where each algorithm fires", 18, 14, 12),
          text("the human annotation store is just another row — this is what "
               "Explore's agreement view used to be", 230, 17, 9, C["muted"], MONO),
          rtext("pick two rows to compare in detail", W - 18, 17, 9,
                C["blue"], MONO)]
    tracks = [("human annotations", C["green"],
               [(20, 70), (210, 60), (420, 130), (690, 70), (860, 110)]),
              ("drop_motifs9", C["blue"],
               [(24, 64), (300, 90), (416, 140), (560, 80), (866, 100), (980, 60)]),
              ("sharkfin_v2", C["purple"],
               [(30, 50), (300, 84), (620, 70), (866, 92)]),
              ("mp_seeded_F03", C["amber"],
               [(210, 56), (420, 120), (700, 64), (980, 54)])]
    for i, (nm, col, segs) in enumerate(tracks):
        yy = 44 + i * 30
        rk.append(text(nm, 18, yy + 3, 10, C["black"], MONO))
        for x0, wd in segs:
            rk.append(rect(180 + x0 * 1.07, yy, wd * 1.07, 16, col, radius=3))
    k.append(frame("coverage", X, 230, W, 176, C["white"], radius=10,
                   stroke=C["border"], children=rk))

    # ---- browse
    bk = [text("Browse this run's detections", 18, 14, 12),
          text("drop_motifs9  ·  50 found", 230, 17, 10, C["grey"], MONO),
          rtext("browse only — judgement happens in Review", W - 18, 17, 9,
                C["muted"], MONO)]
    bk += arrow_nav(18, 38, 12, 50)
    bk += [rect(190, 38, W - 208, 128, C["dark"], radius=5),
           rect(190 + (W - 208) * 0.44, 38, (W - 208) * 0.06, 128, "#4A3A14",
                stroke=C["orange"])]
    bk.append(wander(190, 38, W - 208, 128, 4433, pts=260, amp=0.30, drift=0.22,
                     wobble=13, ripple=0.03, sw=1.3))
    bk += [text("d-0412  ·  192.4 h  ·  score 0.88", 18, 74, 10,
                C["black"], MONO),
           text("no prior adjudication", 18, 92, 9, C["muted"], MONO),
           text("matched to nothing in the store at IoU ≥ 0.5", 18, 110, 9,
                C["muted"], MONO)]
    k.append(frame("browse", X, 418, W, 184, C["white"], radius=10,
                   stroke=C["border"], children=bk))

    # ---- the scoreboard
    pk = [text("How well did each algorithm do?", 18, 14, 12),
          rtext("refresh after reviewing", W - 18, 17, 10, C["blue"], MONO)]
    cols = ["algorithm", "found", "already judged", "reviewed", "interesting",
            "precision", "recall", "surrogate"]
    cxs = [18, 250, 340, 470, 570, 700, 810, 980]
    pk.append(rect(18, 40, W - 36, 1, C["border"]))
    for c, cx in zip(cols, cxs):
        pk.append(text(c, cx, 46, 9, C["muted"], MONO))
    rows = [("drop_motifs9", "50", "8", "50", "12", "24 %",
             "0.71 over 14 h", "6", C["blue"]),
            ("sharkfin_v2", "23", "11", "0", "—", "not yet scored",
             "—", "2", C["purple"]),
            ("mp_seeded_F03", "87", "19", "40", "7", "18 %",
             "no reviewed overlap", "14", C["amber"])]
    for i, r in enumerate(rows):
        yy = 66 + i * 34
        if i % 2 == 0:
            pk.append(rect(14, yy - 7, W - 28, 32, C["page"], radius=4))
        pk.append(ellipse(18, yy + 3, 8, 8, r[8]))
        pk.append(text(r[0], 34, yy, 11, C["black"], MONO))
        for v, cx in zip(r[1:8], cxs[1:]):
            col = C["muted"] if v in ("—", "not yet scored",
                                      "no reviewed overlap") else C["black"]
            pk.append(text(v, cx, yy, 10, col, MONO))
    pk.append(text("Precision is precision, not accuracy — an algorithm that "
                   "finds 5 events and gets all 5 right would score 100 % and "
                   "be worse. Recall appears only where the section overlaps "
                   "human-reviewed coverage, scoped to that overlap.",
                   18, 176, 10, C["muted"], MONO))
    k.append(frame("scoreboard", X, 614, W, 204, C["white"], radius=10,
                   stroke=C["border"], children=pk))

    ak = [text("50 detections from drop_motifs9", 20, 20, 12, C["black"], MONO)]
    p, w1 = button("Discard run  (no adjudications)", 20 + 340, 12, h=30)
    ak += p
    p, w2 = button("Analyse events  →", W - 20 - 380, 12, h=30)
    ak += p
    p, w3 = button("Send all 50 to Review  →", W - 20 - 224, 12,
                   primary=True, h=30)
    ak += p
    k.append(frame("actions", X, 830, W, 54, C["white"], radius=10,
                   stroke=C["border"], children=ak))
    return frame("discovery-1-algorithms", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 7
def discovery_seed(ox):
    k = [nav(2), head("Discovery", "Seed  ·  find more of a shape you already have",
                      "seed F-03 · CH4_A2")]
    tk = [text("section", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("whole channel  ·  720 h", 74, 12, True)
    tk += p
    tk.append(text("MASS is O(n log n), so a whole channel is sub-second",
                   270, 20, 10, C["gink"], MONO))
    p, bw = button("Search", 1376 - 24 - 110, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    X, W = 88, 1328
    sk = [text("CHANNEL", 16, 12, 9, C["muted"], MONO),
          text("CH4_A2  ·  0 – 720 h  ·  searching all of it", 82, 12, 9,
               C["grey"], MONO)]
    sk += section_slider(16, 32, W - 32, 58, sel=(0.02, 0.96))
    k.append(frame("section", X, 108, W, 106, C["white"], radius=10,
                   stroke=C["border"], children=sk))

    # ---- the seed
    qk = [text("Seed", 18, 14, 12),
          rtext("from the Library", 384, 17, 9, C["muted"], MONO),
          rect(18, 40, 366, 104, C["dark"], radius=5)]
    qk.append(sawtooth_drops(20, 44, 362, 96, 77, n=1, col=C["orange"], sw=1.6))
    qk += [text("F-03  ·  sharkfin  ·  medoid member", 18, 156, 10,
                C["black"], MONO),
           text("native length 21.6 s — not quantised to a scale bank, so the "
                "exemplar's own extent is what is searched for",
                18, 176, 9, C["muted"], MONO),
           rect(18, 208, 366, 1, C["border"]),
           text("algorithm", 18, 220, 9, C["muted"], MONO),
           rect(90, 216, 294, 24, C["page"], radius=6, stroke=C["border"]),
           text("MASS distance profile", 100, 222, 10, C["black"], MONO),
           text("exclusion", 18, 254, 9, C["muted"], MONO),
           rect(90, 250, 294, 24, C["page"], radius=6, stroke=C["border"]),
           text("m/2  =  10.8 s", 100, 256, 10, C["black"], MONO),
           text("trivial matches must be excluded explicitly, or the result "
                "looks spectacular and means nothing", 18, 286, 9,
                C["red"], MONO)]
    k.append(frame("seed", X, 226, 402, 316, C["white"], radius=10,
                   stroke=C["border"], children=qk))

    # ---- threshold against the surrogate
    hk = [text("Where to cut", 18, 14, 12),
          text("match distance across the channel, with the surrogate's "
               "distribution behind it", 110, 17, 9, C["muted"], MONO),
          rtext("drag the line", 878, 17, 10, C["blue"], MONO)]
    hk += hist_overlay(24, 46, 850, 160, seed=9, thresh=0.36, excl=0.085)
    hk += [rect(24, 216, 12, 10, C["blue"]),
           text("real matches", 42, 214, 9, C["grey"], MONO),
           rect(150, 216, 12, 10, "#DDDDE2"),
           text("surrogate", 168, 214, 9, C["grey"], MONO),
           rect(250, 216, 12, 10, "#F6DADA"),
           text("trivial-match zone, excluded", 268, 214, 9, C["grey"], MONO),
           rect(24, 240, 850, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("threshold", "0.42", None),
                                         ("matches kept", "63", None),
                                         ("surrogate would give", "9", C["muted"]),
                                         ("7.0× above chance", "", C["gink"])]):
        hk += stat(24 + i * 220, 254, lab, val, col)
    hk.append(text("The threshold is chosen against the null rather than set to "
                   "a round number — you can see how many of these chance alone "
                   "would hand you.", 24, 292, 10, C["muted"], MONO))
    k.append(frame("threshold", 514, 226, 898, 316, C["white"], radius=10,
                   stroke=C["border"], children=hk))

    # ---- results
    rk = [text("63 matches", 18, 14, 12),
          text("sorted by distance", 116, 17, 10, C["grey"], MONO),
          rtext("browse only — judgement happens in Review", W - 18, 17, 9,
                C["muted"], MONO)]
    for i in range(7):
        cx = 18 + i * 188
        d = 0.19 + i * 0.031
        prior = i in (2, 5)
        rk += [rect(cx, 40, 174, 124, C["page"], radius=8,
                    stroke=C["border"]),
               text("m-%03d" % (101 + i), cx + 10, 48, 9, C["black"], MONO),
               rtext("d %.2f" % d, cx + 164, 48, 9, C["grey"], MONO),
               rect(cx + 10, 66, 154, 56, C["dark"], radius=4)]
        rk.append(sawtooth_drops(cx + 11, 68, 152, 52, 300 + i * 41, n=1,
                                 col=C["orange"] if i < 4 else C["trace"],
                                 sw=1.2))
        if prior:
            rk += [ellipse(cx + 10, 132, 7, 7, C["green"]),
                   text("already interesting", cx + 22, 130, 9, C["grey"], MONO)]
        else:
            rk.append(text("new", cx + 10, 130, 9, C["muted"], MONO))
        rk.append(text("%.1f h" % (112 + i * 63.4), cx + 10, 146, 9,
                       C["muted"], MONO))
    k.append(frame("matches", X, 558, W, 178, C["white"], radius=10,
                   stroke=C["border"], children=rk))

    ak = [text("63 matches  ·  19 already judged  ·  44 new", 20, 20, 12,
               C["black"], MONO),
          text("rediscoveries keep a pointer to the prior adjudication, so the "
               "same span is never put to you twice", 20, 40, 9,
               C["muted"], MONO)]
    p, w1 = button("Discard run", 480, 12, h=30)
    ak += p
    p, w2 = button("Analyse events  →", W - 20 - 400, 12, h=30)
    ak += p
    p, w3 = button("Send 44 new to Review  →", W - 20 - 240, 12,
                   primary=True, h=30)
    ak += p
    k.append(frame("actions", X, 752, W, 62, C["white"], radius=10,
                   stroke=C["border"], children=ak))

    k.append(frame("note", X, 826, W, 54, C["gtint"], radius=8, children=[
        text("Sent candidates arrive at the top of Review's queue tagged with "
             "this run. Come back here afterwards and the precision figure "
             "will have filled itself in.", 16, 18, 10, C["gink"], MONO)]))
    return frame("discovery-2-seed", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ output
LABELS = [("1  ·  Analyse — the chain, every stage visible", 0),
          ("2  ·  a stage opened for tuning, with its own null", 1560),
          ("3  ·  terminal type SpanSet — detection", 3120),
          ("4  ·  terminal type features — interrogation", 4680),
          ("5  ·  terminal type Model — training", 6240),
          ("6  ·  Discovery — algorithms at scale, scored", 7800),
          ("7  ·  Discovery — seeded search", 9360)]

screens = [chain_view(0), block_open(1560), detection_surface(3120),
           interrogation(4680), train(6240), discovery_algorithms(7800),
           discovery_seed(9360)]
labels = [text(l, x, -46, 16, C["grey"], MONO) for l, x in LABELS]

write_doc("UI_analyse_discovery_v2.pen", screens + labels)
