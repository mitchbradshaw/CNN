#!/usr/bin/env python3
"""
Explore workspace -- the walk-through, not three competing concepts.

The flow:

  0  corpus        A dataset is selected. Full-page channels x time density
                   map, bird's-eye. The right rail is a filter/options list,
                   not a legend: toggle verdicts, sources and morphology tags
                   to see where each kind of thing occurs across channels.
                   Structured so a future multivariate dataset drops in as
                   extra rows. Pick a channel to go deeper.

  1  signal        Mode one. Overview with coverage + detection-density
                   ribbons, a span selection with draggable edge handles,
                   the span below it, the selected motif below that. Motifs
                   in the span are clickable. A span can be saved with tags
                   and no analysis, or sent to Analyse.

  1b signal+drawer The same screen with the bottom drawer open -- filters,
                   search, the annotation table and bulk operations. This is
                   where the original draft's wall of controls lives without
                   being on screen all the time.

  2  cross-channel Mode two. Deliberately loose -- a placeholder that holds
                   the slot and the future multivariate direction.

  3  agreement     Mode three. One channel. Annotation track, detection
                   track, and their disagreement, with actions to pass
                   machine-only spans to Review.

Run:  python build_explore_flow.py  ->  UI_explore_flow_v1.pen
"""

import math

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, ctext,
                     trace, motif_trace, sidebar, header, chip, button, tw,
                     write_doc)

MODES = ["Signal", "Cross-channel", "Agreement"]
RAMP = ["#F2F2F4", "#DCEAF9", "#B6D6F4", "#7FB8EE", "#3D93E4", "#007AFF"]
CHANS = ["CH%d_%s" % (i + 1, ["A1", "A1", "A2", "A2", "B1", "B1", "B2", "B2",
                              "C1", "C1", "C2", "C2", "D1", "D1", "D2", "D2"][i])
         for i in range(16)]


# ---------------------------------------------------------------- components
def segmented(x, y, items, active, h=30, size=11):
    """Mode switcher."""
    widths = [tw(s, size, MONO) + 28 for s in items]
    total = sum(widths) + 8
    out = [rect(x, y, total, h, C["page"], radius=8, stroke=C["border"])]
    cx = x + 4
    for s, w in zip(items, widths):
        on = s == active
        if on:
            out.append(rect(cx, y + 4, w, h - 8, C["white"], radius=6,
                            stroke=C["border"]))
        out.append(text(s, cx + 14, y + h / 2 - size / 2 - 1, size,
                        C["black"] if on else C["grey"], MONO))
        cx += w
    return out, total


def breadcrumb(x, y, parts, size=11):
    out, cx = [], x
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        out.append(text(p, cx, y, size, C["black"] if last else C["grey"], MONO))
        cx += tw(p, size, MONO)
        if not last:
            out.append(text("  ›  ", cx, y, size, C["muted"], MONO))
            cx += tw("  ›  ", size, MONO)
    return out


def checkbox(x, y, label, on, size=11, dot=None):
    out = [rect(x, y, 14, 14, C["blue"] if on else C["white"], radius=4,
                stroke=None if on else C["border"])]
    if on:
        out.append(text("✓", x + 3, y + 1, 10, C["white"], SANS))
    lx = x + 22
    if dot:
        out.append(ellipse(lx, y + 4, 8, 8, dot))
        lx += 14
    out.append(text(label, lx, y + 1, size, C["black"] if on else C["grey"], MONO))
    return out


def ribbon(x, y, w, label, count=None, open_=False):
    """Collapsed disclosure strip."""
    out = [rect(x, y, w, 34, C["white"], radius=8, stroke=C["border"]),
           text("⌄" if open_ else "›", x + 14, y + 8, 13, C["grey"]),
           text(label, x + 34, y + 10, 11, C["black"], MONO)]
    if count:
        out.append(text(count, x + 34 + tw(label, 11, MONO) + 12, y + 11, 10,
                        C["muted"], MONO))
    return out


def span_handles(px, pw, ph, y=0):
    """Draggable left/right edge grips on a span selection."""
    out = [rect(px, y, pw, ph, C["ov_span"], stroke=C["blue"])]
    for hx in (px - 5, px + pw - 5):
        out.append(rect(hx, y + ph / 2 - 16, 10, 32, C["blue"], radius=3))
        out.append(rect(hx + 4, y + ph / 2 - 9, 1, 18, C["white"]))
    return out


# ================================================================ 0  CORPUS
def corpus(ox):
    k = [sidebar(0), header("Explore", "Corpus  ·  bird's-eye across every channel",
                            "M2_aug_concat_fs1.mat  ·  16 ch  ·  720 h")]

    tb = breadcrumb(24, 18, ["Corpus", "M2_aug_concat_fs1.mat"])
    parts, _ = chip("20 s bins", 340, 12, False)
    tb += parts
    parts, _ = chip("density: count", 440, 12, True)
    tb += parts
    tb.append(rtext("select a channel to open it", 1352, 19, 11, C["muted"], MONO))
    k.append(frame("toolbar", 64, 44, 1376, 52, C["page"], children=tb))

    # ---- the map
    MW, MH = 1000, 700
    mp = [text("COVERAGE MAP", 18, 16, 10, C["muted"], MONO),
          text("16 channels × 720 h", 138, 16, 10, C["grey"], MONO),
          rtext("annotated · interesting", MW - 18, 16, 10, C["muted"], MONO)]
    # ramp legend
    for i, col in enumerate(RAMP):
        mp.append(rect(MW - 210 + i * 16, 34, 14, 8, col, radius=2))
    mp += [text("low", MW - 236, 32, 9, C["muted"], MONO),
           text("high", MW - 112, 32, 9, C["muted"], MONO)]

    x0, y0, cw, chh = 84, 52, 14, 34
    nbins = 57
    for r, nm in enumerate(CHANS):
        y = y0 + r * (chh + 5)
        sel = nm == "CH4_A2"
        mp.append(text(nm, 18, y + chh / 2 - 6, 9,
                       C["blue"] if sel else C["muted"], MONO))
        if sel:
            mp.append(rect(x0 - 4, y - 3, nbins * (cw + 1) + 8, chh + 6,
                           C["tint"], radius=4, stroke=C["blue"]))
        for c in range(nbins):
            v = abs(math.sin((r + 1) / 2.7 + c / 5.1) *
                    math.cos(c / 11.2 + r / 4.5)) ** 1.3
            mp.append(rect(x0 + c * (cw + 1), y, cw, chh,
                           RAMP[min(5, int(v * 6))], radius=2))
    ay = y0 + 16 * (chh + 5) + 6
    mp += [text("0 h", x0, ay, 9, C["muted"], MONO),
           text("360 h", x0 + nbins * (cw + 1) / 2 - 16, ay, 9, C["muted"], MONO),
           rtext("720 h", MW - 18, ay, 9, C["muted"], MONO)]
    k.append(frame("coverage-map", 88, 108, MW, MH, C["white"], radius=10,
                   stroke=C["border"], children=mp))

    # ---- options rail (replaces the legend)
    RW = 300
    op = [text("Show", 20, 18, 12), rect(20, 42, RW - 40, 1, C["border"])]
    y = 54
    for lab, on in [("annotations", True), ("detections", True),
                    ("reviewed coverage", False), ("unreviewed only", False)]:
        op += checkbox(20, y, lab, on)
        y += 26
    op += [rect(20, y + 6, RW - 40, 1, C["border"]),
           text("Verdict", 20, y + 20, 12)]
    y += 44
    for lab, on, col in [("seed", True, C["blue"]),
                         ("interesting", True, C["green"]),
                         ("not_interesting", False, C["muted"]),
                         ("artifact", False, C["red"]),
                         ("unsure", False, C["amber"])]:
        op += checkbox(20, y, lab, on, dot=col)
        y += 26
    op += [rect(20, y + 6, RW - 40, 1, C["border"]),
           text("Morphology tag", 20, y + 20, 12)]
    y += 44
    for lab, on in [("sharkfin", True), ("spike-train", False),
                    ("slow-drift", False), ("burst", False),
                    ("plateau", False), ("biphasic", False)]:
        op += checkbox(20, y, lab, on)
        y += 26
    op += [rect(20, y + 6, RW - 40, 1, C["border"]),
           text("matching", 20, y + 20, 10, C["muted"], MONO),
           rtext("412 spans", RW - 20, y + 20, 11, C["black"], MONO),
           text("across 11 of 16 channels", 20, y + 40, 10, C["muted"], MONO),
           text("a tag that clusters on two channels is a lead;", 20, y + 66, 9,
                C["muted"], MONO),
           text("one spread evenly is probably not.", 20, y + 80, 9,
                C["muted"], MONO)]
    k.append(frame("options-rail", 1112, 108, RW, MH, C["white"], radius=10,
                   stroke=C["border"], children=op))

    # ---- selection bar
    parts, bw = button("Open CH4_A2  →", 1440 - 88 - 170, 12, primary=True, h=32)
    k.append(frame("selection-bar", 88, 826, 1324, 56, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("CH4_A2", 20, 20, 13, C["black"], SANS, True),
        text("708 annotations  ·  1284 detections  ·  184 disagree  ·  "
             "62 % reviewed", 110, 21, 11, C["grey"], MONO)] + parts))

    return frame("explore-0-corpus", ox, 0, 1440, 900, C["page"], children=k)


# ---------------------------------------------------------------- mode chrome
def mode_chrome(active, extra_right=None):
    k = [sidebar(0), header("Explore", "CH4_A2", extra_right)]
    tb = breadcrumb(24, 19, ["Corpus", "M2_aug_concat_fs1.mat", "CH4_A2"])
    parts, total = segmented(520, 11, MODES, active)
    tb += parts
    tb.append(rtext("‹ back to corpus", 1352, 19, 11, C["blue"], MONO))
    k.append(frame("toolbar", 64, 44, 1376, 52, C["page"], children=tb))
    return k


# ================================================================ 1  SIGNAL
def signal(ox, drawer=False):
    k = mode_chrome("Signal", "708 annotations  ·  1284 detections")
    X, W = 88, 1264

    # ---- tier 1: whole channel, span selection with drag handles
    ov = [text("CHANNEL", 18, 14, 10, C["muted"], MONO),
          text("0 – 720 h", 96, 14, 10, C["grey"], MONO),
          rtext("1 : 720", 1246, 14, 10, C["muted"], MONO),
          rtext("drag the handles to resize the span", 1180, 14, 10, C["muted"], MONO),
          frame("overview", 18, 34, 1228, 62, C["dark"], radius=5,
                children=span_handles(470, 88, 62) + [
                    trace(0, 0, 1228, 62, 4711, pts=420, amp=0.34, drift=0.16,
                          wobble=31)]),
          text("coverage", 18, 106, 9, C["muted"], MONO),
          text("detection density", 18, 124, 9, C["muted"], MONO)]
    for x0, wd, col in [(0, 240, C["green"]), (250, 110, C["amber"]),
                        (370, 300, C["green"]), (680, 56, C["red"]),
                        (744, 190, C["amber"]), (944, 240, C["border"])]:
        ov.append(rect(130 + x0 * 0.92, 104, wd * 0.92, 9, col, radius=2))
    for i in range(44):
        h = 2 + int(12 * abs(math.sin(i / 3.1) * math.cos(i / 7.3)))
        ov.append(rect(130 + i * 25, 122 + (14 - h), 21, h, C["blue"], radius=1))
    k.append(frame("tier-1-channel", X, 108, W, 154, C["white"], radius=10,
                   stroke=C["border"], children=ov))

    if not drawer:
        # ---- tier 2: the span, with clickable motif markers
        sp = [text("SPAN", 18, 14, 10, C["muted"], MONO),
              text("276.4 – 278.4 h   ·   2.0 h", 70, 14, 10, C["grey"], MONO),
              rtext("× 360", 1246, 14, 10, C["muted"], MONO),
              text("‹", 1090, 12, 13, C["grey"]),
              text("233 / 344", 1108, 15, 10, C["black"], MONO),
              text("›", 1176, 12, 13, C["grey"]),
              text("click a marker to open it below", 18, 218, 10, C["muted"], MONO)]
        markers = [(96, 54, "det", False), (250, 40, "ann", False),
                   (548, 128, "det", True), (742, 58, "ann", False),
                   (900, 46, "det", False), (1060, 70, "ann", False)]
        plot_kids = []
        for mx, mw, kind, sel in markers:
            col = C["blue"] if kind == "det" else C["green"]
            plot_kids.append(rect(mx, 22, mw, 132,
                                  C["ov_motif"] if sel else
                                  (C["ov_span"] if kind == "det" else C["ov_interest"]),
                                  stroke=C["orange"] if sel else None))
            plot_kids.append(rect(mx, 6, mw, 10, C["orange"] if sel else col, radius=2))
        plot_kids.append(trace(0, 0, 1228, 154, 9137, pts=320, amp=0.28,
                               drift=0.18, wobble=17))
        plot_kids.append(text("MOTIF_233", 554, 26, 9, C["orange"], MONO))
        sp.append(frame("span-plot", 18, 34, 1228, 154, C["dark"], radius=5,
                        children=plot_kids))
        sp += [ellipse(190, 218, 8, 8, C["blue"]),
               text("detected", 204, 216, 10, C["grey"], MONO),
               ellipse(280, 218, 8, 8, C["green"]),
               text("annotated", 294, 216, 10, C["grey"], MONO),
               ellipse(378, 218, 8, 8, C["orange"]),
               text("open", 392, 216, 10, C["grey"], MONO)]
        k.append(frame("tier-2-span", X, 274, W, 244, C["white"], radius=10,
                       stroke=C["border"], children=sp))

        # ---- tier 3: the motif
        mo = [text("MOTIF_233", 18, 14, 10, C["muted"], MONO),
              text("277.312 – 277.318 h   ·   21.6 s   ·   detected, "
                   "unadjudicated", 116, 14, 10, C["grey"], MONO),
              rtext("× 120000", 1246, 14, 10, C["muted"], MONO),
              frame("motif-plot", 18, 34, 1228, 132, C["dark"], radius=5, children=[
                  rect(214, 0, 1, 132, C["red"]),
                  text("ONSET", 222, 6, 9, C["red"], MONO),
                  motif_trace(0, 0, 1228, 132, 551, cycles=3.4)]),
              text("nearest family F-03  ·  d 0.19  ·  tagged sharkfin",
                   18, 174, 10, C["muted"], MONO)]
        parts, _ = button("Send motif to Analyse  →", 1246 - 196, 168, h=26)
        mo += parts
        k.append(frame("tier-3-motif", X, 530, W, 204, C["white"], radius=10,
                       stroke=C["border"], children=mo))

        # ---- span actions: save WITHOUT running anything
        ac = [text("Selected span", 20, 16, 11, C["muted"], MONO),
              text("276.4 – 278.4 h  ·  2.0 h  ·  6 motifs in view",
                   118, 17, 10, C["grey"], MONO),
              text("tags", 20, 44, 10, C["grey"], MONO)]
        tx = 58
        for tag, on in [("sharkfin", True), ("burst", False), ("+ tag", False)]:
            w = tw(tag, 10, MONO) + 18
            ac += [rect(tx, 40, w, 22, C["tint"] if on else C["page"], radius=6,
                        stroke=C["blue"] if on else C["border"]),
                   text(tag, tx + 9, 45, 10, C["blue"] if on else C["grey"], MONO)]
            tx += w + 6
        ac += [text("note", 20, 74, 10, C["grey"], MONO),
               rect(58, 70, 560, 22, C["page"], radius=6, stroke=C["border"]),
               text("recurs on CH3 at similar amplitude — check ground",
                    66, 75, 10, C["muted"], MONO)]
        p1, w1 = button("Save span", 700, 52, h=30)
        p2, w2 = button("Save + send to Analyse  →", 700 + w1 + 10, 52,
                        primary=True, h=30)
        ac += p1 + p2
        ac.append(text("saving does not run anything", 700, 88, 9, C["muted"], MONO))
        k.append(frame("span-actions", X, 746, W, 108, C["white"], radius=10,
                       stroke=C["border"], children=ac))

        # ---- collapsed ribbons
        rx = X
        for lab, cnt in [("Filters & search", None), ("Annotations", "708"),
                         ("Detections", "1284"), ("Keyboard shortcuts", None)]:
            w = 300 if lab == "Filters & search" else 300
            k += ribbon(rx, 866, 307, lab, cnt)
            rx += 319
    else:
        # ---- the drawer, open over the lower screen
        dr = [text("⌄", 14, 10, 13, C["grey"]),
              rtext("collapse", 1246, 14, 11, C["blue"], MONO)]
        tabx = 40
        for t, on in [("Filters & search", True), ("Annotations  708", False),
                      ("Detections  1284", False), ("Shortcuts", False)]:
            w = tw(t, 11, MONO) + 24
            if on:
                dr.append(rect(tabx, 8, w, 26, C["tint"], radius=6, stroke=C["blue"]))
            dr.append(text(t, tabx + 12, 14, 11, C["blue"] if on else C["grey"], MONO))
            tabx += w + 8

        fields = [("verdict", "interesting"), ("source", "any"), ("element", ""),
                  ("quality", ""), ("structure", ""), ("status", ""),
                  ("spike-train length", ""), ("duration band", "medium"),
                  ("search id", "e.g. 42, 108"), ("search note / tags", "sharkfin")]
        for i, (lab, val) in enumerate(fields):
            col, row = i % 5, i // 5
            fx, fy = 20 + col * 244, 52 + row * 46
            dr += [text(lab, fx, fy, 9, C["muted"], MONO),
                   rect(fx, fy + 14, 228, 24, C["page"], radius=6, stroke=C["border"]),
                   text(val if val else "—", fx + 8, fy + 20, 10,
                        C["black"] if val else C["muted"], MONO)]
        p1, w1 = button("Clear filters", 20, 148, h=26)
        dr += p1
        dr.append(text("412 of 708 annotations match", 140, 154, 10, C["grey"], MONO))
        p2, w2 = button("Export CSV", 1246 - 230, 148, h=26)
        p3, w3 = button("Export JSON", 1246 - 114, 148, h=26)
        dr += p2 + p3

        cols = ["id", "start", "end", "verdict", "tags", "source", "note"]
        cx = [20, 90, 180, 270, 400, 560, 700]
        dr.append(rect(20, 190, 1226, 1, C["border"]))
        for c, x in zip(cols, cx):
            dr.append(text(c, x, 196, 9, C["muted"], MONO))
        rows = [("1,835", "50,400", "51,000", "interesting", "sharkfin", "manual_ui",
                 "clean onset"),
                ("1,578", "53,400", "54,000", "interesting", "sharkfin, burst",
                 "manual_ui", ""),
                ("328", "56,600", "57,200", "seed", "sharkfin", "manual_ui",
                 "exemplar for F-03"),
                ("84", "58,200", "58,800", "interesting", "—", "imported_10min", ""),
                ("9,753", "61,000", "61,600", "not_interesting", "—",
                 "imported_10min", ""),
                ("7,102", "63,600", "64,200", "artifact", "—", "imported_10min",
                 "shared ground w/ CH3")]
        vcol = {"interesting": C["green"], "seed": C["blue"],
                "not_interesting": C["muted"], "artifact": C["red"]}
        for i, r in enumerate(rows):
            y = 214 + i * 26
            if i % 2 == 0:
                dr.append(rect(16, y - 5, 1234, 26, C["page"], radius=4))
            for j, (val, x) in enumerate(zip(r, cx)):
                col = vcol.get(val, C["black"]) if j == 3 else C["black"]
                dr.append(text(val, x, y, 10, col, MONO))
        p4, w4 = button("Stage verdict change", 20, 380, h=26)
        p5, w5 = button("Add tag", 20 + w4 + 10, 380, h=26)
        p6, w6 = button("Send selected to Review  →", 1246 - 224, 380,
                        primary=True, h=26)
        dr += p4 + p5 + p6
        k.append(frame("drawer", X, 290, W, 424, C["white"], radius=10,
                       stroke=C["border"], children=dr))

        k.append(frame("tier-3-motif (behind drawer)", X, 730, W, 124, C["white"],
                       radius=10, stroke=C["border"], children=[
            text("MOTIF_233", 18, 14, 10, C["muted"], MONO),
            rtext("× 120000", 1246, 14, 10, C["muted"], MONO),
            frame("motif-plot", 18, 34, 1228, 74, C["dark"], radius=5, children=[
                motif_trace(0, 0, 1228, 74, 551, cycles=3.4)])]))

    name = "explore-1b-signal-drawer" if drawer else "explore-1-signal"
    return frame(name, ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 2  CROSS
def cross_channel(ox):
    """Placeholder -- holds the slot, stays loose on purpose."""
    k = mode_chrome("Cross-channel", "placeholder · not specified")
    X, W = 88, 1264

    k.append(frame("note", X, 108, W, 52, C["gtint"], radius=8, children=[
        text("Placeholder. Kept loose deliberately — this mode also carries "
             "the future multivariate direction, so it is not worth fixing "
             "its layout yet.", 18, 18, 11, C["gink"], MONO)]))

    rows = [("CH4_A2", "0.0", "reference", C["blue"], C["blue"]),
            ("CH3_A2", "+0.04", "artifact  ·  r = 0.98", C["red"], C["trace"]),
            ("CH1_A1", "+1.20", "propagation  ·  r = 0.71", C["amber"], C["trace"]),
            ("CH2_A1", "+2.85", "propagation  ·  r = 0.64", C["amber"], C["trace"]),
            ("CH5_B1", "−18.4", "independent  ·  r = 0.31", C["green"], C["trace"]),
            ("CH6_B1", "—", "no match", C["muted"], C["ghost"])]
    st = [text("SAME SPAN, EVERY SELECTED CHANNEL", 18, 14, 10, C["muted"], MONO),
          text("276.4 – 278.4 h", 310, 14, 10, C["grey"], MONO),
          rtext("lag  ·  waveform identity  ·  bin", 1246, 14, 10, C["muted"], MONO)]
    for i, (nm, lag, cls, col, tcol) in enumerate(rows):
        y = 38 + i * 66
        st += [text(nm, 18, y + 20, 11, C["black"], MONO),
               frame("row%d" % i, 90, y, 880, 56, C["dark"], radius=4, children=[
                   rect(392, 0, 94, 56, C["ov_motif"] if i == 0 else C["ov_span"]),
                   trace(0, 0, 880, 56, 3300 + i * 137, pts=260, amp=0.32,
                         drift=0.20, col=tcol, sw=1.1, wobble=11)]),
               ellipse(990, y + 24, 8, 8, col),
               text(lag + " s", 1008, y + 19, 11, C["black"], MONO),
               text(cls, 1086, y + 20, 10, C["grey"], MONO)]
    k.append(frame("channel-stack", X, 176, W, 452, C["white"], radius=10,
                   stroke=C["border"], children=st))

    open_qs = ["how many channels fit before the stack stops being readable",
               "does the reference channel pin to the top or stay in place",
               "is lag computed live on the visible span, or read from an "
               "existing run",
               "what happens here when the signal type becomes multivariate"]
    oq = [text("Open questions", 20, 18, 12)]
    for i, q in enumerate(open_qs):
        oq += [ellipse(20, 52 + i * 26, 6, 6, C["muted"]),
               text(q, 36, 46 + i * 26, 11, C["grey"], MONO)]
    k.append(frame("open-questions", X, 644, W, 176, C["white"], radius=10,
                   stroke=C["border"], children=oq))

    return frame("explore-2-cross-channel", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ 3  AGREE
def agreement(ox):
    k = mode_chrome("Agreement", "708 annotations  ·  1284 detections  ·  184 disagree")
    X, W = 88, 1000

    # ---- channel trace with both overlays
    ov = [text("CHANNEL", 18, 14, 10, C["muted"], MONO),
          text("CH4_A2  ·  0 – 720 h", 96, 14, 10, C["grey"], MONO),
          rtext("both stores overlaid", W - 18, 14, 10, C["muted"], MONO),
          frame("plot", 18, 34, W - 36, 108, C["dark"], radius=5, children=[
              rect(180, 0, 52, 108, C["ov_interest"]),
              rect(300, 0, 78, 108, C["ov_span"]),
              rect(560, 0, 64, 108, C["ov_span"]),
              rect(700, 0, 46, 108, C["ov_interest"]),
              trace(0, 0, W - 36, 108, 4711, pts=360, amp=0.32, drift=0.16,
                    wobble=27)])]
    k.append(frame("channel-overview", X, 108, W, 158, C["white"], radius=10,
                   stroke=C["border"], children=ov))

    # ---- the three tracks
    tr = [text("WHERE THE TWO STORES AGREE", 18, 14, 10, C["muted"], MONO),
          text("annotations are human, detections are machine — they are "
               "stored separately and never merged", 250, 14, 10, C["muted"], MONO),
          text("annotations", 18, 46, 9, C["muted"], MONO),
          text("detections", 18, 76, 9, C["muted"], MONO),
          text("agreed", 18, 106, 9, C["muted"], MONO),
          text("disagree", 18, 136, 9, C["muted"], MONO)]
    ann = [(20, 70), (150, 48), (300, 96), (470, 60), (600, 84), (790, 52)]
    det = [(24, 64), (218, 70), (302, 92), (540, 66), (604, 78), (700, 58), (860, 50)]
    agr = [(24, 60), (302, 88), (604, 74)]
    dis = [(150, 48), (218, 70), (470, 60), (540, 66), (700, 58), (790, 52), (860, 50)]
    sc = 0.93
    for xs, y, col in [(ann, 44, C["green"]), (det, 74, C["blue"]),
                       (agr, 104, C["muted"]), (dis, 134, C["amber"])]:
        for x0, wd in xs:
            tr.append(rect(110 + x0 * sc, y, wd * sc, 14, col, radius=2))
    k.append(frame("tracks", X, 282, W, 176, C["white"], radius=10,
                   stroke=C["border"], children=tr))

    # ---- the disagreement list
    ls = [text("Disagreements", 18, 16, 12),
          text("184", 132, 17, 11, C["grey"], MONO),
          rtext("sorted by score ↓", W - 18, 19, 10, C["muted"], MONO)]
    items = [("d-0412", "machine only", "192.4 h", "0.88", C["blue"]),
             ("a-1835", "human only", "276.4 h", "—", C["green"]),
             ("d-0455", "machine only", "301.8 h", "0.81", C["blue"]),
             ("a-1578", "human only", "344.2 h", "—", C["green"]),
             ("d-0501", "machine only", "402.6 h", "0.79", C["blue"])]
    for i, (iid, kind, t, sc_, col) in enumerate(items):
        y = 46 + i * 62
        ls += [rect(18, y, W - 36, 54, C["page"], radius=8),
               ellipse(30, y + 23, 8, 8, col),
               text(iid, 48, y + 8, 11, C["black"], MONO),
               text(kind, 48, y + 26, 10, C["grey"], MONO),
               text(t, 150, y + 17, 11, C["black"], MONO),
               frame("sp%d" % i, 230, y + 13, 300, 28, C["dark"], radius=4,
                     children=[trace(0, 0, 300, 28, 700 + i * 91, pts=90,
                                     amp=0.32, drift=0.28, col=C["trace"],
                                     sw=1, wobble=7)]),
               text("score", 556, y + 10, 9, C["muted"], MONO),
               text(sc_, 556, y + 26, 11, C["black"], MONO)]
        if kind == "machine only":
            p, w = button("pass to Review", W - 36 - 150, y + 14, h=26)
            ls += p
        else:
            p, w = button("run detection here", W - 36 - 180, y + 14, h=26)
            ls += p
    k.append(frame("disagreement-list", X, 474, W, 382, C["white"], radius=10,
                   stroke=C["border"], children=ls))

    # ---- summary rail + bulk actions
    RW = 320
    sm = [text("Summary", 20, 18, 12), rect(20, 42, RW - 40, 1, C["border"])]
    for i, (lab, n, col, note) in enumerate([
            ("agreed", "128", C["muted"], "both stores mark it"),
            ("machine only", "76", C["blue"], "no human looked, or human passed"),
            ("human only", "108", C["green"], "an analytical blind spot")]):
        y = 56 + i * 56
        sm += [ellipse(20, y + 5, 9, 9, col), text(lab, 38, y, 12),
               rtext(n, RW - 20, y, 12, C["black"], MONO),
               text(note, 38, y + 20, 9, C["muted"], MONO)]
    sm += [rect(20, 232, RW - 40, 1, C["border"]),
           text("Bulk", 20, 246, 12)]
    p1, w1 = button("Pass all 76 machine-only to Review  →", 20, 274,
                    primary=True, h=30)
    p2, w2 = button("Export disagreement set (CSV)", 20, 314, h=30)
    sm += p1 + p2
    sm += [rect(20, 362, RW - 40, 1, C["border"]),
           text("Nothing here writes a verdict. Adjudication happens in "
                "Review, against detections only — so this screen can never "
                "put a machine verdict into the annotation store.",
                20, 378, 10, C["muted"], MONO),
           text("Human-only spans are the finding, not the backlog: they are "
                "where the algorithms are blind.", 20, 448, 10, C["amber"], MONO)]
    k.append(frame("summary-rail", 1112, 108, RW, 748, C["white"], radius=10,
                   stroke=C["border"], children=sm))

    return frame("explore-3-agreement", ox, 0, 1440, 900, C["page"], children=k)


# ================================================================ output
STEPS = [("1  ·  corpus — pick a channel", 0),
         ("2  ·  Signal mode", 1560),
         ("2b  ·  Signal mode, drawer open", 3120),
         ("3  ·  Cross-channel mode (placeholder)", 4680),
         ("4  ·  Agreement mode", 6240)]

screens = [corpus(0), signal(1560), signal(3120, drawer=True),
           cross_channel(4680), agreement(6240)]
labels = [text(lab, x, -46, 16, C["grey"], MONO) for lab, x in STEPS]

write_doc("UI_explore_flow_v1.pen", screens + labels)
