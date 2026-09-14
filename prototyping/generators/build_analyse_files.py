#!/usr/bin/env python3
"""
Write the Analyse concept pages as three small documents rather than one large
one, so Pencil opens them comfortably.

  UI_analyse_chain_v1.pen          building a chain, and the detection chain
  UI_analyse_interrogation_v1.pen  measuring a Library family
  UI_analyse_training_v1.pen       window matrix -> cluster -> encode -> model

Discovery lives separately in UI_discovery_v1.pen (build_discovery.py).

Run:  python build_analyse_files.py
"""

from pen_kit import C, MONO, text, write_doc
import build_blocks as B

DOCS = [
    ("UI_analyse_chain_v1.pen", [
        ("1  ·  the chain — build it, or import a template", B.p_chain),
        ("2  ·  inserting a stage — the type contract", B.p_insert),
        ("3  ·  block 02  symbolic encoding", B.p_encoding),
        ("4  ·  block 04  drop detection", B.p_detection),
    ]),
    ("UI_analyse_interrogation_v1.pen", [
        ("1  ·  block ●  the family being analysed", B.p_family),
        ("2  ·  block 01  slope analysis", B.p_slope),
        ("3  ·  block 02  aggregate", B.p_aggregate),
    ]),
    ("UI_analyse_training_v1.pen", [
        ("1  ·  block 02  window matrix", B.p_matrix),
        ("2  ·  block 03  cluster", B.p_cluster),
        ("3  ·  block 04  encode", B.p_encode),
        ("4  ·  block 05  model", B.p_model),
    ]),
]

for path, spec in DOCS:
    screens, labels = [], []
    for i, (lab, fn) in enumerate(spec):
        s = fn()
        s["x"] = i * 1560
        screens.append(s)
        labels.append(text(lab, i * 1560, -46, 16, C["grey"], MONO))
    print("\n" + path)
    write_doc(path, screens + labels)
