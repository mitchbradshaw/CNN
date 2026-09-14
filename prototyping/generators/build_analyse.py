#!/usr/bin/env python3
"""
Five concepts for the Analyse workspace.

The organising idea, taken from the drop_motifs9 figure: a chain is a
FILM STRIP. Each stage gets a row, and each row is drawn the way that stage
needs to be drawn -- a line for raw signal, a twin overlay for detrending,
symbol bands for dSAX, threshold bars for the noise floor, markers for
detections. The transformation is the interface.

Every stage row also carries one plain-English sentence saying what it did.
That sentence is the whole product thesis: the researcher should not have to
read the code to know whether a stage is doing the right thing.

  A  film-strip      the chain as a scrolling strip of stage rows
  B  inspector       strip compressed to a rail; one stage opened large with
                     its generated controls and a live derived readout
  C  sweep           one parameter swept, its output drawn as small multiples
                     so the setting is chosen by eye against a null
  D  compare         two chains side by side, rows aligned, identical stages
                     dimmed, with a set-overlap panel underneath
  E  workbench       after the run: the heterogeneous outputs -- dendrogram,
                     families, encodings, scores -- as interrogable cards

All five obey the PRD: a linear spine with named side-inputs, no node canvas,
seven interchange types, surrogate control on by default.

Run:  python build_analyse.py  ->  UI_analyse_concepts_v1.pen
"""

import math

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, ctext,
                     sidebar, header, chip, button, tw, write_doc)
from pen_widgets import (SYM, SYM_ORDER, HEAT, MAGMA, ONSET, dashes, vdashes,
                         wander, sawtooth_drops, baseline_overlay, ensemble,
                         symbol_strip, slope_bars, heat_grid, scalogram,
                         dendrogram, slider, selectbox, seg_control, toggle,
                         stat)

TYPES = {"sig": "Signal", "enc": "Encoding", "sco": "Scores",
         "spn": "SpanSet", "win": "WindowSet", "grp": "Grouping",
         "mod": "Model"}


# ---------------------------------------------------------------- chrome
def toolbar(active_chain, right_note, run_label="Run chain",
            surrogate=True, y=44, w=1376):
    k = [text("CH4_A2", 24, 19, 11, C["black"], MONO),
         text("  ·  825 – 875 s  ·  50 s span", 24 + tw("CH4_A2", 11, MONO),
              19, 11, C["grey"], MONO)]
    cx = 300
    parts, cw = chip(active_chain, cx, 12, True)
    k += parts
    cx += cw + 10
    parts, cw = chip("6 stages", cx, 12, False)
    k += parts
    k += toggle(640, 15, "surrogate control", surrogate)
    k.append(text(right_note, 830, 19, 10, C["muted"], MONO))
    parts, bw = button(run_label, w - 24 - 140, 11, primary=True, h=30)
    k += parts
    return frame("toolbar", 64, y, w, 56, C["page"], children=k)


def type_pill(x, y, src, dst):
    label = TYPES[src] + "  →  " + TYPES[dst]
    w = tw(label, 9, MONO) + 16
    return [rect(x, y, w, 18, C["page"], radius=5),
            text(label, x + 8, y + 5, 9, C["muted"], MONO)], w


def insert_bar(x, y, w):
    label = "+  insert a stage here"
    lw = tw(label, 10, MONO) + 28
    return [rect(x, y + 9, w, 1, C["border"]),
            rect(x + (w - lw) / 2, y, lw, 20, C["white"], radius=10,
                 stroke=C["border"]),
            text(label, x + (w - lw) / 2 + 14, y + 5, 10, C["grey"], MONO)]


# ---------------------------------------------------------------- stage rows
STAGES = [
    ("00", "Locate", "where this span sits in the recording",
     "50 s of 1200 s", "sig", "sig", 76),
    ("01", "Raw window", "the signal exactly as it comes off the channel",
     "the slow wander is resting potential, not signal", "sig", "sig", 104),
    ("02", "Baseline removal", "subtract a 7 s rolling median",
     "every gradient below is measured on the blue trace", "sig", "sig", 128),
    ("03", "Symbolic encoding", "each 0.2 s segment becomes a letter",
     "dSAX k=3, then D and U split by the noise floor", "sig", "enc", 104),
    ("04", "Noise floor", "the cut is physical, not statistical",
     "σ of slope noise = 0.00958 mV/s, so d starts at 8σ", "enc", "sco", 104),
    ("05", "Drop detection", "23 raw detections, 6 kept after dedupe",
     "shaded span runs onset → trough", "sco", "spn", 124),
]


def stage_plot(kind, x, y, w, h):
    """Each stage is drawn the way that stage needs to be drawn."""
    if kind == "00":
        out = [rect(x, y, w, h, C["dark"], radius=4),
               rect(x + w * 0.68, y, w * 0.055, h, "#5A3A18", stroke=C["orange"]),
               wander(x, y, w, h, 4711, pts=380, amp=0.34, drift=0.16, wobble=29)]
        return out
    if kind == "01":
        return [rect(x, y, w, h, C["dark"], radius=4),
                wander(x, y, w, h, 9137, pts=300, amp=0.30, drift=0.20,
                       wobble=17, ripple=0.035, col=C["trace"], sw=1.3)]
    if kind == "02":
        return [rect(x, y, w, h, C["white"], radius=4, stroke=C["border"])] + \
               baseline_overlay(x + 4, y + 4, w - 8, h - 8, 9137)
    if kind == "03":
        sh = (h - 10) / 2
        return (symbol_strip(x, y, w, sh, 21, n=130, five=True) +
                symbol_strip(x, y + sh + 10, w, sh, 21, n=130, five=False))
    if kind == "04":
        return [rect(x, y, w, h, C["white"], radius=4, stroke=C["border"])] + \
               slope_bars(x + 6, y + 6, w - 12, h - 12, 33, n=104)
    if kind == "05":
        out = [rect(x, y, w, h, C["dark"], radius=4)]
        for mx, mw, col in [(0.11, 0.02, "#3A3A3C"), (0.22, 0.018, "#3A3A3C"),
                            (0.40, 0.022, "#3A3A3C"), (0.545, 0.034, "#4A2B6B"),
                            (0.71, 0.02, "#3A3A3C"), (0.845, 0.030, "#16544B")]:
            out.append(rect(x + w * mx, y, w * mw, h, col))
        out.append(wander(x, y, w, h, 9137, pts=300, amp=0.30, drift=0.20,
                          wobble=17, ripple=0.035, col=C["trace"], sw=1.3))
        for mx, col, filled in [(0.554, C["purple"], True), (0.856, "#1E8E7E", True),
                                (0.118, C["muted"], False), (0.228, C["muted"], False),
                                (0.408, C["muted"], False), (0.716, C["muted"], False)]:
            if filled:
                out.append(ellipse(x + w * mx - 4, y + h * 0.24, 9, 9, col))
            else:
                out.append(ellipse(x + w * mx - 3, y + h * 0.30, 7, 7, "#4A4A4E"))
        return out
    return []


def stage_row(x, y, w, spec, compact=False):
    idx, name, cap1, cap2, src, dst, h = spec
    kids = [text(idx, 14, 14, 10, C["muted"], MONO),
            text(name, 40, 12, 12, C["black"], SANS, True),
            text(cap1, 14, 36, 9, C["grey"], MONO),
            text(cap2, 14, 50, 9, C["muted"], MONO)]
    parts, pw = type_pill(14, h - 30, src, dst)
    kids += parts
    kids.append(rtext("⋮", 196, 12, 13, C["grey"]))
    px, pw2 = 222, w - 222 - 14
    kids += stage_plot(idx, px, 14, pw2, h - 28)
    if idx == "03":
        lx = px
        for s in SYM_ORDER:
            kids += [rect(lx, h - 13, 9, 9, SYM[s]),
                     text({"d": "fast down", "D": "down", "S": "same",
                           "U": "up", "u": "fast up"}[s], lx + 13, h - 14, 8,
                          C["muted"], MONO)]
            lx += 13 + tw({"d": "fast down", "D": "down", "S": "same",
                           "U": "up", "u": "fast up"}[s], 8, MONO) + 16
    return frame("stage/" + idx + "-" + name.lower().replace(" ", "-"),
                 x, y, w, h, C["white"], radius=10, stroke=C["border"],
                 children=kids)


# ================================================================ A
def film_strip(ox):
    k = [sidebar(1), header("Analyse", "Film strip  ·  the chain is the picture",
                            "drop_motifs9 + refine9")]
    k.append(toolbar("drop_motifs9 + refine9", "est. 1.8 s  ·  runs locally"))

    X, W = 88, 1328
    y = 100
    for i, spec in enumerate(STAGES):
        k.append(stage_row(X, y, W, spec))
        y += spec[6]
        if i < len(STAGES) - 1:
            k += insert_bar(X, y, W)
            y += 20

    fk = [text("6 detections kept", 20, 20, 13, C["black"], SANS, True),
          text("from 23 raw  ·  surrogate found 2  ·  6.1× above chance",
               170, 21, 11, C["grey"], MONO)]
    p1, w1 = button("Save as template", W - 20 - 470, 12, h=30)
    p2, w2 = button("Export run", W - 20 - 330, 12, h=30)
    p3, w3 = button("Pass 6 to Review  →", W - 20 - 216, 12, primary=True, h=30)
    fk += p1 + p2 + p3
    k.append(frame("run-footer", X, 850, W, 42, C["white"], radius=10,
                   stroke=C["border"], children=fk))

    return frame("analyse-A-film-strip", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ B
def inspector(ox):
    k = [sidebar(1), header("Analyse", "Inspector  ·  one stage, room to tune it",
                            "drop_motifs9 + refine9")]
    k.append(toolbar("drop_motifs9 + refine9", "stage 03 retunes from cache"))

    # ---- stage rail
    rk = [text("Chain", 20, 16, 12),
          rtext("6 stages", 280, 19, 10, C["muted"], MONO)]
    for i, spec in enumerate(STAGES):
        idx, name, cap1, _, src, dst, _ = spec
        on = idx == "03"
        ry = 44 + i * 78
        rk += [rect(14, ry, 272, 68, C["tint"] if on else C["white"], radius=8,
                    stroke=C["blue"] if on else C["border"]),
               text(idx, 26, ry + 10, 9, C["muted"], MONO),
               text(name, 48, ry + 8, 11, C["blue"] if on else C["black"], MONO),
               rtext("cached" if i < 3 else "—", 274, ry + 10, 9,
                     C["green"] if i < 3 else C["muted"], MONO)]
        rk += stage_plot(idx, 26, ry + 28, 248, 30)
    k.append(frame("stage-rail", 64, 100, 300, 800, C["white"], children=rk +
                   [rect(299, 0, 1, 800, C["border"])]))

    X, W = 388, 1028
    k += [text("03  Symbolic encoding", X, 114, 16, C["black"], SANS, True),
          text("Signal  →  Encoding", X + 250, 120, 10, C["muted"], MONO),
          rtext("stages 04–05 will recompute  ·  00–02 reuse cache",
                X + W, 120, 10, C["amber"], MONO)]

    # ---- the big view: trace, both strips, slope bars, all on one axis
    bk = [text("detrended input", 16, 12, 9, C["muted"], MONO),
          rect(16, 28, W - 32, 66, C["dark"], radius=4)]
    bk.append(wander(16, 28, W - 32, 66, 9137, pts=280, amp=0.28, drift=0.20,
                     wobble=15, ripple=0.04, col=C["trace"], sw=1.2))
    bk.append(text("5 bands  (d D S U u)", 16, 106, 9, C["muted"], MONO))
    bk += symbol_strip(16, 122, W - 32, 30, 21, n=140, five=True)
    bk.append(text("dSAX k=3  (D S U)", 16, 162, 9, C["muted"], MONO))
    bk += symbol_strip(16, 178, W - 32, 30, 21, n=140, five=False)
    bk.append(text("segment slope, mV/s", 16, 218, 9, C["muted"], MONO))
    bk += slope_bars(16, 234, W - 32, 96, 33, n=112)
    lx = 16
    for s in SYM_ORDER:
        lab = {"d": "fast down", "D": "down", "S": "same", "U": "up",
               "u": "fast up"}[s]
        bk += [rect(lx, 340, 9, 9, SYM[s]),
               text(lab, lx + 13, 339, 9, C["muted"], MONO)]
        lx += 13 + tw(lab, 9, MONO) + 18
    k.append(frame("stage-view", X, 144, W, 362, C["white"], radius=10,
                   stroke=C["border"], children=bk))

    # ---- generated parameter controls
    pk = [text("Parameters", 18, 16, 12),
          rtext("generated from the adapter spec", W - 18, 19, 9, C["muted"], MONO)]
    parts, _ = seg_control(18, 48, "alphabet size  k", [3, 4, 5], 3)
    pk += parts
    pk += slider(200, 48, 200, "segment length", "0.2 s", 0.20,
                 "2 samples per segment · 250 segments")
    pk += slider(440, 48, 200, "same_fraction", "0.60", 0.60,
                 "recommended 0.58 for this span")
    pk += slider(680, 48, 200, "noise floor", "8 σ", 0.55,
                 "σ = 0.00958 mV/s (MAD)")
    pk += selectbox(910, 44, 100, "split", "d/D, U/u")
    k.append(frame("parameters", X, 522, W, 122, C["white"], radius=10,
                   stroke=C["border"], children=pk))

    # ---- live derived readout, in plain English
    dk = [text("At these settings", 18, 16, 12),
          text("60 % of segments land in SAME, which is what same_fraction "
               "is asking for. The 8σ cut puts 'd' at −0.0767 mV/s — "
               "\"falling faster than the noise can explain\".",
               18, 44, 11, C["grey"], MONO),
          text("k=5 is NOT read from dSAX directly: its quantile cutlines "
               "honour same_fraction only at k=3, so the bands are split "
               "afterwards by the physical noise floor.",
               18, 64, 11, C["muted"], MONO)]
    for i, (lab, val, col) in enumerate([("segments", "250", None),
                                         ("in SAME", "60 %", None),
                                         ("qualify as d", "23", SYM["d"]),
                                         ("qualify as u", "31", SYM["u"]),
                                         ("σ slope noise", "0.00958", None),
                                         ("recompute cost", "0.4 s", C["green"])]):
        dk += stat(18 + i * 170, 96, lab, val, col)
    p1, w1 = button("Revert to recommended", W - 18 - 340, 100, h=28)
    p2, w2 = button("Apply and rerun from 03  →", W - 18 - 190, 100,
                    primary=True, h=28)
    dk += p1 + p2
    k.append(frame("derived", X, 660, W, 140, C["white"], radius=10,
                   stroke=C["border"], children=dk))

    k.append(frame("cache-note", X, 816, W, 44, C["gtint"], radius=8, children=[
        text("Stages 00–02 are content-hashed and cached, so retuning "
             "this stage costs 0.4 s rather than recomputing the chain.",
             16, 15, 10, C["gink"], MONO)]))

    return frame("analyse-B-inspector", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ C
def sweep(ox):
    k = [sidebar(1), header("Analyse", "Sweep  ·  choose a parameter by eye",
                            "drop_motifs9 + refine9")]
    k.append(toolbar("drop_motifs9 + refine9", "8 variants  ·  est. 12 s",
                     run_label="Run sweep"))

    X, W = 88, 1328

    # ---- chain ribbon, with the swept stage marked
    ck = [text("chain", 16, 22, 9, C["muted"], MONO)]
    cx = 62
    for idx, name, _, _, src, dst, _ in STAGES:
        on = idx == "04"
        bw = tw(name, 10, MONO) + 30
        ck += [rect(cx, 14, bw, 36, C["tint"] if on else C["page"], radius=7,
                    stroke=C["blue"] if on else C["border"]),
               text(idx, cx + 10, 21, 9, C["muted"], MONO),
               text(name, cx + 10, 34, 10, C["blue"] if on else C["black"], MONO)]
        cx += bw
        if idx != "05":
            ck.append(text("›", cx + 6, 24, 12, C["muted"]))
            cx += 20
    ck.append(rtext("sweeping stage 04  ·  noise floor multiplier",
                    W - 16, 26, 10, C["blue"], MONO))
    k.append(frame("chain-ribbon", X, 108, W, 64, C["white"], radius=10,
                   stroke=C["border"], children=ck))

    # ---- small multiples
    vals = [("2 σ", 148, 96, False), ("4 σ", 92, 41, False),
            ("6 σ", 48, 17, False), ("8 σ", 23, 2, True),
            ("10 σ", 14, 1, False), ("12 σ", 9, 1, False),
            ("16 σ", 4, 0, False), ("20 σ", 1, 0, False)]
    cw, ch = 320, 196
    for i, (lab, det, sur, on) in enumerate(vals):
        col, row = i % 4, i // 4
        vx, vy = X + col * (cw + 16), 188 + row * (ch + 16)
        kids = [text(lab, 14, 12, 12, C["blue"] if on else C["black"], MONO),
                rtext("selected" if on else "use this", cw - 14, 14, 9,
                      C["blue"] if on else C["muted"], MONO),
                rect(14, 34, cw - 28, 74, C["white"], radius=4, stroke=C["border"])]
        kids += slope_bars(18, 38, cw - 36, 66, 33 + i, n=44,
                           sigma=0.14 + i * 0.085)
        kids += [text("detections", 14, 120, 9, C["muted"], MONO),
                 rtext(str(det), cw - 14, 119, 11, C["black"], MONO),
                 rect(14, 136, cw - 28, 7, C["border"], radius=3),
                 rect(14, 136, max(4, (cw - 28) * det / 148), 7, C["blue"], radius=3),
                 text("surrogate", 14, 150, 9, C["muted"], MONO),
                 rtext(str(sur), cw - 14, 149, 11, C["black"], MONO),
                 rect(14, 166, cw - 28, 7, C["border"], radius=3),
                 rect(14, 166, max(3, (cw - 28) * sur / 148), 7, C["muted"], radius=3)]
        ratio = "—" if sur == 0 else "%.1f×" % (det / sur)
        kids.append(rtext(ratio + " above chance", cw - 14, 178, 9,
                          C["gink"] if on else C["muted"], MONO))
        k.append(frame("variant/" + lab, vx, vy, cw, ch,
                       C["tint"] if on else C["white"], radius=10,
                       stroke=C["blue"] if on else C["border"], children=kids))

    # ---- the curve that actually decides it
    gk = [text("Detections against the null, across the sweep", 18, 14, 12),
          rtext("the knee is the answer, not the peak", W - 18, 17, 10,
                C["muted"], MONO)]
    base = 60
    for i, (lab, det, sur, on) in enumerate(vals):
        bx = 60 + i * 150
        hd = det / 148 * 86
        hs = sur / 148 * 86
        gk += [rect(bx, base + 86 - hd, 34, hd, C["blue"] if on else "#9CC4F0",
                    radius=3),
               rect(bx + 40, base + 86 - max(2, hs), 34, max(2, hs),
                    C["border"], radius=3),
               text(lab, bx + 16, base + 92, 9,
                    C["blue"] if on else C["muted"], MONO)]
    gk += dashes(52, base, 1180, C["border"], 6, 6)
    p1, w1 = button("Apply 8 σ to the chain  →", W - 18 - 200, 118,
                    primary=True, h=30)
    gk += p1
    k.append(frame("sweep-curve", X, 620, W, 170, C["white"], radius=10,
                   stroke=C["border"], children=gk))

    k.append(frame("sweep-note", X, 802, W, 46, C["gtint"], radius=8, children=[
        text("Every variant runs its own surrogate, so the sweep is chosen "
             "against a null rather than by counting detections. Below 6 σ the "
             "count climbs but so does the surrogate — that is noise being "
             "harvested, not signal.", 16, 16, 10, C["gink"], MONO)]))

    return frame("analyse-C-sweep", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ D
def compare(ox):
    k = [sidebar(1), header("Analyse", "Compare  ·  does one chain find what the "
                            "other misses", "run 114 vs run 119")]
    k.append(toolbar("compare: direct vs banded", "both runs complete",
                     run_label="Rerun both"))

    COLS = [("A  ·  direct", 88, "run 114", C["blue"]),
            ("B  ·  banded 0.001–0.01 Hz", 762, "run 119", C["purple"])]
    ROWS = [("01", "Raw window", True), ("bp", "Bandpass", False),
            ("02", "Baseline removal", True), ("03", "Symbolic encoding", True),
            ("05", "Drop detection", False)]

    for title, cx, runid, ccol in COLS:
        k += [text(title, cx, 112, 13, C["black"], SANS, True),
              text(runid, cx + tw(title, 13) + 16, 116, 10, C["muted"], MONO)]
        y = 140
        for idx, name, same in ROWS:
            banded = idx == "bp"
            present = not (banded and cx == 88)
            kids = []
            if present:
                kids = [text(name, 14, 10, 11, C["black"], MONO)]
                if same:
                    kids.append(rtext("identical", 636, 12, 9, C["muted"], MONO))
                else:
                    kids.append(rtext("differs", 636, 12, 9, C["amber"], MONO))
                pk = idx if idx != "bp" else "01"
                kids += stage_plot(pk, 14, 30, 622, 48)
                if banded:
                    kids.append(rect(14, 30, 622, 48, "#2A1F3D"))
                    kids += [wander(14, 30, 622, 48, 7711, pts=240, amp=0.36,
                                    drift=0.30, col=C["purple"], sw=1.2,
                                    wobble=7)]
            else:
                kids = [text("no equivalent stage", 14, 32, 10, C["muted"], MONO),
                        rect(14, 30, 622, 48, C["page"], radius=4)]
            k.append(frame("%s/%s" % (runid, name), cx, y, 650, 88,
                           C["white"] if present else C["page"], radius=10,
                           stroke=C["border"],
                           children=kids))
            y += 100

    # ---- set overlap
    ok = [text("Set overlap", 18, 16, 13, C["black"], SANS, True),
          text("spans matched within ± 2 s", 130, 19, 10, C["muted"], MONO)]
    total = 187
    segs = [("only A  ·  direct", 42, C["blue"]),
            ("both", 118, C["muted"]),
            ("only B  ·  banded", 27, C["purple"])]
    bx = 18
    for lab, n, col in segs:
        wseg = 1288 * n / total
        ok += [rect(bx, 48, wseg, 30, col, radius=4),
               text(str(n), bx + 10, 56, 12, C["white"], MONO)]
        ok.append(text(lab, bx, 86, 10, C["grey"], MONO))
        bx += wseg + 4
    for i, (lab, val, col) in enumerate([
            ("A detections", "160", C["blue"]),
            ("A surrogate", "26", C["muted"]),
            ("B detections", "145", C["purple"]),
            ("B surrogate", "19", C["muted"]),
            ("B-only above chance", "yes", C["gink"])]):
        ok += stat(18 + i * 250, 112, lab, val, col)
    p1, w1 = button("Adjudicate the 27 B-only spans  →", 1324 - 18 - 250, 112,
                    primary=True, h=30)
    ok += p1
    k.append(frame("set-overlap", 88, 646, 1324, 166, C["white"], radius=10,
                   stroke=C["border"], children=ok))

    k.append(frame("compare-note", 88, 824, 1324, 46, C["gtint"], radius=8,
                   children=[text("The 27 spans only the banded chain finds are "
                                  "the whole point of the comparison — they go to "
                                  "Review by hand, because a set difference is a "
                                  "claim about method, not a finding yet.",
                                  16, 16, 10, C["gink"], MONO)]))

    return frame("analyse-D-compare", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ E
def workbench(ox):
    k = [sidebar(1), header("Analyse", "Workbench  ·  interrogate what came out",
                            "run 121  ·  complete")]
    k.append(toolbar("cluster_shapes_v3", "34 motifs  ·  ran on the cluster",
                     run_label="Rerun"))

    X = 88
    # ---- dendrogram
    dk = [text("Shape families", 18, 14, 12),
          text("Ward linkage, 34 motifs  ·  cophenetic r = 0.886", 140, 17, 9,
               C["muted"], MONO),
          rtext("Grouping", 622, 17, 9, C["muted"], MONO)]
    dk += dendrogram(24, 40, 592, 176, nleaves=26, seed=9,
                     groups=[(6, "#2E7D5B"), (8, "#2B5BA8"),
                             (4, "#7B3FA0"), (8, "#1E8E7E")])
    dk += dashes(24, 74, 592, C["grey"], 8, 6)
    dk += dashes(24, 104, 592, C["muted"], 8, 6)
    dk += [text("coarse cut  ·  6 families", 24, 224, 9, C["muted"], MONO),
           text("fine cut  ·  10 families", 200, 224, 9, C["muted"], MONO),
           rtext("drag a cutline to regroup", 616, 224, 9, C["blue"], MONO)]
    k.append(frame("dendrogram", X, 108, 640, 250, C["white"], radius=10,
                   stroke=C["border"], children=dk))

    # ---- family panels
    fk = [text("Families at the coarse cut", 18, 14, 12),
          rtext("onset-aligned  ·  each panel scaled to itself", 650, 17, 9,
                C["muted"], MONO)]
    fams = [("F-01", 3, "#2E7D5B"), ("F-02", 13, "#2B5BA8"),
            ("F-03", 3, "#7B3FA0"), ("F-04", 13, "#1E8E7E")]
    for i, (fid, n, col) in enumerate(fams):
        fx = 18 + i * 161
        fk += [rect(fx, 40, 150, 150, C["white"], radius=6, stroke=col),
               text(str(n), fx + 8, 46, 10, col, MONO)]
        fk += ensemble(fx + 6, 58, 138, 126, n=min(n, 10), seed=40 + i * 13,
                       onset=0.40, sw=1)
        fk.append(text(fid, fx + 8, 194, 10, C["black"], MONO))
        fk.append(rtext("send to Library", fx + 150, 195, 8, C["blue"], MONO))
    fk.append(text("the haloed line is the medoid — a real member, not an average",
                   18, 220, 9, C["muted"], MONO))
    k.append(frame("families", 744, 108, 668, 250, C["white"], radius=10,
                   stroke=C["border"], children=fk))

    # ---- encodings
    ek = [text("Encodings", 18, 14, 12),
          text("what the classifier actually sees", 104, 17, 9, C["muted"], MONO),
          rtext("Encoding", 622, 17, 9, C["muted"], MONO)]
    for i, (lab, diag, ramp) in enumerate([("GASF", False, HEAT),
                                           ("GADF", False, HEAT),
                                           ("recurrence", True, HEAT),
                                           ("fusion RGB", False, HEAT)]):
        gx = 20 + i * 152
        ek += heat_grid(gx, 42, 132, 132, nx=16, ny=16, seed=3 + i * 2,
                        ramp=ramp, diag=diag)
        ek.append(text(lab, gx, 180, 9, C["muted"], MONO))
    ek.append(text("CNN confidence on this window   0.91", 20, 202, 10,
                   C["black"], MONO))
    k.append(frame("encodings", X, 374, 640, 232, C["white"], radius=10,
                   stroke=C["border"], children=ek))

    # ---- scores / wavelet activity
    sk = [text("Activity and scores", 18, 14, 12),
          text("wavelet energy, then the thresholded profile", 158, 17, 9,
               C["muted"], MONO),
          rtext("Scores", 650, 17, 9, C["muted"], MONO)]
    sk += scalogram(18, 40, 632, 84, seed=4, ncol=58, nrow=10)
    sk += [rect(18, 134, 632, 52, C["white"], radius=4, stroke=C["border"])]
    r = 0
    for i in range(96):
        v = abs(math.sin(i / 4.3) * math.cos(i / 9.1)) ** 2.2
        hgt = 2 + v * 42
        sk.append(rect(22 + i * 6.5, 182 - hgt, 4.5, hgt,
                       C["green"] if hgt > 26 else "#BFE8C9", radius=1))
    sk += dashes(22, 156, 624, C["red"], 6, 5)
    sk += [text("threshold 153", 24, 142, 9, C["red"], MONO),
           text("4 peak clusters  ·  340 high-energy regions  ·  177 peaks",
                18, 194, 10, C["grey"], MONO)]
    k.append(frame("activity", 744, 374, 668, 232, C["white"], radius=10,
                   stroke=C["border"], children=sk))

    # ---- what leaves this screen
    ak = [text("What leaves this run", 20, 18, 13, C["black"], SANS, True),
          text("nothing here writes a verdict — candidates go to Review, "
               "families go to the Library, and both carry the recipe hash "
               "that produced them", 20, 42, 10, C["muted"], MONO)]
    for i, (lab, val, col) in enumerate([("motifs", "34", None),
                                         ("families, coarse", "6", None),
                                         ("families, fine", "10", None),
                                         ("surrogate motifs", "5", C["muted"]),
                                         ("recipe hash", "a7f3…9c", None)]):
        ak += stat(20 + i * 170, 70, lab, val, col)
    p1, w1 = button("Save as template", 1324 - 20 - 560, 66, h=30)
    p2, w2 = button("Export run", 1324 - 20 - 420, 66, h=30)
    p3, w3 = button("Send 4 families to Library", 1324 - 20 - 318, 66, h=30)
    p4, w4 = button("Pass 34 to Review  →", 1324 - 20 - 150, 66,
                    primary=True, h=30)
    ak += p1 + p2 + p3 + p4
    k.append(frame("handoff", X, 622, 1324, 112, C["white"], radius=10,
                   stroke=C["border"], children=ak))

    k.append(frame("wb-note", X, 750, 1324, 120, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("Why these cards and not a fixed layout", 18, 16, 12),
        text("A chain's output type decides which cards appear. A Grouping "
             "brings the dendrogram and the family panels; an Encoding brings "
             "the image grid and the classifier confidence; a Scores brings "
             "the activity profile and its threshold.", 18, 42, 10, C["grey"], MONO),
        text("So the workbench is not a dashboard someone has to configure — "
             "it is the seven interchange types, each knowing how it wants to "
             "be looked at.", 18, 62, 10, C["grey"], MONO),
        text("That is the part that makes the tool feel like it understands "
             "the analysis rather than merely running it.", 18, 88, 10,
             C["blue"], MONO)]))

    return frame("analyse-E-workbench", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ output
LABELS = [("A  ·  film strip — the chain is the picture", 0),
          ("B  ·  inspector — one stage, room to tune", 1560),
          ("C  ·  sweep — choose a parameter by eye", 3120),
          ("D  ·  compare — two chains, aligned", 4680),
          ("E  ·  workbench — interrogate the output", 6240)]

screens = [film_strip(0), inspector(1560), sweep(3120), compare(4680),
           workbench(6240)]
labels = [text(l, x, -46, 16, C["grey"], MONO) for l, x in LABELS]

write_doc("UI_analyse_concepts_v1.pen", screens + labels)
