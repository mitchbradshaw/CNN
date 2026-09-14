# DECISIONS.md — running log for the UI stack prototypes (issue #12)

Started 2026-09-14 ~13:00 UTC. Worktree `C:/Users/mmebr/Documents/CNN-ui-proto`, branch
`proto/ui-stack-slices`. This file is also my memory if context is compacted: every choice
and its reason goes here as it is made, newest section at the bottom.

## 0. Setup facts (do not re-derive)

- Worktree created from `main` @ 208e72c. `DATA/` in the worktree is a **junction** to the real
  `C:\Users\mmebr\Documents\CNN\DATA`. The worktree's own checked-out `DATA/` (only
  `README.md` + `library_seed/`) was **moved aside** (not deleted) to the session scratchpad
  (`.../scratchpad/DATA_worktree_checkout_moved_aside`) before the junction was made.
- Consequence: `git status` shows ` M DATA/README.md` because the real README differs from the
  tracked one. **Never `git add -A` or `git add DATA`.** Always `git add ui-prototypes`.
- Issue #12 assigned to me (tracker write 1 of 2). The only remaining tracker write is the
  closing summary comment.
- DATA mtime snapshot at start: `ui-prototypes/DATA_MTIMES_START.txt` (db: annotations.sqlite
  mtime 1789297374, size 4349952; step_cache: 6 files under 11 dirs).
- Python with deps: `"/c/ProgramData/anaconda3/python.exe"`. Bare `python` in Bash is 3.13 with
  nothing. `gh` is `"/c/Program Files/GitHub CLI/gh.exe"`.
- Real DATA layout: `DATA/db/annotations.sqlite` (+ a .bak), `DATA/derived/{channels,step_cache,
  encodings,models,windows,...}`, `DATA/raw`, `DATA/catalogue`, `DATA/fixture`.
- Held-out recording: `M4_aug_concat_fs1.mat` — the UI must refuse it (spec §0 D6, header chip
  "M4 held out").
- Venv for A: `ui-prototypes/A-react-fastapi/.venv` (system-site-packages + fastapi + uvicorn).
  Client scaffold: `ui-prototypes/A-react-fastapi/client` (Vite react-ts + d3).

## 1. What the concept pages actually ask for (read 2026-09-14)

Frames read: shell-nav-rail, shell-header, explore-1-corpus, explore-2-signal, chain-1-chain,
chain-2-insert-stage, chain-1d-running, chain-1e-invalid-junction, chain-1f-failed-block,
chain-1h-scores-chain, chain-3-block03-symbolic-encoding, chain-7-block-matrix-profile-scores.

- **Shell.** 64 px nav rail, white, blue logo tile top; icons + 11 px labels: Explore, Analyse,
  Discovery, Models, Review, Library; foot: Jobs · 3, divider, Settings. Header: bold workspace
  name, thin divider, page name, muted mono subtitle; right: search pill "Search spans, runs,
  families  Ctrl K", blue chip "● 3 need you", grey chip "🔒 M4 held out". Page ground is
  #F5F6F8-ish; cards are white with 1 px #E5E7EB border, 10 px radius. Mono (Geist Mono) for
  data/labels, Inter for headings.
- **Explore › Corpus.** Toolbar: recording select (db icon, "M2_aug_concat_fs1.mat 16 ch · 721 h ·
  1 Hz"), pager "1 / 5", time range slider "0 – 721 h", bin "auto · 12.6 h", colour by
  [annotations | detections | both | disagree] segmented control. Card "COVERAGE MAP  16 channels ·
  0 – 721 h · bin 12.6 h" with legend low→high (5 blues), 16 rows × ~57 bins (721/12.6=57.2),
  channel labels mono on the left, selected row outlined blue with label in blue, x axis 0 h … 721 h.
  Right rail: Show (annotations ✓, detections ✓, reviewed coverage, unreviewed only), Detections
  from (runs all · 34, method any · 7), Verdict (seed, interesting, not_interesting, artifact,
  unsure with colour dots), Morphology tag (sharkfin…), "matching 412 spans / across 11 of 16
  channels". Bottom bar: "CH4_A2  708 annotations · 1284 detections · 184 disagree · 62 % reviewed",
  buttons "Cross-channel from CH4_A2" and blue "Open CH4_A2 →".
- **Explore › Signal.** Breadcrumb "Corpus › M2_aug_concat_fs1.mat › CH4_A2", segmented
  [Signal | Cross-channel], "detections 6 runs · 4 methods ▾", "display raw ▾", "‹ back to corpus".
  Tier 1 CHANNEL 0 – 721 h: full-channel overview trace, blue selected-span box with two blue grip
  handles, below it a green/orange/red coverage ribbon and a blue detection-density bar ribbon,
  axis 0 h … 721 h. Tier 2 SPAN 276.4 – 278.4 h · 2.0 h, nav "‹ 233 / 344 ›", zoom -/+/fit icons;
  trace on light ground with tinted bands: blue (detected), green (annotated), orange (selected)
  + caps above; y axis "+0.4 mV / 0 / −0.4 mV"; legend dots. Tier 3 MOTIF_233 with ONSET/END lines,
  "context ±20 s", "overlay F-03 medoid", buttons "Send motif to Analyse →", blue "Review this
  motif →". Span-action row: tags chips, note input, "Save span", "Send span to Analyse →", blue
  "Take span for Review →", caption "saving stores tags and note only · verdicts are given in
  Review". Four collapsed ribbons: Filters & search, Annotations 708, Detections 1284, Keyboard
  shortcuts.
- **Analyse › Chain.** Toolbar: name chip "drop_motifs9 · unsaved", source chip (blue, waveform
  icon) "Signal span · CH4_A2 · 825–875 s ▾", surrogate toggle "surrogate 200×", amber estimate
  "≈ 0.6 s · 03 → 04", buttons History, Import, Save template, blue "Re-run from 03". Rows: left
  panel (drag handle, number + name, badge + type signature, one-line summary, icon row: settings ·
  bypass · duplicate · delete) and a plot on the right; all plots share one x axis; "+ insert" pill
  between rows; footer axis "all rows share this time axis  825 s … 875 s". Footer card: green
  chip "terminal SpanSet → detection template", "last run · 6 detections kept", caption, buttons
  Export run, Analyse events, blue "Pass 6 to Review".
  Badges: cached (green), stale (amber, plus "last run shown · stale" pill over the plot and a veil),
  new (blue-grey), running (blue; progress bar drawn over the plot with "estimating slope noise · 64 %
  · 0.2 s left"; downstream rows "waits for 02 · last result hidden" with hourglass), failed (red;
  red-bordered row with an error card in place of the plot: title "04 Drop detection failed after
  0.3 s", the exception line, "adapter drop_detect v3 · recipe a7f39c · traceback in log", buttons
  View log · Open settings · blue Retry 04; toolbar "failed at 04 · 01–03 cached", "Retry from 04";
  footer "No result / run #134 failed at 04 · nothing was written to detections"), invalid junction
  (red row border, red pill between rows "⊗ 04 Drop detection needs Encoding · 02 Noise floor emits
  Signal", buttons "+ Insert Symbolic encoding here", "Show blocks that fit"; toolbar "1 invalid
  junction", Run disabled; footer "Chain is invalid / fix the red junction · validation runs on every
  edit"; toast "03 Symbolic encoding deleted  Undo Ctrl Z").
- **Insert stage modal (chain-2).** Title "Insert a stage between 03 … and 04 …", chain ribbon with
  "+ new stage" slot, three pills "03 outputs Encoding → [new stage accepts Encoding → emits
  Encoding] → 04 requires Encoding", "4 of 21 blocks fit"; search, category tabs
  (all/preprocess/encode/detect/cluster/model/control), "sort fits first", toggle "show
  incompatible". Grid of cards: glyph 44×26, name, signature, "≈ 0.2 s", "has null/no null",
  "✓ fits here" or red reason "needs Signal · here: Encoding". Right detail panel: name, signature,
  glyph 272×96, description, defaults table, est. cost / null / side-inputs tiles, amber "04 goes
  stale · 00–03 stay cached", note "inserting at the end changes the terminal type". Footer:
  "21 blocks in the registry · a new technique is one adapter file", Cancel, Insert, blue "Insert
  and open settings".
- **Scores row (chain-1h).** Series against time, surrogate p5/p95 band behind, top locations marked
  (M1a/D1/M1b/M2 labels green/red), legend inside bottom-right, y label "z-norm distance". End of
  chain: "+ insert · end of chain" then a suggestion card "Scores → SpanSet fits here — Threshold to
  spans · Top-k motif pairs · Peak picker — 3 blocks accept Scores", "Browse compatible", blue
  "Insert Threshold to spans".
- **Block page (chain-3 SAX).** "‹ full chain", chain ribbon with the open block highlighted, main
  card with four aligned strips (signal + PAA; slope + cutlines with draggable red lines labelled
  d/D/U/u values; quantised k5; dSAX k3), legend; Parameters panel (alphabet k segmented 3/4/5,
  split select, segment length slider, same_fraction slider, noise floor slider "= recommended · the
  sweep knee", edges select; stat tiles segments/qualify as d/qualify as u/in SAME; info line);
  "This parameter against the null" sweep bar chart; footer "No unapplied changes … Revert to
  recommended · Re-run from 03".

## 2. Stack ranking (before building; will be revised in REPORT.md with what building taught)

Discriminators, from the pages + spec + audit §4–6: (1) draggable plot controls bound to
parameters, (2) many rows on one linked time axis with a hover crosshair, (3) heatmap 16×57,
(4) image-per-window stacks, (5) ~22 small multiples, (6) live run state (progress, cancel,
badges), (7) a *very* specific visual system (nav rail, chips, pills, cards, modal card grids,
Geist Mono/Inter, light grounds, thin lines, tinted bands, never normalised), (8) loud failure,
(9) agentic throughput, (10) publication export (low priority for this slice).

| Family | Verdict | Why |
|---|---|---|
| **React + TypeScript (Vite) + FastAPI bridge; charts hand-rolled in SVG/canvas with d3 scales/zoom** | **A — build first** | The pages are a bespoke web design, not a dashboard: chips, pills, badges, modals, a card grid, a nav rail. A component framework reproduces that 1:1 with plain CSS; every Python-native framework has to fight its own widget styling to get there. Shared time axis, crosshair, draggable cutlines and tinted bands are all one `xScale` in SVG — no library boundary in the way. Loud failure is structural: a React error boundary + Vite's dev overlay + a FastAPI 500 with a traceback are each visible without configuration. Largest agent corpus. Cost: a bridge (progress thread→loop, cancel, 7-type serialisation) that this slice must design — which is exactly the evidence #12 lacks. Node is available; FastAPI installs into a project-local venv. |
| Panel 1.9.3 + Bokeh (rebuilt without HoloViews DynamicMap) | **B — second family** | Incumbent; must win or lose on evidence (#12). In-process callbacks and cancel, no transport to design, decimator ports directly. Cost: the visual system needs heavy CSS overrides; a shared axis across rows is Bokeh `x_range` linking; draggable cutlines are Bokeh `Span` + a `PointDrawTool`-style hack or a slider; the insert-stage modal is a `pn.Modal`/Column with custom HTML; silent-failure remains the open question — this prototype measures it. Nothing to install. |
| Dash / NiceGUI (Python-native, Plotly/ECharts) | C if budget | Same family as B (Python UI over a WS); NiceGUI's Quasar/Vue components are closer to the design language than Panel's. Needs pip into a venv (allowed). Lower priority than proving A and B. |
| Desktop Qt / PySide6 + pyqtgraph | dropped | The spec is written as a web app ("this browser" in §9.15/9.16 personal settings, Ctrl-K search, "the site" in §6.8). No HTML output path. Every renderer custom. PySide6 is not installed and a pip wheel into a venv alongside conda numpy is untested on this machine. Not worth a slice. |
| Desktop-wrapped webview (pywebview/Tauri/Electron) | dropped | Adds a shell to the JS family without answering any open question; single-machine localhost has no packaging problem to solve. |

**Chart layer for A.** d3-scale/d3-zoom/d3-shape + React-rendered SVG (and a `<canvas>` for the
2.6M-sample overview trace if SVG proves slow). Reasons: total control over the visual rules;
one `xScale` shared by every row; drag handles are `<rect>`s with pointer events; the smoke test
can assert `path[d]` length and canvas pixel variance. uPlot/ECharts were considered: faster
canvas out of the box, but their styling and drag affordances are plugin territory and agents
know d3 idioms better. The trade is recorded as evidence to measure (zoom latency).

## 3. Service-layer seam for A (draft; refined after backend readers report)

`ui-prototypes/A-react-fastapi/server/` — a thin FastAPI app that imports `Working/` and
`Adapters/` from the worktree root **unchanged**.

Runtime isolation (rule 2): on startup copy `DATA/db/annotations.sqlite` to
`ui-prototypes/A-react-fastapi/runtime/<stamp>/annotations.sqlite` (dev_serve pattern), set
`Working.config.STEP_CACHE_ROOT` to `runtime/<stamp>/step_cache` (absolute) and
`STEP_CACHE_WRITE_THRESHOLD_S` to 0.0 so short-span steps are cached and the suffix re-run test
is meaningful, and never import `UI.viewer.session` (its SESSION_STATE_PATH is the old tree's).
`DATA/` is opened read-only (`.npy` via `np.load(mmap_mode='r')`).

Endpoints (JSON unless noted):
- `GET /api/recordings` — grouped by file; `held_out: true` for M4; `GET` of an M4 channel → 423.
- `GET /api/corpus/{file}/coverage?bins=57&colour_by=…` — rows × bins counts from annotations
  and detections tables.
- `GET /api/channels/{id}/window?t0&t1&px` — bucketed min/max envelope of the viewport
  (`_minmax_decimate` copied with attribution into `server/decimate.py`).
- `GET /api/channels/{id}/spans?t0&t1` — annotation + detection spans in view (capped).
- `GET /api/adapters` — registry: name, in/out types, params (name/type/default/bounds), estimate.
- `POST /api/chain/validate` — steps → per-junction status + reason strings; per-position
  compatibility for the insert modal.
- `POST /api/runs` → `{run_id}`; `GET /api/runs/{id}/events` — **SSE** stream of
  `{step, phase, fraction, elapsed, cached, error}`; `POST /api/runs/{id}/cancel`;
  `GET /api/runs/{id}` — snapshot for reload-mid-run; `GET /api/runs` — history.
- `GET /api/runs/{id}/steps/{i}` — the step output serialised by **one server-side seam**
  `serialize.py: to_payload(value, t_axis)` keyed on the seven types; the client has **one**
  `Renderer.tsx: renderByType(payload)` keyed on `payload.type`.

Transport rules: bulk arrays never cross — the server ships decimated envelopes (≤ ~2× px
points), capped span lists, symbol strips, base64 PNG thumbnails for image stacks, and a
metadata card for Model. Progress crosses thread→event-loop through `loop.call_soon_threadsafe`
onto an `asyncio.Queue` per run. Cancel is a `threading.Event` read by `should_cancel`. Client
disconnect does **not** cancel (the run finishes and its snapshot survives reload).
