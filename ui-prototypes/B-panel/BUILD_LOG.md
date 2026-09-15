# Prototype B (Panel 1.9.3 + Bokeh 3.9.2) — build log

Appended after each checklist item (cutoff insurance). Server: `"/c/ProgramData/anaconda3/python.exe" run_app.py --port 8766`.
Runtime dir: `B-panel/runtime/<stamp>/` (A's `Runtime` object with its paths re-pointed before `setup()`, so B never
writes into A's runtime folder; the adapter-path assertion still runs). Read-only JSON evidence route: `GET /b/debug`.

## 1. Shell (2026-09-15 ~18:40)
- Works: rail + header from the skeleton; routing now waits for `pn.state.onload` + a 500 ms grace before defaulting
  the hash. **Friction:** the browser hash reaches the server as a property patch from Panel's client-side Location
  model that can land *after* onload — the skeleton's `if not hash: hash = '#explore/corpus'` in `make_app` clobbered
  every deep link (`#analyse/chain` rendered Corpus). Rail pane `sizing_mode='stretch_height'` + width (fixes
  FIXED_SIZING_MODE warning). Header "N need you" = failed jobs started in this browser session; rail "Jobs · N" =
  running jobs in the process; `ctx.refresh_chrome()` updates both.
- Verified: Playwright screenshot of `#analyse/chain` deep link, no console errors.

## 2. Explore › Corpus (~18:45)
- Works: recording Select (M4 shown with 🔒, selecting it renders the locked card with `held_out_reason`, no coverage
  call), pager `n / 6`, bin select 28/57/114, colour-by RadioButtonGroup, Bokeh `rect` heatmap 16×57 with quantile
  5-step blue ramp and 1 px white gaps, hover "CH4_A2 · 341–354 h · 12 spans", TapTool selects a row (blue outline +
  blue label drawn as a `text` glyph because an axis cannot colour one tick label), right rail Show/Verdict checkboxes
  wired (verdicts refetch coverage with counts in the labels), morphology tags 0 "no tags in this database",
  matching N spans across K of 16; bottom bar with "— disagree" when one side is empty, "Open CH4_A2 →" navigates.
- Verified: screenshot; `/b/debug` heatmap = 912 rects, 6 distinct colours.
- Friction: every widget style needs `:host(.cls)` selectors inside raw_css (css_classes land on the shadow host);
  glyph `text_font` needs `value(...)` but annotation `Label.text_font` rejects `value(...)`.

## 3. Explore › Signal (~19:00)
- Works: tier 1 full-channel envelope (2,600 pts) + `RangeTool` linked to tier 2's x_range (the blue box), verdict
  coverage ribbon, detection-density ribbon ("no detections on this channel" for CH4_A2 in this DB); tier 2 viewport
  with x-wheel zoom + x-pan, **envelope re-fetched per viewport** through `corpus.window` with a leading+trailing 60 ms
  throttle, tinted bands + caps from `corpus.spans` per viewport, "‹ n / 698 ›" motif nav, −/+/fit; tier 3 motif ±20 s
  with ONSET/END; Send motif/span to Analyse set `ctx.source` and navigate; Save span toast stub; four collapsed ribbons.
- Timing loop: CustomJS stamps the moment a range leaves the browser; when the matching viewport's meta arrives it
  computes the round trip, pushes to `window.__zoomStats`, and writes JSON into a hidden Bokeh `Div` whose change syncs
  back to Python → `pn.state.cache['zoom_stats']` → `/b/debug`.
- Measured (6 wheel steps, 2 h → 5.6 min): n_points 2162→337, server decimate 0.1–0.6 ms, server total 5–11 ms,
  **browser round trip 14–26 ms**.
- Friction (silent-failure class): (a) a `ColumnDataSource` that no renderer references is *not serialised* into the
  browser document — Python writes to it vanish and its `js_on_change` never fires, no error anywhere (cost 3 restarts);
  (b) `source.stream()` does not fire `js_on_change('data')`; (c) `RangeTool` is not a GestureTool in Bokeh 3.9 so
  `toolbar.active_multi = rtool` raises; (d) `fig.inner_width` raises UnsetValueError until the browser has laid out;
  (e) four `stretch_width` Cards in a `Row` made the page 5,464 px wide — needed a `GridBox(ncols=4)`.

## 4. Analyse › Chain — first pass (~19:40)
- Works: toolbar (name chip, source chip from `ctx.source` / example-span note, surrogate Switch disabled, estimate chip
  from `chain.estimate`, History/Import popovers, Save template → `save_template` on the DB copy + toast, Run / ↻ Re-run
  from 0N / ■ Cancel / ↻ Retry from 0N, disabled with the reason for invalid / over-ceiling / held-out); Source row +
  one row per step (number + page name, badge + signature, caption, ⚙ ⊘ ⧉ ✕ icons) with plots from the single seam
  `renderer.render(payload, x_range, height, ghost)` over all seven types; rows share ONE `Range1d` + ONE crosshair
  `Span` overlay; "+ insert" pills open the insert-stage modal (`pn.Modal`, cards = Buttons with SVG glyph icons,
  disabled with reason, per-card in-process estimates); invalid-junction pill + "+ Insert <first fitting> here";
  footer shared axis + terminal chip + last-run line + Export run; running/waiting/failed/cancelled/blocked/stale
  row states from a Python port of A's rowState.ts (`runstate.derive_rows`).
- Verified headless (scratch construct harness): run completes, then editing the threshold → "↻ Re-run from 03" and the
  re-run's `job.step_timings` = {0: 0.0, 1: 0.0, 2: 0.0004} → badges "cached · 0 s" on 01/02. Browser: Run click →
  completed rows painted (signal+ghost, scores with M/D marks, spanset bands), no console errors; modal opens.
- Friction: `pn.Modal` needs `pn.extension('modal')` (warning otherwise); Panel has no clickable rich card — the modal
  cards are multi-line Button labels (`white-space: pre-line` via `:host(.card-btn)`), so no bold name, no chips.
