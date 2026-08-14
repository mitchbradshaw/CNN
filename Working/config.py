"""
config.py
==========
The one place tunable thresholds live, so changing a cutoff never means
hunting through unrelated modules. Nothing here does anything on its own —
these are just constants, imported by whichever module applies them
(`Working/database/bands.py`, `Working/database/similarity.py`, `UI/`).
"""

import os

# ── Duration / spike-train bands (Working/database/bands.py) ──────────────
#
# Both tables are (upper_bound, label) pairs consumed by `bands._band()`,
# which uses an INCLUSIVE upper bound (value <= bound -> that band) — the
# last entry's bound is unused, anything above the second-to-last bound
# falls there.
#
# event_count is an integer, so "short (<5)" / "medium (5-9)" / "long
# (10+)" is expressed as inclusive bounds one below each old exclusive
# cutoff (4 and 9, not 5 and 10) to keep the exact same buckets as the old
# `<`-based version — e.g. event_count=10 must stay "long" (10 < 10 was
# False under the old strict comparison, same as 10 <= 9 is False here).
SPIKE_TRAIN_BANDS = [
    (4, "short"),   # event_count <= 4  (i.e. < 5)
    (9, "medium"),  # 5-9 events
    (None, "long"), # 10+ events
]

# Duration is continuous (samples / fs), so there's no equivalent "shift by
# one" trick — instead the boundaries themselves are chosen so that no
# common annotation duration in this dataset sits on an edge. The dominant
# case by far is the imported 10-minute (600s) windows: 11,234 of 11,265
# annotations are exactly 600s. The old bounds (60, 600) put that entire
# class exactly ON the 600s edge, and combined with a strict `<` comparison
# that pushed literally all of them into "long" — see bands.py's docstring.
# 900s (not 600s) as the medium/long edge leaves 600s comfortably inside
# the "medium" band (60s < 600s <= 900s), 300s from either edge.
DURATION_BANDS_S = [
    (60, "short"),        # <= 1 min
    (900, "medium"),      # 1-15 min (600s / 10 min sits well inside)
    (3600, "long"),       # 15-60 min
    (21600, "very_long"), # 1-6 h
    (None, "extreme"),    # 6 h+
]

# ── Overlay density (UI/plots.py, Part 4b) ─────────────────────────────────
#
# Above this many rows, `build_annotation_ribbon` switches from one
# rectangle per annotation to a bucketed density ribbon — a channel can
# carry thousands of annotations, and drawing each as its own rectangle
# makes the pane unreadable well before counts reach that scale.
OVERLAY_DENSITY_THRESHOLD = 300
# Buckets spanning the annotation set's own [min_start, max_end] — same
# order of magnitude as the curve's own MAX_RENDER_POINTS, fine-grained
# enough that concentration patterns are still legible.
DENSITY_RIBBON_BUCKETS = 300

# ── Reviewed-coverage ribbon (UI/plots.py, Part 4c) ────────────────────────
#
# `build_reviewed_ribbon` buckets the channel and reports, per bucket, the
# TRUE fraction of that bucket's time actually covered by a reviewed span
# (via Working.database.queries.merge_intervals — the same merge the
# "reviewed: X%" summary figure uses, so the two can never silently
# disagree). A bucket at or above this fraction renders as "fully
# reviewed"; below it (but above 0), "partially reviewed" — a distinct
# colour, not an alpha blend, specifically so partial coverage can never
# be mistaken for full coverage at a glance. Buckets at exactly 0 render
# as an explicit gap colour, not "nothing drawn" — the whole point of this
# ribbon is that absence of coverage must be the obvious thing, especially
# since ~600-sample reviewed islands scattered across a multi-million-
# sample channel would otherwise visually merge into apparent continuous
# coverage at a coarse enough zoom, which is misleading in the worst
# direction (looks reviewed when it mostly isn't).
REVIEWED_FULL_COVERAGE_THRESHOLD = 0.95
REVIEWED_COVERAGE_BUCKETS = 300

# ── Ribbon panes — SEPARATE thin plots above/below the main curve, not
# overlays inside it (UI/plots.py, UI/app.py) ───────────────────────────────
#
# Superseded design (2026-08): the ribbons used to draw AS OVERLAYS on top
# of the main curve, positioned as a fraction of that frame's own
# y-range (`ANNOTATION_RIBBON_Y_FRACTION`/`REVIEWED_RIBBON_Y_FRACTION`,
# now retired). In practice a ribbon could go missing at some zoom levels
# — reported, but NOT reproduced by direct inspection of the actual
# rendered Bokeh y-range with and without the ribbon renderers present
# (`apply_ranges=False` was already correctly excluding them from
# auto-ranging; a hypothesized ribbon/auto-range circular dependency was
# tested directly and refuted — see UI/README.md). Whatever the exact
# cause, sharing an axis with the trace at all was the wrong design: a
# ribbon's position should never depend on what the SIGNAL happens to be
# doing. Ribbons now live in their own dedicated panes with a FIXED
# (0, 1) y-range that has nothing to do with the curve's axis, linked to
# the main plot only by x-range.
RIBBON_PANE_HEIGHT = 36  # px; small enough to read as a strip, not a second plot
# Same value applied to the main curve AND both ribbon panes so their
# plot FRAMES (not just their outer figures) start/end at identical pixel
# x-positions — the main risk with separate panes (Part A3). Chosen wide
# enough for the widest realistic y-tick label ("-0.098765" or similar)
# plus the rotated "amplitude" axis title on the curve; the ribbon panes
# don't need this space themselves (their y-axis is hidden) but must
# still RESERVE it, or their frames would start further left than the
# curve's and every bucket would be visibly offset from what it's
# annotating.
RIBBON_FRAME_MIN_BORDER_LEFT = 70
# Same value used for BOTH the curve and the ribbon panes' right border.
# The original design reserved EXTRA right-side space on the ribbon panes
# to compensate for the curve's toolbar, on the assumption the toolbar
# consumes frame width the ribbons don't have to. Measured directly
# against the real rendered page instead of assumed (Part A3): the
# curve's and ribbons' `<canvas>` elements come out pixel-identical in
# width regardless of toolbar_location — Panel/Bokeh render the toolbar
# as a widget outside the canvas, not by shrinking it — so the
# compensation was solving a problem that didn't exist and was actually
# introducing a real ~40px right-edge misalignment. Kept as a single
# shared constant specifically so this can't silently drift apart again.
CURVE_FRAME_MIN_BORDER_RIGHT = 12
RIBBON_FRAME_MIN_BORDER_RIGHT = 12

# Ribbons no longer draw over the trace, so the old "low enough that the
# trace stays readable through it" alpha ceiling no longer applies — a
# dedicated pane can afford to be much more visually definite.
RIBBON_ALPHA = 0.85

# A flat, colour-neutral tint drawn UNDER every ribbon bucket/individual
# annotation rectangle, spanning the FULL pane regardless of data —
# without it, an empty stretch (no annotations/reviewed spans in view)
# would render as blank space indistinguishable from "this pane is
# broken", rather than "correctly showing nothing is here" (Part B1,
# 2026-08). Always present (never conditionally omitted) so it can't
# create a DynamicMap type-consistency gap across frames.
RIBBON_LANE_BACKGROUND_COLOR = "#000000"
RIBBON_LANE_BACKGROUND_ALPHA = 0.045

# ── Zoom presets (UI/app.py, Part E2) ──────────────────────────────────────
#
# Fixed viewport widths, in seconds — one click, exactly reproducible,
# since switching timescale (the research question this whole app serves)
# must never depend on eyeballing a scroll-wheel zoom.
ZOOM_PRESETS_SECONDS = [
    ("1 min", 60),
    ("10 min", 600),
    ("1 h", 3600),
    ("6 h", 21600),
    ("24 h", 86400),
]

# ── Session persistence (UI/app.py, Part E9) ───────────────────────────────
#
# Remembers the last-viewed recording/channel/viewport/filters/toggles and
# restores them on reopen — a plain JSON file (not a DB table) since it's
# pure UI/session state, not data.
SESSION_STATE_PATH = os.path.join("DATA", "db", "ui_session.json")

# ── Run algorithm tab (UI/run_panel.py, Part 5) ────────────────────────────
#
# One height for the pre-run "staged span" preview AND each Before/After
# panel (Part 5 Section A/B) — the preview IS the "Before" of whatever
# hasn't run yet, so giving it a different height would make the panel
# visibly resize the moment a run finishes, for no reason.
RUN_PREVIEW_HEIGHT = 200

# ── Encoding inspection view (UI/plots.py, UI/run_panel.py, Part 6) ────────
#
# Above this many symbols currently in view, the symbol strip (panel 4)
# renders colour only — drawing a `hv.Text` glyph per cell for, say, 6,275
# visible symbols is both unreadable and slow. Below it, each cell gets
# its letter.
ENCODING_LETTER_THRESHOLD = 120
# Heights for the four stacked encoding panels (Part 7, 2026-08: raised —
# this tab's whole point is to read these panels, and they were shorter
# than the pre-run preview above them). Panel 4 (the symbol strip) stays
# deliberately shorter than the rest, matching the ribbon panes' "compact
# strip, not a second plot" convention; Quantisation gets the most of any
# panel since it must show up to 16 labelled bands legibly.
ENCODING_SIGNAL_HEIGHT = 220
ENCODING_PAA_HEIGHT = 220
ENCODING_QUANT_HEIGHT = 320
ENCODING_STRIP_HEIGHT = 60
# Left/right frame border for ALL FOUR encoding panels (Part 7, Part 1
# item 4) — one shared value, like RIBBON_FRAME_MIN_BORDER_LEFT/RIGHT,
# so differing y-tick-label widths across panels (amplitude ranges here
# can differ by orders of magnitude between panels) never shift where
# each panel's plot frame starts. Wider than the ribbon panes' 70px
# since these panels show negative, multi-decimal amplitudes (e.g.
# "-0.098765") rather than the ribbons' hidden y-axis.
ENCODING_FRAME_MIN_BORDER_LEFT = 90
ENCODING_FRAME_MIN_BORDER_RIGHT = 20
# The full symbol string display (Part 6 3c) defaults to "Visible range
# only" above this length — a 6,275-symbol string is unreadable rendered
# in full, and recomputing it on every keystroke of a zoom is wasted work
# nobody's looking at anyway.
ENCODING_STRING_INLINE_THRESHOLD = 500
# A reused encoding run is cheap to recompute (fractions of a second even
# at ~63k samples) below this span length — above it, show the cached
# symbol string only, without the detail panels, rather than silently
# eating a multi-second recompute the user didn't ask for right now.
ENCODING_RECOMPUTE_MAX_SAMPLES = 2_000_000
# "Auto-preview on parameter change" (Part 6, 4c) defaults ON below this
# span length (a live preview recompute is near-instant) and OFF above it
# (where it would otherwise silently eat CPU on every keystroke).
AUTO_PREVIEW_SPAN_THRESHOLD = 200_000
AUTO_PREVIEW_DEBOUNCE_MS = 400

# ── Readability (UI/app.py, UI/plots.py, UI/run_panel.py, Part 7) ──────────
#
# Panel's own default body text is ~12px — too small to read comfortably
# for a data-dense app used for long stretches. Applied app-wide via one
# raw_css/stylesheet block (`UI/app.py`), not scattered per-widget, so
# there is exactly one place to retune it. Tabulator does NOT inherit
# Panel's font sizing (it renders inside its own shadow DOM), so it needs
# its own explicit rule wherever a Tabulator is built.
UI_BASE_FONT_SIZE = "14px"
UI_TABLE_FONT_SIZE = "13px"
UI_MONO_FONT_SIZE = "13px"    # the symbol string / RLE boxes
# Bokeh plot text — applied via the `fontsize=` opts dict on every plot
# this codebase builds (the main curve, the cross-channel peek, and all
# four encoding panels), not just the newest ones, so the whole app reads
# consistently rather than the encoding tab looking like a different
# application from the Viewer.
PLOT_TITLE_FONT_SIZE = "15px"
PLOT_LABEL_FONT_SIZE = "13px"
PLOT_TICK_FONT_SIZE = "12px"

# ── Matrix profile (Working/Detection/matrix_profiling/, Working/database/
# matrix_profile_store.py, Adapters/detection_matrix_profile.py) ──────────
#
# See MATRIX_PROFILE_UI_PROMPT.md §0: a matrix profile at one window length
# is NOT interpolable to another — different query, different
# normalisation, different distance units. This ladder is a fixed set of
# independently-computed scales, not a resolution hierarchy. Values are in
# MINUTES (not samples) specifically so the same ladder means the same
# thing regardless of `fs` — `m` is always derived, never stored as the
# primary key.
MP_SCALE_LADDER_MIN = (1, 10, 60, 600)

# stumpy's own floor (`m >= 4`) and the point below which the exclusion
# zone (`m // 2` either side of a match) leaves almost nothing in a span
# to match against. A ladder entry failing this check is "invalid" for a
# given span, not "missing" — the UI must show why, not offer a Compute
# button that would just fail inside stumpy.
MP_MIN_WINDOW_SAMPLES = 4
MP_MAX_WINDOW_SPAN_FRACTION = 2  # m <= n // this

# ── Matrix profile cost / execution routing (Working/Detection/
# matrix_profiling/cost.py, Working/execution.py) ─────────────────────────
#
# stump is O(n^2/T) in series length and effectively flat in m (the
# sliding dot-product update is incremental), so a single calibrated
# constant per backend (t_est(n) = k_backend * n**2) is enough to route a
# job before running it. Three tiers, per MATRIX_PROFILE_UI_PROMPT.md §3.2:
MP_INTERACTIVE_BUDGET_S = 60    # <= this: run inline, blocking, progress bar
MP_BACKGROUND_BUDGET_S = 900    # <= this: background thread + cancel;
                                 #  > this: HPC export only

# ── HPC export (Working/hpc/job_export.py) ─────────────────────────────────
#
# `HPC/README.md` records that `--chdir` disagrees between hand-written job
# scripts (`/home/s4699158/CNN` in score_job.sh vs
# `/home/Student/s4699158/CNN` in wm_job.sh and mp_job.sh). mp_job.sh — the
# one actually relevant to matrix-profile HPC jobs — already uses the
# `/home/Student/...` form, so that's the value taken here; flagged in
# MATRIX_PROFILE_UI_PROMPT.md's implementation notes as worth confirming
# against the real SLURM account before the first generated job is submitted.
HPC_REMOTE_REPO_ROOT = "/home/Student/s4699158/CNN"

# ── Motif browser (UI/motif_browser.py) ─────────────────────────────────────
#
# Top pane (full channel + occurrence markers) is taller than the bottom
# one (relative-time waveform overlay) — matches the Encoding view's
# convention of giving the "main" panel more room than a supporting one.
MOTIF_TOP_HEIGHT = 320
MOTIF_BOTTOM_HEIGHT = 280
# max_motifs default: NOT 1000 (the slide's original value) -- a 1000-motif
# precompute is a long, visible-cost operation; 50 is enough to browse
# comfortably and keeps "just opened the tab" fast (MATRIX_PROFILE_UI_PROMPT.md
# §6.3).
MOTIF_DEFAULT_MAX_MOTIFS = 50
MOTIF_DEFAULT_N_NEIGHBORS = 10

# ── Window matrix (Working/Preprocessing/window_matrix/, Working/database/
# window_matrix_store.py, Adapters/preprocessing_window_matrix.py) ─────────
#
# See WINDOW_MATRIX_UI_PROMPT.md §0.1: a window matrix at one timescale is
# NOT derivable from another. Almost none of the 33 measures aggregate —
# sample entropy of a 60-minute window is not any function of the sample
# entropies of the six 10-minute windows inside it, because the
# template-matching count that defines it ranges over the whole window and
# the cross-boundary pairs at 60 minutes have no representative at 10. The
# same holds for every Catch22 feature, for permutation/SVD entropy (both
# embed vectors that straddle sub-window boundaries), and for the Gramian
# images behind the CNN scores.
#
# VALUES are deliberately identical to MP_SCALE_LADDER_MIN so a user
# comparing a matrix profile at 10 minutes against a window matrix at 10
# minutes is comparing the same span of signal. It is a SEPARATE constant
# because the two ladders' VALIDITY rules differ (below), and because a
# future divergence must not be a silent edit to the MP ladder.
WM_SCALE_LADDER_MIN = (1, 10, 60, 600)

# Unlike MP_MIN_WINDOW_SAMPLES (4, which is stumpy's own array-length
# floor), this floor is set by the measures being DEFINED rather than the
# call not crashing: permutation entropy at order=3 technically runs at
# m=4 but means nothing; a periodogram over 15 samples has 8 bins; Catch22
# has its own internal minima. 32 is the point above which every measure
# in the set returns something interpretable. A ladder entry below this is
# "invalid" for a given fs, not "missing" — at fs=0.25 the 1-minute entry
# is m=15 and the ladder is genuinely shorter, which the UI must explain
# rather than offer a Compute button for.
WM_MIN_WINDOW_SAMPLES = 32

# Below this many windows there is no matrix, just a few rows —
# preprocess_window_matrix would drop most columns as constant and any
# clustering on the result is meaningless. Has no matrix-profile analogue
# (an MP is perfectly happy on a short series).
WM_MIN_WINDOWS = 3

# ── Per-measure scale limits (WINDOW_MATRIX_UI_PROMPT.md §3.3) ─────────────
#
# A ladder scale can be valid for SOME measures and not others — the
# finer-grained analogue of the matrix profile's all-or-nothing "invalid"
# state. Above these window lengths the affected columns are UNAVAILABLE
# at that scale: written with computed=False, reported by ladder_status,
# and named in the UI. Not slow, not failed — unavailable.
#
# Sample and approximate entropy are O(m^2) per window. At m=600 (10 min
# at fs=1) that is already the dominant stage; at m=36000 (600 min) it is
# 1.3e9 operations per window.
WM_SLOW_ENTROPY_MAX_SAMPLES = 4096
# The Gramian encodings behind the CNN scores are O(m^2) in MEMORY (a GASF
# image is an m x m matrix before the resize to 224x224). This MUST equal
# the `MAX_SPAN_SAMPLES` the catalogue_gramian_* adapters declare as their
# own max_span_samples — it is the same physical limit, and a window matrix
# that accepted a window those adapters would refuse would just fail inside
# them. It is duplicated as a literal rather than imported because
# `Working/config.py` must not depend on `Adapters/`;
# `tests/test_window_matrix_store.py` asserts the two agree, so the
# duplication cannot drift silently.
WM_GRAMIAN_MAX_SAMPLES = 5000

# ── Window matrix cost / execution routing (Working/Preprocessing/
# window_matrix/cost.py) ───────────────────────────────────────────────────
#
# The shape here is the OPPOSITE of the matrix profile's: linear in the
# number of windows, strongly super-linear in m per window, with the
# exponent differing by stage (m log m for Catch22/fast entropy, m^2 for
# slow entropy and Gramian construction). So a single constant per backend
# is not enough — see cost.py. Same three tiers, own constants, because
# the two workloads are not comparable.
WM_INTERACTIVE_BUDGET_S = 60    # <= this: run inline, blocking, progress bar
WM_BACKGROUND_BUDGET_S = 900    # <= this: background thread + cancel;
                                #  > this: HPC export only

# ── Window matrix coverage ribbon (UI/plots.py, UI/window_matrix_panel.py)
#
# One `hv.Rectangles`-bucketed ribbon pane per ladder scale that has any
# stored coverage, same bucketing machinery as the reviewed-coverage ribbon
# (`build_reviewed_ribbon`) applied to `window_matrix_store.
# coverage_by_completeness` instead of reviewed spans. Defaulted to
# REVIEWED_COVERAGE_BUCKETS's value rather than a new number: both ribbons
# bucket the SAME x-range (the current viewport) for the SAME reason
# (per-bucket fractional coverage, not a raw per-row rectangle), so there is
# no basis yet for a different resolution — kept as its own constant (not a
# reused import of REVIEWED_COVERAGE_BUCKETS) because the two ribbons answer
# unrelated questions and must be free to diverge later without one edit
# silently retuning the other.
WM_COVERAGE_RIBBON_BUCKETS = 300

# ── Near-duplicate similarity (Working/database/similarity.py) ────────────
#
# Two spans count as near-duplicates when their interval IoU exceeds
# SIMILARITY_IOU_THRESHOLD *and* their widths are within
# SIMILARITY_WIDTH_RATIO_THRESHOLD of each other (the wider divided by the
# narrower) — IoU alone can't distinguish "same span, twice" from "one span
# almost entirely contains a much shorter one", which the width-ratio check
# catches.
SIMILARITY_IOU_THRESHOLD = 0.8
SIMILARITY_WIDTH_RATIO_THRESHOLD = 1.5
