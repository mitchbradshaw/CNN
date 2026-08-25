# UI/

**The signal viewer and annotation tool.** The only place in this repo that
imports Panel, HoloViews or Datashader — everything in `Working/` and
`Pipelines/` must stay runnable headless on the SLURM cluster. The UI adapts
to the analysis code, never the reverse: it only ever calls into
`Working.database.queries` / `vocabulary` / `bands` / `runs` / `similarity`,
the same plain-function API a headless script would use.

## Running it

```bash
panel serve UI/app.py --show
# or
python UI/app.py
```

Requires `panel`, `holoviews`, `datashader`, `bokeh` (not in the root
requirements list yet — install alongside the stage you need, per the root
README). Also requires the database to be populated first:

```bash
python Pipelines/materialize_channels/materialize_channels.py
python Pipelines/import_labels/import_10min_labels.py
```

## Visual verification during development

Several bugs in this module (ribbons floating away from the visible axis,
a sidebar overflowing into the main column, a table pin marker not
appearing) only showed up when actually rendered — reading the code, or
even a headless HoloViews/Bokeh model inspection, missed them. For any
change to layout, overlay geometry, or CSS, verify with a real browser
screenshot, not code inspection alone.

**One-time setup** (not a project dependency — a local dev tool, installed
per-machine):

```bash
python -m pip install --user playwright
python -m playwright install chromium
```

**Pattern for a screenshot check** (adjust the specifics per what you're
verifying):

```python
import shutil, panel as pn, holoviews as hv
hv.extension("bokeh")
import Working.config as config
config.SESSION_STATE_PATH = "/scratch/path/session.json"  # BEFORE importing UI.app
import UI.app as appmod
from bokeh.io import save as bokeh_save
from bokeh.resources import INLINE
from playwright.sync_api import sync_playwright

shutil.copyfile("DATA/db/annotations.sqlite", "/scratch/path/copy.sqlite")  # NEVER the real DB
app = appmod.ViewerApp(db_path="/scratch/path/copy.sqlite")
app.source_file, app.channel = "M2_aug_concat_fs1.mat", 0
app._range_stream.event(x_range=(12000, 12600))   # drive state directly, no mouse simulation
app._refresh_view()

renderer = hv.renderer("bokeh")
plot = renderer.get_plot(app.plot_pane.object)
plot.refresh()          # re-evaluate from the CURRENT stream state --
                         # a `plot` fetched before a state change goes stale otherwise
bokeh_save(plot.state, filename="/scratch/path/out.html", resources=INLINE)

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1100, "height": 500})
    page.goto("file:///scratch/path/out.html")
    page.wait_for_timeout(300)
    page.screenshot(path="/scratch/path/out.png")
    browser.close()
```

For verifying the FULL Panel layout (not just one plot — sidebar
structure, accordions, table), call `app.layout()` and either (a) run a
real `pn.serve(...)` in the background and point Playwright at
`http://localhost:PORT/`, or (b) `tabs.save(out_html, resources=INLINE,
embed=False)` for a quicker static render (`embed=True` is NOT viable
here — it tries to enumerate every possible widget-state combination and
runs out of memory on an app with this many interactive widgets).

Never point any of this at `DATA/db/annotations.sqlite` or
`DATA/db/ui_session.json` — always a scratch copy, per the project's
never-touch-the-real-DB rule.

## Layout

```
app.py          Panel entry point — the ViewerApp param.Parameterized class:
                widgets, callbacks, and the layout. Owns the database
                connection. Also hosts the "Viewer" tab; the other tabs
                below are separate classes it composes.
plots.py        Pure HoloViews/Datashader construction — no Panel, no
                database calls. Builds the zoom-driven rasterized curve and
                every overlay (annotations, reviewed coverage, detections,
                pending selection, cross-channel peek).
admin.py        "Vocabulary admin" tab — add/deactivate controlled-
                vocabulary terms (element/quality/structure/provenance/
                status) without editing the database by hand.
file_import.py  "Import recording" tab — materialize a new .mat/.npy file
                into the database without leaving the UI.
run_panel.py    "Run algorithm" tab — configure and launch a
                Working/Pipelines analysis recipe against the current
                recording/span, tracked in the `runs`/`configs`/
                `detections` tables.
analyse/history.py  Analyse's run-history sidebar (ticket 34) — browse past
                runs, reopen one's chain in the chain builder, see artifacts.
```

## How the plot stays responsive and honest

A channel is 1-5M+ samples. `plots.build_channel_dmap` drives a
`hv.DynamicMap` off a `hv.streams.RangeX` stream: each callback slices the
`np.load(..., mmap_mode='r')`'d channel to just the currently visible span
(only that span pages in off disk) and hands the slice to `rasterize` — not
`datashade`, so aggregated values stay inspectable rather than being baked
into a fixed RGB image. At full zoom-out the slice is the whole channel; at
high zoom it's small and effectively shows every sample.

Annotations and reviewed spans are drawn as `hv.Rectangles` — **one
vectorized element per group** (imported vs manual), not one HoloViews
element per row. A channel can carry hundreds to thousands of annotations,
and overlaying that many individual elements (the first version of this used
`hv.VSpan` per row) makes HoloViews' internal path de-duplication
pathologically slow — a confirmed multi-minute hang building the Bokeh
model for ~700 elements. Vectorized `Rectangles` with a `verdict` value
dimension renders in well under a second regardless of row count.

Every `DynamicMap` callback in this codebase (main curve, the two ribbon
panes, selected-annotation highlight, detections, pending selection,
cross-channel peek) is written to return the *same HoloViews element type*
on every frame, no matter which code path it takes. Mixing element types
across frames makes HoloViews raise an `AssertionError` deep in Bokeh's
model-diffing that Panel swallows silently, leaving the plot pane simply
blank with no visible error — this has happened once already in this
codebase (the annotation ribbon vs. individual-rectangles switch) and is
the reason every overlay builder in `plots.py` always returns an
`Overlay`-of-`Rectangles`, never a bare `Rectangles` in one branch and an
`Overlay` in another.

## Visual encoding

- **Colour** = verdict (green interesting / gray not-interesting / red
  artifact / purple unsure).
- **Alpha + border** = source — imported annotations are low-alpha with no
  border; manual ones are higher-alpha with a black border.
- A dashed outline = the current drag-selected span, pending save.

### Density ribbons (SEPARATE panes, not overlays inside the plot)

**Architecture (Part A, 2026-08 restructure).** The reviewed-coverage and
annotation-density ribbons are each their own small, fixed-height (`
RIBBON_PANE_HEIGHT`, `Working/config.py`) Bokeh pane — reviewed-coverage
directly ABOVE the main curve, annotation-density directly BELOW it —
not overlays drawn inside the main plot. Each pane has a FIXED, fake
`(0, 1)` y-range with the y-axis hidden, no toolbar, and no title; the
main curve is the only interactive plot in the stack and the only one
with a visible x-axis. The panes are linked to it by x-range alone: each
is a `hv.DynamicMap` driven by the same `RangeX` stream as the curve, so
panning/zooming the curve moves the ribbons in lock-step, but dragging
inside a ribbon pane does nothing (it has no tools of its own).

**Why this replaced the earlier overlay design.** Ribbons used to draw
*on* the curve, positioned as a fraction of that frame's own y-range. In
practice a ribbon could occasionally go missing at some zoom levels. The
suspected cause — a circular dependency where Bokeh's y-auto-ranging
accounted for the ribbon glyphs, so ribbon position and axis range each
depended on the other — was tested directly (the curve's real rendered
y-range compared with and without the ribbon renderers present) and
**refuted**: `apply_ranges=False` was already correctly excluding every
overlay from that computation. The exact disappearance was not
reproduced by direct inspection either. Regardless, sharing an axis with
the trace at all was the wrong design — a ribbon's position should never
depend on what the signal happens to be doing — so the fix is
architectural, not a tighter version of the same coupling: separate
panes with a y-range that has nothing to do with the curve's make the
whole class of bug structurally impossible rather than merely rare.

**Alignment risk.** Three separate Bokeh figures stacked in a column
don't automatically line up — differing y-axis tick-label widths (the
curve has one, the hidden-axis ribbon panes don't) shift where each
figure's actual plot FRAME starts. Fixed via matching `min_border_left`/
`min_border_right` (`RIBBON_FRAME_MIN_BORDER_LEFT/RIGHT`,
`CURVE_FRAME_MIN_BORDER_RIGHT`) applied through a Bokeh `hooks=` callback
(`min_border_*` has no direct `.opts()` equivalent). One subtlety: a hook
attached to the curve ELEMENT alone is silently dropped once it's
combined with other `hv.DynamicMap`s into the final main-plot overlay
(confirmed directly) — `UI/plots.py`'s `style_main_plot_frame` applies it
to the finished combined overlay instead, which is the only place it
reliably reaches the shared figure. Verified by measuring the actual
rendered `<canvas>` bounding boxes (inside Bokeh's shadow DOM) via a real
browser: all three panes' frames are pixel-identical.

**x-range linking (Part A, second 2026-08 round).** Sharing the curve's
`RangeX` stream as an extra stream on the ribbon `DynamicMap`s is not, by
itself, enough to keep a ribbon pane's rendered axis in sync with the
curve on every pan/zoom. `RangeX(source=X)` has built-in two-way sync
only with the figure `X` it was originally constructed from; used as a
plain listener on a *different* figure it correctly triggers that
figure's callback to re-run (so the bucket DATA is recomputed for the new
viewport) but does not reliably push the resulting `xlim` opt into that
figure's actual Bokeh `x_range` model past the DynamicMap's first
rendered frame — confirmed directly with a persistent plot object
refreshed repeatedly, matching how a live Panel session behaves. The
symptom: a ribbon's glyphs render at the right width for the current
viewport, but against an axis still pinned to whatever range was current
when the pane was first built, so panning/zooming the curve visibly
decouples the ribbons from it. The fix, in `UI/plots.py`'s
`_set_x_range`, is a `hooks=` callback that sets
`plot.state.x_range.start`/`.end` directly on every refresh, bypassing
HoloViews' range-update pipeline entirely. `tests/test_ribbon_panes.py`
pins this by creating the three plot objects once and refreshing the same
objects across a simulated pan/zoom sequence — recreating a fresh
`get_plot()` after every event (an earlier version's approach) only ever
exercises "first frame" behaviour and silently passes even when this bug
is present, so that pattern must not be reintroduced.

**y-range linking is document-wide, not Layout-scoped (Part 7, 2026-08).**
The encoding view's four panels (`UI/plots.py`'s `build_encoding_panels`)
hit a Y-axis analogue of the x-range bug above, plus a second, distinct
mechanism that the Before/After section's existing note (below) doesn't
fully cover. Two things were confirmed directly, via the live browser's
own Bokeh model state (`Bokeh.documents[...].y_range.id`), not just
suspected:

1. **`axiswise=True` must be set on every LEAF element, not just an
   enclosing `Overlay`.** The PAA and Quantisation panels each wrapped
   several elements (a background curve, bars, boundary lines, band
   `HSpan`s, cutline `HLine`s, a step curve, labels) in `hv.Overlay(...).
   opts(hv.opts.Overlay(axiswise=True, ...))` — `axiswise=True` at the
   Overlay level only. That was NOT enough: the two panels' figures ended
   up sharing the literal same `Range1d` Python/JS object with each other
   (confirmed by comparing `y_range.id` across figures), so each one's
   hook-driven range update clobbered the other's on every refresh. Only
   `_panel_signal`'s bare `Curve` — no `Overlay` wrapper, `axiswise=True`
   set directly on itself — was ever actually protected. Fix: `axiswise=
   True` on every individual leaf element's own `.opts(...)` call.
2. **The linking is NOT scoped to one `hv.Layout` or one `pn.pane.
   HoloViews`** — it reaches across entirely separate panes in the same
   Bokeh document. `UI/plots.py`'s `_decimated_curve` (backs the "staged
   span, not yet processed" preview AND the cross-channel peek) shares
   this module's "amplitude" vdim name and had no `axiswise` at all; its
   own never-changing raw-scale range kept winning the shared `Range1d`
   back from the encoding panels' correctly-recomputed, much narrower
   one, even though that curve lives in a completely different
   `pn.pane.HoloViews` with no Layout relationship to the encoding
   section whatsoever.

Symptom of both, together: with a preprocessing transform active, the
PAA and Quantisation panels' TITLES showed the correct tiny recomputed
range (computed from the same `yr` value used everywhere else) while
their RENDERED axes stayed pinned to the old raw-signal scale, drawing
the transformed data as a flat line pinned near the old zero — easy to
mistake for "the transform isn't being applied" when it actually was;
only the axis was stale. `UI/plots.py`'s `_set_y_range` hook (the Y
analogue of `_set_x_range`) is kept as defense in depth on top of the
`axiswise=True` fix, for the same reason `_set_x_range` is needed
alongside `xlim`/`framewise=True`: even a correctly-unshared `Range1d`
still needs its `.start`/`.end` forced past the first frame.
`tests/test_encoding_panels.py` cannot see this class of bug through
Python-level range/opts inspection alone — it was only caught by
inspecting the actual rendered Bokeh model in a real browser session; a
future regression here would most reliably resurface the same way.

**Density ribbon.** Above `OVERLAY_DENSITY_THRESHOLD` annotations
currently in view, individual verdict-coloured rectangles are replaced by
a bucketed density ribbon — darker/more saturated where more annotations
overlap that time bucket. `Show annotation density ribbon`
(`show_annotation_ribbon_toggle`) does NOT hide the pane — it controls
whether bucketing kicks in at all above the threshold (off = always
render individual rectangles, for precise inspection at the cost of
possible slowness); `Show annotations` (`show_annotations_toggle`) is
what shows/hides the pane itself, collapsing it entirely (no empty strip
left behind) rather than just feeding it empty data.

**Reviewed-coverage ribbon.** Three flat colours (not a gradient) per
bucket: fully reviewed (≥`REVIEWED_FULL_COVERAGE_THRESHOLD`), partially
reviewed, or an explicit gap colour for zero coverage — a gradient was
deliberately rejected because sparse reviewed islands would otherwise
visually blur into "looks mostly reviewed" at a coarse enough zoom, which
is misleading in the worst direction. `Show reviewed-coverage ribbon`
(`show_reviewed_ribbon_toggle`) shows/hides its pane directly (there's no
sub-mode toggle here, unlike the density ribbon). The "reviewed: X%"
summary figure and the ribbon are computed from the exact same
interval-merge logic (`Working.database.queries.merge_intervals`), so
they can never disagree.

**Both ribbons bucket over whatever time span is currently in view** on
every pan/zoom (not just when the whole channel is visible) — recomputed
via the same `RangeX` stream that drives the curve.

**The lane itself is visually distinct from the data drawn in it**: a
flat, colour-neutral background tint (`RIBBON_LANE_BACKGROUND_COLOR`/
`_ALPHA`) is always drawn first, underneath every bucket/individual
rectangle, spanning the pane's full width and height regardless of
whether there's data at that position — without it, an empty stretch (no
annotations/reviewed spans in view) would render as blank space
indistinguishable from a broken pane.

**Hovering a ribbon bucket shows what's in it** — the density ribbon
reports the verdict and count of annotations in that bucket; the
reviewed-coverage ribbon reports the exact coverage percentage (not just
which of the three fixed tiers it fell into). At coarse zoom the ribbon
is the only readable summary, so being able to interrogate a bucket
without zooming in first is worth having.

## Viewer tab layout

The left sidebar holds only: a collapsed **Keyboard shortcuts** accordion,
**Recording** (source file/channel/time-unit/view controls/zoom presets),
an EXPANDED-by-default **Summary** accordion (verdict counts + reviewed
%), **Annotation navigator**, and **New annotation**. A collapsed
**Verdict colour key** accordion sits at the top of the main column.
Each accordion's open/closed state persists across restarts (Part E9,
see Session persistence below). **Selected annotations** (selection
count, Zoom to selected, Run algorithms on selected, and the whole Bulk
operations block) sits directly *beneath* the annotations table in the
main column, not in the sidebar — it acts on whatever's selected in the
table/plot, so it reads more naturally next to it.

Any row of fixed-width buttons in the 340px sidebar (the zoom presets,
the two "clear selection" buttons) uses `pn.FlexBox`, not `pn.Row` —
`Row` does not wrap, so buttons that don't fit rendered PAST the
sidebar's right edge and visually collided with whatever the main column
had at that height (a real bug: this is what made the zoom presets look
"truncated after 6h" and produced stray/overlapping text near unrelated
controls). The sidebar column also sets `overflow-x: hidden` as a
backstop, so a future addition that doesn't fit can't silently repeat
this by bleeding into the main column instead of visibly wrapping or
clipping in place.

## Drag modes

One `RadioButtonGroup` (**Pan** / **New span** / **Select annotations**)
controls what a click-drag on the plot does — Bokeh only ever has one
active drag tool, so this makes the current meaning of a drag unmistakable
instead of two overlapping toggles that could combine into a nonsensical
state. The current mode is restated as a sentence with its own
mode-coloured background directly under the buttons (gray/blue/yellow) —
the RadioButtonGroup's own highlighting is easy to miss mid-workflow, and a
wrong-mode drag fails *silently* (no error, just the wrong effect).

- **Pan** — drag pans the view (Bokeh's x-pan tool).
- **New span** — drag creates a pending span for a fresh annotation.
- **Select annotations** — drag toggle-selects existing annotations it
  covers (box-select).

## View controls

- **Reset to full view** — Bokeh's own toolbar "Reset" restores the
  *previous* zoom (its pan/zoom history), not the whole channel, and is
  easy to mistake for "go home." This button is an explicit,
  always-whole-channel reset (also clears any vertical pan).
- **Pan up / Pan down** — vertical pan, implemented at the app level
  (shifts the per-frame auto-computed local y-range by a fixed fraction of
  its own span) rather than via Bokeh's y-pan tool, since that tool's
  cross-browser reliability for a restricted-to-y-axis drag couldn't be
  verified without a live browser.
- **Zoom presets** (1 min / 10 min / 1 h / 6 h / 24 h / full channel,
  `ZOOM_PRESETS_SECONDS`) — one click to a fixed, exactly reproducible
  viewport width centered on the current view, clamped to the channel's
  extent. The current viewport width is always shown next to these
  buttons.
- **View transforms** (display-only — see the loud banner below): remove
  DC offset, light linear detrend (subsumes DC-offset removal, so the two
  are mutually exclusive), and y-autoscale-to-viewport (on by default).
  These only affect the *rendered* curve slice inside
  `build_channel_dmap`'s per-frame callback — annotations only ever store
  sample indices, never amplitude values, so there is no path from these
  toggles to anything written to the database. Whenever any transform is
  active, a bright banner reading **"DISPLAY TRANSFORM ACTIVE"** appears
  above the plot so a transformed view can never be mistaken for raw data.
- **Cross-channel peek** — pick another channel from the same recording to
  show, in a small linked panel below the main plot, the exact same time
  span the main plot currently shows (driven off the same `RangeX`
  stream). Equipment faults tend to appear on every channel at once; real
  biological activity usually doesn't, so this is a fast discriminator.

## Keyboard shortcuts

Active whenever focus isn't inside a text input. Implemented by a hidden
`pn.pane.HTML` `<script>` block that maps `keydown` to clicking one of
several invisible (`opacity: 0`, real 1×1px, not `width=0`/`height=0` —
zero-sized elements risk being pruned from the render tree by a CSS/layout
rule, silently breaking `.click()`) Bokeh buttons, each wired to the real
Python handler. A reference strip listing all of these is always visible
above the plot.

| Key       | Action                                            |
|-----------|----------------------------------------------------|
| `1`-`4`   | Set verdict (interesting / not interesting / artifact / unsure) |
| `Enter`   | Save the current pending annotation                |
| `n` / `p` | Next / previous annotation (respects filters+search)|
| `Esc`     | Clear the current annotation selection             |
| `r`       | Mark the current viewport reviewed                 |
| `z`/`x`/`c` | Drag mode: Pan / New span / Select annotations   |

## Filters and search

Every multi-select filter (verdict, source, and each tag category —
element/quality/structure/provenance/status) is **OR within that
category** (selecting two verdicts returns the union, never nothing) and
**AND across categories**. The id/free-text search box composes with all
of the above (ANDed on top). The table, the plot overlay, and the live
match-count display all call the exact same function
(`ViewerApp._filtered_annotation_rows`) — there is no second, independently
written copy of this logic to drift out of sync. The live count
(`**N** of M annotation(s) match` vs. `**N** annotation(s) (no filters
active)`) exists specifically so an empty result is distinguishable from a
broken filter at a glance.

## Annotation table

- **Selected rows sort to the top**, marked with a pin icon, with the rest
  of the ordering unchanged beneath — from EITHER a table checkbox click
  or a plot box-select drag. Every place that changes
  `_selected_annotation_ids` calls `_refresh_table` (which rebuilds the
  pin column and re-applies the pin-sort), not just
  `_sync_table_selection_from_ids` (which only pushes checkbox state onto
  whatever dataframe the table already has) — a real bug (2026-08) had
  the plot-drag and "jump to similar/navigate" paths call only the
  latter, so a newly plot-selected annotation could show as "N selected"
  in the info line below the table without a pin icon anywhere, and
  without landing on the first page. The info line itself reads "N
  selected, pinned to top" for exactly this reason — it names where to
  look, not just how many.
- **Inline edit**: verdict, status, event_count, and note are editable
  directly in the table. Imported annotations (`source != manual_ui`)
  require checking **"Allow editing imported annotations"** first — an
  edit attempted without it is refused and the cell reverts. This is the
  same override checkbox bulk operations use (see below); **it does not
  apply to delete**, which always refuses on an imported row regardless.
- **Navigator** (`< Prev annotation` / `Next annotation >`) steps through
  the current filtered+searched set in order, zooming to each with
  configurable padding (`Navigator padding` field, as a fraction of the
  annotation's own span).
- **Bulk operations**: with rows multi-selected in the table, stage a
  verdict change, status change, or tag add/remove, or bulk-stage the
  selection for an algorithm run. Staging shows a preview (affected count,
  and how many are imported) and does nothing until you click the
  **CONFIRM** button that appears — no bulk action ever applies silently.
  Imported rows are skipped unless the same override checkbox above is
  checked.
- **Soft delete**: deleting a row sets `deleted_at` instead of removing it
  — it disappears from the table/plot/counts (every read goes through
  `list_annotations(..., include_deleted=False)`, the default) but can be
  restored with **Undo last delete** immediately after. Imported rows can
  never be deleted from the UI, with or without the override checkbox.
- **Export** — "Export filtered set" (CSV / JSON) downloads exactly the
  currently filtered+searched rows, including derived spike-train/duration
  bands and tags, computed fresh at click time.

## Run algorithm tab

**Pre-run preview (Part 5, Section A, 2026-08).** Arriving on this tab — by
staging a span from the Viewer, or just clicking the tab — immediately
renders whatever `Span` currently resolves to as a single curve titled
"Staged span — not yet processed", so you can confirm the window you're
about to run on before committing to it. It's rendered through
`UI.plots.build_peek_curve` — the exact same decimated-curve path the
Viewer's cross-channel peek uses — never a second, independent renderer;
a multi-million-sample "Whole channel" preview is decimated exactly like
the Viewer's own curve, not rendered raw. `RunPanel.result_pane` has
exactly two writers, this preview and the post-run Before/After pair
(below), so a stale single-plot and a Before/After pair can never both be
on screen — whichever last wrote to it is what's showing.

`Span: Selected span` resolves to the Staged spans table's checkbox-
selected row (or the first row, if none is explicitly checked) rather
than the ad hoc drag-selected span, for any staged row belonging to the
recording currently loaded in the Viewer — arriving here via staging a
span is the overwhelmingly common path, and that staged span IS "the
selected span" in that flow. Selecting a different staged row, or
switching `Span` mode, immediately updates the preview (`preview_info`
also states which staged row, e.g. "staged row 2/3", and the sample
count/duration) — both read from `RunPanel._current_span()`, the same
method an actual Run uses, so the preview can never show something
different from what Run would actually do.

**Independent vs. shared y-axis (Part 5, Section B).** The Before/After
comparison defaults to giving each panel its own auto-scaled y-range
(`compute_display_y_range`, the same per-frame autoscale the Viewer's main
curve uses). This matters because most algorithms run here change
amplitude scale or remove an offset — e.g. a bandpass filter's output can
be four orders of magnitude smaller than the raw signal's DC-offset range
— and forcing both panels onto one shared/normalized range (HoloViews'
default behaviour for same-dimension elements in a `Layout`) renders the
smaller one as a flat line near zero, indistinguishable from "nothing
happened". `axiswise=True` on each curve is what actually stops this —
without it, an explicit per-curve `ylim` alone is not enough; HoloViews'
range normalization overrides it (broader than just one `Layout` — see
"y-range linking is document-wide, not Layout-scoped" above for the full
scope, found while debugging the same class of bug in the encoding
view). The `Shared y-axis` toggle
is there for the rarer amplitude-preserving transform where one shared
scale IS the more informative comparison, and re-renders the last result
without re-running anything. Each panel's title states its exact numeric
y-range, and a line beneath the plots states the ratio of the After
range to the Before range, so a scale change is always visible rather
than needing to be inferred from eyeballing two axes.

**Staged spans table** shows source_file/channel/start_idx/end_idx and a
human-readable duration (`10.0 min`, matching `UI.plots.format_scale_viewed`'s
thresholds) with `layout="fit_columns"` so all of them fit the sidebar
without horizontal scrolling — `annotation_id` stays in the underlying
data (useful elsewhere) but is hidden from this compact view; showing it
too left every column, including the ones that matter, too narrow to
read.

**Before a run**, "Detections (this run)" shows "No run yet." rather than
an empty table with just headers (which reads as broken, not "hasn't run
yet"); after a run with zero detections it says so explicitly rather than
going back to looking empty. **Save selected detection as motif** stays
disabled until a run has actually produced at least one detection to
pick from; **Save current selection as motif** stays disabled until
`Span` resolves to an actual bounded span (not `Whole channel`, which it
has always explicitly rejected) — a brief note above the buttons explains
both conditions.

## Session persistence

The last recording/channel/viewport/time-unit/filters/search/toggles
**and each accordion's open/closed state** are saved to a plain JSON file
(`Working.config.SESSION_STATE_PATH`, default `DATA/db/ui_session.json` —
UI preference state, not data, so it's deliberately not a database table)
and restored the next time the app opens. Accordion state is global (not
gated on the recording matching, since it's presentation chrome, not
recording-specific); everything else only restores when the saved
source_file is the one that actually loads.

If the saved recording or channel no longer exists (re-materialized under
a different name, a channel count that shrank, etc.), that's surfaced as
a **visible red status-line notice naming the missing recording/channel**
before falling back to a default — never a silent substitution, which
could otherwise look like a real bug in whatever DID load ("why does this
channel look wrong?"). Every other field still degrades silently
field-by-field (a stale filter/vocabulary term just doesn't get applied),
since those don't change WHICH recording you're looking at. Switching
recording or channel while a span is drawn but not yet saved clears that
pending span (nothing in the database is lost — only the un-saved
on-screen selection) and shows a warning in the status line.

## Editing rules

Imported annotations (`source='imported_10min'` or other non-`manual_ui`
sources) cannot be edited, bulk-edited, or deleted from the UI **without**
first checking "Allow editing imported annotations" — enforced in
`Working/database/queries.py` (`update_annotation` raises `PermissionError`
unless `force=True`), not just hidden in the UI layer. Deletion is the one
exception with no override: `delete_annotation` always refuses on an
imported row.

## Configuration

Every tunable threshold used by this module (overlay density threshold,
ribbon bucket counts, ribbon pane geometry/alignment, reviewed-coverage
full/partial cutoff, zoom-preset widths, the session-state file path,
near-duplicate similarity thresholds) lives in `Working/config.py`, not
inline here — see that file's comments for what each one means and why
its default was chosen.
