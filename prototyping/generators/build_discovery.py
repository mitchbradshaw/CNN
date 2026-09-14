#!/usr/bin/env python3
"""
Discovery workspace only -- four screens, kept in their own document so the
file stays small enough to open comfortably.

  1  algorithms at scale      apply saved detectors, scored against review
  2  two algorithms compared  recipe diff, shared time axis, set overlap
  2b the same window, stage by stage   why they disagreed, as pictures
  3  seeded search            MASS at native length, threshold against a null

Run:  python build_discovery.py  ->  UI_discovery_v1.pen
"""

from pen_kit import C, MONO, text, write_doc
import build_blocks as B
from build_v3 import discovery_algorithms, discovery_seed

SCREENS = [
    ("1  ·  algorithms at scale, scored", discovery_algorithms),
    ("2  ·  two algorithms compared", B.p_compare),
    ("2b  ·  the same window, stage by stage", B.p_compare_window),
    ("3  ·  seeded search", discovery_seed),
]

screens, labels = [], []
for i, (lab, fn) in enumerate(SCREENS):
    s = fn()
    s["x"] = i * 1560
    screens.append(s)
    labels.append(text(lab, i * 1560, -46, 16, C["grey"], MONO))

write_doc("UI_discovery_v1.pen", screens + labels)
