# REPORT.md — UI stack prototypes for issue #12 (overnight, 2026-09-14 → 15)

Branch `proto/ui-stack-slices`, worktree `C:/Users/mmebr/Documents/CNN-ui-proto`. Running log with
every decision: `DECISIONS.md`. Checklist: `CHECKLIST.md`.


## 1. Summary table

| Prototype | Stack | Start (one command) | URL |
|---|---|---|---|
| **A** | React 19 + TypeScript + Vite 8 + d3 (SVG) · FastAPI/uvicorn bridge in a project-local venv | `ui-prototypes/A-react-fastapi/start.ps1` (Git Bash: `./start.sh`) | http://127.0.0.1:8765 |
| **B** | Panel 1.9.3 + Bokeh 3.9.2, in-process (reuses A's service modules read-only) | `ui-prototypes/B-panel/start.ps1` (Git Bash: `./start.sh`) | http://127.0.0.1:8766 |

| Checklist item | A | B |
|---|---|---|
| 1 Shell (rail + header; Explore/Analyse live, others inert) | done | done |
| 2 Explore › Corpus (real heatmap, colour-by, selection → bottom bar, Open) | done | done |
| 3 Explore › Signal (721 h pan/zoom, per-viewport decimation, tinted bands, send span) | done | done — the span box is Bokeh's RangeTool overlay, without the frame's grooved grips |
| 4a Composition (source row from the span; insert modal with real adapters, disabled with reasons) | done | done — modal cards are multi-line button labels (no rich card in Panel) |
| 4b Rows on a shared axis, badges, one-line summaries | done | done (one shared `Range1d` + one crosshair `Span`) |
| 4c One dispatch seam over all seven types; awkward types real | done — Scores, Encoding (symbolic), WindowSet, Grouping, Model all run for real; Encoding image runs only on spans ≤ 5000 samples (core cap) | done — same seven-type payloads; `renderer.render` dispatches to seven Bokeh renderers |
| 4d Run against the untouched core on the DB copy; live per-row progress; cancel; running/failed/invalid states | done (progress is per step — the core reports no within-step fraction) | done — in-process thread, page polls the job every 200 ms |
| 4e Suffix re-run shows prefix rows `cached · 0 s` | done (core `step_timings` 0.0 on the prefix) | done |
| 5 Block page with a draggable control bound to a parameter | done — Threshold-to-spans page: draggable threshold over the score series and histogram; marks downstream stale. (SAX cutlines are learned by the adapters, not parameters — see §5) | done — `PointDrawTool` cut; x snaps back via a server round trip, data reaches Python on release |
| 6 Run history popover; Save template | done (history from the DB copy + live jobs; templates saved to the DB copy) | done — popovers render in page flow, not anchored |
| 7 Export run (simple report) | partial — JSON export of recipe + timings + payloads under `runtime/<stamp>/exports/`; no rendered figures | partial — same JSON export |
| 8 Cross-channel view | missing (button present, inert, labelled out of scope) | missing (inert) |

**Decision (2026-09-15, after review):** you chose **A**. §8 has the head-to-head scorecard that went
with that choice, including load, memory and size measurements taken after the overnight run.

## 2. Why A ranked first (and what building taught)

**Pre-build ranking** (DECISIONS.md §2): React + TypeScript + d3-in-SVG over a FastAPI bridge first,
Panel + Bokeh second (the incumbent, which #12 says must win or lose on evidence), Dash/NiceGUI as
a possible third, desktop Qt and webview wrappers dropped (the spec is written as a web app and no
web output path exists). The discriminators that decided it: the pages are a *bespoke* web design
(chips, badges, modals, a card grid, a nav rail, one shared time axis with drag handles and a
crosshair), loud failure has to be structural rather than configured, and agentic throughput is
the heaviest criterion.

**What building A taught.**
- The frames were reproducible 1:1 in hand-written SVG + CSS with no library in the way; the two
  builders needed zero and one compile-fix iterations over 3,600 lines, and every interaction the
  pages ask for (draggable handles and cut lines, per-viewport re-decimation with a CSS-transform
  bridge, symbol strips, image canvases, a shared axis crosshair) took less time than the
  *state* semantics (which badge, whose result is this). That is evidence that the stack is not
  where the difficulty of this UI lives.
- Loud failure came for free: a thrown render error is a red card in place of the row (plus a
  console error the test gate catches); a server exception is a 500 with the traceback in the
  body and the log. Nothing rendered blank in three critics' attempts to make it.
- The bridge cost was real but bounded: ~1,660 lines of Python, of which the seven-type
  serialiser is 270 and the run manager 246; the thread → event-loop → SSE path, cancel,
  reload-replay and a cache-hit meta sidecar were all designed and verified in one night. The
  first critique found the SSE path fragile under a network blip — fixed with a polling fallback,
  which is exactly the kind of transport work the audit said only a spike could cost.
- The core's shape, not the frontend, set most limits: per-step (not within-step) progress,
  cancel only between steps, learned (not parameterised) SAX cutlines, no null declaration on
  adapters, a 70× pessimistic MP estimate, `Encoding` being terminal, and adapters that write
  files from inside their run bodies. Those are recorded in §5 and are identical for any stack.
- Orchestration friction outweighed stack friction: the account's usage limit cut off both
  fixer agents once and the reader phase once; Vite 8 binding `::1`, React 19 dropping the
  global `JSX` namespace, and Windows `cp1252` consoles were the only toolchain surprises.

**What building B changed.** Nothing in B's build or critique overturned the ranking; three
things sharpened it.
- *Loud failure is the separator the audit predicted, and it is now measured, not asserted.* On
  Panel 1.9.3 an exception in a callback leaves the previous page on screen with a clean console and
  a line in `server.log`; B reproduced it deliberately, and its critic then hit the same class by
  accident (a Bokeh image row that failed in the browser while Python reported it drawn). In A the
  equivalent is a red card and a console error that fails the test gate.
- *The frames are a bespoke web design.* Every place B had to approximate a designed component with
  a widget (cards, grips, draggable lines, popovers, the font) is a visible departure; A drew them
  directly. B's builder hit three silent Bokeh behaviours on the way.
- *B's real advantages are real but smaller than they looked:* no bridge to write (A's bridge was
  ~1,660 lines, but it is now written and critiqued twice), in-process cancel, no build step, and a
  shared axis that is one object. Zoom and interaction latency do not separate the stacks: both are
  interactive (A median round trip 9–20 ms, B 23 ms).

## 3. Evidence gathered while building, per stack

### A — React + TypeScript + FastAPI

**Zoom latency on the full 721 h channel** (2,595,600 float64 samples, memory-mapped, min/max
decimated to ≈2× the plot width).

| measure | value | source |
|---|---|---|
| server decimation, full channel → 2,400 points | 12–14 ms warm (first call after a restart 50–98 ms: page cache) | `Server-Timing` header; `prof_dec.py` |
| server decimation, 2 h viewport | 0.3–1 ms | same |
| round trip (fetch → JSON parsed), full channel | 92–119 ms | `window.__zoomStats` (smoke run 2: max 91.7 ms) |
| round trip, typical viewport (2 h … 60 s) | min 5.5 · median 16–20 · max ~30 ms | smoke run 2 + builder's 12-step sequence |
| paint after commit (rAF) | median 27 ms, max 42 ms | builder's sequence |
| points per viewport | 61 (60 s, raw) · ~2,600–2,900 (decimated) | same |
| perceived latency during a gesture | 0 ms: the previous path is CSS-transformed immediately; new data lands after the 60 ms debounce + fetch | `data-transformed=1` read 15 ms after a wheel event |

The verbatim `UI/plots._minmax_decimate` measures 35 ms on this machine for the full channel
(its docstring's 12 ms was another machine); an equal-bucket reshape/argmin path with identical
per-bucket semantics measures 12–14 ms and is what the bridge uses for NaN-free input.

**Run and progress round trip** (default chain: detrend → matrix profile (m = 60 s) → threshold,
on the 2 h example span, 7,200 samples):

| measure | value |
|---|---|
| POST /api/runs → first SSE event | < 40 ms |
| whole run, warm | 0.34 s wall; core: detrend 0.2 ms · MP 100 ms · threshold 0.3 ms |
| suffix re-run after a threshold edit | 0.2 s wall; core `step_timings` = {0: 0.0, 1: 0.0, 2: 0.0003} → rows 01/02 badge `cached · 0 s` |
| identical re-run | all three 0.0 |
| first matrix-profile call in a server process | ~30 s (STUMPY numba JIT; the bridge warms it at startup in a thread, but a run started within those 30 s waits — smoke run 2's first run took 31.9 s wall) |
| 20 h span (72,000 samples) | MP 2.7 s core, 3.4 s wall including a mid-run reload; cancel between steps verified |
| core estimate vs actual | `estimate_recipe_seconds` says ≈ 7.2 s for MP on 2 h; actual 0.10 s (70× pessimistic; the chip is prefixed "≈") |

**What a thrown render error looked like.** `#/analyse/chain?throw=1` makes the first row's
renderer throw: the row is replaced by a red card (`data-testid="render-error"`) with the
message and the React component stack, the rest of the page stays alive, and the error is
logged to the browser console (`console.error`), so the Playwright gate goes red. In dev mode
Vite additionally shows its full-screen overlay. Server side, `GET /api/boom` returns a 500
whose JSON body carries the traceback and the same traceback is written to
`runtime/<stamp>/server.log`; the page shows API failures as red cards / error toasts with the
traceback text. Nothing in this stack can render blank on an exception: an error either
throws through React (boundary card) or is an HTTP status (error card).

**Install and build friction.**
- venv `--system-site-packages` + `pip install fastapi uvicorn[standard]`: ~1 min, no conflicts with the conda numpy/pandas.
- `npm create vite@latest -- --template react-ts` + `npm install d3 @types/d3`: ~1 min. Versions landed: React 19.2, Vite 8.3, TypeScript 6.0, d3 7.9.
- Client build: 4.6 s; type-check 3–5 s. Bundle 423 kB JS (130 kB gzip), 31 kB CSS.
- Builder friction (their own reports, verbatim in DECISIONS.md §6 / journal): Explore builder — **zero** compile-fix iterations over 1,274 lines; Analyse builder — **one** (the global `JSX` namespace is gone in @types/react 19). Gotchas hit: Vite 8 bound `::1` only (127.0.0.1 refused); React's wheel listener is passive (native listener needed for zoom-without-scroll); StrictMode double-runs effects in dev; `theme.css svg text { fill }` beats SVG attributes; two semantic bugs only the browser caught (a `<g>` in HTML context; a stale-step summary lookup).
- Playwright from the conda python drove everything; no Node test harness was needed.

**Lines of code.**

| part | lines |
|---|---|
| service layer (`server/*.py` + `run_server.py`), excluding the 327-line smoke test | 1,664 |
| — of which the server-side seam `serialize.py` (all seven types) | 270 (per type: signal 15 · scores 29 · spanset 19 · windowset 25 · encoding 55 · grouping 17 · model 14) |
| client shared (theme, api, state, shell, charts) | 862 |
| client Explore | 1,274 (16 files) |
| client Analyse | 2,336 (18 files) |
| — of which the client-side seam `Renderer.tsx` (dispatch + seven renderers) | 276 (`renderByType` switch 17; SignalR 15 · ScoresR 28 · SpansetR 15 · SymbolicR 28 · ImageR 47 · WindowsetR 28 · GroupingR 24 · ModelR 14 · ErrorR 8) |
| adding an eighth type touches | `serialize.py` (one function + one dict entry), `api.ts` (one interface + union member), `Renderer.tsx` (one component + one case), `glyphs.tsx` (one glyph); optionally `BlockPage.tsx` for a process view |

**Where the stack fought the design.** It did not, in the sense of the frames: hand-written
SVG in JSX reproduced every surface (chips, badges, modal card grid, shared axis, crosshair,
drag handles, symbol strips, image canvas) with no library boundary in the way, and the
builders reported that the *core's* shape, not the stack, set the difficulty: row-state
semantics (which badge, is this payload still the current step's, hide another source's
results) took more time than all seven renderers; the raw channel sits at −0.66 mV DC while
the detrended output is ±0.003 mV, so "input ghosted behind" cannot share the real y axis
(drawn on its own scale and labelled so); the frames assume data the core does not serve
(per-parameter null sweeps, a slope strip, a per-query distance profile, motif *pairs*), which
became labelled approximations or explicit empty states. The one design/stack tension: the
canonical time axis (spec §0, hours since start) versus the frames' seconds on a 50 s example.

### B — Panel 1.9.3 + Bokeh 3.9.2 (in-process)

Built by one agent (two sessions after a stall) in ~70 minutes of agent time. B imports A's service
layer unchanged, so the comparison isolates the frontend. Its own runtime dir is `B-panel/runtime/`.

**Zoom latency on the full 721 h channel.** 12 wheel steps from 480.7 h down to 5.6 h, about 2,500
points per viewport. Server decimation min 0.39 / median 2.18 / max 12.7 ms; server total 5.8–21 ms;
browser round trip (range leaves the browser until the matching data lands) **min 14.9 / median 23.2 /
max 41.6 ms**. A measured median 9–20 ms on the same kind of sequence. Both are interactive; B pays an
extra websocket hop per viewport, and has no immediate CSS-transform bridge during a gesture.

**Run and progress round trip.** Click to "last run" 1.29 s on a 5.6 h span (MP 0.32 s core). Progress
is a 200 ms `add_periodic_callback` poll of the in-process job object; no transport to design. Suffix
re-run after dragging the threshold 8.0 → 6.128: step_timings {0: 0.0, 1: 0.0, 2: 0.0005}, badges
`cached · 0 s` on the prefix. Cancel is the same cooperative `threading.Event`.

**What a thrown render error looked like — the decisive measurement.** With B's own catch
(`?throw=1`) the row shows a red error card and the log carries the traceback, but the **browser
console stays clean**, so a console-error gate cannot see it. Without the catch (`?throw=1&uncaught=1`,
and separately with `main.py`'s `try/except` literally commented out and then restored): navigating
from Corpus leaves **the Corpus page on screen while the URL says `#analyse/chain`** and the rail
highlights Analyse; a fresh deep link shows "loading…" forever. **Zero console errors, no page error.**
The only trace is `server.log` (`panel.reactive - Callback failed for object named Location…` and a
tornado `Exception in callback` with the traceback). This is the historical silent-pane failure
class, reproduced on Panel 1.9.3 with no HoloViews involved: every failure must be caught and drawn by
hand, and a test gate must read the server log, because the browser never learns of it.

**Install and build friction.** None to install; no build step; the loop is restart + reload (~20
restarts at a few seconds each). The friction is elsewhere — the builder's log names three **silent**
Bokeh behaviours it hit: a `ColumnDataSource` that no renderer references is not serialised to the
browser, so writes to it vanish and its `js_on_change` never fires, with no error (cost three
restarts); `source.stream()` does not fire `js_on_change('data')`; and any exception in a Panel callback,
including the hash router, leaves the previous page on screen. Plus: the browser hash reaches the
server after `onload`, which clobbered every deep link until handled; every widget style needs
`:host(.cls)` rules because `css_classes` land on shadow hosts; no clickable rich card; `stretch_width`
cards in a `Row` made a 5,464 px page; `fig.inner_width` raises until the browser lays out;
`RangeTool` stopped being a `GestureTool` in 3.9; `PointDrawTool` drags in both axes, so a vertical cut
needs a server round trip to snap x; Bokeh stacks transparent canvas layers per figure, so naive
"did it paint" checks report blank on healthy plots; `pn.state.cache` is invisible to Playwright, so a
read-only tornado debug route was added for the smoke test.

**Lines of code.**

| part | lines |
|---|---|
| B's own app (`app/*.py`) | 2,935 (analyse 604, signalview 485, blockpage 409, explore 269, runstate 259, renderer 246, main 177, modal 167, charts 127, theme 97, shell 64, debug 44) |
| — dispatch seam `render()` | 14 lines; per type: signal 14 · scores 24 · spanset 18 · encoding 48 · windowset 20 · grouping 20 · model 16 |
| service layer | 0 new (A's `server/` imported unchanged) |
| smoke test | 434 |
| adding an eighth type touches | A's `serialize.py` (shared) and B's `renderer.py` (one function + one dict entry) |

**Where the stack fought the design.** The frames' custom surfaces: the span box has no grooved
grips (RangeTool's overlay), modal cards cannot be rich (button labels), popovers render in page
flow, checkbox labels would not take the mono font, and the draggable cut needs a server round trip.
The shared time axis and the crosshair were easier than in A (one `Range1d`, one `Span`).

## 4. Critique rounds

### A — round 1 (three critics in parallel: fidelity, backend integrity, robustness/usability; 42 findings)

**Verdicts.** Backend: "sound and I could not break it" — core byte-identical to main, every write in the DB copy, prefix cache really hit (core timings 0.0 + prefix dirs present), envelope points are true samples with the global min/max present at every zoom, all seven types paint, M4 423 everywhere, cancel cooperative as documented, provoked failure recorded as `failed` with the traceback in the copy. Fidelity: "a faithful, honest rendering" of the shell, Corpus, Signal and Chain frames; no P0. Robustness: happy path good and failure loud (row-scoped card + console errors; 500 JSON + log); zoom over 721 h interactive (round trip min 5.3 / median 11.8 / max 48.6 ms over 20 gestures, never a blank frame); reload after completion re-attaches.

**P0 (1).** A stray `catalogue_classifier_153815b9dea451b2.joblib` (13,986 B) in the *real* `DATA/derived/models`, written at 23:05:59 by a read-only reader subagent that executed the classifier adapter directly, before any runtime redirect existed. Not deleted (rule 5); reported for the user to remove; the closing DATA check now covers every file under `DATA/` and `Results/`; `runtime.py` refuses to start if an adapter path escapes the runtime dir. See DECISIONS.md §7.

**P1 (11) — all fixed.** Over-ceiling stage could be run locally and failed (now: Run disabled with the reason, and `POST /api/runs` refuses with 422); insert-modal refusal reasons ellipsised on 17/22 cards (wrap); surrogate toggle shown ON with the placeholder "200×" (now OFF, "not in this slice", footer says "no null"); block-page Re-run navigated away (stays); SSE stream: a 3 s network blip or a corrupt frame left the tab "Running" forever (now: typed stream errors + 2 s snapshot polling fallback + backoff + a "lost contact" card); stale index leaked across sources (cleared on source change); M4 run rows leaked through `GET /api/runs?recording_id=49` (423 + filtered); cache-restored steps lost adapter meta (JSON sidecar per prefix hash); REPORT §5 deviations was empty (this document).

**P2 (30) — fixed unless noted.** db_run_id on failed/cancelled runs; cancelled runs shown as failed in history; params normalised before hashing; captions/failed message ellipsised; Ctrl+Z undo; Escape/dialog role/focus; threshold line red→amber; 'Spans vs cut' + hand-offs cards on the threshold page; per-adapter glyphs (were keyed on signature only); dSAX cutline strip empty after a cached run; '= recommended' meant '= default'; degenerate 'disagree' count; 'N need you' counted every failed job in the server; first tick label half off-surface; linear heatmap ramp collapsed by one hot cell; motif label overprinting y labels; 'overlay F-03 medoid' placeholder leak; empty Model card; toast killed before painting; badge/plot disagreement on an undrawable payload; Explore had no per-tier error boundary; estimate chip ignored the cache prediction; elapsed counter restarted after reload; TYPE_LABEL duplicated server/client; read endpoints accepted inverted windows; fit-from-deep-zoom stretched path for one round trip; **left open:** full keyboard operability of handles/heatmap/cut line (partial: handles + span svg only), per-card estimates in the insert modal (needs a hypothetical-recipe endpoint), motif *pairs* from the core.

### The pytest gate (rule 7)

`pytest -n auto` in the worktree: **1296 passed, 41 failed** in 406 s. The failures are
pre-existing on `main` @ 208e72c, not caused by the prototypes: every tested tree is byte-identical
to `main` (`git diff --stat main -- Working Adapters UI tests scripts` is empty) and pytest only
collects `tests/`. They are a test/code contract mismatch (`LibraryGrid(conn)` in the tests versus
`LibraryGrid(app)` in `UI/workspaces/library/grid.py`) and Windows file locks at teardown
(`PermissionError [WinError 32]` on still-mapped temp `.npy`/`.sqlite`, reproduced serially). The
run also wrote into the real DATA through the junction (§7, question 1), so it was not re-run.

### A — round 2 (bounded re-check; the first two launches were killed by usage limits)

**Verdicts.** Fidelity: every round-1 fidelity finding fixed or partly fixed in the live app, no
P0/P1, no placeholder leakage (`708` appears only as CH1_A1's real count). Backend: every round-1
backend finding fixed *in the running server*; core untouched; cache hits real (prefix timings 0.0,
restored Scores keep `m` via the sidecar); peaks exact at 721 h and 60 s; seven types dispatched;
M4 423 on every route. Robustness: every forced error visible, never blank; reload mid-run
re-attaches on the server clock; zoom over 721 h median round trip 9.4 ms (min 6.1 / max 69.1 over
23 fetches, paint median 12 ms).

**P0 (2, both real-data writes, neither fixable by deletion under rule 5).** The round-1 stray joblib
is still present (documented), and the **repo's own pytest suite wrote into the real DATA** through
the junction (DECISIONS §10; `REAL_DATA_WRITES.md` lists every file with size and hash).

**Fixed after round 2 (P2).** Literal "0N" in block-page copy; stale REPORT §5 (D-A3 reworded,
meta-sidecar noted, D-A13/D-A14 added); chain and block axes print their t0/t1 ends; a computed step
reads "computed · now cached" and the chip says "N computed · M from the step cache" instead of "all
cached"; a cancelled run names the step that never started; the block page says "▶ Run chain" when
nothing has run for the source; inferred "has null" chips removed; the dSAX in-plot key no longer
covers the strip; the amber threshold chip is legible; the recommend header no longer claims values
it does not have; a row render failure keeps its "render failed" badge until a new result arrives
(round 1 had fixed this only for the source row); Tab is trapped inside dialogs; estimates read "≤ N
core est.".

**Left open (stop rule).** Y-axis labels and matrix-profile motif chips still overprint traces in
chain rows; adding an eighth type still touches four files and the block page still dispatches on the
adapter name inside one 550-line file; Explore does not warn that a dragged span exceeds the default
chain's local ceiling (Analyse does); full keyboard operability of the heatmap and cut line; per-card
estimates in the insert modal; motif pairs from the core.

### B — round 1 (the only round, per your instruction; three critics; 2 P0, 8 P1, ~20 P2)

**Verdicts.** Backend: "mostly sound" — core untouched, writes only to B's runtime copy (0 files under
DATA/ or Results/ newer than 19:00), prefix cache really hit (suffix re-run timings 0.0 / 0.0 / 0.0002),
per-viewport re-fetch through the same envelope, M4 refused, failures reported honestly. Fidelity:
"B has the frames' structure right and gets the details wrong in the places where Panel/Bokeh widgets
had to stand in for designed components". Robustness: the Must flow works and every Panel round trip
was fast (modal open 270 ms, drag to parameter 73 ms, cached re-run 768 ms, viewport re-fetch
10–30 ms, heatmap first paint 1.14 s), "robustness is where it falls short, and the reason is the stack
itself".

**P0.** (1) The built-in gramian template's image row throws inside Bokeh's JavaScript and blanks every
chain row except Source, while the Python side (`/b/debug`) reports the image as drawn — the silent-pane
class, reached by an ordinary template the smoke test did not run. (2) The Cancel button lags the job
by up to one 200 ms poll; clicking a stale "■ Cancel" after completion silently starts a duplicate run
that writes detections (reproduced twice).

**P1.** Exceptions outside B's two hand-written try/excepts reach only `server.log` (step-row and
block-page renderers, the run poll, the viewport fetch, widget callbacks); a reload or a second tab
loses the sent span, the run link and its results because state lives in the Panel session; freshly
computed steps are badged "cached"; wheel zoom collapses the viewport to 0 s; a zero-length span is
accepted as the source with Run enabled; the "shared" time axis drifts 32 px from the rows although
they share one `Range1d`; all 22 insert-modal cards overflow and clip their reasons; the RangeTool span
box is 3.7 px wide with no grips and a move-drag makes a new selection.

**Stack evidence the three lenses agreed on.**
- *Loud failure.* In Panel a server-side exception becomes a log line and the old DOM stays; the browser
  console stays clean, so a Playwright console gate cannot see it. B is loud only where its author
  wrapped the code by hand; "forgot one wrapper" is a silent failure. In A the same mistake is a red
  card plus a console error that fails the gate. And B's P0 image bug shows the second face of it: the
  Python side can succeed while Bokeh fails in the browser.
- *Fidelity.* Every designed component (rich clickable card, grip handle, draggable line, dot-beside-
  checkbox, floating toast, anchored popover, the Inter font) had to be approximated from a widget or a
  Bokeh tool, and each visibly departs from its frame. A drew all of them directly.
- *State.* The Panel session is the unit of state; A keeps the draft in the client and re-attaches to
  runs by id, so A survives reloads and B does not without extra work.
- *In B's favour.* No transport to design (0 new service-layer lines), in-process cancel, no build step,
  and a shared axis that is conceptually one object.

**Fix pass (one, then stop).** Both P0s and all eight P1s fixed; B's smoke test green afterwards
(73 checks, 28 screenshots, 0 console/page errors). The image row now passes Bokeh a 2-D uint32 array
with the correct ABGR packing; a stale Cancel is refused ("run already finished"); computed steps read
"✓ computed" and only core timing 0.0 reads "cached"; every Panel callback, row renderer, poll tick and
viewport fetch now goes through a hand-written guard that draws a red card; zoom clamps at 30 s in the
browser and in Python; empty spans disable Run; the footer axis shares the rows' frame wrapper (0 px
drift); modal cards no longer clip; Inter applies through Bokeh's `--bokeh-base-font` variable; source
span and job id live in the URL hash so a reload or second tab re-attaches. **Left open:** RangeTool
grips and move-drag (stack limit), modal cards as rich cards (Panel has no clickable rich card),
whole-line threshold drag, row thumbnails versus the §6.8 type table, corpus rail details,
per-session debug evidence, icon buttons' accessible names.

The fix pass is itself stack evidence. Its agent reported that Panel 1.9 has no hook that surfaces
callback exceptions in the browser, so *every* `on_click`, `param.watch`, `on_change` and periodic
callback had to be wrapped by hand; `Range1d.min_interval` is not honoured by Bokeh 3.9's wheel zoom;
Panel `styles` pad the outer host while the inner shadow container keeps its width, so content spills
silently (two bugs); Bokeh's `:host` font rule overrides the page font; a click is judged against
server-side widget state that a poll repaints, so buttons cannot be disabled on click without extra JS;
and there is no per-browser storage primitive, so the URL hash had to carry state.


## 5. Deviations from the pages/spec, with justification

| # | Deviation | Why | Spec / frame |
|---|---|---|---|
| D-A1 | The default chain is Baseline removal (detrend) → Matrix profile → Threshold-to-spans, not baseline → noise floor → symbolic encoding → drop detection | `Encoding` is terminal in the registry: no adapter consumes it, so "Encoding → SpanSet" cannot exist. The brief says compose the closest real chain. dSAX, window-matrix/cluster/classifier and gramian chains are built-in templates so all seven types run | §6.1, chain-1 |
| D-A2 | The draggable control is the **threshold** on the Threshold-to-spans page, not SAX cutlines | SAX cutlines are *learned* by the adapters (Lloyd-Max / Mean-Shift / KDE) and surfaced in `meta.details`, not parameters; drawing them is honest but dragging them would assert a parameter the core does not have. The dSAX page draws the learned cutlines dashed and labelled "learned · not a parameter" | §6.8 row `Signal → Encoding`; chain-3 |
| D-A3 | Surrogate toggle is rendered OFF and disabled ("surrogate · not in this slice"), footers say "no null", the insert modal shows "null · not declared" rather than inferring one, and "This parameter against the null" is an explicit empty state | Null runs are out of slice scope; the core's null is a paired `preprocessing.surrogate` run, not a per-adapter declaration | §6.8 null column; chain-2, chain-3 |
| D-A4 | Progress is per step with an elapsed timer, never a percentage | `execute_recipe` reports `on_progress(i, n, …)` before each step and `on_step_result` after; no within-step fraction (except window_matrix's own callback) | chain-1d "64 % · 0.2 s left" |
| D-A5 | Cancel takes effect between steps | The core polls `should_cancel` once before each step | chain-1d Cancel |
| D-A6 | Header chips are real counts ("N need you" = failed jobs this session; "Jobs · N" = running jobs); the frames' "3 need you", "6 runs · 4 methods", "708 / 1284" are not copied | "Nothing claims more than it knows" (§3); real data wins | shell-header, explore-1/2 |
| D-A7 | Time axes are hours since recording start with adaptive decimals | §0 canon; the frames' "825 s … 875 s" only reads well because their example starts at t = 0 | §0; chain-1 |
| D-A8 | Morphology tags show count 0 with "no tags in this database"; "nearest family —" | The real DB has no tags and no library families for this channel | explore-1/2 |
| D-A9 | "input ghosted behind" is drawn on its own y scale and says so | −0.66 mV DC input vs ±0.003 mV detrended output | §6.8 row `Signal → Signal` |
| D-A10 | Inert controls are visible and titled "out of slice scope" (Cross-channel, Review actions, medoid overlay, bypass/duplicate/reorder, SLURM/upload, Analyse events, Pass to Review) | Brief: other workspaces visible but inert; keep the shape, do not fake behaviour | various |
| D-A11 | Save span / tags / note are client-side stubs that write nothing | Explore never writes verdicts (P6); no annotation write path exists in this prototype at all | §5.2 |
| D-A12 | Insert modal shows an estimate only for the selected card ("est. at run" on the others) | The core estimates a *recipe*, not a block; per-card estimates would need 22 hypothetical validations | chain-2 "≈ 0.2 s" per card |
| D-A13 | A stage over its local ceiling disables Run (with the reason) and the bridge refuses the run with 422; it does not pause at that stage and hand off to HPC | Pausing needs the manifest-inbox / SLURM flow, out of slice scope; running it locally fails at once | §12 P4, P24; §9.6; chain-1g |
| D-A14 | Estimates are shown as "≤ N core est." | `estimate_recipe_seconds` is a calibrated upper bound; measured 70–230× above actual on short spans, so "≈" would mislead | chain-1 "≈ 0.6 s" |

**Backend gaps wrapped or stubbed** (none required editing the core):
- No public read API for step outputs → payloads are built in `on_step_result` and kept in server memory per job. A cache-restored step loses `AdapterResult.meta` (SAX cutlines, MP window, model card) in the core; the bridge keeps a JSON meta sidecar per prefix hash at first compute and restores it on a hit, so cached re-runs show the same detail.
- `validate_recipe_steps` reports only the first bad junction, and treats an unknown adapter as valid → `server/chain.py` walks every junction with `check_step_compatibility` and reports unknown blocks as invalid.
- `UI/analyse/chain_state.py` cannot be imported headless through its package (pulls Panel) and has no insert-at-position check → not reused (DECISIONS §4).
- Step cache only writes steps > 1.0 s → `STEP_CACHE_WRITE_THRESHOLD_S` set to 0.0 in the redirected runtime.
- Three adapter-level writable paths (`RESULTS_DIR` ×2, `MODEL_ROOT`) are read at call time → rebound to the runtime dir.
- `detections.score` holds `inf` in the real DB → mapped to null (JSON has no inf).
- STUMPY numba JIT cold start ~30 s → warmed at startup in a thread.
- `detection.wavelet_scattering` fails at run time on this machine (kymatio/scipy) → listed, flagged "known broken" in the modal.
- Gramian adapters cap the span at 5,000 samples → the modal/rows show the over-ceiling card; the template says so.
- `estimate_recipe_seconds` is ~70× pessimistic for MP on short spans → shown with "≈".
- SpanSet indices are span-relative at the producers → shifted by `span_start` in the seam (WindowSet starts are absolute; handled once, in `serialize.py`).

## 6. Screenshot index (screenshot → concept frame)

`ui-prototypes/A-react-fastapi/screenshots/` (smoke run 2, 1440×900):

| screenshot | frame |
|---|---|
| 01-explore-1-corpus.png | explore/explore-1-corpus.pdf |
| 02-explore-1-corpus-colour-by.png | explore-1-corpus (colour-by segmented control) |
| 03-explore-1-corpus-selected.png | explore-1-corpus (selected row + bottom bar) |
| 04-explore-2-signal.png | explore/explore-2-signal.pdf |
| 05-explore-2-signal-zoomed.png | explore-2-signal (tier 2 after wheel zoom + pan) |
| 06-explore-2-signal-motif.png | explore-2-signal (tier 3 motif) |
| 07-explore-m4-held-out.png | shell-header "M4 held out" (locked state) |
| 08-chain-1-chain-before-run.png | analyse-chain/chain-1-chain.pdf (new badges) |
| 09-chain-2-insert-stage.png | analyse-chain/chain-2-insert-stage.pdf |
| 10-chain-1-chain-completed.png | chain-1-chain (cached badges; Scores row as chain-1h) |
| 11-chain-7b-block-threshold.png | analyse-chain/chain-7b-block-threshold-to-spans.pdf |
| 12-chain-7b-block-threshold-dragged.png | chain-7b after dragging the threshold |
| 13-chain-1-chain-suffix-rerun.png | chain-1-chain (01/02 `cached · 0 s`) |
| 14-chain-1b-run-history.png | analyse-chain/chain-1b-run-history.pdf |
| 15-chain-1e-invalid-junction.png | analyse-chain/chain-1e-invalid-junction.pdf |
| 16-chain-1f-failed-block.png | analyse-chain/chain-1f-failed-block.pdf |
| 17-chain-1d-running.png | analyse-chain/chain-1d-running.pdf |
| 18-chain-cancelled.png | chain-1d after Cancel |
| 19-loud-failure-render-error.png | (evidence) thrown render error |

`ui-prototypes/B-panel/screenshots/` uses the same numbering (01–18 pair to the same frames as A's),
plus `19-loud-failure-render-error.png` (B's caught `?throw=1` card), `20-loud-failure-uncaught.png`
(Corpus still painted while the URL is `#analyse/chain`, console clean) and
`loud-failure-main-try-commented/{navigate-from-corpus,fresh-deep-link}.png` (the same with the router's
try/except literally commented out). Compare A's and B's same-numbered screenshots side by side.

The builders' own walkthrough screenshots (dev servers) are under `screenshots/dev-explore/`
and `screenshots/dev-analyse/` (includes dsax, windows_model, templates, run-log modal,
reload-mid-run).

## 7. Open questions and recommended next step

**Recommendation: build on A — React + TypeScript (Vite) with SVG charts drawn directly on d3
scales, over a thin FastAPI bridge to the untouched core.** Runner-up: **Panel + Bokeh (B)**, which
lost on loud failure (silent by default, loud only where every callback is wrapped by hand), on
fidelity to the designed pages, and on state that does not survive a reload; it would win only if
avoiding a second toolchain (Node) outweighed those, which #12's weighting says it does not.

What A's evidence says to carry into the build ticket:
- Keep the **one serialiser per interchange type on the server and one renderer switch on the
  client**; it held for all seven types and survived two critique rounds.
- The bridge is the part that needs its own tests: SSE with a polling fallback, cancel between
  steps, reload re-attach, the meta sidecar for cache-restored steps, the held-out guard on every
  route. A's `server/` is a usable starting point, not a spike to discard.
- Plotting: d3 scales + hand-written SVG was fast to build and fully faithful at these densities
  (≤ ~3k points per path). Publication export was out of scope; #12 still has to decide it
  (the SVG is exportable, but matplotlib parity was not tested).
- Toolchain consequence for #12's sign-off: Node 25 + npm for the client (project-local
  `node_modules`), FastAPI + uvicorn for the bridge (a project-local venv worked alongside the conda
  env without conflicts).

Next step: take this to #12 as the decision record (an ADR is warranted), then open the three
downstream tickets #12 names — how the frontend reaches the core (A's bridge is the proposal),
where the new tree lives, and its test gates (A's Playwright smoke pattern is the proposal).

Open questions for you:
1. **Files written into the real `DATA/` during the night — none deleted, all yours to decide.**
   - `DATA/derived/models/catalogue_classifier_153815b9dea451b2.joblib` (14 kB): written by a
     read-only *reader* subagent that executed the classifier adapter directly (§4, P0).
   - Written by **the repo's own pytest suite** when I ran it as the brief's rule 7 asked, because
     the worktree's `DATA` is a junction to the real data while the tests assume a local fixture
     `DATA/`: 5 step-cache files re-written with identical sizes, 5 `UNITTEST_encoding_view*` text
     files, 4 new classifier joblibs and one existing one (`…f918586712c715e2`) overwritten.
     Exact list in DECISIONS.md §10. `annotations.sqlite` is unchanged.
   - Worth a ticket: the brief's junction-plus-pytest combination is unsafe for this repo; either
     tests redirect `STEP_CACHE_ROOT`/`MODEL_ROOT`/`ENCODING_ROOT`, or worktrees get a copied DATA.
2. **Time axis convention.** Spec §0 says hours since recording start; frame chain-1 prints
   seconds for a 50 s span at t = 0. A uses hours with span-adaptive decimals everywhere. Confirm.
3. **SAX cutlines.** §6.8 asks for draggable cutlines on the Encoding page, but the adapters learn
   them and expose no parameter. Should the adapters grow an explicit `cutlines` override
   parameter (core change), or should the page keep them read-only ("learned") as A does?
4. **Over-ceiling stages.** A refuses to run a chain with a stage over its local ceiling
   (P4/P24 say "pause and hand to HPC"); implementing the pause needs the manifest-inbox flow,
   which is out of slice scope. Confirm refusal is the right interim.
5. **Progress granularity.** Only `window_matrix` reports within-step progress. If the running
   frame's "64 % · 0.2 s left" matters, adapters need to accept `on_progress`.


## 8. Head-to-head scorecard (added 2026-09-15, after review)

Written because the two prototypes' differences were not obvious from §1–§7, which are organised by
evidence type rather than by the quality a reader cares about. The scores (out of 10) are judgement,
each anchored to a measurement or observation in this report. The rows are not equally weighted,
so no total is given: a silent-failure row outweighs a disk-space row. **You chose A on this basis.**

### 8.1 New measurements behind the scorecard

§3 measured zoom and run latency but not page load, memory or footprint. These were taken after the
overnight run with `ui-prototypes/bench_ab.py`, which writes `bench_result.json`.

- **Method.** Both servers were started on spare ports (8775/8776) against their own runtime DB copies.
  Headless Chromium at 1440 × 900 ran 3 runs per prototype, each in a fresh browser context (empty cache).
  Then the same page was reloaded (warm cache), and the app navigated in place from Corpus to Signal
  (channel 4, 721 h). Both servers were stopped afterwards, and no port was left open.
- **"Painted" means different things per prototype.**
  - For A, it means ≥ 448 heatmap cells in the DOM, or ≥ 1 path in the signal overview.
  - For B, it means the Python side reports 912 heatmap rects and a canvas is attached, or the Signal page's text and ≥ 2 canvases are present.
  - B's check is coarser: it does not wait for pixels. **B's times are therefore, if anything, flattering to B.**

| measure | A | B |
|---|---|---|
| server start → first HTTP 200 | 3.8 s | 7.1 s |
| Corpus page, empty cache → painted (3 runs) | 624 / 624 / 603 ms (median 624) | 1,091 / 903 / 869 ms (median 903) |
| Corpus page, reload with warm cache | median 213 ms | median 435 ms |
| in-app navigation Corpus → Signal (721 h) | median 109 ms | median 544 ms |
| bytes to the browser on the first visit | 571 kB over HTTP | 3,074 kB over HTTP + 691 kB over the websocket |
| browser JS heap after the three pages | 9.5 MB | 31.6 MB |
| server memory (process tree), idle → after 3 runs | 388 → 507 MB | 488 → 521 MB |

**Both** prototypes still take the ~30 s STUMPY JIT warm-up on the first matrix-profile run of a server
process (§3). The startup numbers above do not include it.

**Footprint on disk.**

| | A | B |
|---|---|---|
| new installs | `client/node_modules` 97 MB (development only) + `.venv` 20 MB (FastAPI/uvicorn on top of conda via `--system-site-packages`) | none (Panel 1.9.3 + Bokeh 3.9.2 already in the conda env; the two packages occupy ~150 MB there) |
| what is served to the browser | `client/dist`: 457 kB JS + 33 kB CSS (130 kB JS gzip); the 1.7 MB source map is not needed at runtime | Bokeh + Panel bundles, ~3 MB on the first visit (table above) |
| source written | ~5,300 lines TypeScript/CSS + ~1,660 lines Python bridge | ~2,900 lines Python (plus the parts of A's service layer it imports) |
| runtime copy per server start | 4.2 MB DB copy; grows with step caches (one 20 h matrix-profile session reached 285 MB) | same (two sessions reached 100 MB) |

The runtime directories are never cleaned up. At this point they hold 772 MB for A and 502 MB for B.
The rebuilt app will need a retention policy for them.

### 8.2 Scorecard

**Plotting and large data**

| quality | A | B | evidence |
|---|---|---|---|
| 721 h signal (2.6 M samples) | 9 | 8 | Both use the same server-side min/max decimation to ≈ 2,500 points per view, and both are interactive at every zoom. |
| headroom for very dense plots (tens of thousands of marks at once) | 6 | 9 | A draws SVG, which degrades past roughly 10–20k elements; canvas/WebGL would have to be added by hand. Bokeh draws to canvas, with WebGL built in. Untested at that density in either prototype. |
| zoom/pan lag | 9 | 7 | Median round trip is A 9–20 ms and B 23 ms (§3). A moves the old path instantly with a CSS transform during the gesture; B waits for the websocket reply. |

**Speed and size**

| quality | A | B | evidence |
|---|---|---|---|
| server start | 9 | 7 | 3.8 s vs 7.1 s |
| first page load | 8 | 6 | 0.62 s vs 0.90 s |
| reload | 9 | 6 | 0.21 s vs 0.44 s |
| page switch | 9 | 5 | 0.11 s vs 0.54 s |
| download per first visit | 9 | 5 | 0.57 MB vs 3.8 MB |
| browser memory | 9 | 7 | JS heap 9.5 MB vs 31.6 MB; server memory similar |
| disk space for installs | 5 | 9 | 117 MB of project-local installs vs none |
| amount of code | 5 | 7 | ~7,000 lines vs ~2,900 (+ borrowed modules) |

**Frontend design features**

| quality | A | B | evidence |
|---|---|---|---|
| match to the concept pages | 9 | 5 | A drew every designed component. B approximated cards, grips, popovers and fonts with widgets (§4, B round 1). |
| custom interactions (drag handles, draggable threshold, crosshair) | 9 | 6 | B's span box has no grips, and B's threshold value lands only on release, with an x snap-back round trip. |
| one time axis shared across rows | 8 | 9 | B's is one `Range1d`; A synchronises the rows by hand (it works). |
| all seven interchange types drawn | 9 | 8 | Both draw all seven. B's gramian image row blanked the whole chain until the fix pass. |

**Reliability and development**

| quality | A | B | evidence |
|---|---|---|---|
| errors are visible (never a silent blank) | 9 | 3 | The decisive row (§2, §3). B is loud only where each callback is wrapped by hand. |
| survives reload / a second tab | 8 | 5 | B needed the URL hash to carry state. |
| automated tests catch breakage | 8 | 5 | A's Playwright gate fails on any console error. B's errors never reach the browser, so its gate needs `/b/debug` plus `server.log`. |
| plumbing to the core | 5 | 9 | A needs its own bridge (SSE with a polling fallback, cancel, reload replay, meta sidecar). B calls the core in-process. |
| toolchain simplicity | 5 | 9 | A adds Node, npm, TypeScript and a build step. B is pure Python. |
| fit with the existing repo | 4 | 9 | `UI/`, `tests/ui`, `scripts/dev_serve.py` and CLAUDE.md all assume Panel. A means a new tree and new test gates. |

**Reading the scorecard.** A wins on what the person using the app sees and feels: speed, fidelity
to the pages, and failures that show. B wins on what the person maintaining it carries: one language,
no bridge, the existing repo's shape, and dense-plot headroom. The cost of choosing A is concentrated
in the last three rows. Two of them are one-off: the bridge is written, and the tree move is a single
merge. The third is permanent: a second toolchain. #12's weighting down-weights exactly that cost.

**Additional findings from this pass.**
- **Dense plotting is A's one real technical ceiling.** If a future page must draw tens of thousands of
  marks at once (e.g. every detection across a recording as a scatter, or a large recurrence matrix),
  A's renderer for that page should draw to `<canvas>`. Examples: a library such as uPlot or regl, or a
  hand-written canvas layer like A's image rows. Keep the same seam: one renderer per interchange type.
- **Runtime directories accumulate** (see 8.1). Decide a retention policy when the bridge graduates
  from prototype.
- **Old servers can linger on the default ports.** The benchmark found 8765 and 8766 already occupied
  by manually started prototype servers. Start scripts should fail loudly on a busy port rather than
  appear to start.
