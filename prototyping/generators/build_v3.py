#!/usr/bin/env python3
"""
Assemble the v3 Analyse + Discovery concept document.

Twelve screens, left to right:
   1  chain                 build it, or import a template
   2  block 02 encoding     the pattern every block page follows
   3  block 04 detection
   4  block *  library family        (interrogation chain)
   5  block 01 slope analysis
   6  block 02 aggregate
   7  block 02 window matrix         (training chain)
   8  block 03 cluster
   9  block 04 encode
  10  block 05 model
  11  discovery, algorithms
  12  discovery, seeded search

Run:  python build_v3.py  ->  UI_analyse_discovery_v3.pen
"""

import math

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, chip,
                     button, tw, write_doc, _rng)
from pen_widgets import (dashes, vdashes, wander, sawtooth_drops, slope_bars,
                         stat, _poly)
import build_blocks as B


# ---------------------------------------------------------------- discovery
def hist_overlay(x, y, w, h, seed=9, nbins=34, thresh=0.38, excl=0.10):
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


def section_slider(x, y, w, h, seed=4711, sel=(0.44, 0.10)):
    px, pw = x + w * sel[0], w * sel[1]
    out = [rect(x, y, w, h, C["dark"], radius=5),
           rect(px, y, pw, h, C["ov_span"], stroke=C["blue"]),
           wander(x, y, w, h, seed, pts=400, amp=0.34, drift=0.16, wobble=29)]
    for hx in (px - 5, px + pw - 5):
        out += [rect(hx, y + h / 2 - 14, 10, 28, C["blue"], radius=3),
                rect(hx + 4, y + h / 2 - 8, 1, 16, C["white"])]
    return out


def arrow_nav(x, y, cur, total, w=150):
    return [rect(x, y, 26, 26, C["white"], radius=6, stroke=C["border"]),
            text("‹", x + 10, y + 5, 13, C["grey"]),
            text("%d / %d" % (cur, total), x + 36, y + 8, 11, C["black"], MONO),
            rect(x + w - 26, y, 26, 26, C["white"], radius=6, stroke=C["border"]),
            text("›", x + w - 16, y + 5, 13, C["grey"])]


X, W = B.X, B.W


def discovery_algorithms():
    k = [B.nav(2), B.head("Discovery", "Algorithms  ·  apply saved detectors at "
                          "scale", "M2_aug_concat_fs1.mat · CH4_A2")]
    tk = [text("section", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("112 – 286 h  ·  174 h of 720 h", 74, 12, True)
    tk += p
    tk.append(text("drag the handles below to change it", 330, 20, 10,
                   C["muted"], MONO))
    bx = 1376 - 24
    for lab, pri in [("Run 3 algorithms  →", True),
                     ("Preview on a sample", False)]:
        p, bw = button(lab, 0, 11, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        tk += p
        bx -= 12
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    sk = [text("CHANNEL", 16, 12, 9, C["muted"], MONO),
          text("CH4_A2  ·  0 – 720 h", 82, 12, 9, C["grey"], MONO),
          rtext("preview ran on 4 h · extrapolated 38 min · routes to cluster",
                W - 16, 12, 9, C["amber"], MONO)]
    sk += section_slider(16, 32, W - 32, 62, sel=(0.155, 0.24))
    k.append(B.card("section", X, 108, W, 110, sk))

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
    k.append(B.card("coverage", X, 230, W, 176, rk))

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
    bk += [text("d-0412  ·  192.4 h  ·  score 0.88", 18, 74, 10, C["black"], MONO),
           text("no prior adjudication", 18, 92, 9, C["muted"], MONO),
           text("matched to nothing at IoU ≥ 0.5", 18, 110, 9, C["muted"], MONO)]
    k.append(B.card("browse", X, 418, W, 184, bk))

    pk = [text("How well did each algorithm do?", 18, 14, 12),
          rtext("refresh after reviewing", W - 18, 17, 10, C["blue"], MONO)]
    cols = ["algorithm", "found", "already judged", "reviewed", "interesting",
            "precision", "recall", "surrogate"]
    cxs = [18, 250, 340, 470, 570, 700, 810, 980]
    pk.append(rect(18, 40, W - 36, 1, C["border"]))
    for c, cx in zip(cols, cxs):
        pk.append(text(c, cx, 46, 9, C["muted"], MONO))
    rows = [("drop_motifs9", "50", "8", "50", "12", "24 %", "0.71 over 14 h",
             "6", C["blue"]),
            ("sharkfin_v2", "23", "11", "0", "—", "not yet scored", "—",
             "2", C["purple"]),
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
                   "finds 5 events and gets all 5 right would score 100 % and be "
                   "worse. Recall appears only where the section overlaps "
                   "human-reviewed coverage.", 18, 176, 10, C["muted"], MONO))
    k.append(B.card("scoreboard", X, 614, W, 204, pk))

    ak = [text("50 detections from drop_motifs9", 20, 20, 12, C["black"], MONO)]
    bx = W - 20
    for lab, pri in [("Send all 50 to Review  →", True),
                     ("Analyse events  →", False),
                     ("Discard run  (no adjudications)", False)]:
        p, bw = button(lab, 0, 12, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        ak += p
        bx -= 10
    k.append(B.card("actions", X, 830, W, 54, ak))
    return frame("discovery-1-algorithms", 0, 0, 1440, 900, C["page"], children=k)


def discovery_seed():
    k = [B.nav(2), B.head("Discovery", "Seed  ·  find more of a shape you already "
                          "have", "seed F-03 · CH4_A2")]
    tk = [text("section", 24, 20, 9, C["muted"], MONO)]
    p, cw = chip("whole channel  ·  720 h", 74, 12, True)
    tk += p
    tk.append(text("MASS is O(n log n), so a whole channel is sub-second",
                   270, 20, 10, C["gink"], MONO))
    p, bw = button("Search", 1376 - 24 - 110, 11, primary=True, h=30)
    tk += p
    k.append(frame("toolbar", 64, 44, 1376, 56, C["page"], children=tk))

    sk = [text("CHANNEL", 16, 12, 9, C["muted"], MONO),
          text("CH4_A2  ·  0 – 720 h  ·  searching all of it", 82, 12, 9,
               C["grey"], MONO)]
    sk += section_slider(16, 32, W - 32, 58, sel=(0.02, 0.96))
    k.append(B.card("section", X, 108, W, 106, sk))

    qk = [text("Seed", 18, 14, 12),
          rtext("from the Library", 384, 17, 9, C["muted"], MONO),
          rect(18, 40, 366, 104, C["dark"], radius=5)]
    qk.append(sawtooth_drops(20, 44, 362, 96, 77, n=1, col=C["orange"], sw=1.6))
    qk += [text("F-03  ·  sharkfin  ·  medoid member", 18, 156, 10,
                C["black"], MONO),
           text("native length 21.6 s — not quantised to a scale bank, so the "
                "exemplar's own extent is what is searched for", 18, 176, 9,
                C["muted"], MONO),
           rect(18, 208, 366, 1, C["border"]),
           text("algorithm", 18, 220, 9, C["muted"], MONO),
           rect(90, 216, 294, 24, C["page"], radius=6, stroke=C["border"]),
           text("MASS distance profile", 100, 222, 10, C["black"], MONO),
           text("exclusion", 18, 254, 9, C["muted"], MONO),
           rect(90, 250, 294, 24, C["page"], radius=6, stroke=C["border"]),
           text("m/2  =  10.8 s", 100, 256, 10, C["black"], MONO),
           text("trivial matches must be excluded explicitly, or the result "
                "looks spectacular and means nothing", 18, 286, 9, C["red"], MONO)]
    k.append(B.card("seed", X, 226, 402, 316, qk))

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
                   "a round number.", 24, 292, 10, C["muted"], MONO))
    k.append(B.card("threshold", 514, 226, 898, 316, hk))

    rk = [text("63 matches", 18, 14, 12),
          text("sorted by distance", 116, 17, 10, C["grey"], MONO),
          rtext("browse only — judgement happens in Review", W - 18, 17, 9,
                C["muted"], MONO)]
    for i in range(7):
        cx = 18 + i * 188
        d = 0.19 + i * 0.031
        prior = i in (2, 5)
        rk += [rect(cx, 40, 174, 124, C["page"], radius=8, stroke=C["border"]),
               text("m-%03d" % (101 + i), cx + 10, 48, 9, C["black"], MONO),
               rtext("d %.2f" % d, cx + 164, 48, 9, C["grey"], MONO),
               rect(cx + 10, 66, 154, 56, C["dark"], radius=4)]
        rk.append(sawtooth_drops(cx + 11, 68, 152, 52, 300 + i * 41, n=1,
                                 col=C["orange"] if i < 4 else C["trace"], sw=1.2))
        if prior:
            rk += [ellipse(cx + 10, 132, 7, 7, C["green"]),
                   text("already interesting", cx + 22, 130, 9, C["grey"], MONO)]
        else:
            rk.append(text("new", cx + 10, 130, 9, C["muted"], MONO))
        rk.append(text("%.1f h" % (112 + i * 63.4), cx + 10, 146, 9,
                       C["muted"], MONO))
    k.append(B.card("matches", X, 558, W, 178, rk))

    ak = [text("63 matches  ·  19 already judged  ·  44 new", 20, 20, 12,
               C["black"], MONO),
          text("rediscoveries keep a pointer to the prior adjudication, so the "
               "same span is never put to you twice", 20, 40, 9, C["muted"], MONO)]
    bx = W - 20
    for lab, pri in [("Send 44 new to Review  →", True),
                     ("Analyse events  →", False), ("Discard run", False)]:
        p, bw = button(lab, 0, 12, primary=pri, h=30)
        bx -= bw
        for n in p:
            n["x"] += bx
        ak += p
        bx -= 10
    k.append(B.card("actions", X, 752, W, 62, ak))
    k.append(B.card("note", X, 826, W, 54, [
        text("Sent candidates arrive at the top of Review's queue tagged with "
             "this run. Come back and the precision figure will have filled "
             "itself in.", 16, 18, 10, C["gink"], MONO)],
        fill=C["gtint"], stroke=C["gtint"]))
    return frame("discovery-2-seed", 0, 0, 1440, 900, C["page"], children=k)


# ---------------------------------------------------------------- assemble
SCREENS = [
    ("1  ·  the chain — build it, or import a template", B.p_chain),
    ("2  ·  block 02  encoding", B.p_encoding),
    ("3  ·  block 04  detection", B.p_detection),
    ("4  ·  block ●  the family being analysed", B.p_family),
    ("5  ·  block 01  slope analysis", B.p_slope),
    ("6  ·  block 02  aggregate", B.p_aggregate),
    ("7  ·  block 02  window matrix", B.p_matrix),
    ("8  ·  block 03  cluster", B.p_cluster),
    ("9  ·  block 04  encode", B.p_encode),
    ("10  ·  block 05  model", B.p_model),
    ("11  ·  inserting a stage — the type contract", B.p_insert),
    ("12  ·  Discovery — algorithms at scale", discovery_algorithms),
    ("13  ·  Discovery — two algorithms compared", B.p_compare),
    ("13b  ·  the same window, stage by stage", B.p_compare_window),
    ("14  ·  Discovery — seeded search", discovery_seed),
]

if __name__ == "__main__":
    screens, labels = [], []
    for i, (lab, fn) in enumerate(SCREENS):
        sc = fn()
        sc["x"] = i * 1560
        screens.append(sc)
        labels.append(text(lab, i * 1560, -46, 16, C["grey"], MONO))

    write_doc("UI_analyse_discovery_v3.pen", screens + labels)
