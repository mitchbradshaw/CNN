#!/usr/bin/env python3
"""
The Review workspace — the settled design (formerly "C2").

Rebuilt on the current kit (pen_kit / pen_widgets / build_blocks chrome) so it
matches the Analyse and Discovery documents. The design is unchanged from the
version agreed earlier:

  * Both side rails collapse, and are collapsed by default, so the motif gets
    the canvas. The queue rail keeps cluster sparklines; the evidence rail
    keeps four micro-stats.
  * The three signals that justify slowing down — adjudication status, family
    affinity, member cohesion — are promoted out of the collapsible evidence
    rail into always-visible chips beside the title. A waveform can look dull
    and still sit at low distance to a known family; if that signal hides
    inside a collapsed panel, the case it exists for is the case you miss.
  * The verdict row sits below the plot rather than inside the evidence
    column, so the fast path survives the rails being shut.
  * An annotation row below it carries tags, class and notes — the deep-work
    path, available without leaving the queue.
  * Clusters are first class: the title states cluster or single, and
    "Verdict for all N members" applies a batch verdict.
  * Previous/next navigation shows the prior verdict, so a mis-keyed judgement
    can be revisited rather than only undone.

Run:  python build_review.py  ->  UI_review_v1.pen
"""

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, keycap,
                     button, tw, write_doc)
from pen_widgets import wander, ensemble, stat
from build_blocks import nav, head, card

X, W = 144, 1216
VERDICTS = [("S", "seed"), ("I", "interesting"), ("N", "not interesting"),
            ("A", "artifact"), ("U", "unsure")]


def review():
    k = [nav(3), head("Review", "Inspector  ·  rails collapsed, cluster-aware",
                      "342 / 1284  ·  ~1.9 s / candidate")]

    # ---- collapsed queue rail
    qr = [rect(55, 0, 1, 856, C["border"]),
          text("›", 24, 12, 15, C["grey"]),
          text("48", (56 - tw("48", 11, MONO)) / 2, 40, 11, C["black"], MONO),
          text("clusters", (56 - tw("clusters", 8, MONO)) / 2, 56, 8,
               C["muted"], MONO)]
    for i in range(14):
        on = i == 4
        qr.append(frame("q%d" % i, 10, 84 + i * 38, 36, 30,
                        C["tint"] if on else C["page"], radius=5,
                        stroke=C["blue"] if on else None,
                        children=[wander(0, 0, 36, 30, 180 + i * 53, pts=26,
                                         amp=0.30, drift=0.34,
                                         col=C["blue"] if on else C["muted"],
                                         sw=1, wobble=4)]))
    k.append(frame("queue-rail (collapsed)", 64, 44, 56, 856, C["white"],
                   children=qr))

    # ---- collapsed evidence rail
    er = [rect(0, 0, 1, 856, C["border"]),
          text("‹", 24, 12, 15, C["grey"])]
    for i, (v, col) in enumerate([("0.84", C["black"]), ("6.1×", C["green"]),
                                  ("d.19", C["purple"]), ("7", C["blue"])]):
        er.append(text(v, (56 - tw(v, 10, MONO)) / 2, 44 + i * 26, 10, col, MONO))
    k.append(frame("evidence-rail (collapsed)", 1384, 44, 56, 856, C["white"],
                   children=er))

    # ---- title and the three always-visible signals
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

    # ---- the candidate in context
    ck = [text("Exemplar in context", 18, 16, 12),
          text("\u00b1120 s  \u00b7  \u2325 scroll to zoom", 178, 18, 10,
               C["muted"], MONO)]
    p, ebw = button("Edit span in Explore  \u2192", W - 18 - 178, 10, h=26)
    ck += p
    ck += [rtext("returns you here when you are done", W - 18 - 190, 18, 9,
                 C["muted"], MONO),
           rect(18, 44, 1180, 226, C["dark"], radius=6),
          rect(18 + 492, 44, 196, 226, C["tint"], stroke=C["blue"])]
    ck.append(wander(18, 44, 1180, 226, 3311, pts=320, amp=0.30, drift=0.20,
                     wobble=13, sw=1.2))
    ck.append(wander(18 + 492, 44, 196, 226, 8822, pts=110, amp=0.34,
                     drift=0.26, col=C["red"], sw=1.6, wobble=5))
    k.append(card("candidate-context", X, 116, W, 288, ck))

    # ---- members, z-normalised
    zk = [text("Members, z-normalised", 18, 14, 12),
          rtext("7  ·  mean d 0.24", 578, 16, 10, C["muted"], MONO),
          rect(18, 42, 560, 118, C["dark"], radius=6)]
    for i in range(6):
        zk.append(wander(18, 42, 560, 118, 2200 + i * 91, pts=80, amp=0.26,
                         drift=0.22, col=C["ghost"], sw=1))
    zk.append(wander(18, 42, 560, 118, 777, pts=80, amp=0.26, drift=0.22,
                     col=C["blue"], sw=2))
    k.append(card("member-overlay", X, 416, 596, 180, zk))

    # ---- nearest families
    fk = [text("Nearest families", 18, 14, 12),
          rtext("low distance ≠ interesting", 578, 16, 10, C["muted"], MONO)]
    for i, (fid, d, tag, col) in enumerate([
            ("F-03", "0.19", "spike-train", C["purple"]),
            ("F-11", "0.37", "burst", C["muted"]),
            ("F-07", "0.52", "slow-drift", C["muted"])]):
        y = 44 + i * 44
        fk += [rect(18, y, 560, 38, C["page"], radius=6),
               ellipse(28, y + 16, 7, 7, col),
               text(fid, 46, y + 12, 11, C["black"], MONO),
               text(tag, 108, y + 13, 10, C["grey"], MONO),
               rect(258, y + 16, 180, 6, C["border"], radius=3),
               rect(258, y + 16, max(6, 180 * (1 - float(d))), 6, col, radius=3),
               rtext("d " + d, 568, y + 13, 10, C["grey"], MONO)]
    k.append(card("family-affinity", X + 620, 416, 596, 180, fk))

    # ---- verdict row
    vk = [text("Verdict", 20, 16, 11, C["muted"], MONO),
          rect(20, 40, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("‹", 30, 45, 13, C["grey"]),
          rect(52, 40, 26, 26, C["white"], radius=6, stroke=C["border"]),
          text("›", 62, 45, 13, C["grey"]),
          text("c-0342 was marked interesting", 88, 47, 10, C["muted"], MONO),
          rect(760, 14, 16, 16, C["white"], radius=4, stroke=C["border"]),
          text("Verdict for all 7 members", 784, 15, 11, C["black"], MONO),
          rtext("← undo  (reverses the whole cluster)", 1196, 16, 10,
                C["grey"], MONO)]
    for i, (key, lab) in enumerate(VERDICTS):
        vk += keycap(20 + i * 236, 76, key, lab, w=220, h=52)
    k.append(card("verdict-row", X, 616, W, 148, vk))

    # ---- annotation row
    ak = [text("Annotate", 20, 14, 11, C["muted"], MONO),
          text("optional — only for motifs worth the time", 92, 15, 10,
               C["muted"], MONO),
          text("morphology tags", 20, 40, 10, C["grey"], MONO)]
    tx = 20
    for tag, on in [("spike-train", True), ("slow-drift", False),
                    ("burst", True), ("plateau", False), ("biphasic", False),
                    ("+ new", False)]:
        w = tw(tag, 10, MONO) + 18
        ak += [rect(tx, 60, w, 24, C["tint"] if on else C["page"], radius=6,
                    stroke=C["blue"] if on else C["border"]),
               text(tag, tx + 9, 66, 10, C["blue"] if on else C["grey"], MONO)]
        tx += w + 6
    ak += [text("class", 480, 40, 10, C["grey"], MONO),
           rect(480, 60, 220, 24, C["page"], radius=6, stroke=C["border"]),
           text("unassigned", 490, 66, 10, C["grey"], MONO),
           rtext("⌄", 692, 64, 11, C["grey"], MONO),
           text("notes", 724, 40, 10, C["grey"], MONO),
           rect(724, 60, 472, 24, C["page"], radius=6, stroke=C["border"]),
           text("shape recurs on CH2 at ~0.5× duration — check scale "
                "invariance", 734, 66, 10, C["muted"], MONO)]
    k.append(card("annotation-row", X, 776, W, 104, ak))

    return frame("review-inspector", 0, 0, 1440, 900, C["page"], children=k)


s = review()
s["x"] = 0
write_doc("UI_review_v1.pen",
          [s, text("Review  ·  the adjudication surface", 0, -46, 16,
                   C["grey"], MONO)])
