#!/usr/bin/env python3
"""
Settings — five screens covering eight sections.

Contents matter more than layout here. The eight sections, and why each exists:

  Datasets            recordings and their metadata; the held-out lock; linked
                      recordings that must never be split across train and test
  Vocabulary          verdicts (names, keys, roles) and morphology tags. One
                      vocabulary across the human and machine stores, so a
                      rename rewrites both
  Analysis defaults   surrogate control, the matching rule, the seeded-search
                      exclusion zone, step cache, cluster routing
  Compute & HPC       SLURM job generation, guided parameters or raw template
  Storage             repository roots, naming convention, pull/push
  Export & reporting  motif and family catalogues; run reports for a paper
  Display             two plot profiles (across site, for report), units
  Interaction         keyboard map and the adjudication safety behaviours

Additions beyond the original list, each because it changes what a result means:
held-out lock, surrogate defaults, matching rule, step cache, batch-verdict
auto-advance.

Run:  python build_settings.py  ->  UI_settings_v1.pen
"""

from pen_kit import (C, MONO, SANS, frame, rect, ellipse, text, rtext, chip,
                     button, tw, write_doc)
from pen_widgets import wander, slider, selectbox, seg_control, toggle, stat
from build_blocks import card

MX, MW = 316, 1104          # main column
SECTIONS = [
    ("DATA", None),
    (None, "Datasets"),
    (None, "Vocabulary"),
    ("ANALYSIS", None),
    (None, "Analysis defaults"),
    (None, "Compute & HPC"),
    ("FILES", None),
    (None, "Storage & repository"),
    (None, "Export & reporting"),
    ("INTERFACE", None),
    (None, "Display"),
    (None, "Interaction"),
]


# ---------------------------------------------------------------- chrome
def nav_settings(h=900):
    kids = [rect(18, 18, 28, 28, C["blue"], radius=8)]
    for i in range(5):
        kids.append(rect(21, 170 + i * 46, 22, 22, C["muted"], radius=6))
    kids += [rect(21, h - 58, 22, 22, C["blue"], radius=6),
             rect(16, h - 74, 32, 1, C["border"])]
    return frame("sidebar", 0, 0, 64, h, C["white"], children=kids)


def head_bar(label, right=None, w=1376):
    kids = [rect(0, 43, w, 1, C["border"]),
            text("Signal", 24, 14, 15, bold=True),
            text("Settings", 92, 16, 13, C["grey"]),
            text(label, 164, 17, 11, C["muted"], MONO)]
    if right:
        kids.append(rtext(right, w - 24, 17, 11, C["grey"], MONO))
    return frame("header", 64, 0, w, 44, C["white"], children=kids)


def side_list(active):
    kids = [rect(235, 0, 1, 856, C["border"])]
    y = 20
    for group, item in SECTIONS:
        if group:
            kids.append(text(group, 20, y + 4, 9, C["muted"], MONO))
            y += 26
            continue
        on = item == active
        kids += [rect(12, y, 210, 32, C["tint"] if on else C["white"],
                      radius=7),
                 text(item, 26, y + 9, 11, C["blue"] if on else C["black"],
                      MONO)]
        y += 36
    kids += [rect(12, y + 14, 210, 1, C["border"]),
             text("changes apply on save", 26, y + 26, 9, C["muted"], MONO),
             text("nothing here writes until then", 26, y + 40, 9,
                  C["muted"], MONO)]
    return frame("section-list", 64, 44, 236, 856, C["white"], children=kids)


def sect(title, y, h, kids, sub=None, open_=True):
    head = [text("⌄" if open_ else "›", 18, 14, 13, C["grey"]),
            text(title, 40, 15, 13, C["black"], SANS, True)]
    if sub:
        head.append(text(sub, 40 + tw(title, 13) + 18, 18, 10, C["muted"], MONO))
    return card("sect/" + title, MX, y, MW, h, head + kids)


def collapsed(title, y, sub=None):
    kids = [text("›", 18, 12, 13, C["grey"]),
            text(title, 40, 13, 12, C["black"], MONO)]
    if sub:
        kids.append(rtext(sub, MW - 18, 15, 9, C["muted"], MONO))
    return card("collapsed/" + title, MX, y, MW, 40, kids)


def table(x, y, w, cols, widths, rows, rowh=26, size=10, colour_col=None):
    out = [rect(x, y, w, 1, C["border"])]
    cx = x
    for c, cw in zip(cols, widths):
        out.append(text(c, cx, y + 8, 9, C["muted"], MONO))
        cx += cw
    for i, r in enumerate(rows):
        yy = y + 26 + i * rowh
        if i % 2 == 0:
            out.append(rect(x - 6, yy - 5, w + 12, rowh, C["page"], radius=4))
        cx = x
        for j, (v, cw) in enumerate(zip(r, widths)):
            col = C["black"]
            if colour_col and j in colour_col and v in colour_col[j]:
                col = colour_col[j][v]
            if isinstance(v, tuple):
                out.append(ellipse(cx, yy + 3, 9, 9, v[1]))
                out.append(text(v[0], cx + 15, yy, size, col, MONO))
            else:
                out.append(text(v, cx, yy, size, col, MONO))
            cx += cw
    return out


def save_bar(n, note):
    kids = [ellipse(20, 22, 9, 9, C["amber"]),
            text("%d unsaved change%s" % (n, "" if n == 1 else "s"), 38, 18,
                 12, C["black"], SANS, True),
            text(note, 220, 21, 10, "#9A6206", MONO)]
    bx = MW - 20
    for lab, pri in [("Save changes", True), ("Discard", False)]:
        p, bw = button(lab, 0, 14, primary=pri, h=32)
        bx -= bw
        for nd in p:
            nd["x"] += bx
        kids += p
        bx -= 10
    return card("save-bar", MX, 820, MW, 60, kids)


def page(name, active, body, n_changes, note):
    return frame(name, 0, 0, 1440, 900, C["page"], children=[
        nav_settings(), head_bar(active), side_list(active)] + body +
        [save_bar(n_changes, note)])


# ================================================================ 1
def p_vocabulary():
    vk = [text("one vocabulary across the human and machine stores — no "
               "translation table exists, so none can drift", 18, 44, 10,
               C["grey"], MONO)]
    vk += table(18, 66, 1068,
                ["verdict", "key", "role", "in annotations", "in adjudications",
                 ""],
                [220, 70, 220, 180, 190, 180],
                [[("seed", C["blue"]), "S", "exemplar-worthy", "412", "96",
                  "edit  ·  remove"],
                 [("interesting", C["green"]), "I", "accept", "1,284", "2,140",
                  "edit  ·  remove"],
                 [("not_interesting", C["muted"]), "N", "reject", "3,901",
                  "5,772", "edit  ·  remove"],
                 [("artifact", C["red"]), "A", "flag", "211", "318",
                  "edit  ·  remove"],
                 [("unsure", C["amber"]), "U", "defer", "88", "144",
                  "edit  ·  remove"]])
    vk += [rect(12, 220, 1080, 1, C["border"]),
           text("+  add a verdict", 18, 232, 10, C["blue"], MONO),
           rect(18, 258, 1068, 62, "#FDF0D5", radius=7),
           text("editing  interesting", 30, 268, 11, C["black"], MONO),
           rect(180, 264, 200, 24, C["white"], radius=6, stroke=C["amber"]),
           text("noteworthy", 190, 269, 10, C["black"], MONO),
           text("key", 400, 270, 9, C["muted"], MONO),
           rect(428, 264, 44, 24, C["white"], radius=6, stroke=C["border"]),
           text("→", 440, 269, 11, C["black"], MONO),
           text("on save this rewrites 3,424 rows across both stores and "
                "every existing export keeps the old name", 30, 298, 10,
                "#9A6206", MONO),
           text("Removing a verdict that is in use asks where its rows should "
                "go — it never silently drops them.", 18, 334, 10,
                C["grey"], MONO)]
    body = [sect("Verdict vocabulary", 108, 366, vk,
                 sub="names, keys, roles · applies everywhere at once")]

    tk = [text("many-to-many on library entries, never a primary key — so a "
               "tag can be renamed or merged without touching family identity",
               18, 44, 10, C["grey"], MONO)]
    tk += table(18, 66, 1068, ["tag", "families", "members", "first used", ""],
                [260, 150, 150, 220, 280],
                [["sharkfin", "3", "412", "12 Aug 2026", "rename  ·  merge"],
                 ["spike-train", "2", "96", "19 Aug 2026", "rename  ·  merge"],
                 ["slow-drift", "4", "188", "21 Aug 2026", "rename  ·  merge"],
                 ["burst", "2", "77", "02 Sep 2026", "rename  ·  merge"],
                 ["plateau", "1", "26", "04 Sep 2026", "rename  ·  merge"],
                 ["biphasic", "3", "210", "09 Sep 2026", "rename  ·  merge"]])
    tk += [rect(12, 246, 1080, 1, C["border"]),
           text("+  add a tag", 18, 258, 10, C["blue"], MONO),
           rtext("merging two tags keeps both names as aliases so old exports "
                 "still resolve", 1086, 258, 9, C["muted"], MONO)]
    body.append(sect("Morphology tags", 490, 292, tk,
                     sub="the controlled vocabulary"))
    body += [collapsed("Analysis defaults", 798, "surrogate on · IoU 0.5")]
    return page("settings-1-vocabulary", "Vocabulary", body, 2,
                "renaming a verdict rewrites 3,424 rows")


# ================================================================ 2
def p_datasets():
    dk = table(18, 44, 1068,
               ["name", "file", "fs", "ch", "duration", "recorded", "species",
                "status"],
               [140, 250, 70, 50, 100, 110, 180, 168],
               [["M2_aug fs1", "M2_aug_concat_fs1.mat", "1 Hz", "16", "720 h",
                 "Aug 2025", "P. ostreatus", "in use"],
                ["M2_aug fs2", "M2_aug_concat_fs2.mat", "2 Hz", "16", "720 h",
                 "Aug 2025", "P. ostreatus", "linked to fs1"],
                ["M3_jul", "M3_jul_concat.mat", "1 Hz", "8", "280 h",
                 "Jul 2025", "G. lucidum", "in use"],
                ["M4_aug", "M4_aug_concat_fs1.mat", "1 Hz", "16", "300 h",
                 "Aug 2025", "H. erinaceus", "HELD OUT · locked"]])
    dk += [rect(12, 160, 1080, 1, C["border"])]
    p, bw = button("Import a recording", 18, 172, h=28)
    dk += p
    dk.append(text("M2 fs1 and fs2 are the same recording at two sample rates. "
                   "They are linked, and the runner refuses to split a linked "
                   "pair across training and test.", 180, 178, 10,
                   C["grey"], MONO))
    body = [sect("Recordings", 108, 212, dk, sub="4 recordings · 56 channels")]

    ek = [text("display name", 18, 48, 9, C["muted"], MONO),
          rect(18, 64, 300, 26, C["page"], radius=6, stroke=C["border"]),
          text("M2_aug fs1", 28, 70, 10, C["black"], MONO),
          text("species", 338, 48, 9, C["muted"], MONO),
          rect(338, 64, 300, 26, C["page"], radius=6, stroke=C["border"]),
          text("Pleurotus ostreatus", 348, 70, 10, C["black"], MONO),
          text("substrate", 658, 48, 9, C["muted"], MONO),
          rect(658, 64, 300, 26, C["page"], radius=6, stroke=C["border"]),
          text("hardwood sawdust block", 668, 70, 10, C["black"], MONO)]
    for i, (lab, val) in enumerate([("noise floor", "0.1 mV"),
                                    ("electrode config", "sub-dermal pairs"),
                                    ("temperature", "21.4 ± 0.8 °C"),
                                    ("humidity", "88 – 94 % RH")]):
        xx = 18 + (i % 4) * 320 if i < 1 else 18 + i * 240
        ek += [text(lab, 18 + i * 240, 104, 9, C["muted"], MONO),
               rect(18 + i * 240, 120, 220, 26, C["page"], radius=6,
                    stroke=C["border"]),
               text(val, 28 + i * 240, 126, 10, C["black"], MONO)]
    ek += [text("notes", 18, 160, 9, C["muted"], MONO),
           rect(18, 176, 700, 52, C["page"], radius=6, stroke=C["border"]),
           text("chamber door opened around 148 h — the step in CH4 at that "
                "point is almost certainly mechanical", 28, 184, 10,
                C["muted"], MONO),
           text("the amplitude excursion at 29 h has no lab-book entry",
                28, 200, 10, C["muted"], MONO),
           text("linked recordings", 750, 160, 9, C["muted"], MONO)]
    p, cw = chip("M2_aug fs2", 750, 176, True)
    ek += p
    ek += [text("never split across train and test", 750, 208, 9,
                C["amber"], MONO),
           text("noise floor gates the minimum detectable drop, so it belongs "
                "on the recording rather than in a chain — every detector "
                "reads it from here.", 18, 244, 10, C["blue"], MONO)]
    body.append(sect("Editing M2_aug fs1", 336, 278, ek,
                     sub="metadata travels with every export"))

    hk = [ellipse(18, 50, 10, 10, C["red"]),
          text("M4_aug is held out", 38, 46, 12, C["black"], SANS, True),
          text("the viewer and the runner both refuse it; the lock is what "
               "makes the methods claim true by construction rather than by "
               "memory", 200, 49, 10, C["grey"], MONO),
          text("unlock requires typing the recording name, and is recorded "
               "with a timestamp on the run log", 38, 74, 10, C["red"], MONO)]
    p, bw = button("Unlock for the freeze-day run", 1068 - 214 + 18, 42, h=28)
    hk += p
    body.append(sect("Held-out recording", 630, 108, hk, sub="one recording"))
    body.append(collapsed("Vocabulary", 754, "5 verdicts · 6 tags"))
    return page("settings-2-datasets", "Datasets", body, 3,
                "3 metadata fields edited on M2_aug fs1")


# ================================================================ 3
def p_analysis():
    ak = [text("surrogate control", 18, 46, 10, C["black"], MONO)]
    ak += toggle(180, 44, "on for every run", True)
    ak += [text("locked — default-on is what makes ‘every result has a "
                "null’ true in practice rather than merely likely",
                340, 46, 9, C["gink"], MONO)]
    ak += selectbox(18, 76, 200, "realisations", "19")
    ak += selectbox(238, 76, 200, "method", "phase randomisation")
    ak += selectbox(458, 76, 200, "seed", "fixed per recipe")
    ak += [rect(18, 148, 1068, 1, C["border"]),
           text("matching rule", 18, 160, 10, C["black"], MONO),
           text("decides what counts as the same event, so every precision "
                "figure is a function of it — recorded on each run",
                140, 161, 9, C["muted"], MONO)]
    ak += slider(18, 184, 200, "reciprocal overlap (IoU)", "0.50", 0.5)
    ak += slider(238, 184, 200, "onset tolerance", "0.25 × duration", 0.25)
    ak += slider(458, 184, 200, "seed search exclusion", "m / 2", 0.5)
    ak += [rect(18, 250, 1068, 1, C["border"]),
           text("step cache", 18, 262, 10, C["black"], MONO)]
    ak += slider(18, 286, 200, "write artifacts above", "2.0 s", 0.2)
    ak += [text("location", 238, 286, 9, C["muted"], MONO),
           rect(238, 302, 420, 26, C["page"], radius=6, stroke=C["border"]),
           text("./artifacts/steps", 248, 308, 10, C["black"], MONO),
           text("14.2 GB in use", 678, 308, 10, C["grey"], MONO)]
    p, bw = button("Clear cache", 900, 300, h=26)
    ak += p
    ak += [rect(18, 346, 1068, 1, C["border"]),
           text("cluster routing", 18, 358, 10, C["black"], MONO)]
    ak += slider(18, 382, 200, "promote cluster export above", "600 s", 0.4)
    ak += slider(238, 382, 200, "local concurrency", "2 runs", 0.2)
    ak += [text("above the ceiling, ‘export cluster job’ becomes the primary",
                458, 390, 10, C["muted"], MONO),
           text("action — local execution is demoted, not removed",
                458, 404, 10, C["muted"], MONO)]
    body = [sect("Analysis defaults", 108, 434, ak,
                 sub="these travel into every recipe hash")]

    ck = []
    p, gw = seg_control(18, 40, "job definition", ["guided", "raw template"],
                        "guided")
    ck += p
    ck.append(text("guided keeps the template valid; raw is there for "
                   "cluster-specific quirks the fields do not cover",
                   18 + gw + 24, 58, 10, C["muted"], MONO))
    for i, (lab, val) in enumerate([("account", "a_myco"),
                                    ("partition", "gpu_short"),
                                    ("gres", "gpu:1"), ("cpus", "8")]):
        ck += selectbox(18 + i * 268, 88, 240, lab, val)
    for i, (lab, val) in enumerate([("memory", "32 G"),
                                    ("time limit", "04:00:00"),
                                    ("array task limit", "16"),
                                    ("email on finish", "on")]):
        ck += selectbox(18 + i * 268, 148, 240, lab, val)
    ck += [rect(18, 210, 1068, 62, "#15161A", radius=6),
           text("#SBATCH --account=a_myco  --partition=gpu_short", 30, 220, 9,
                "#9CC4F0", MONO),
           text("#SBATCH --gres=gpu:1 --cpus-per-task=8 --mem=32G "
                "--time=04:00:00", 30, 236, 9, "#9CC4F0", MONO),
           text("python -m pipeline.run --recipe {{recipe}} "
                "--from-stage {{from}} --to-stage {{to}}", 30, 252, 9,
                C["trace"], MONO),
           text("preview, generated from the fields above", 18, 280, 9,
                C["muted"], MONO)]
    body.append(sect("Compute & HPC", 556, 302, ck, sub="SLURM job generation"))
    return page("settings-3-analysis", "Analysis defaults", body, 1,
                "IoU threshold changed — existing precision figures will "
                "recompute")


# ================================================================ 4
def p_storage():
    sk = []
    for i, (lab, path, act) in enumerate([
            ("recordings", "./data/recordings", "scan"),
            ("artifacts", "./artifacts", "scan"),
            ("window matrices", "./MATRICES", "scan · pull"),
            ("matrix profiles", "./PROFILES", "scan · pull"),
            ("models", "./MODELS", "scan · pull"),
            ("manifest inbox", "./cluster_out", "import")]):
        yy = 44 + i * 32
        sk += [text(lab, 18, yy + 6, 10, C["grey"], MONO),
               rect(160, yy, 560, 26, C["page"], radius=6, stroke=C["border"]),
               text(path, 170, yy + 6, 10, C["black"], MONO),
               text(act, 736, yy + 6, 10, C["blue"], MONO)]
    sk += [rect(18, 244, 1068, 1, C["border"]),
           text("naming convention", 18, 256, 10, C["black"], MONO)]
    cx = 180
    for tok in ["<recording>", "<channel>", "<fs>", "<window>", "<stride>",
                "<hash8>"]:
        p, cw = chip(tok, cx, 250, True)
        sk += p
        cx += cw + 6
    sk += [text("+ token", cx + 4, 256, 10, C["blue"], MONO),
           text("preview", 18, 292, 9, C["muted"], MONO),
           rect(180, 286, 560, 26, C["darker"], radius=6),
           text("M2_aug_fs1_CH4_1Hz_600s_300s_a7f39c.npz", 190, 292, 10,
                C["trace"], MONO),
           text("the hash is the recipe prefix — a file name",
                760, 286, 9, C["muted"], MONO),
           text("says which settings produced it",
                760, 298, 9, C["muted"], MONO)]
    body = [sect("Storage & repository", 108, 336, sk,
                 sub="where things are read from and written to")]

    ek = [text("motifs and families", 18, 46, 10, C["black"], MONO)]
    cx = 200
    for lab, on in [("xlsx catalogue", True), ("CSV", True),
                    ("JSON manifest", True), ("atlas plot PDF", True),
                    ("atlas plot SVG", False)]:
        p, cw = chip(lab, cx, 40, on)
        ek += p
        cx += cw + 6
    ek.append(text("include", 18, 82, 9, C["muted"], MONO))
    cx = 200
    for lab, on in [("medoid", True), ("all members", True), ("edges", True),
                    ("scope", True), ("tags", True), ("notes", False),
                    ("recipe hash", True)]:
        p, cw = chip(lab, cx, 76, on)
        ek += p
        cx += cw + 6
    ek += [text("one workbook for the catalogue, one sheet per family — or "
                "one file per family", 18, 114, 10, C["muted"], MONO),
           rect(18, 140, 1068, 1, C["border"]),
           text("run reports", 18, 152, 10, C["black"], MONO)]
    ek += table(18, 172, 1068, ["run", "chain", "when", "stages", ""],
                [120, 340, 180, 160, 268],
                [["131", "cluster_shapes_v3", "13 Sep 09:12", "6", "export"],
                 ["128", "drop_motifs9 + refine9", "12 Sep 17:40", "5",
                  "export"],
                 ["119", "sharkfin_v2 (banded)", "11 Sep 14:02", "5",
                  "export"]])
    ek += [text("layout", 18, 282, 9, C["muted"], MONO)]
    cx = 76
    for lab, on in [("one document, stages in sequence", True),
                    ("split — one file per stage", False)]:
        p, cw = chip(lab, cx, 276, on)
        ek += p
        cx += cw + 6
    ek += [text("each stage exports its plot with the parameters that produced "
                "it printed beneath, at figure resolution", 18, 310, 10,
                C["grey"], MONO),
           rect(18, 334, 300, 22, C["gtint"], radius=6),
           text("recipe hash + code version", 28, 338, 9, C["gink"], MONO),
           text("always included, not optional — an export that cannot be "
                "traced to a repository state is not evidence", 330, 338, 10,
                C["gink"], MONO)]
    body.append(sect("Export & reporting", 458, 374, ek,
                     sub="what leaves the tool"))
    return page("settings-4-storage", "Storage & repository", body, 2,
                "naming convention and export formats changed")


# ================================================================ 5
def p_display():
    dk = []
    p, gw = seg_control(18, 40, "profile", ["across site", "for report"],
                        "for report")
    dk += p
    dk.append(text("two independent sets of values — the screen can be dense "
                   "and dark while figures stay light and sparse",
                   18 + gw + 24, 58, 10, C["muted"], MONO))
    dk += slider(18, 96, 200, "trace line width", "1.2 pt", 0.3)
    dk += slider(238, 96, 200, "grid opacity", "0.15", 0.15)
    dk += selectbox(458, 92, 200, "panel background", "light")
    dk += selectbox(678, 92, 200, "palette", "colourblind-safe")
    dk += selectbox(18, 156, 200, "time axis", "hours")
    dk += selectbox(238, 156, 200, "amplitude axis", "mV")
    dk += selectbox(458, 156, 200, "figure font", "Inter")
    dk += selectbox(678, 156, 200, "export DPI", "300")
    dk += [text("time units apply site-wide,", 898, 160, 9, C["blue"], MONO),
           text("not only to plots — every", 898, 172, 9, C["blue"], MONO),
           text("readout follows this", 898, 184, 9, C["blue"], MONO),
           rect(18, 216, 1068, 96, C["white"], radius=6, stroke=C["border"]),
           text("preview", 30, 224, 9, C["muted"], MONO)]
    dk.append(wander(30, 240, 1040, 62, 4711, pts=300, amp=0.32, drift=0.18,
                     col="#1F6FB8", sw=1.2, wobble=21))
    body = [sect("Display", 108, 336, dk, sub="two plot profiles")]

    ik = [text("keyboard", 18, 46, 10, C["black"], MONO)]
    ik += table(18, 66, 520, ["action", "key"], [360, 160],
                [["next candidate", "→  or  space"],
                 ["previous candidate", "←"],
                 ["undo last verdict", "⌘ Z"],
                 ["open in Explore", "E"],
                 ["mark viewport reviewed", "R"],
                 ["toggle both rails", "\\"]])
    ik += [text("verdict keys are set in Vocabulary", 18, 244, 9,
                C["muted"], MONO),
           rect(580, 60, 1, 200, C["border"]),
           text("adjudication behaviour", 620, 46, 10, C["black"], MONO)]
    ik += toggle(620, 76, "auto-advance after a verdict", True)
    ik += toggle(620, 112, "auto-advance after a BATCH verdict", False)
    ik.append(text("off by default: a mis-keyed batch commits across every "
                   "member and moves on", 620, 138, 9, "#9A6206", MONO))
    ik += toggle(620, 166, "cluster-aware undo", True)
    ik.append(text("locked — one keystroke reverses a whole batch, not the "
                   "last write", 620, 192, 9, C["gink"], MONO))
    ik += toggle(620, 220, "confirm before discarding a run", True)
    body.append(sect("Interaction", 458, 292, ik,
                     sub="keys and the safety behaviours"))
    body.append(collapsed("Datasets", 766, "4 recordings · 1 held out"))
    return page("settings-5-display", "Display", body, 1,
                "report profile line width changed")


SCREENS = [("1  ·  vocabulary — verdicts and tags", p_vocabulary),
           ("2  ·  datasets — recordings and metadata", p_datasets),
           ("3  ·  analysis defaults and compute", p_analysis),
           ("4  ·  storage, export and reporting", p_storage),
           ("5  ·  display and interaction", p_display)]

screens, labels = [], []
for i, (lab, fn) in enumerate(SCREENS):
    s = fn()
    s["x"] = i * 1560
    screens.append(s)
    labels.append(text(lab, i * 1560, -46, 16, C["grey"], MONO))

write_doc("UI_settings_v1.pen", screens + labels)
