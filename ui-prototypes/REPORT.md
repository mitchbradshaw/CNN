# REPORT.md — UI stack prototypes for issue #12 (overnight, 2026-09-14 → 15)

Branch `proto/ui-stack-slices`, worktree `C:/Users/mmebr/Documents/CNN-ui-proto`. Running log with
every decision: `DECISIONS.md`. Checklist: `CHECKLIST.md`.

> DRAFT — sections 1, 2, 4 and the B column are completed at close-out.

## 1. Summary table

| Prototype | Stack | Start (one command) | URL |
|---|---|---|---|
| **A** | React 19 + TypeScript + Vite 8 + d3 (SVG) · FastAPI/uvicorn bridge in a project-local venv | `ui-prototypes/A-react-fastapi/start.ps1` (Git Bash: `./start.sh`) | http://127.0.0.1:8765 |
| **B** | Panel 1.9.3 + Bokeh 3.9.2, in-process (reuses A's service modules) | `ui-prototypes/B-panel/start.ps1` | http://127.0.0.1:8766 |

| Checklist item | A | B |
|---|---|---|
| 1 Shell (rail + header; Explore/Analyse live, others inert) | done | |
| 2 Explore › Corpus (real heatmap, colour-by, selection → bottom bar, Open) | done | |
| 3 Explore › Signal (721 h pan/zoom, per-viewport decimation, tinted bands, send span) | done | |
| 4a Composition (source row from the span; insert modal with real adapters, disabled with reasons) | done | |
| 4b Rows on a shared axis, badges, one-line summaries | done | |
| 4c One dispatch seam over all seven types; awkward types real | done — Scores, Encoding (symbolic), WindowSet, Grouping, Model all run for real; Encoding image runs only on spans ≤ 5000 samples (core cap) | |
| 4d Run against the untouched core on the DB copy; live per-row progress; cancel; running/failed/invalid states | done (progress is per step — the core reports no within-step fraction) | |
| 4e Suffix re-run shows prefix rows `cached · 0 s` | done (core `step_timings` 0.0 on the prefix) | |
| 5 Block page with a draggable control bound to a parameter | done — Threshold-to-spans page: draggable threshold over the score series and histogram; marks downstream stale. (SAX cutlines are learned by the adapters, not parameters — see §5) | |
| 6 Run history popover; Save template | done (history from the DB copy + live jobs; templates saved to the DB copy) | |
| 7 Export run (simple report) | partial — JSON export of recipe + timings + payloads under `runtime/<stamp>/exports/`; no rendered figures | |
| 8 Cross-channel view | missing (button present, inert, labelled out of scope) | |

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

**B is judged in §3 and §4 after its build**; the closing recommendation is in §7.

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

### B — Panel + Bokeh

(filled after B is built)

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

The builders' own walkthrough screenshots (dev servers) are under `screenshots/dev-explore/`
and `screenshots/dev-analyse/` (includes dsax, windows_model, templates, run-log modal,
reload-mid-run).

## 7. Open questions and recommended next step

(finalised at close-out; the items below are the ones already known after A)

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
