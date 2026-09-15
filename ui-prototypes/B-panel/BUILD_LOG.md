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

## 5. Block page — Threshold to spans with the draggable cut (~19:25)
- Works: `blockpage.py` — ‹ full chain, chips, chain ribbon (Buttons, this block highlighted, each navigates),
  "Scores with the cut" (upstream Scores envelope + orange `Span` + a one-point `ColumnDataSource` handle edited by
  `PointDrawTool(add=False, drag=True, num_objects=1)`; a CustomJS moves the line/histogram cut/label, Python's
  `on_change('data')` snaps the handle's x back, writes `params.threshold`, syncs the FloatInput and marks 03 stale),
  last-run spans strip on the shared axis, envelope preview count, histogram with the same cut, spans table;
  Parameters generated from `chain.catalog()` specs (Select / Int|FloatSlider when both bounds / Int|FloatInput / Checkbox
  / TextInput, "= default" marker); honest null card; footer "Unapplied changes · N" / Revert / ↻ Re-run from 0N that
  stays on the page (periodic poll, rebuilds the process card when the job ends). Generic blocks show their output
  through the same renderer seam at 260 px.
- Verified (smoke run 1): Playwright drag of the handle (pixel position computed from `/b/debug` geometry — the
  browser syncs `inner_width/inner_height` back to Python) wrote threshold 8.0 → 6.128, statuses
  ['cached','cached','stale'], footer "Unapplied changes · 1"; Re-run from the block page → step_timings
  {0: 0.0, 1: 0.0, 2: 0.0005}; back on the chain page badges ['cached · 0 s', 'cached · 0 s', 'cached · <0.1 s'].
- Friction: PointDrawTool drags x and y — a vertical-only drag needs a server round trip to snap x back; its data change
  reaches Python only on release, so the parameter/stale state lags the line (the line itself follows via CustomJS).

## 6. Chain states verified in the browser (smoke run 1, ~19:25)
- Insert modal at position 1: 22 cards, 17 disabled with reasons, "5 of 22 blocks fit". Run: badges cached, seam drew
  signal/signal/scores/spanset. History popover opens. Delete 02 → red junction pill, Run disabled "1 invalid junction",
  Undo restores. window_min = 500 on 02 → error card "02 Matrix profile failed … ValueError: window (m=30000 samples)
  must be shorter than the span (20006 samples) · adapter detection.matrix_profile · recipe 4e1c90ba · db run #44",
  03 blocked, header "● 1 need you", toolbar "↻ Retry from 02", footer "No result … nothing was written to detections".
- Gaps found: cancel test finished before the Cancel click (11 h span MP too fast) → smoke now widens to ~22 h and clicks
  Cancel ~450 ms after Run; row-canvas ink check must group Bokeh's stacked canvas layers (upper layers are transparent).

## 7. smoke.py — green (runs 2 and 3, ~19:28 / ~19:32): 20 screenshots, 0 failures, 44 checks
- Gates: console/page errors + failed requests (0), canvas ink through shadow DOM (heatmap 519 distinct colours;
  chain rows [156, 263, 442, 213] after grouping Bokeh's stacked canvas layers), Python-side renderer counts from
  `/b/debug` (heatmap 912 rects; seam drew signal/signal/scores/spanset), server.log tracebacks (only the deliberate
  ones and the provoked failed run).
- Measurements (run 3): zoom over the full 721 h, 12 wheel steps 480.7 h → 5.56 h, ~2,500 pts per viewport:
  server decimate min 0.39 / median 2.18 / max 12.67 ms; server total 5.8–21 ms; **browser round trip min 14.9 /
  median 23.2 / max 41.6 ms** (slowest at the widest viewports). Run round trip (click → footer "last run", MP on
  the sent 5.56 h span, JIT warm) 1.29 s; step timings {0: 0.0004, 1: 0.316, 2: 0.0011}. Suffix re-run from the block
  page {0: 0.0, 1: 0.0, 2: 0.0005} → badges "cached · 0 s". Cancel on a 22.2 h span (80,020 samples, under MP's 80,527
  ceiling) clicked while 02 was running → job cancelled, 02 cached (3.2 s), 03 "cancelled · this step never started".
- Screenshots: screenshots/01…20 (names = frames), smoke-result.json.

## 8. Loud-failure measurement (~19:29)
- `?throw=1` (row-level catch present): the Source row shows a red error card with the traceback; browser console
  clean; server.log "ERROR protoB: render error in Source row renderer" + traceback. (screenshot 19)
- `?throw=1&uncaught=1` (the flag re-raises past BOTH the row catch and main.py's catch — equivalent to deleting them)
  navigating from Corpus: the browser keeps showing **Corpus** while the URL says `#analyse/chain` and the rail
  highlights Analyse; **zero console errors, no page error**; server.log: "ERROR: panel.reactive - Callback failed for
  object named 'Location…' changing properties {'hash': …}" + traceback, then "ERROR tornado.application: Exception in
  callback … ServerSession.with_document_locked … RuntimeError('deliberate render failure …')" + traceback. (screenshot 20)
- Literal check as the brief asked: main.py's try/except temporarily commented out (backup, edit, restart, measure,
  restore; `cmp` against the backup = identical): same result from navigation
  (`screenshots/loud-failure-main-try-commented/navigate-from-corpus.png`); a fresh load straight onto the deep link
  shows the "loading…" placeholder forever with Analyse highlighted, console only Bokeh's normal info lines
  (`…/fresh-deep-link.png`). Verdict: without an explicit try/except + error card, a Python exception in a Panel
  callback is invisible in the browser — the historical silent-failure class, reproduced on Panel 1.9.3.

## 9. Export + wrap-up (~19:36)
- Export run (Could): writes `runtime/<stamp>/exports/run-<job>.json`; smoke run 4 green (0 failures) with the export
  check added. Modal: GridBox(height, scroll) did not clip its last row over the footer → wrapped in a scrolling Column
  (verified by a modal-only probe, 22 cards / 17 disabled, screenshot 09 refreshed); chain row "waits for 0N" now
  tracks the running step; running badge no longer carries a frozen elapsed (the bar text does).
- `find DATA/ -newermt "2026-09-15 18:30" -type f` → nothing. B's server on 8766 killed. A's 8765 untouched.
- LOC: app/ 2,951 + smoke.py 428 + run_app.py 88. Dispatch seam `renderer.render` 14 lines; `_scores` 22, `_spanset`
  16, `_signal` 12, `_encoding` 46; renderer.py 211 non-blank lines for all seven types.
- Not done: Cross-channel (inert, by design); tier-1 grips are Bokeh's RangeTool box (no grooved blue grips);
  motif overlay/family medoid (no families in DB); modal cards cannot carry bold names/chips; per-row stale veil is a CSS
  opacity on the pane; the History popover floats in flow under the toolbar (no anchored popover primitive).

## 10. Critique round 1 fixes (2026-09-15 ~20:00 →)
- P0 gramian blanks the chain page → `renderer._encoding` passes `image_rgba` a 2-D uint32 (h, w) array (was a 3-D uint8 view) and packs the LUT little-endian A<<24|B<<16|G<<8|R (was R/B swapped = orange) → browser probe on `#analyse/chain?rid=4&s0=995040&s1=998640` (3,600 samples), Import gramian, Run: job completed, 3 `.row-left`, "not time-aligned" present, blue GASF image painted, 0 console/page errors.
- P1 fresh steps badged "cached" → `runstate.derive_rows` reads "cached" only when `jstep.cached` or the core timing is exactly 0.0, else new status "computed" (badge "✓ computed · t", outlined green) → same probe: badges ['✓ computed · <0.1 s', '✓ computed · 0.1 s'] on a first run.
- P0 stale "■ Cancel" starts a duplicate run → `ChainView` (and `BlockView`) record the mode the Run button is SHOWING (run/cancel + when it changed); a click in cancel mode (or ≤600 ms after it flipped back) on a finished job toasts "run already finished" and starts nothing; queued counts as live; a requested cancel shows "■ Cancelling…" disabled + "cancel requested · stops before the next step" → probe with `?poll_ms=8000` on a fresh 72,000-sample span: job finished at 2.6 s while the button still read "■ Cancel", click → jobs 2 → 2, event `stale_cancel`, 0 errors.
- P1 loud failure → new `app/guard.py` (`error_card`, `guarded`); `ctx.fail` puts a red card in a session banner above the page + an error toast; every `on_click` / `param.watch` / Bokeh `on_change` in analyse, blockpage, signalview, explore and modal goes through `ctx.guard(label, fn)`; each step row's `_plot` is caught per row (`?throw=row` raises in row 02 as evidence); block page `build_process` (incl. the threshold build) caught; chain + block `tick()` stop the poll and draw a `poll-error` card; the tier-2 viewport fetch draws a `fetch-error` card. `?throw=1&uncaught=1` left as is → verified in smoke (below).
- P1 wheel zoom ignores min span → CustomJS on tier-2 `x_range` clamps to ≥30 s around the centre with `setv` before any paint; Python `clamp_view()` repeats it before fetching; Send span / Send motif disabled (description + red reason in the actions line) under 30 s and refused server-side → probe: 40 wheel steps in, 40 fetches, min viewport 30.0 s, no blank frame, RTT 41–89 ms.
- P1 zero-length span accepted → `runstate.validate_full` sets `recipe_error` for ≤0 samples, `update_toolbar` disables Run with it as the reason, `source_payload` raises "the source span is empty (0 samples)" (no numpy traceback) → probe `#analyse/chain?rid=4&s0=995040&s1=995040`: Run disabled, reason shown, Source card says the span is empty.
- P1 shared axis drift → the footer axis is built through the same `_frame()` wrapper as every row (card margin 20 + 1 px transparent border, left LEFT_W margin 12/6, plot margin 4/12); failed/invalid outline moved to an inset box-shadow so it cannot shift the frame → Bokeh view geometry: Source row frame 366–1398, axis frame 366–1398 (Δ 0 px).
- P2 Inter never applies → `:root{--bokeh-base-font: Inter…}` (Bokeh's :host rule reads this variable) + `:host{font-family:var(--font-ui)}` in raw_css → computed header font "Inter, system-ui…", `document.fonts.check('12px Inter')` true, captions still Geist Mono.
- P1 reload / second tab loses state → analyse pages write `rid, s0, s1, job` into the hash query (`ctx.sync_hash`, after render and after a run starts) and `ctx.hydrate()` rebuilds source + lastRunJobId (+ the job's steps if they differ) from it; `render()` skips a rebuild when only our own state keys changed → fresh browser page on `#analyse/chain?rid=4&s0=995040&s1=998640&job=1`: footer "last run · 3 spans", badges computed with timings, 0 errors.
- P2 Escape → document_ready CustomJS listener clicks the open dialog's own close button → modal hidden after Escape.
- P1 insert-modal cards clipped → `:host(.card-btn)` min-height + `height:auto` + wrapping instead of `height:96px; overflow:hidden`, Button `min_height=100` instead of `height=100`; detail panel frame moved from the pane's `styles` (which pad the HOST while the inner container keeps the full 300 px — the 13 px spill) into the markup, border-box, glyph 240 px, tiles wrap → probe: 22 cards, 0 overflowing (heights 103–119 px); detail spill re-measured in smoke (below).
- Cheap P2s → history lists a core "failed + Cancelled before step N" run as "cancelled" (`runstate.history`); estimate chip grey unless over the ceiling, "0 s · all cached" when everything is cached, otherwise "≤ N core est." (title: the cost model's estimate, not a measurement) or "no core estimate"; zoom RTT matched through a browser-side per-request sequence queue (matched + superseded entries dropped); Escape closes the insert modal; tier-1/tier-2 timing text moved behind an "ⓘ timing" title (numbers still in `window.__zoomStats` and `/b/debug`), motif nav drops its doubled text chevrons, short spans titled in seconds; Export disabled on an invalid chain and its toast trims the path; focus-visible ring on buttons; threshold-page null card padding moved into markup (same host-padding spill as the modal detail panel); a step-cache hit with no attached run reads "cached · not loaded" with an honest hatch message instead of "cached" over "no result".
- smoke.py additions: min-span wheel test; honest-badge invariant on the first run (cached ⇔ core timing 0.0); `templates()` imports and runs all four built-ins on 3,600 samples and checks per-row paint (canvas ink inside each row's band, model card for Model), seam types, 0 page errors, and the shared-axis frame vs every row frame (Bokeh view geometry, ≤1 px); `stale_cancel()` (`poll_ms=8000`, fresh 20 h span); `url_state()` (second tab on the same URL re-attaches, zero-length span → Run disabled with reason); `modal_and_font()` (0 clipped cards, detail spill ≤0, Inter on the header, Escape closes); `?throw=row` per-row error card. Smoke run A (before the last P2 batch): 28 screenshots, 0 failures.
- Final smoke run B (fresh server, after every fix above): **28 screenshots, 0 failures, 73 checks**, 0 browser console/page errors, 0 unexpected server tracebacks (9 error lines, all deliberate/provoked). Templates on 3,600 samples: mp_threshold / dsax / windows_model / gramian all completed, every row painted, 0 errors. Axis frame 366–1398 = every row frame. Stale Cancel: jobs 9 → 9. Min viewport 30.0 s. `find DATA/ -newermt "2026-09-15 19:55" -type f` → nothing. 8766 killed; 8765 (A) untouched. LOC app/ + smoke.py + run_app.py = 4,007.
- Not done (stack limits / out of this round): tier-1 RangeTool grips left as Bokeh's box (stack limit, as instructed); whole-line threshold drag; modal cards are still Button labels (no bold name/chips — Panel has no clickable rich card); row-thumbnail divergences (null band, ghost scale); corpus right-rail dots/range slider; per-session debug keys; icon buttons' accessible names.
