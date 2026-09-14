#!/usr/bin/env python3
"""
Three Explore-workspace concepts for Underground Brains.

All three keep the zoom cascade from the Figma design -- recording overview,
selected span, resolved motif -- because that nesting is what makes a
multi-hour univariate recording navigable. They differ in what the SECOND
axis of the interface is:

  explore-1-cascade    zoom depth is the whole interface. Four tiers, explicit
                       magnification readouts, coverage/density ribbons under
                       the overview. PRD stories 1-5, 25.
  explore-2-channels   the span is shown across N channels at once, with lag
                       and waveform-identity readouts per channel. Moves the
                       artifact/propagation/independent judgement to view time
                       instead of library time. PRD stories 36, 42.
  explore-3-divergence navigate by where the interesting material already is:
                       a channels x time density map with separate human and
                       machine tracks, so disagreement is the thing you steer
                       by. PRD stories 2, 4, 30.

Run:  python build_explore.py  ->  UI_explore_concepts_v1.pen
"""

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, ctext,
                     trace, motif_trace, sidebar, header, chip, button, keycap,
                     tw, write_doc)

VERDICTS = [("S", "seed"), ("I", "interesting"), ("N", "not interesting"),
            ("A", "artifact"), ("U", "unsure")]

# density ramp; first entry stays near-page so empty bins read as empty
RAMP_SAFE = ["#F0F0F2", "#DCEAF9", "#B6D6F4", "#7FB8EE", "#3D93E4", "#007AFF"]


def filter_bar(items, y=44, w=1376, right=None, extra=None):
    kids, cx = [], 24
    for lab, act in items:
        parts, cw = chip(lab, cx, 12, act)
        kids += parts
        cx += cw + 8
    if extra:
        kids += extra(cx)
    if right:
        kids.append(rtext(right, w - 24, 19, 11, C["grey"], MONO))
    return frame("filter-bar", 64, y, w, 52, C["page"], children=kids)


# ============================================================ CONCEPT 1
def cascade(ox):
    """Zoom depth as the primary structure."""
    k = [sidebar(0), header("Explore", "Cascade  ·  zoom depth is the interface",
                            "M2_aug_concat_fs1.mat  ·  CH4_A2")]
    k.append(filter_bar([("CH4_A2", True), ("annotations on", True),
                         ("detections on", True), ("seed mode", False)],
                        right="session restored  ·  3 spans this session"))

    X, W = 88, 1264

    # ---- tier 1: whole recording + coverage/density ribbons
    t1 = [text("RECORDING", 18, 14, 10, C["muted"], MONO),
          text("0 – 3600 s", 108, 14, 10, C["grey"], MONO),
          rtext("1 : 3600", 1246, 14, 10, C["muted"], MONO),
          frame("overview", 18, 34, 1228, 52, C["dark"], radius=5, children=[
              rect(446, 0, 42, 52, C["ov_span"], stroke=C["blue"]),
              trace(0, 0, 1228, 52, 4711, pts=420, amp=0.34, drift=0.16, wobble=31)]),
          text("coverage", 18, 96, 9, C["muted"], MONO),
          text("detection density", 18, 112, 9, C["muted"], MONO)]
    # coverage ribbon: contiguous adjudicated regions
    for x0, wd, col in [(0, 260, C["green"]), (268, 120, C["amber"]),
                        (396, 300, C["green"]), (704, 60, C["red"]),
                        (772, 200, C["amber"]), (980, 248, C["border"])]:
        t1.append(rect(120 + x0 * 0.9, 96, wd * 0.9, 8, col, radius=2))
    # density ribbon: detection counts per bin
    import math as _m
    for i in range(46):
        h = 2 + int(10 * abs(_m.sin(i / 3.1) * _m.cos(i / 7.3)))
        t1.append(rect(120 + i * 24, 112 + (12 - h), 20, h, C["blue"], radius=1))
    k.append(frame("tier-1-recording", X, 108, W, 140, C["white"],
                   radius=10, stroke=C["border"], children=t1))

    # ---- tier 2: selected span, with overlays
    t2 = [text("SPAN", 18, 14, 10, C["muted"], MONO),
          text("1420 – 1540 s   ·   120 s", 70, 14, 10, C["grey"], MONO),
          rtext("× 30", 1246, 14, 10, C["muted"], MONO),
          rtext("drag to reselect  ·  ⌥ scroll to zoom", 1190, 14, 10, C["muted"], MONO),
          frame("span-plot", 18, 34, 1228, 176, C["dark"], radius=5, children=[
              rect(180, 0, 96, 176, C["ov_interest"]),
              rect(742, 0, 58, 176, C["ov_artifact"]),
              rect(548, 0, 128, 176, C["ov_motif"], stroke=C["orange"]),
              trace(0, 0, 1228, 176, 9137, pts=320, amp=0.30, drift=0.18, wobble=17),
              text("annotation  interesting", 186, 6, 9, C["green"], MONO),
              text("artifact", 748, 6, 9, C["red"], MONO),
              text("MOTIF_233", 554, 6, 9, C["orange"], MONO)]),
          text("2 annotations  ·  1 detection in view", 18, 218, 10, C["muted"], MONO)]
    k.append(frame("tier-2-span", X, 260, W, 244, C["white"],
                   radius=10, stroke=C["border"], children=t2))

    # ---- tier 3: the motif itself
    t3 = [text("MOTIF", 18, 14, 10, C["muted"], MONO),
          text("1482.4 – 1485.6 s   ·   3.2 s", 74, 14, 10, C["grey"], MONO),
          rtext("× 1125", 1246, 14, 10, C["muted"], MONO),
          frame("motif-plot", 18, 34, 1228, 150, C["dark"], radius=5, children=[
              rect(214, 0, 1, 150, C["red"]),
              text("ONSET  t = 1482.96 s", 222, 8, 9, C["red"], MONO),
              motif_trace(0, 0, 1228, 150, 551, cycles=3.4)]),
          text("matches library exemplar E-014  ·  d = 0.31  ·  scale-invariant",
               18, 192, 10, C["muted"], MONO)]
    k.append(frame("tier-3-motif", X, 516, W, 218, C["white"],
                   radius=10, stroke=C["border"], children=t3))

    # ---- actions
    act = [text("Mark this span", 20, 16, 11, C["muted"], MONO)]
    bx = 20
    for key, lab in [("S", "seed exemplar"), ("I", "interesting"), ("A", "artifact")]:
        act += keycap(bx, 40, key, lab, w=210, h=48)
        bx += 222
    parts, bw = button("Run analysis on this span  →", 1264 - 20 - 238, 50,
                       primary=True, h=32)
    act += parts
    act.append(rtext("or add to a chain in Analyse", 1244, 24, 10, C["muted"], MONO))
    k.append(frame("span-actions", X, 746, W, 104, C["white"],
                   radius=10, stroke=C["border"], children=act))

    return frame("explore-1-cascade", ox, 0, 1440, 900, C["page"], children=k)


# ============================================================ CONCEPT 2
def channels(ox):
    """The same span across many channels -- artifact judgement at view time."""
    k = [sidebar(0), header("Explore", "Channels  ·  one span, every channel",
                            "M2_aug_concat_fs1.mat")]

    # ---- channel selector
    ch = [text("Channels", 20, 20, 14, C["black"], SANS, True),
          text("6 of 16 shown", 20, 44, 11, C["grey"], MONO),
          rect(20, 68, 176, 1, C["border"])]
    names = ["CH1_A1", "CH2_A1", "CH3_A2", "CH4_A2", "CH5_B1", "CH6_B1",
             "CH7_B2", "CH8_B2", "CH9_C1", "CH10_C1"]
    for i, nm in enumerate(names):
        on = i < 6
        ref = nm == "CH4_A2"
        y = 84 + i * 46
        ch += [rect(20, y, 176, 40, C["tint"] if ref else C["white"], radius=7,
                    stroke=C["blue"] if ref else None),
               rect(30, y + 13, 14, 14, C["blue"] if on else C["white"],
                    radius=4, stroke=None if on else C["border"]),
               text(nm, 54, y + 6, 11, C["blue"] if ref else C["black"], MONO),
               frame("sp%d" % i, 54, y + 22, 130, 12, C["dark"], radius=2, children=[
                   trace(0, 0, 130, 12, 900 + i * 71, pts=40, amp=0.34,
                         drift=0.34, col=C["blue"] if ref else C["trace"],
                         sw=1, wobble=4)])]
        if ref:
            ch.append(rtext("ref", 188, y + 7, 9, C["blue"], MONO))
    k.append(frame("channel-panel", 64, 44, 216, 856, C["white"], children=ch))

    X, W = 304, 1112

    # ---- tier 1 overview, compressed
    k.append(frame("tier-1-recording", X, 60, W, 104, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("RECORDING", 16, 12, 10, C["muted"], MONO),
        text("0 – 3600 s  ·  span 1420 – 1540 s", 98, 12, 10, C["grey"], MONO),
        rtext("× 30", W - 16, 12, 10, C["muted"], MONO),
        frame("overview", 16, 32, W - 32, 54, C["dark"], radius=5, children=[
            rect(392, 0, 38, 54, C["ov_span"], stroke=C["blue"]),
            trace(0, 0, W - 32, 54, 4711, pts=380, amp=0.34, drift=0.16, wobble=31)])]))

    # ---- tier 2: the same 120 s on every selected channel
    rows = [("CH4_A2", "0.0", "reference", C["blue"], C["blue"]),
            ("CH3_A2", "+0.04", "artifact  ·  r = 0.98", C["red"], C["trace"]),
            ("CH1_A1", "+1.20", "propagation  ·  r = 0.71", C["amber"], C["trace"]),
            ("CH2_A1", "+2.85", "propagation  ·  r = 0.64", C["amber"], C["trace"]),
            ("CH5_B1", "−18.4", "independent  ·  r = 0.31", C["green"], C["trace"]),
            ("CH6_B1", "—", "no match", C["muted"], C["ghost"])]
    st = [text("SPAN ACROSS CHANNELS", 16, 12, 10, C["muted"], MONO),
          text("1420 – 1540 s  ·  120 s", 190, 12, 10, C["grey"], MONO),
          rtext("lag · waveform identity · bin", W - 16, 12, 10, C["muted"], MONO)]
    for i, (nm, lag, cls, col, tcol) in enumerate(rows):
        y = 34 + i * 62
        st += [text(nm, 16, y + 18, 11, C["black"], MONO),
               frame("row%d" % i, 84, y, 756, 52, C["dark"], radius=4, children=[
                   rect(338, 0, 80, 52, C["ov_motif"] if i == 0 else C["ov_span"]),
                   trace(0, 0, 756, 52, 3300 + i * 137, pts=240, amp=0.32,
                         drift=0.20, col=tcol, sw=1.1, wobble=11)]),
               ellipse(856, y + 22, 8, 8, col),
               text(lag + " s", 874, y + 17, 11, C["black"], MONO),
               text(cls, 950, y + 18, 10, C["grey"], MONO)]
    k.append(frame("tier-2-channels", X, 178, W, 432, C["white"], radius=10,
                   stroke=C["border"], children=st))

    # ---- tier 3 + classification summary
    k.append(frame("tier-3-motif", X, 624, 700, 168, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("MOTIF on reference", 16, 12, 10, C["muted"], MONO),
        text("1482.4 – 1485.6 s  ·  3.2 s", 174, 12, 10, C["grey"], MONO),
        frame("motif-plot", 16, 32, 668, 118, C["dark"], radius=5, children=[
            rect(116, 0, 1, 118, C["red"]),
            motif_trace(0, 0, 668, 118, 551, cycles=3.4)])]))

    summ = [text("Cross-channel", 16, 14, 12),
            text("1 artifact excluded from counts", 16, 128, 10, C["red"], MONO)]
    for i, (lab, n, col) in enumerate([("artifact", "1", C["red"]),
                                       ("propagation", "2", C["amber"]),
                                       ("independent", "1", C["green"])]):
        y = 44 + i * 26
        summ += [ellipse(16, y + 4, 8, 8, col), text(lab, 32, y, 11, C["grey"]),
                 rtext(n, 372, y, 11, C["black"], MONO)]
    k.append(frame("cross-channel-summary", X + 720, 624, 392, 168, C["white"],
                   radius=10, stroke=C["border"], children=summ))

    act = []
    bx = 0
    for key, lab in [("S", "seed"), ("I", "interesting"), ("A", "artifact")]:
        act += keycap(X + bx, 812, key, lab, w=200, h=44)
        bx += 210
    parts, _ = button("Run analysis across selected channels  →",
                      X + W - 302, 818, primary=True, h=32)
    k += act + parts

    return frame("explore-2-channels", ox, 0, 1440, 900, C["page"], children=k)


# ============================================================ CONCEPT 3
def divergence(ox):
    """Navigate by where human and machine judgement already disagree."""
    import math as _m
    k = [sidebar(0), header("Explore", "Divergence  ·  navigate by what is already marked",
                            "M2_aug_concat_fs1.mat  ·  16 channels")]
    k.append(filter_bar([("detections", True), ("annotations", True),
                         ("disagreement only", False), ("CH all", False)],
                        right="1284 detections  ·  312 annotations  ·  184 disagree"))

    X, W = 88, 1080

    # ---- the map: channels x time
    mp = [text("COVERAGE MAP", 16, 12, 10, C["muted"], MONO),
          text("16 channels × 3600 s  ·  20 s bins", 130, 12, 10, C["grey"], MONO),
          rtext("click a cell to drill in", W - 16, 12, 10, C["muted"], MONO)]
    chans = ["CH%d" % (i + 1) for i in range(16)]
    cw, chh = 20, 15
    for r, nm in enumerate(chans):
        y = 36 + r * (chh + 2)
        mp.append(text(nm, 16, y + 2, 9, C["muted"], MONO))
        for c in range(48):
            v = abs(_m.sin((r + 1) / 2.7 + c / 4.1) * _m.cos(c / 9.2 + r / 5.5))
            idx = min(5, int(v * 6))
            sel = (r == 3 and 22 <= c <= 24)
            mp.append(rect(56 + c * (cw + 1), y, cw, chh,
                           C["blue"] if sel else RAMP_SAFE[idx], radius=2,
                           stroke=C["black"] if sel else None))
    mp += [text("0 s", 56, 322, 9, C["muted"], MONO),
           text("1800 s", 500, 322, 9, C["muted"], MONO),
           rtext("3600 s", W - 16, 322, 9, C["muted"], MONO)]
    k.append(frame("coverage-map", X, 108, W, 348, C["white"], radius=10,
                   stroke=C["border"], children=mp))

    # ---- divergence tracks
    dv = [text("HUMAN vs MACHINE", 16, 12, 10, C["muted"], MONO),
          text("CH4_A2  ·  where the two stores disagree", 158, 12, 10, C["grey"], MONO),
          text("annotations", 16, 40, 9, C["muted"], MONO),
          text("detections", 16, 66, 9, C["muted"], MONO),
          text("disagreement", 16, 92, 9, C["muted"], MONO)]
    ann = [(40, 90), (210, 60), (420, 130), (690, 70), (860, 110)]
    det = [(44, 84), (300, 90), (416, 140), (560, 80), (866, 100), (980, 60)]
    for x0, wd in ann:
        dv.append(rect(112 + x0 * 0.86, 38, wd * 0.86, 12, C["green"], radius=2))
    for x0, wd in det:
        dv.append(rect(112 + x0 * 0.86, 64, wd * 0.86, 12, C["blue"], radius=2))
    # disagreement = symmetric difference, drawn in amber
    for x0, wd in [(210, 60), (300, 90), (560, 80), (690, 70), (980, 60)]:
        dv.append(rect(112 + x0 * 0.86, 90, wd * 0.86, 12, C["amber"], radius=2))
    dv.append(text("184 spans marked by one store and not the other — "
                   "a measurable finding, not noise", 112, 116, 10, C["muted"], MONO))
    k.append(frame("divergence-tracks", X, 468, W, 148, C["white"], radius=10,
                   stroke=C["border"], children=dv))

    # ---- drill-down: span + motif side by side
    k.append(frame("tier-2-span", X, 628, 700, 222, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("SPAN", 16, 12, 10, C["muted"], MONO),
        text("CH4  ·  1420 – 1540 s", 62, 12, 10, C["grey"], MONO),
        rtext("× 30", 684, 12, 10, C["muted"], MONO),
        frame("span-plot", 16, 32, 668, 158, C["dark"], radius=5, children=[
            rect(298, 0, 70, 158, C["ov_motif"], stroke=C["orange"]),
            rect(120, 0, 52, 158, C["ov_interest"]),
            trace(0, 0, 668, 158, 9137, pts=240, amp=0.30, drift=0.18, wobble=17),
            text("human only", 126, 6, 9, C["green"], MONO)]),
        text("annotated interesting, no detection overlaps it",
             16, 198, 10, C["amber"], MONO)]))

    k.append(frame("tier-3-motif", X + 720, 628, 360, 222, C["white"], radius=10,
                   stroke=C["border"], children=[
        text("MOTIF", 16, 12, 10, C["muted"], MONO),
        text("3.2 s", 70, 12, 10, C["grey"], MONO),
        rtext("× 1125", 344, 12, 10, C["muted"], MONO),
        frame("motif-plot", 16, 32, 328, 118, C["dark"], radius=5, children=[
            motif_trace(0, 0, 328, 118, 551, cycles=3.0)]),
        text("no library match above threshold", 16, 158, 10, C["muted"], MONO),
        rect(16, 180, 150, 26, C["blue"], radius=6),
        text("mark as seed", 30, 187, 10, C["white"], MONO)]))

    # ---- right rail: legend + counts
    lg = [text("Legend", 20, 20, 12),
          rect(20, 44, 224, 1, C["border"])]
    for i, (lab, col, note) in enumerate([
            ("annotation", C["green"], "human, from Explore"),
            ("detection", C["blue"], "machine, from a run"),
            ("disagreement", C["amber"], "one store only"),
            ("selected", C["black"], "current drill-down")]):
        y = 58 + i * 44
        lg += [rect(20, y, 14, 14, col, radius=3),
               text(lab, 44, y, 11),
               text(note, 44, y + 16, 9, C["muted"], MONO)]
    lg += [rect(20, 240, 224, 1, C["border"]),
           text("Disagreement", 20, 254, 12)]
    for i, (lab, n, col) in enumerate([("human only", "108", C["green"]),
                                       ("machine only", "76", C["blue"]),
                                       ("agreed", "128", C["muted"])]):
        y = 282 + i * 26
        lg += [ellipse(20, y + 4, 8, 8, col), text(lab, 36, y, 11, C["grey"]),
               rtext(n, 244, y, 11, C["black"], MONO)]
    lg += [rect(20, 372, 224, 1, C["border"]),
           text("Adjudicating the remainder is how divergence becomes a "
                "finding rather than a gap.", 20, 388, 10, C["muted"], MONO)]
    k.append(frame("legend-rail", 1184, 108, 256, 742, C["white"], radius=10,
                   stroke=C["border"], children=lg))

    return frame("explore-3-divergence", ox, 0, 1440, 900, C["page"], children=k)


write_doc("UI_explore_concepts_v1.pen",
          [cascade(0), channels(1560), divergence(3120)])
