#!/usr/bin/env python3
"""
The Library workspace — the walk-through.

  1  recurrence   The entry point. Families x channels, grouped by recording,
                  with arrows to page through more datasets than fit. The
                  family GROUPING is chosen here — event type, filters, and
                  the basis (shape / scale / amplitude / polarity / tag, or a
                  clustering exported from Analyse) — and the rows and the
                  recurrence counts recompute from it. Checkboxes per channel
                  and per dataset build a selection; Browse carries it on.

  2  atlas        The contact sheet, scoped to that selection. Same grouping
                  controls; changing one regroups the whole catalogue and
                  clears the channel scope, which the page says out loud.

  3  family       Click into a family and every individual member is there:
                  editable, taggable, noteable, stageable for Review. An
                  unadjudicated family says so at the top.

  4  regroup      Optional view kept from the earlier concepts: the same
                  entries under two bases at once, with the families that move
                  between them called out. PRD story 35.

Run:  python build_library.py  ->  UI_library_v2.pen
"""

import math

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, chip,
                     button, tw, write_doc, _rng, motif_trace)
from pen_widgets import wander, sawtooth_drops, ensemble, _poly
from build_blocks import nav, head, card

X = 88
TRACE_COLS = ["#34C759", "#0A84FF", "#FF9F0A", "#BF5AF2", "#40C8C0", "#FF6B6B"]
RAMP = ["#F2F2F4", "#DCEAF9", "#B6D6F4", "#7FB8EE", "#3D93E4", "#007AFF"]
GROUPINGS = ["Shape", "Scale", "Amplitude", "Polarity", "Tag", "Custom"]

FAMILIES = [
    ("F-01  sharkfin", 84, "1.2 s", "0.22 mV", 0, "saw"),
    ("F-02  fast burst", 42, "0.8 s", "0.45 mV", 1, "osc8"),
    ("F-03  biphasic", 112, "1.5 s", "0.18 mV", 2, "osc4"),
    ("F-04  spike train", 19, "4.2 s", "0.11 mV", 0, "noisy"),
    ("F-05  slow ripple", 31, "3.8 s", "0.65 mV", 1, "osc6"),
    ("F-06  plateau", 26, "4.6 s", "0.31 mV", 3, "step"),
    ("F-07  slow drift", 14, "38 s", "0.08 mV", 4, "drift"),
    ("F-08  long fall", 22, "44 s", "0.52 mV", 5, "saw"),
]


# ---------------------------------------------------------------- helpers
def shape(kind, x, y, w, h, col, seed=7):
    if kind == "saw":
        return [sawtooth_drops(x, y, w, h, seed, n=4, col=col, sw=1.5)]
    if kind == "osc8":
        return [motif_trace(x, y, w, h, seed, cycles=8.0, col=col, sw=1.4)]
    if kind == "osc6":
        return [motif_trace(x, y, w, h, seed, cycles=5.5, col=col, sw=1.4)]
    if kind == "osc4":
        return [motif_trace(x, y, w, h, seed, cycles=3.6, col=col, sw=1.5)]
    if kind == "noisy":
        return [wander(x, y, w, h, seed, pts=140, amp=0.30, drift=0.42,
                       col=col, sw=1.3, wobble=4)]
    if kind == "drift":
        return [wander(x, y, w, h, seed, pts=120, amp=0.34, drift=0.10,
                       col=col, sw=1.3, wobble=21)]
    if kind == "step":
        r = _rng(seed)
        P = []
        for i in range(120):
            t = i / 119
            base = 0.30 if t < 0.28 else (0.74 if t < 0.72 else 0.34)
            P.append((t * w, h * (1 - base) + (r() - 0.5) * h * 0.08))
        return [_poly(x, y, w, h, P, col, 1.4)]
    return []


def cbox(x, y, on, size=13):
    out = [rect(x, y, size, size, C["blue"] if on else C["white"], radius=4,
                stroke=None if on else C["border"])]
    if on:
        out.append(text("✓", x + size * 0.22, y + size * 0.04,
                        size * 0.70, C["white"], SANS))
    return out


def group_control(x, y, active, items=GROUPINGS, size=10, h=28):
    widths = [tw(s, size, MONO) + 26 for s in items]
    total = sum(widths) + 8
    out = [rect(x, y, total, h, C["page"], radius=7, stroke=C["border"])]
    cx = x + 4
    for s, w in zip(items, widths):
        on = s == active
        if on:
            out.append(rect(cx, y + 4, w, h - 8, C["white"], radius=5,
                            stroke=C["border"]))
        out.append(text(s, cx + 13, y + h / 2 - size / 2 - 1, size,
                        C["black"] if on else C["grey"], MONO))
        cx += w
    return out, total


def fam_card(x, y, w, h, fam, selected=False):
    name, n, dur, amp, ci, kind = fam
    col = TRACE_COLS[ci]
    kids = [text(name, 14, 12, 12, C["black"], SANS, True),
            rtext("%d members" % n, w - 14, 14, 10,
                  C["blue"] if selected else C["grey"], MONO),
            rect(14, 36, w - 28, h - 76, C["darker"], radius=5)]
    kids += shape(kind, 16, 38, w - 32, h - 80, col, seed=40 + n)
    kids += [text("Dur: " + dur, 14, h - 30, 10,
                  C["blue"] if selected else C["muted"], MONO),
             rtext("Amp: " + amp, w - 14, h - 30, 10,
                   C["blue"] if selected else C["muted"], MONO)]
    return frame("family/" + name, x, y, w, h, C["white"], radius=10,
                 stroke=C["blue"] if selected else C["border"], children=kids)


def grouping_bar(y, custom=False, right=None):
    k = [text("events", 24, 9, 9, C["muted"], MONO)]
    cx = 76
    for lab, on in [("single motifs", True), ("sequences", False)]:
        p, cw = chip(lab, cx, 2, on)
        k += p
        cx += cw + 6
    cx += 14
    k.append(text("filter", cx, 9, 9, C["muted"], MONO))
    cx += 50
    for lab, on in [("adjudicated only", False), ("≥ 10 members", True),
                    ("exclude artifact-binned", True)]:
        p, cw = chip(lab, cx, 2, on)
        k += p
        cx += cw + 6
    if custom:
        cx += 14
        k += [text("source", cx, 9, 9, C["muted"], MONO),
              rect(cx + 48, 2, 268, 24, C["gtint"], radius=6),
              text("cluster_k6  ·  run 131  ·  Ward 10.1", cx + 58, 8, 10,
                   C["gink"], MONO)]
    if right:
        k.append(rtext(right, 1352, 9, 10, C["grey"], MONO))
    return frame("grouping-bar", 64, y, 1376, 32, C["page"], children=k)


# ================================================================ 1
def p_recurrence():
    k = [nav(4), head("Library", "Recurrence  ·  where every family occurs",
                      "1,402 occurrences")]
    tk = [text("group families by", 24, 21, 9, C["muted"], MONO)]
    p, gw = group_control(140, 14, "Custom")
    tk += p
    tk += [text("rows and counts recompute from this", 160 + gw, 21, 10,
                C["muted"], MONO),
           rtext("12 families at this grouping", 1352, 21, 10, C["black"], MONO)]
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))
    k.append(grouping_bar(104, custom=True))

    MW = 1000
    RECS = [("M2_aug fs1", 6), ("M2_aug fs2", 6), ("M3_jul", 4)]
    rows = ["C1  sharkfin-like", "C2  fast burst", "C3  biphasic",
            "C4  spike train", "C5  slow ripple", "C6  plateau",
            "C7  drift", "C8  long fall", "C9  mixed", "C10  rare",
            "C11  rare", "C12  singleton"]
    sel_ch = {(0, 2), (0, 3), (1, 1)}
    mk = [text("MEMBERS PER CHANNEL", 18, 12, 9, C["muted"], MONO),
          text("darker is more  ·  red is a cross-channel artifact", 180, 12,
               9, C["muted"], MONO),
          rect(MW - 214, 6, 24, 20, C["white"], radius=5, stroke=C["border"]),
          text("‹", MW - 205, 9, 12, C["grey"]),
          text("datasets 1–3 of 5", MW - 180, 11, 9, C["black"], MONO),
          rect(MW - 44, 6, 24, 20, C["white"], radius=5, stroke=C["border"]),
          text("›", MW - 35, 9, 12, C["grey"])]
    gx, gy, cw, chh = 118, 76, 46, 32
    cx = gx
    for ri, (rname, nch) in enumerate(RECS):
        wid = nch * (cw + 2) - 2
        allsel = any(c[0] == ri for c in sel_ch)
        mk += cbox(cx, 36, allsel)
        mk += [text(rname, cx + 20, 38, 10, C["black"], MONO),
               rect(cx, 58, wid, 2, C["blue"] if allsel else C["border"])]
        for c in range(nch):
            mk += cbox(cx + c * (cw + 2) + cw / 2 - 6, 62, (ri, c) in sel_ch,
                       size=12)
        cx += wid + 18
    for j, fid in enumerate(rows):
        yy = gy + 24 + j * (chh + 3)
        mk.append(text(fid, 18, yy + chh / 2 - 6, 10, C["black"], MONO))
        cx = gx
        for ri, (rname, nch) in enumerate(RECS):
            for c in range(nch):
                v = abs(math.sin((j + 1) / 2.3 + c / 1.7 + ri) *
                        math.cos(c / 3.1 + j / 4.5))
                if j > 8 and ri == 2:
                    v *= 0.15
                idx = min(5, int(v * 6))
                art = (j == 2 and ri == 0 and c in (2, 3))
                sel = (ri, c) in sel_ch
                mk.append(rect(cx, yy, cw, chh,
                               "#F6DADA" if art else RAMP[idx], radius=3,
                               stroke=C["red"] if art else
                               (C["blue"] if sel else None)))
                if art:
                    mk.append(text("!", cx + cw / 2 - 2, yy + 10, 10,
                                   C["red"], MONO))
                elif idx >= 3:
                    mk.append(text(str(3 + idx * 4), cx + cw / 2 - 6, yy + 10,
                                   9, C["white"] if idx >= 4 else C["black"],
                                   MONO))
                cx += cw + 2
            cx += 18
    mk.append(text("CH1 → CH16 within each recording", gx, gy + 24 +
                   len(rows) * (chh + 3) + 4, 9, C["muted"], MONO))
    k.append(card("matrix", X, 146, MW, 620, mk))

    RW = 300
    rk = [text("This grouping", 18, 14, 12),
          text("custom  ·  cluster_k6", 18, 38, 10, C["black"], MONO),
          text("exported from Analyse run 131 — window", 18, 54, 9,
               C["muted"], MONO),
          text("matrix, Ward linkage, cut at 10.1", 18, 68, 9, C["muted"], MONO),
          rect(18, 88, RW - 36, 1, C["border"])]
    for i, (lab, val, col) in enumerate([("families", "12", None),
                                         ("members", "1,402", None),
                                         ("artifact-binned", "excluded",
                                          C["red"]),
                                         ("singletons", "1", C["muted"])]):
        rk += [text(lab, 18, 100 + i * 20, 10, C["grey"], MONO),
               rtext(val, RW - 18, 100 + i * 20, 10, col or C["black"], MONO)]
    rk.append(text("scope: CH4_A2 only  \u00b7  214 members outside it",
                   18, 166, 9, C["amber"], MONO))
    rk += [rect(18, 188, RW - 36, 1, C["border"]),
           text("Selection", 18, 200, 12),
           text("2 recordings  ·  3 channels", 18, 226, 10, C["black"], MONO)]
    for i, (lab, n) in enumerate([("M2_aug fs1", "CH3, CH4"),
                                  ("M2_aug fs2", "CH2")]):
        rk += [ellipse(18, 252 + i * 20, 7, 7, C["blue"]),
               text(lab, 34, 250 + i * 20, 10, C["grey"], MONO),
               rtext(n, RW - 18, 250 + i * 20, 10, C["black"], MONO)]
    rk += [text("412 members inside this selection", 18, 296, 9,
                C["muted"], MONO),
           rect(18, 320, RW - 36, 1, C["border"]),
           text("CH3 and CH4 of M2 fs1 are flagged as", 18, 332, 9,
                C["red"], MONO),
           text("a shared-ground pair on C3 — browsing", 18, 346, 9,
                C["red"], MONO),
           text("both double-counts that family.", 18, 360, 9, C["red"], MONO)]
    by = 392
    for lab, pri in [("Browse 3 channels  →", True),
                     ("Select all channels", False),
                     ("Clear selection", False)]:
        p, bw = button(lab, 18, by, primary=pri, h=30)
        rk += p
        by += 34
    rk += [rect(18, 502, RW - 36, 1, C["border"]),
           text("A row dark in one recording and empty", 18, 514, 9,
                C["grey"], MONO),
           text("in the others is a property of that", 18, 528, 9,
                C["grey"], MONO),
           text("recording, not of the organism — which", 18, 542, 9,
                C["grey"], MONO),
           text("is the distinction the catalogue", 18, 556, 9, C["grey"], MONO),
           text("exists to make.", 18, 570, 9, C["grey"], MONO)]
    k.append(card("panel", 1112, 146, RW, 620, rk))

    k.append(card("note", X, 782, 1324, 98, [
        text("Grouping first, then scope", 18, 16, 12),
        text("The basis at the top decides what a row IS. Change it and the "
             "rows, the counts and the artifact exclusions all recompute — a "
             "family is not a fact about the data, it is a fact about",
             18, 42, 10, C["grey"], MONO),
        text("the grouping you chose, which is why the basis travels with "
             "every export. A clustering exported from Analyse arrives as just "
             "another basis, on equal footing with shape or tag.",
             18, 60, 10, C["grey"], MONO),
        text("Channel and dataset checkboxes only scope what you browse next. "
             "They never change the grouping.", 18, 78, 10, C["blue"], MONO)]))
    return frame("library-1-recurrence", 0, 0, 1440, 900, C["page"], children=k)


# ================================================================ 2
def p_atlas():
    k = [nav(4), head("Library", "Atlas  ·  browsing the selection",
                      "412 members  ·  3 channels  ·  2 recordings")]
    tk = [text("group families by", 24, 21, 9, C["muted"], MONO)]
    p, gw = group_control(140, 14, "Custom")
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))
    k.append(grouping_bar(104, custom=True,
                          right="8 families in this selection"))

    sk = [text("scope", 18, 12, 9, C["muted"], MONO)]
    cx = 62
    for lab in ["M2_aug fs1 · CH3", "M2_aug fs1 · CH4",
                "M2_aug fs2 · CH2"]:
        w = tw(lab, 10, MONO) + 34
        sk += [rect(cx, 6, w, 24, C["tint"], radius=6, stroke=C["blue"]),
               text(lab, cx + 10, 12, 10, C["blue"], MONO),
               text("×", cx + w - 16, 11, 11, C["blue"])]
        cx += w + 8
    sk += [text("‹ back to recurrence", cx + 10, 13, 10, C["blue"], MONO),
           rtext("changing the grouping regroups the whole catalogue and "
                 "clears this scope", 1306, 13, 9, C["amber"], MONO)]
    k.append(card("scope", X, 146, 1324, 42, sk))

    SECTIONS = [("C1–C3   SHORT SCALE   ~1 s", FAMILIES[0:3]),
                ("C4–C6   MEDIUM SCALE   ~4 s", FAMILIES[3:6]),
                ("C7–C8   LONG SCALE   ~40 s", FAMILIES[6:8])]
    y = 204
    for title, fams in SECTIONS:
        k.append(text(title, X, y, 10, C["muted"], MONO))
        y += 18
        for i, fam in enumerate(fams):
            k.append(fam_card(X + i * 329, y, 313, 146, fam,
                              selected=fam[0].startswith("F-03")))
        y += 146 + 24

    RW = 340
    rk = [rect(0, 0, 1, 856, C["border"]),
          text("F-03  biphasic", 24, 20, 14, C["black"], SANS, True),
          text("112 members  ·  44 in this scope", 24, 44, 10, C["grey"], MONO),
          text("MEDOID", 24, 70, 9, C["muted"], MONO),
          rect(24, 86, RW - 48, 92, C["darker"], radius=6)]
    rk += shape("osc4", 28, 90, RW - 56, 84, TRACE_COLS[2], seed=143)
    rk += [text("ALL MEMBERS, z-normalised", 24, 190, 9, C["muted"], MONO),
           rect(24, 206, RW - 48, 74, C["darker"], radius=6)]
    rk += ensemble(28, 210, RW - 56, 66, n=10, seed=61, onset=0.42, sw=1)
    rk.append(text("AMPLITUDE DISTRIBUTION", 24, 292, 9, C["muted"], MONO))
    for i, v in enumerate([3, 8, 22, 31, 18, 9, 4, 2]):
        rk.append(rect(24 + i * 34, 364 - v * 1.6, 28, v * 1.6,
                       C["blue"] if 2 <= i <= 4 else "#CBE3FA", radius=2))
    rk.append(rect(24, 374, RW - 48, 1, C["border"]))
    for i, (lab, val) in enumerate([("variance", "σ² = 0.04"),
                                    ("avg SNR", "18.4 dB"),
                                    ("mean member distance", "0.24"),
                                    ("adjudicated", "44 of 112")]):
        rk += [text(lab, 24, 386 + i * 20, 10, C["grey"], MONO),
               rtext(val, RW - 24, 386 + i * 20, 10,
                     C["amber"] if i == 3 else C["black"], MONO)]
    rk += [rect(24, 472, RW - 48, 1, C["border"]),
           text("CROSS-CHANNEL", 24, 484, 9, C["muted"], MONO)]
    for i, (lab, n, col) in enumerate([("artifact", "2", C["red"]),
                                       ("propagation", "4", C["amber"]),
                                       ("independent", "1", C["green"])]):
        rk += [ellipse(24, 506 + i * 20, 8, 8, col),
               text(lab, 40, 504 + i * 20, 10, C["grey"], MONO),
               rtext(n, RW - 24, 504 + i * 20, 10, C["black"], MONO)]
    rk += [rect(24, 574, RW - 48, 1, C["border"]),
           text("EDGES", 24, 586, 9, C["muted"], MONO),
           text("scale-invariant  ·  threshold 0.42", 24, 604, 9,
                C["grey"], MONO),
           text("recipe a7f3…9c", 24, 620, 9, C["muted"], MONO)]
    by = 648
    for lab, pri in [("Open all 112 members  →", True),
                     ("Stage 68 for Review", False),
                     ("Analyse events", False),
                     ("Search at other durations", False),
                     ("Export entry", False)]:
        p, bw = button(lab, 24, by, primary=pri, h=28)
        rk += p
        by += 32
    k.append(frame("detail-rail", 1100, 44, RW, 856, C["white"], children=rk))
    return frame("library-2-atlas", 0, 0, 1440, 900, C["page"], children=k)


# ================================================================ 3
def p_family():
    k = [nav(4), head("Library", "F-03 biphasic  ·  every member",
                      "112 members  ·  44 adjudicated")]
    tk = [text("‹ back to the atlas", 24, 21, 10, C["blue"], MONO),
          text("F-03  biphasic", 176, 18, 13, C["black"], SANS, True),
          text("sort", 320, 21, 9, C["muted"], MONO)]
    cx = 354
    for lab, on in [("distance to medoid", True), ("time", False),
                    ("amplitude", False), ("unadjudicated first", False)]:
        p, cw = chip(lab, cx, 14, on)
        tk += p
        cx += cw + 6
    tk.append(rtext("112 members  ·  16 shown", 1352, 21, 10, C["grey"], MONO))
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    bk = [ellipse(18, 15, 10, 10, C["amber"]),
          text("68 of 112 members have never been adjudicated", 38, 12, 12,
               C["black"], SANS, True),
          text("a family whose members are unjudged is a proposal, not a "
               "finding", 396, 15, 10, "#9A6206", MONO)]
    p, bw = button("Stage all 68 for Review  →", 1324 - 18 - 212, 8,
                   primary=True, h=28)
    bk += p
    k.append(card("banner", X, 108, 1324, 44, bk, fill="#FDF0D5",
                  stroke=C["amber"]))

    CW2 = 239
    verdicts = [None, "interesting", None, "seed", None, None, "artifact",
                None, "interesting", None, None, "not", None, None, None, None]
    dots = {"interesting": C["green"], "seed": C["blue"], "artifact": C["red"],
            "not": C["muted"]}
    for i in range(16):
        col, row = i % 4, i // 4
        cx, cy = X + col * (CW2 + 14), 164 + row * 160
        sel = i == 5
        v = verdicts[i]
        kids = [text("m-%04d" % (1841 + i), 12, 10, 10, C["black"], MONO),
                rtext("d %.2f" % (0.08 + i * 0.021), CW2 - 34, 11, 9,
                      C["grey"], MONO)]
        kids += cbox(CW2 - 28, 10, sel, size=12)
        kids.append(rect(12, 34, CW2 - 24, 66, C["darker"], radius=4))
        kids += shape("osc4", 14, 36, CW2 - 28, 62, TRACE_COLS[2],
                      seed=100 + i * 13)
        kids.append(text("CH%d  ·  %.1f h" % (3 + i % 3, 112 + i * 9.4),
                         12, 108, 9, C["muted"], MONO))
        if v:
            kids += [ellipse(12, 126, 7, 7, dots[v]),
                     text(v, 26, 124, 9, C["grey"], MONO)]
        else:
            kids.append(text("unadjudicated", 12, 124, 9, C["amber"], MONO))
        k.append(frame("member/%d" % i, cx, cy, CW2, 146,
                       C["tint"] if sel else C["white"], radius=9,
                       stroke=C["blue"] if sel else C["border"], children=kids))

    ak = [text("3 selected", 20, 18, 12, C["black"], SANS, True)]
    bx = 1324 - 20
    for lab, pri in [("Stage selected for Review  →", True),
                     ("Add tag", False), ("Assign class", False),
                     ("Remove from family", False)]:
        p, bw = button(lab, 0, 12, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        ak += p
        bx -= 10
    k.append(card("batch", X, 812, 1324, 54, ak))

    RW = 300
    rk = [text("m-1846", 18, 14, 13, C["black"], SANS, True),
          rtext("d 0.19", RW - 18, 18, 10, C["grey"], MONO),
          rect(18, 38, RW - 36, 82, C["darker"], radius=5)]
    rk += shape("osc4", 22, 42, RW - 44, 74, TRACE_COLS[2], seed=165)
    rk += [text("in context  \u00b7  \u00b1 30 s", 18, 126, 9, C["muted"], MONO),
           rect(18, 142, RW - 36, 50, C["darker"], radius=5),
           rect(18 + (RW - 36) * 0.42, 142, (RW - 36) * 0.14, 50, "#12365E",
                stroke=C["blue"])]
    rk.append(wander(18, 142, RW - 36, 50, 771, pts=140, amp=0.30, drift=0.22,
                     wobble=9, sw=1.2))
    rk.append(rect(18, 202, RW - 36, 1, C["border"]))
    for i, (lab, val) in enumerate([("recording", "M2_aug fs1"),
                                    ("channel", "CH4"),
                                    ("onset", "148.6021 h"),
                                    ("duration", "1.62 s"),
                                    ("amplitude", "0.21 mV"),
                                    ("found by", "mp_seeded_F03")]):
        rk += [text(lab, 18, 212 + i * 18, 10, C["grey"], MONO),
               rtext(val, RW - 18, 212 + i * 18, 10, C["black"], MONO)]
    rk += [rect(18, 312, RW - 36, 1, C["border"]),
           text("REVISIONS", 18, 322, 9, C["muted"], MONO),
           text("rev 1   d-0412", 18, 338, 10, C["black"], MONO),
           rtext("machine", RW - 18, 338, 9, C["muted"], MONO),
           text("run 128  \u00b7  what re-runs match", 18, 352, 9, C["muted"], MONO),
           text("rev 2   a-2077", 18, 372, 10, C["blue"], MONO),
           rtext("current", RW - 18, 372, 9, C["blue"], MONO),
           text("human edit, 14 Sept  \u00b7  what you see", 18, 386, 9,
                C["muted"], MONO),
           text("run 140 found rev 1 again and resolved", 18, 406, 9,
                C["gink"], MONO),
           text("to this motif rather than duplicating it.", 18, 420, 9,
                C["gink"], MONO),
           rect(18, 436, RW - 36, 1, C["border"]),
           text("VERDICT", 18, 446, 9, C["muted"], MONO),
           rect(18, 462, RW - 36, 24, "#FDF0D5", radius=6),
           text("unadjudicated", 28, 467, 10, "#9A6206", MONO),
           text("TAGS", 18, 496, 9, C["muted"], MONO)]
    tx = 18
    for tag, on in [("biphasic", True), ("clean", False), ("+ tag", False)]:
        w = tw(tag, 10, MONO) + 18
        rk += [rect(tx, 512, w, 22, C["tint"] if on else C["page"], radius=6,
                    stroke=C["blue"] if on else C["border"]),
               text(tag, tx + 9, 517, 10, C["blue"] if on else C["grey"], MONO)]
        tx += w + 6
    rk += [text("CLASS", 18, 546, 9, C["muted"], MONO),
           rect(18, 562, RW - 36, 24, C["page"], radius=6, stroke=C["border"]),
           text("unassigned", 28, 567, 10, C["grey"], MONO),
           text("NOTE", 18, 596, 9, C["muted"], MONO),
           rect(18, 612, RW - 36, 48, C["page"], radius=6, stroke=C["border"]),
           text("onset is ambiguous \u2014 the rise", 28, 620, 9, C["muted"], MONO),
           text("starts before the window does", 28, 634, 9, C["muted"], MONO)]
    by = 672
    for lab, pri in [("Stage for Review  \u2192", True),
                     ("Open in Explore to redraw", False),
                     ("Remove from family", False)]:
        p, bw = button(lab, 18, by, primary=pri, h=28)
        rk += p
        by += 32
    k.append(card("member-detail", 1112, 108, RW, 772, rk))
    return frame("library-3-family", 0, 0, 1440, 900, C["page"], children=k)


# ================================================================ 4
def p_regroup():
    k = [nav(4), head("Library", "Regroup  ·  does the basis change the answer?",
                      "optional view  ·  14 families")]
    tk = [text("left basis", 24, 21, 9, C["muted"], MONO)]
    p, gw = group_control(94, 14, "Shape")
    tk += p
    tk.append(text("right basis", 104 + gw + 20, 21, 9, C["muted"], MONO))
    p, gw2 = group_control(174 + gw + 20, 14, "Tag")
    tk += p
    tk.append(rtext("9 of 14 agree  ·  5 move", 1352, 21, 10, C["amber"], MONO))
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    k.append(card("why", X, 108, 1264, 48, [
        text("The same entries grouped two ways. One that lands in a matching "
             "group under both bases is robust; one that moves is a finding "
             "about the grouping, not about the fungus.", 18, 16, 11,
             C["grey"], MONO)]))

    LG = [("shape cluster 1", ["F-01", "F-08"], C["green"]),
          ("shape cluster 2", ["F-02", "F-05", "F-06"], C["blue"]),
          ("shape cluster 3", ["F-03", "F-11", "F-12"], C["purple"]),
          ("shape cluster 4", ["F-04", "F-07", "F-09"], C["amber"])]
    RG = [("tag: sharkfin", ["F-01", "F-08", "F-03"], C["green"]),
          ("tag: burst", ["F-02", "F-05"], C["blue"]),
          ("tag: biphasic", ["F-11", "F-12"], C["purple"]),
          ("tag: slow-drift", ["F-04", "F-07", "F-09", "F-06"], C["amber"])]
    LX, RX, GW = X, 1264 + X - 420, 420
    ys = {}
    for side, groups, gx in [("L", LG, LX), ("R", RG, RX)]:
        y = 176
        for gname, members, col in groups:
            h = 34 + len(members) * 30
            kids = [ellipse(12, 14, 9, 9, col),
                    text(gname, 28, 10, 11, C["black"], MONO),
                    rtext("%d" % len(members), GW - 12, 11, 10, C["muted"], MONO)]
            for i, m in enumerate(members):
                kids += [rect(12, 34 + i * 30, GW - 24, 26, C["page"], radius=6),
                         text(m, 24, 40 + i * 30, 10, C["black"], MONO)]
                kids += shape(["saw", "osc8", "osc4", "noisy", "drift",
                               "step"][i % 6], 90, 38 + i * 30, 120, 18, col,
                              seed=9 + i)
                ys[(side, m)] = y + 34 + i * 30 + 13
            k.append(frame("%s/%s" % (side, gname), gx, y, GW, h, C["white"],
                           radius=9, stroke=C["border"], children=kids))
            y += h + 12
    for m, lc in [("F-01", C["green"]), ("F-08", C["green"]),
                  ("F-02", C["blue"]), ("F-05", C["blue"]),
                  ("F-03", C["purple"]), ("F-11", C["purple"]),
                  ("F-12", C["purple"]), ("F-04", C["amber"]),
                  ("F-07", C["amber"]), ("F-09", C["amber"]),
                  ("F-06", C["blue"])]:
        if ("L", m) not in ys or ("R", m) not in ys:
            continue
        y0, y1 = ys[("L", m)], ys[("R", m)]
        x0, x1 = LX + GW, RX
        moved = m in ("F-03", "F-06")
        col = C["amber"] if moved else lc
        P = [(0, y0 - 172), ((x1 - x0) * 0.42, y0 - 172),
             ((x1 - x0) * 0.58, y1 - 172), (x1 - x0, y1 - 172)]
        k.append(_poly(x0, 172, x1 - x0, 520, P, col, 2.6 if moved else 1.4))

    mk = [text("The five that move", 18, 16, 12),
          text("each is a place where shape and tag disagree", 168, 19, 9,
               C["muted"], MONO)]
    for i, (fid, frm, to, why) in enumerate([
            ("F-03", "shape cluster 3", "tag: sharkfin",
             "tagged sharkfin by eye, clusters with the biphasics"),
            ("F-06", "shape cluster 2", "tag: slow-drift",
             "a plateau: shape says burst-like, the tag says drift"),
            ("F-09", "shape cluster 4", "tag: slow-drift", "agrees on drift"),
            ("F-11", "shape cluster 3", "tag: biphasic", "agrees"),
            ("F-12", "shape cluster 3", "tag: biphasic", "agrees")]):
        yy = 46 + i * 26
        mk += [rect(18, yy - 6, 1228, 1, C["border"]),
               text(fid, 18, yy, 10, C["black"], MONO),
               text(frm, 90, yy, 10, C["grey"], MONO),
               text("→", 260, yy - 1, 11, C["muted"]),
               text(to, 286, yy, 10, C["grey"], MONO),
               text(why, 450, yy, 10, C["amber"] if i < 2 else C["muted"], MONO)]
    k.append(card("movers", X, 700, 1264, 180, mk))
    return frame("library-4-regroup", 0, 0, 1440, 900, C["page"], children=k)


SCREENS = [("1  ·  recurrence — group, then scope", p_recurrence),
           ("2  ·  atlas — browse the selection", p_atlas),
           ("3  ·  family — every member, editable", p_family),
           ("4  ·  regroup — optional view", p_regroup)]

screens, labels = [], []
for i, (lab, fn) in enumerate(SCREENS):
    s = fn()
    s["x"] = i * 1560
    screens.append(s)
    labels.append(text(lab, i * 1560, -46, 16, C["grey"], MONO))

write_doc("UI_library_v2.pen", screens + labels)
