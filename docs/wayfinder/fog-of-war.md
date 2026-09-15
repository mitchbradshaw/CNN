# Fog of war — carry-forward for the whole-project map

This file collects every question that is still open across the Underground Brains pipeline and its interface, as of **2026-09-16**, the night the map [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] closes. It seeds a future wayfinder map covering the whole pipeline and project, of which that map was one subsection. Items decided that night are not listed: the stack (React 19 + TypeScript + Vite + d3/SVG over a FastAPI bridge, `docs/adr/0001-web-ui-stack.md`), the tree at `webui/` against a throwaway runtime, its gates (`webui/smoke.py` + `tsc -b` + `vite build`), the HTTP JSON + SSE seam speaking the seven interchange types through one serialiser and one client renderer switch, and keeping `UI/` intact but ignored.

Cite items as "fog-of-war.md §Core seam C3". Each item carries one status:
- `ticketable now` — precise enough to open as a decision or task ticket today.
- `fog` — in scope, but not yet sharp enough to ticket; needs grilling, evidence or the researcher.
- `out of scope` — ruled out; listed only so it is not rediscovered as fog.

Rows from `prototyping/UI_FUNCTIONAL_SPEC.md` §12 (decisions that depart from the PRD) appear as confirmation items, grouped under each area's "PRD departures to confirm" heading.

## Core seam and data

### C1 — Public read API for step outputs
- **Question** — What public core function returns a step's output (value plus adapter meta) for a given recipe prefix, so the bridge stops keeping payloads in server memory and a JSON meta sidecar per prefix hash?
- **Why it matters** — The only path today is private `_recipe_prefix_hash` → `get_step_artifact` → the type's `from_path`, and a cache-restored step loses `AdapterResult.meta` (SAX cutlines, MP window, model card) in the core; the bridge papers over both, and a server restart loses every finished job's payloads.
- **Source** — [Decide how the frontend reaches the core and the database][frontend-core] "concrete gaps" bullet 1; [Correct the four factual errors in UI_CONTEXT.md][ui-context] correction 4; `ui-prototypes/REPORT.md` §5 "Backend gaps wrapped or stubbed" bullet 1, §7 "carry into the build ticket".
- **Status** — `ticketable now`

### C2 — `init_db()` cost on every connection
- **Question** — Should `init_db()` split into a once-per-process migrate-and-rebuild and a cheap connect, given it runs additive migrations and a verdict-table rebuild on every call and the bridge calls it per job (`webui/server/runs.py:129`, `:150`)?
- **Why it matters** — Every opener pays for migrations and a rebuild; with job threads, or the old and new servers, opening the same file, repeated rebuilds are the likeliest source of writer contention once a real-database mode exists (C9).
- **Source** — [Decide how the frontend reaches the core and the database][frontend-core] gap 3 (`Working/database/schema.py:622-645`); [Decide where the new tree lives and how both trees are served][tree-location] "Whether they can run at the same time".
- **Status** — `ticketable now`

### C3 — Adapter self-description (the registry's shape)
- **Question** — What must an adapter declare so a non-Python caller can describe it without reading its code: its null (none is declared today), whether it reports within-step progress, which learned values it exposes, its span ceiling, and a calibrated cost estimate?
- **Why it matters** — The bridge infers or stubs each of these ("null · not declared", cutlines drawn "learned · not a parameter", "≤ N core est."), and every new page repeats the inference. What adapters compute is frozen; how they declare themselves is open. The sharp halves are C4, C5, A1 and A2.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Not yet specified" (adapter self-declaration); [Decide how the frontend reaches the core and the database][frontend-core] sub-question 5; `ui-prototypes/REPORT.md` §2 "The core's shape, not the frontend, set most limits", §5 D-A2, D-A3, D-A4, D-A14.
- **Status** — `fog`

### C4 — Within-step progress
- **Question** — Should adapters accept an `on_progress` fraction callback through `execute_recipe` (only `window_matrix` reports one today), or does the interface settle for per-step progress with an elapsed timer?
- **Why it matters** — The designed running frame ("64 % · 0.2 s left", chain-1d) cannot be honest without it, and a whole-channel matrix profile runs for hours behind an indeterminate bar.
- **Source** — `ui-prototypes/REPORT.md` §7 open question 5, §5 D-A4; `ui-prototypes/DECISIONS.md` §4 "Progress is per step"; [Correct the four factual errors in UI_CONTEXT.md][ui-context] correction 4 (four progress channels).
- **Status** — `ticketable now`

### C5 — Estimate calibration and per-block estimates
- **Question** — Should `estimate_recipe_seconds` be recalibrated (measured 70–230× pessimistic on short spans), and should the core estimate a hypothetical recipe so the insert modal can show an estimate on every card?
- **Why it matters** — Estimates drive local-versus-HPC routing and over-ceiling refusal (A3); a 70× overestimate refuses runs that take 0.1 s, and the modal currently shows "est. at run" on every card but the selected one.
- **Source** — `ui-prototypes/REPORT.md` §3 A run table ("core estimate vs actual"), §5 D-A12, D-A14 and "Backend gaps", §4 A rounds 1–2 "left open"; `ui-prototypes/DECISIONS.md` §6 "Not done".
- **Status** — `ticketable now`

### C6 — Run state across a reload or a server restart
- **Question** — Should live job state (event history, payloads, cancel handle) be recoverable from the database — the `runs.current_step` column already exists — so a restarted bridge re-attaches to, or honestly reports, an in-flight run?
- **Why it matters** — The bridge keeps jobs in server memory, replays SSE history to a late subscriber and the client re-attaches by job id; that survives a browser reload but not a server restart, which orphans a multi-hour run's `runs` row.
- **Source** — [Decide how the frontend reaches the core and the database][frontend-core] sub-question 4; `ui-prototypes/DECISIONS.md` §3 "Transport rules", §4 "Reload mid-run"; `ui-prototypes/REPORT.md` §7 (reload re-attach needs its own tests), §4 B round 1 "State".
- **Status** — `ticketable now`

### C7 — Detection/annotation write guard at the seam
- **Question** — When the new UI gains write paths (verdicts, tags, notes, span edits, hand edits), which Python-side module owns each write, and what structurally stops a human verdict reaching a machine row or the reverse?
- **Why it matters** — "The frontend never touches SQLite" is the precondition for enforcing the frozen separation, but the prototype has no annotation write path at all (Save span, tags and note are client-side stubs), so the guard has never been exercised.
- **Source** — [Decide how the frontend reaches the core and the database][frontend-core] gap 5 ("an argument for the seam"); `ui-prototypes/REPORT.md` §5 D-A11; `prototyping/UI_FUNCTIONAL_SPEC.md` §12 P6; `CLAUDE.md` non-negotiable rule 5.
- **Status** — `ticketable now`

### C8 — Signal reduction: where it lives, and never a chain step
- **Question** — Does bucketed min/max decimation move into `Working/` as a public "read this channel span at N points" function, explicitly a display read that can never enter a recipe hash, and who owns the point budget?
- **Why it matters** — It now exists twice: the verbatim `_minmax_decimate` in `UI/plots.py` (pinned by `tests/test_plots_perf.py`, which dies with the old tree) and a faster reshape/argmin copy with a NaN-aware fallback in `webui/server/decimate.py`. Open sub-questions: `MAX_RENDER_POINTS = 40000` versus the bridge's ≈2× plot width, and which other pure-numpy helpers are marooned in `UI/plots.py`.
- **Source** — [Decide where signal reduction lives, and whether it is a chain step][signal-reduction] (whole body); `ui-prototypes/DECISIONS.md` §4 "Decimation fast path"; `ui-prototypes/REPORT.md` §3 A zoom table note; `docs/adr/0001-web-ui-stack.md` "Inherited".
- **Status** — `ticketable now`

### C9 — When the new UI writes to the real database
- **Question** — The webui runs only against a copy under `webui/runtime/<stamp>/` with the step cache, two adapter `RESULTS_DIR`s and `MODEL_ROOT` redirected and the step-cache write threshold forced to 0.0; what is the route to a mode where runs, templates and verdicts persist, and which redirects and overrides survive into it?
- **Why it matters** — Until then nothing the researcher does in the new UI outlives a restart, and whether old and new servers may run side by side on one file is undecided.
- **Source** — `ui-prototypes/DECISIONS.md` §3 runtime isolation; `docs/adr/0001-web-ui-stack.md` "Consequences" (the bridge "must keep redirecting every writable path into a throwaway runtime"); `ui-prototypes/REPORT.md` §5 "Backend gaps" bullets 4–5; [Decide where the new tree lives and how both trees are served][tree-location] "Whether they can run at the same time".
- **Status** — `fog`

### C10 — Writable paths hardcoded in adapters and pipelines
- **Question** — Should every location an adapter or pipeline writes to (`detection_matrix_profile.RESULTS_DIR`, `preprocessing_window_matrix.RESULTS_DIR`, `catalogue_classifier.MODEL_ROOT`, the channels root in `Pipelines/materialize_channels`) resolve through `Working/config.py` at call time, so one override redirects them all?
- **Why it matters** — Each is a module-level constant, some written from inside a run body; `webui/server/runtime.py` rebinds three by hand and asserts none escapes, and an agent that ran the classifier "just to time it" wrote into the real `DATA/`. Same root cause as T1.
- **Source** — `ui-prototypes/REPORT.md` §2 ("adapters that write files from inside their run bodies"), §5 "Backend gaps" bullet 5; `ui-prototypes/DECISIONS.md` §4 "Three more writable paths", §7 lesson; `tests/test_materialize_channels.py:9-14`.
- **Status** — `ticketable now`

### C11 — Chain validation and insertion owned by the core
- **Question** — Should the core own full-chain validation (every bad junction reported, unknown adapters invalid) and a two-sided insert-at-position check, including side-input bindings, instead of the bridge reimplementing them in `webui/server/chain.py`?
- **Why it matters** — `validate_recipe_steps` reports only the first bad junction and accepts unknown adapters; `UI/analyse/chain_state.py` cannot be imported headless and its `to_recipe()` drops side-inputs, so the insert check now lives in both `UI/workspaces/analyse/builder.py` and the bridge.
- **Source** — `ui-prototypes/REPORT.md` §5 "Backend gaps" bullets 2–3; `ui-prototypes/DECISIONS.md` §4 "`UI/analyse/chain_state.py` not reused".
- **Status** — `ticketable now`

### C12 — Where the chain draft lives; one API surface or two
- **Question** — Is the draft recipe client state only, as the prototype keeps it, or does the core hold drafts; and is the bridge one API or a read side and an execute side with different guarantees?
- **Why it matters** — The prototype answered both by default rather than by decision, and they determine what a second tab, undo history and "Save template" mean.
- **Source** — [Decide how the frontend reaches the core and the database][frontend-core] sub-questions 1 and 3; `ui-prototypes/REPORT.md` §4 B round 1 "State" (A keeps the draft in the client).
- **Status** — `fog`

### C13 — Suffix re-execution and the step-cache write threshold
- **Question** — Is "re-run the whole recipe with `force=True` and rely on prefix-cache hits" the accepted execution model, and does the core's `STEP_CACHE_WRITE_THRESHOLD_S = 1.0` stay when the bridge's runtime sets it to 0.0?
- **Why it matters** — Without `force=True` a completed recipe returns `{reused: True}` and fires no callbacks; with the 1.0 s threshold a cheap chain caches nothing, so "cached · 0 s" badges would stop being true in a real-database mode.
- **Source** — [Correct the four factual errors in UI_CONTEXT.md][ui-context] correction 3; `ui-prototypes/DECISIONS.md` §4 "`force=True` on every run" and threshold bullet; `ui-prototypes/REPORT.md` §5 "Backend gaps" bullet 4.
- **Status** — `ticketable now`

### C14 — Cancelling a long step
- **Question** — Is cancel-between-steps acceptable for multi-hour steps, or must a long step run in a killable subprocess while keeping `execute_recipe`'s crash-safety?
- **Why it matters** — No transport can interrupt an in-flight numpy call; for a whole-channel matrix profile the honest "cancel checks between steps" means Cancel does nothing for hours.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Decisions so far" (transport survey); `ui-prototypes/REPORT.md` §5 D-A5; `ui-prototypes/DECISIONS.md` §4 "Cancel is honest".
- **Status** — `fog`

### C15 — Index frame of `SpanSet` on the wire
- **Question** — Should `SpanSet` producers emit absolute sample indices, as `WindowSet` starts already are, instead of span-relative indices that `serialize.py` shifts by `span_start`?
- **Why it matters** — The bridge handles it once, but every other consumer of a span run's `SpanSet` (export, Review, Library) must know the convention or place every span at the wrong hour.
- **Source** — `ui-prototypes/REPORT.md` §5 "Backend gaps" last bullet.
- **Status** — `ticketable now`

### C16 — Non-finite values in stored scores
- **Question** — Is `inf` in `detections.score` a deliberate sentinel or an upstream bug, and what does the wire contract send for it?
- **Why it matters** — JSON has no `inf`; the bridge maps it to null, which a renderer or an export can read as "no score".
- **Source** — `ui-prototypes/REPORT.md` §5 "Backend gaps" bullet 6.
- **Status** — `ticketable now`

### C17 — Matrix-profile JIT cold start
- **Question** — Should the ~30 s STUMPY numba warm-up be shown as a state in the UI, or taken out of the request path (cached compiled kernels), given a run started inside the warm-up silently waits?
- **Why it matters** — The first run of every server process took 31.9 s wall for a 0.1 s computation, which reads as a hang.
- **Source** — `ui-prototypes/REPORT.md` §3 A run table, §5 "Backend gaps" bullet 7, §8.1 note under the table.
- **Status** — `ticketable now`

### C18 — True sampling rates per source file
- **Question** — Are the rates fs1 = 1 Hz, fs2 = 2 Hz, and 10 Hz for Mushroom (M3_jul) and L_LM_Jul26_J correct, given L_LM's rate is inferred, not read from the file?
- **Why it matters** — Every sample-to-hours conversion, motif length and ± window in the pages and payloads depends on fs; Settings › Datasets marks each rate `read` or `inferred`, but none is confirmed.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` "Open decisions" D3.
- **Status** — `ticketable now`

### C19 — Recording import in the new tree
- **Question** — Which UI-free core function does the new UI call to import a recording (dry run, fs read or entered, channel map, start time, link to an existing recording), given the only implementation is Panel-bound `UI/file_import.py`?
- **Why it matters** — Settings frame 1b designs the flow, but without a core import path the new tree cannot add data.
- **Source** — `prototyping/UI_FUNCTIONAL_SPEC.md` §11 (recording import; its "no designed flow" is stale); `prototyping/UI_REVIEW_BACKLOG.md` "Done" B20; [Correct the four factual errors in UI_CONTEXT.md][ui-context] correction 2 (`UI/file_import.py:131-135`).
- **Status** — `fog`

## Analysis semantics

### A1 — SAX cutlines: a parameter, or learned only
- **Question** — Should the SAX/dSAX adapters grow an explicit `cutlines` override parameter (a core change that enters the recipe hash), or does the Encoding block page keep the learned cutlines read-only, as the prototype draws them?
- **Why it matters** — Spec §6.8 asks for draggable cutlines, but the adapters learn them (Lloyd-Max, Mean-Shift, KDE) and expose them only in `meta.details`; dragging them would assert a parameter the core does not have.
- **Source** — `ui-prototypes/REPORT.md` §7 open question 3, §5 D-A2, §1 checklist 5; `prototyping/UI_FUNCTIONAL_SPEC.md` §6.8 row `Signal → Encoding`; see C3.
- **Status** — `ticketable now`

### A2 — What a null is, block by block
- **Question** — Is a block's null a per-adapter declaration, a paired `preprocessing.surrogate` run (the core's model today), or a per-analysis-kind method held in Settings › Nulls, and which views does each support (per-parameter null sweeps, "this parameter against the null", null bands behind histograms)?
- **Why it matters** — The pages put a null beside nearly every result, while the prototype had to show "no null" and "null · not declared" everywhere; the frames' null sweeps have no core source.
- **Source** — `ui-prototypes/REPORT.md` §5 D-A3, §3 A "Where the stack fought the design"; `prototyping/UI_FUNCTIONAL_SPEC.md` §12 P10, P23; `prototyping/UI_REVIEW_BACKLOG.md` "Design rules agreed" (interrogation null default).
- **Status** — `fog`

### A3 — Over-ceiling stage: refuse, or pause and hand to HPC
- **Question** — Is refusing a chain with a stage over its local ceiling (Run disabled with the reason, bridge answers 422) the right interim, until a core flow exists that pauses the run at that stage and continues once an uploaded result passes checks (recipe hash, per-channel shape, length, finite values)?
- **Why it matters** — P4 and P24 design per-stage pausing so cached cheap stages are never re-sent; the prototype refuses because pausing needs the manifest-inbox/SLURM flow, and running locally fails at once. The interim is ticketable; the pause flow itself is still fog.
- **Source** — `ui-prototypes/REPORT.md` §7 open question 4, §5 D-A13, §4 A round 1 P1; `prototyping/UI_FUNCTIONAL_SPEC.md` §12 P4, P24, §9.6; `prototyping/UI_REVIEW_BACKLOG.md` B22 (paused state drawn in chain 1i and Discovery).
- **Status** — `ticketable now`

### A4 — `Encoding` is terminal, yet the canonical chain consumes it
- **Question** — Does the core gain an `Encoding → SpanSet` drop-detection adapter so the designed default chain (baseline → noise floor → symbolic encoding → drop detection) can be composed, or is the canonical chain redrawn around adapters that exist?
- **Why it matters** — No registered adapter consumes `Encoding`, so the pages' headline chain cannot run; the prototype substituted detrend → matrix profile → threshold. B24 fixed the signatures (`Signal → Signal + estimate`, then `Encoding → SpanSet`) in the pages only.
- **Source** — `ui-prototypes/REPORT.md` §5 D-A1; `ui-prototypes/DECISIONS.md` §4 "Chain composed from real adapters"; `prototyping/UI_REVIEW_BACKLOG.md` B24 and "Sweep fixes applied" › Analyse › Chain.
- **Status** — `ticketable now`

### A5 — Motif pairs from the matrix profile
- **Question** — Should the matrix-profile adapter return its profile indices so motif pairs (M1a/M1b) come from the core, rather than being inferred client-side from equal profile values?
- **Why it matters** — Pairing by equal values can match the wrong subsequences, and the inference is invisible to export and Review.
- **Source** — `ui-prototypes/REPORT.md` §4 A round 1 and round 2 "Left open"; `ui-prototypes/DECISIONS.md` §6 "Not done".
- **Status** — `ticketable now`

### A6 — Values the pages draw that the core does not produce
- **Question** — For each designed view with no core source — per-parameter null sweeps, the slope strip, a per-query distance profile — is it a new adapter output, a derived read in the core, or dropped from the design?
- **Why it matters** — The prototype rendered these as labelled approximations or explicit empty states; left undecided, empty page shells on fixture data harden placeholders into apparent features.
- **Source** — `ui-prototypes/REPORT.md` §3 A "Where the stack fought the design", §5 D-A3.
- **Status** — `fog`

### A7 — Span ceiling of the image encoders
- **Question** — Do the gramian/image encoders keep their 5,000-sample `max_span_samples` cap (about 83 min at 1 Hz), or accept longer spans by windowing or downsampling?
- **Why it matters** — The cap refuses the 2 h example span, so the built-in gramian template works only on short spans and shows an over-ceiling card otherwise.
- **Source** — `ui-prototypes/REPORT.md` §1 checklist 4c, §5 "Backend gaps" (gramian cap); `ui-prototypes/DECISIONS.md` §6 (template renamed).
- **Status** — `ticketable now`

### A8 — Cross-channel and multi-channel analysis
- **Question** — What form do cross-channel viewing and multivariate analysis take in the new tree (the old tree's cross-channel peek and classification, Explore's lag-aligned frame, Discovery's multi-channel scope), and what must the core serve for them?
- **Why it matters** — Present in the old tree, parked in the spec and an inert button in the prototype; P3 keeps Analyse single-channel, so the question lands on Explore and Discovery.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Not yet specified" (cross-channel); `prototyping/UI_FUNCTIONAL_SPEC.md` §11 bullet 2, §12 P3; `ui-prototypes/REPORT.md` §1 checklist 8.
- **Status** — `fog`

### A9 — FitzHugh–Nagumo as a feature block
- **Question** — What does a FitzHugh–Nagumo fit block emit as features, with what null and what behaviour when the fit fails?
- **Why it matters** — It is permitted in interrogation as a feature-producing block but not designed, and one-block-per-analysis (P7) gives it its own page.
- **Source** — `prototyping/UI_FUNCTIONAL_SPEC.md` §11 bullet 3, §12 P7; `prototyping/UI_REVIEW_BACKLOG.md` "Design rules agreed".
- **Status** — `fog`

### A10 — Cluster selection criterion
- **Question** — Which criterion chooses the cluster count (fixed k, fixed cut, max silhouette, gap statistic, minimum class size), and what is its default?
- **Why it matters** — Nothing is pre-registered, and the choice shapes the cluster-label arm of the paired label comparison.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B4.
- **Status** — `fog`

### A11 — Splitting a supplied window set
- **Question** — When windows arrive as a source rather than from sliding windows, what applies the blocked split: a split filter on the source windows (blocked by recording and time, gap ≥ one window, straddling windows dropped), or a rule that only saved sets carrying their split are accepted?
- **Why it matters** — Human-labelled windows may be adjacent or overlapping, which is where leakage bites; P15 keeps the split inside the sliding-windows block, so nothing applies it to a supplied set.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B7; `prototyping/UI_FUNCTIONAL_SPEC.md` §12 P15, P18.
- **Status** — `fog`

### A12 — Saved window sets as stored artifacts
- **Question** — Where and how is a saved window set persisted (id, split, spacing check, verdict coverage, train-safe flag) so Analyse, Models and Review can pick it as a source?
- **Why it matters** — The Library shelf and the Models picker are drawn, but Save window set on the sliding-windows row, the Analyse source-chip picker and the Review queue source are not, and nothing in the core stores one.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B12, "Sweep fixes applied" › Models (frame 1b); `prototyping/UI_FUNCTIONAL_SPEC.md` §6.9, §12 P18.
- **Status** — `fog`

### A13 — Where window verdicts are stored
- **Question** — Are human verdicts on training and verification windows stored in a window-verdict table on the adjudication side, keyed by window-set id + window index, or by materialising each queued window as a detection row of a "windows" run?
- **Why it matters** — These windows are machine-produced with no detection row, yet the verdict is human judgement; either option must keep the machine/human separation (C7).
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B15; `prototyping/UI_FUNCTIONAL_SPEC.md` §10.1, §12 P13; `CLAUDE.md` rule 5.
- **Status** — `ticketable now`

### A14 — Cluster grouping rule values
- **Question** — What defaults define a Review *sequence* cluster (maximum gap between detections, placeholder 6 min; minimum events, placeholder 2; same run and channel) and the cohesion limit (placeholder 0.45), and do they live in Settings › Analysis defaults?
- **Why it matters** — The placeholders already appear in Settings › Review queues and Library groupings, and sequence detection is shared with the Library's grouping bases (A15).
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B16, "Sweep fixes applied" › Settings ("Not done, needs you").
- **Status** — `fog`

### A15 — Library grouping basis definitions
- **Question** — How are sequence similarity (events, order and gaps), the *frequency content* and *timescale* features, and a *spike train* unit that was not imported as one defined, with what default cuts, bins and minimum group size?
- **Why it matters** — Spec §8.2 names the bases and Settings shows placeholders, but nothing is pre-registered, and every Library grouping is computed from them.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B17, "Sweep fixes applied" › Settings; `prototyping/UI_FUNCTIONAL_SPEC.md` §8.2.
- **Status** — `fog`

### A16 — The key a Library hand edit binds to
- **Question** — What key does a hand edit (add, remove, exemplar, tag, class) bind to so it survives regrouping, given family ids are not stable across groupings?
- **Why it matters** — Hand edits must be stored apart from computed groupings and re-applied on regroup, under the "points at a family this grouping lacks → hand group" rule.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B18; `prototyping/UI_FUNCTIONAL_SPEC.md` §8.3, §12 P22.
- **Status** — `fog`

### A17 — Encoder versions
- **Question** — How does a new encoder or image size register as a version (today GASF / GADF / RP / fusion at 224 px) so templates and models record exactly which encoder they used?
- **Why it matters** — The pages keep an encoder-set selector for this, but the registry has no versioning scheme, so a changed encoder would silently alter reused templates.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B6, "Done" › Analyse › Training (04 encode, encoder versioning note).
- **Status** — `fog`

### A18 — Which HPC clusters and node profiles exist
- **Question** — Which clusters and nodes can the researcher actually submit to, and can a job use two nodes (the `gpu-multinode` profile)?
- **Why it matters** — Settings › Compute & HPC allows several clusters and job profiles; script generation and stage routing (A3) need the real list.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B19 (listed under "Done" but unresolved), "Sweep fixes applied" › Settings ("Not done, needs you").
- **Status** — `ticketable now`

### PRD departures to confirm (analysis)

Decisions recorded during the page review that override a PRD passage; each needs the researcher to confirm or reverse it. Source for all: `prototyping/UI_FUNCTIONAL_SPEC.md` §12 (row named). P4 is folded into A3.

- **A19 — P3: Analyse is single-channel**
  - **Question** — Confirm Analyse takes a span or one whole channel, never a channel or band list, with fan-out and multi-channel templates in Discovery.
  - **Why it matters** — Overrides PRD Part 1 stories 16–17 and the Analyse scope selector; B25 already rewrote the pages to it.
  - **Source** — §12 P3; `prototyping/UI_REVIEW_BACKLOG.md` B25.
  - **Status** — `ticketable now`
- **A20 — P6: verdicts are given in Review only**
  - **Question** — Confirm Explore offers *Take span for Review* / *Review this motif* instead of verdict buttons, while still saving tags and notes.
  - **Why it matters** — Overrides Part 1 stories 4–5 and Explore's seed verdict; keeps one write path into the human store (C7).
  - **Source** — §12 P6.
  - **Status** — `ticketable now`
- **A21 — P7: one block per analysis type**
  - **Question** — Confirm slope geometry, spike shape and a FitzHugh–Nagumo fit are separate blocks with their own pages, feeding a generic Aggregate block.
  - **Why it matters** — Overrides §6.6's single fixed interrogation chain; decides the block registry's granularity.
  - **Source** — §12 P7.
  - **Status** — `ticketable now`
- **A22 — P10: interrogation carries a null by default**
  - **Question** — Confirm matched random windows (200×) and shuffled onsets as the default interrogation nulls, with every fitted exponent shown beside the null exponent.
  - **Why it matters** — Extends the Part 1 surrogate protocol from runs to distributions and fits; depends on A2.
  - **Source** — §12 P10.
  - **Status** — `ticketable now`
- **A23 — P11: Analyse builds the training template, Models trains**
  - **Question** — Confirm the training chain is built and trialled on one channel in Analyse, and *Train in Models* runs it across channels with the paired cluster-label versus manual-label comparison on one split.
  - **Why it matters** — Overrides Part 1 story 16 / the RQ1 row, which put training and evaluation in Analyse.
  - **Source** — §12 P11.
  - **Status** — `ticketable now`
- **A24 — P12: leakage guards are parameters**
  - **Question** — Confirm sliding windows carry an editable gap (≥ window length) and a blocked-by-time split, random splits are marked leaking, and label-derived features (CNN scores) are off by default in the window matrix.
  - **Why it matters** — Part 1 is silent on split leakage; overlapping windows or label-trained features would contaminate the RQ1 comparison.
  - **Source** — §12 P12.
  - **Status** — `ticketable now`
- **A25 — P13: unreviewed windows go to Review from the training chain**
  - **Question** — Confirm *Send N unseen windows to Review* (queue cap 20,000, binary verdicts sufficient).
  - **Why it matters** — New relative to the PRD; the manual-label arm needs verdicts on the same windows, and where they are stored is A13.
  - **Source** — §12 P13.
  - **Status** — `ticketable now`
- **A26 — P15: a stage the source makes redundant is absent, not skipped**
  - **Question** — Confirm a `WindowSet` source feeds the window matrix directly with no greyed "skipped" row, and the split stays inside the sliding-windows block.
  - **Why it matters** — Overrides §6.2's "skipped rather than optional"; leaves the supplied-set split open (A11).
  - **Source** — §12 P15.
  - **Status** — `ticketable now`
- **A27 — P16: models reach Discovery only inside detection templates**
  - **Question** — Confirm Discovery never lists a bare model: detection with a model means a Model stage (`Model + WindowSet → Scores`) then a threshold stage, saved as a template.
  - **Why it matters** — One path, not two; the threshold turning scores into spans gets its own null.
  - **Source** — §12 P16.
  - **Status** — `ticketable now`
- **A28 — P17: a seed search is a run**
  - **Question** — Confirm Discovery has one page with *Apply template* and *Seed search* sharing one results area, any two runs compare pairwise, and scope is one recording × one or more channels.
  - **Why it matters** — Overrides §7's separate single-channel pages; comparing a seed to a template becomes possible.
  - **Source** — §12 P17.
  - **Status** — `ticketable now`
- **A29 — P18: a window set is a saved, reusable artifact**
  - **Question** — Confirm any `WindowSet` output offers *Save window set*, carrying its split, spacing check and verdict coverage, accepted as a source in Analyse, Models and Review.
  - **Why it matters** — Overrides Part 1's windows-as-intermediate; storage is A12.
  - **Source** — §12 P18.
  - **Status** — `ticketable now`
- **A30 — P19: blocked test portion and a registration gate**
  - **Question** — Confirm evaluation on a blocked test portion set aside before training, registration requiring held-out checks, human verification and sign-off, local training only at ≤ 2 h estimate, HPC status marked by hand, and M4 locked in Models too.
  - **Why it matters** — Overrides Part 1's held-out recording as the test set and adds a model lifecycle the PRD does not specify.
  - **Source** — §12 P19.
  - **Status** — `ticketable now`
- **A31 — P20: Review works in named, blindable queues**
  - **Question** — Confirm named queues with one source each, machine opinion hidden until the verdict in training-window and verification queues, the blind state stored with every verdict, and artifact likelihood never hidden.
  - **Why it matters** — Overrides Part 1's single filterable queue with the score always shown; adds a column to every verdict.
  - **Source** — §12 P20.
  - **Status** — `ticketable now`
- **A32 — P21: the seed verdict promotes to the Library automatically**
  - **Question** — Confirm pressing S promotes to the Library, a class is optional and implies `interesting` unless non-informative, and a binary verdict is the minimum for "annotated".
  - **Why it matters** — Overrides Part 1 story 32's separate explicit promotion step.
  - **Source** — §12 P21.
  - **Status** — `ticketable now`
- **A33 — P22: the Library computes its own groupings**
  - **Question** — Confirm three Library sections (Motifs, Window sets, Templates), groupings chosen by unit and basis, non-fitting entries omitted and flagged, hand edits surviving regroup, and no regroup comparison frame.
  - **Why it matters** — Overrides Part 1's thumbnail grid with a group-by selector; definitions are A15 and A16.
  - **Source** — §12 P22.
  - **Status** — `ticketable now`
- **A34 — P24: one global Jobs page; an over-limit stage pauses the run**
  - **Question** — Confirm Jobs lists every job across workspaces (Review queues included, replacing the Models Jobs tab) and a paused run continues from the next stage once its result passes checks, refusing a result made with other parameters.
  - **Why it matters** — Overrides Part 1 "Cluster routing" and the first §7b draft; the implementation question is A3.
  - **Source** — §12 P24.
  - **Status** — `ticketable now`

## Frontend design

### F1 — Time axis convention: hours or seconds
- **Question** — Confirm hours since recording start with span-adaptive decimals everywhere, falling back to absolute seconds only for spans ≤ 15 min, against frame chain-1's seconds on a 50 s span starting at t = 0.
- **Why it matters** — Every shared axis, crosshair, span hand-off and export inherits the convention; the pens have already moved Review and chain 1h / 7 from clock time to hours (X12).
- **Source** — `ui-prototypes/REPORT.md` §7 open question 2, §3 A "Where the stack fought the design" (last sentence), §5 D-A7; `ui-prototypes/DECISIONS.md` §6 (`fmtAxis`); `prototyping/UI_FUNCTIONAL_SPEC.md` §0; `prototyping/UI_REVIEW_BACKLOG.md` B26 (X12), "Sweep fixes applied" › Review and › Analyse › Chain.
- **Status** — `ticketable now`

### F2 — One state model for rows and jobs
- **Question** — What is the single state model for a chain row and a job (new, stale, running, computed, cached, failed, cancelled, invalid, on cluster, paused, render failed), which layer owns it (client store, bridge or core), and which transitions are legal?
- **Why it matters** — Row-state semantics (which badge, whether a payload is still the current step's, hiding another source's results) cost the prototype more than all seven renderers, the pens' badge words disagreed until B26, and Analyse, Discovery and Jobs all show the same states.
- **Source** — `ui-prototypes/REPORT.md` §2 "What building A taught" bullet 1, §3 A "Where the stack fought the design", §4 A round 2 fixes (computed versus cached wording); `prototyping/UI_REVIEW_BACKLOG.md` B26 (X15).
- **Status** — `fog`

### F3 — Block pages: a dispatch seam and the block contract
- **Question** — Should block pages get a per-adapter registry seam like the per-type renderer switch, replacing dispatch on the adapter name inside one ~550-line file, with the §6.8 block contract as its checklist; and can adding an eighth interchange type touch fewer than four files?
- **Why it matters** — The type seam held for seven types, but every new block page grows one file, and B11 requires each new type signature to gain a §6.8 row before its first block.
- **Source** — `ui-prototypes/REPORT.md` §4 A round 2 "Left open", §3 A "Lines of code" (what an eighth type touches); `prototyping/UI_REVIEW_BACKLOG.md` B11; `prototyping/UI_FUNCTIONAL_SPEC.md` §6.8, §12 P5.
- **Status** — `ticketable now`

### F4 — Keyboard operability of plots and handles
- **Question** — What keyboard model do the corpus heatmap, the draggable cut/threshold line and the span handles use, given only the handles and span SVG are operable today?
- **Why it matters** — Left open through both critique rounds; draggable controls with no keys make precise parameter values hard to set.
- **Source** — `ui-prototypes/REPORT.md` §4 A round 1 P2 ("left open") and round 2 "Left open".
- **Status** — `ticketable now`

### F5 — Labels and chips overprinting traces
- **Question** — How are y-axis labels and matrix-profile motif chips placed in chain rows so they never cover the trace (gutter, halo or collision avoidance)?
- **Why it matters** — Still present after round 2, and the same class as the pens' label-on-trace collisions, so it recurs on every row type the shells add.
- **Source** — `ui-prototypes/REPORT.md` §4 A round 2 "Left open"; `prototyping/UI_REVIEW_BACKLOG.md` B29 (label-on-trace collisions).
- **Status** — `ticketable now`

### F6 — Explore warns before sending an over-ceiling span
- **Question** — Should Explore warn when a dragged span exceeds the default chain's local ceiling, as Analyse already does?
- **Why it matters** — Today the researcher learns of the refusal only after the hand-off to Analyse (A3).
- **Source** — `ui-prototypes/REPORT.md` §4 A round 2 "Left open".
- **Status** — `ticketable now`

### F7 — Client type hygiene on the wire contract
- **Question** — Should run events get a discriminated-union `RunEvent` type (the analyse store carries about eight casts) and `staleFrom` move into the shared `ChainDraft`?
- **Why it matters** — Casts hide wire-contract drift from `tsc -b`, one of the new tree's three gates.
- **Source** — `ui-prototypes/DECISIONS.md` §6 "Not done".
- **Status** — `ticketable now`

### F8 — "Input ghosted behind" on its own y scale
- **Question** — Confirm that a `Signal → Signal` row draws the ghosted input on its own, labelled y scale rather than the output's.
- **Why it matters** — Raw input sits at −0.66 mV DC and the detrended output at ±0.003 mV, so one axis flattens one of them; it is a visible departure from §6.8, and waveforms are never normalised.
- **Source** — `ui-prototypes/REPORT.md` §5 D-A9, §3 A "Where the stack fought the design"; `prototyping/UI_FUNCTIONAL_SPEC.md` §6.8 row `Signal → Signal`.
- **Status** — `ticketable now`

### F9 — Header chips once jobs persist
- **Question** — What do "N need you" and "Jobs · N" count in the real app — the designed cross-workspace needs-you set (paused runs, overdue cluster jobs, review queues) — rather than failed and running jobs in the current server process?
- **Why it matters** — The prototype's honest counts reset on every restart; the designed chips need the persistent job state of C6.
- **Source** — `ui-prototypes/REPORT.md` §5 D-A6; `ui-prototypes/DECISIONS.md` §4 "Header chips are real"; `prototyping/UI_FUNCTIONAL_SPEC.md` §7c, §12 P24.
- **Status** — `fog`

### F10 — Which pages need the canvas escape hatch
- **Question** — Which designed pages must draw tens of thousands of marks at once (every detection across a recording, Library recurrence, a large recurrence matrix, the Library atlas), and is each renderer SVG, hand-written canvas or a small canvas library behind the same per-type seam?
- **Why it matters** — SVG degrades past roughly 10–20k elements, the chosen stack's one technical ceiling, untested at that density; deciding after pages exist means rewriting renderers. The export consequence is E5.
- **Source** — `ui-prototypes/REPORT.md` §8.2 "headroom for very dense plots", §8 "Additional findings" bullet 1; `docs/adr/0001-web-ui-stack.md` "Plotting approach".
- **Status** — `fog`

### F11 — Web fonts on a localhost-only tool
- **Question** — Should Inter and Geist Mono be bundled with the client instead of loaded from Google Fonts (`webui/client/index.html:8-10`)?
- **Why it matters** — The app is single-machine and localhost; offline it silently falls back to system fonts, which changes the smoke screenshots used as review evidence.
- **Source** — `ui-prototypes/DECISIONS.md` §4 "Fonts"; `webui/client/index.html`; [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Constraints settled while charting" (localhost).
- **Status** — `ticketable now`

### F12 — Review and Library workspaces in the new tree
- **Question** — How, and in what order, are Review (G7: adjudicate without contaminating ground truth) and Library (G8: browse along two independent axes) built on the new stack, given both have designed `.pen` forms?
- **Why it matters** — The slice did not touch them, and they carry the write paths (C7, A13, A16) and the densest plots (F10, E3).
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Not yet specified" bullet 1; `prototyping/UI_FUNCTIONAL_SPEC.md` §8, §10.
- **Status** — `fog`

### F13 — Explore › Signal bottom ribbons versus drawer tabs (D1)
- **Question** — Should the bottom ribbons (Filters & search · Annotations · Detections · Keyboard shortcuts) mirror the drawer's three tabs (Annotations · Detections · Shortcuts) with filters inside each?
- **Why it matters** — The drawer was rebuilt as tabs with a collapsible filter section, so the page now has two disagreeing navigation schemes.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` "Open decisions" D1.
- **Status** — `ticketable now`

### F14 — Span edit reachable from Explore (D2)
- **Question** — Should Explore offer "edit extent" on an annotation it already owns, or stay reachable only as a hand-off from Review?
- **Why it matters** — Spec §4.3 puts editing in Explore entered from Review; the answer adds or removes a human write path (C7).
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` "Open decisions" D2; `prototyping/UI_FUNCTIONAL_SPEC.md` §4.3.
- **Status** — `ticketable now`

### F15 — Arithmetic and state inside the reference frames (B28 remainder)
- **Question** — Fix the frame numbers that still do not reconcile: chain (baseline warning, scores markers, run-history interrogation row, 1c Save template enabled); interrogation (4c-b stacked histograms, 4c-c copied histograms, 4c "100 % one fall" versus a flagged event, 4b missing null panel); training (01 block and split counts, 5b class sizes 343 vs 543, 2b contingency sums, 5c window-time and image sums, 0 vs 5b cluster strips); Explore (drawer filters vs rows, MOTIF_233 box scale, span-edit px scale, corpus filter vs map).
- **Why it matters** — The `.pen` pages are the interface target; shells built on fixture data will copy inconsistent placeholders as though they were designed.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B28, and "Sweep fixes applied" "Not done (optional, B28)" under Analyse › Chain, › Interrogation, › Training and Explore; `prototyping/UI_SWEEP_2026-09-14.md`.
- **Status** — `ticketable now`

### F16 — Remaining layout defects in the reference frames (B29 remainder)
- **Question** — Fix the B29 defects not recorded as fixed: chain 6 disabled-reason text overrunning its cards, the chain 1e banner over a card edge, Explore 1b's overlapping popovers, Explore 1 label-on-trace collisions, and empty regions (Explore 1d, Library 5, chain 1c and 6 detail panels).
- **Why it matters** — As F15; the sweep fixed Models 3, Library 4, Review's labels and Settings' "differs" dots, but not these.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B29 and "Sweep fixes applied".
- **Status** — `ticketable now`

### F17 — Family colours still on the old hues
- **Question** — Move the remaining family colours to the canon palette in Review (nearest-families sparklines, F-03 pill dot), Discovery and Analyse.
- **Why it matters** — D8 took the family palette off semantic hues; stale hues in the reference pages would carry red and green families into the build.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` "Sweep fixes applied" › Library "Follow-up, cross-file"; D8.
- **Status** — `ticketable now`

### F18 — Missing algorithm glyphs
- **Question** — Draw the missing glyphs in chain frame 6b's registry: Span dedupe, Top-k pairs, Peak picker, Spike shape.
- **Why it matters** — Glyphs identify blocks in the insert modal, Discovery's template picker and Library template cards (B9); a block without one has no card identity.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` "Sweep fixes applied" › Analyse › Chain "Not done (optional)"; B9.
- **Status** — `ticketable now`

### PRD departures to confirm (frontend)

Source for all: `prototyping/UI_FUNCTIONAL_SPEC.md` §12 (row named).

- **F19 — P1: the chain page is vertical rows**
  - **Question** — Confirm each row carries its block's result plot, with the horizontal ribbon kept only for moving between block pages.
  - **Why it matters** — Overrides PRD Part 2 "Chain shape, revised" (horizontal canvas plus filmstrip), the very passage `CLAUDE.md` warns supersedes Part 1's vertical list; the prototype and `webui/` already follow P1.
  - **Source** — §12 P1; `CLAUDE.md` "What this repo is".
  - **Status** — `ticketable now`
- **F20 — P2: run history is a pop-up**
  - **Question** — Confirm run history sits behind a History button beside Import, with *Apply to source* disabled (with the reason) when the source type does not fit.
  - **Why it matters** — Overrides Part 2 stories 29–32 (collapsible sidebar).
  - **Source** — §12 P2.
  - **Status** — `ticketable now`
- **F21 — P5: block pages show process, chain rows show result**
  - **Question** — Confirm a block page shows internals (for SAX: signal + PAA, slope + cutlines, quantised and dSAX strips) and its chain row shows only the output.
  - **Why it matters** — Overrides Part 2 story 14's focus mode; shapes F3.
  - **Source** — §12 P5.
  - **Status** — `ticketable now`
- **F22 — P8: show-all views cap at about ten**
  - **Question** — Confirm strips slide with navigation and overlays draw a seeded random sample with *resample*.
  - **Why it matters** — New relative to the PRD; families run to hundreds of members, and it bounds what renderers must draw (F10).
  - **Source** — §12 P8; `prototyping/UI_REVIEW_BACKLOG.md` "Design rules agreed".
  - **Status** — `ticketable now`
- **F23 — P9: explanatory text behind info icons**
  - **Question** — Confirm explanations move into info icons and pop-overs, with plain-language captions kept to one line.
  - **Why it matters** — Overrides §3 "plain-language captions are load-bearing".
  - **Source** — §12 P9.
  - **Status** — `ticketable now`
- **F24 — P14: Models is a sixth workspace**
  - **Question** — Confirm Explore · Analyse · Discovery · Models · Review · Library, with Models launching training from Analyse templates, holding results and nulls, and keeping the registry.
  - **Why it matters** — Overrides §2's five workspaces and the decisions doc's rationale; fixes the nav rail every shell page builds.
  - **Source** — §12 P14.
  - **Status** — `ticketable now`
- **F25 — P23: Settings in project and personal scopes**
  - **Question** — Confirm Settings as sixteen pages in two scopes (project, recorded with runs; personal, this browser), per-workspace local limits (Analyse 20 min, Discovery 20 min, Models 2 h), several clusters, a timed event log, rule-based recommended values, and an append-only audit log.
  - **Why it matters** — Overrides §9's first draft (one ceiling, one surrogate setting, one SLURM template); "project" settings must enter run provenance, so it touches the core.
  - **Source** — §12 P23.
  - **Status** — `ticketable now`

### Found while building the page shells (2026-09-16)

No items yet; frontend-design fog found while the concept pages are built as empty shells on fixture data is appended here.

## Export and reporting

### E1 — The reporting and export surface, and its figure target
- **Question** — What does the reporting and export surface produce (today a folder of manifest + CSV + copied plots, goal G9), and which generations of the `Pipelines/` figure corpus are its visual target?
- **Why it matters** — Producing plots and reports of an analysis is a main downstream goal and was a stack criterion; the `.pen` pages cover only Settings › Export, and choosing the target figures needs the researcher present.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Not yet specified" bullet 2 and "Constraints settled while charting"; [Identify the visual target from the existing figure corpus][visual-target] (as summarised in the map's "Decisions so far").
- **Status** — `fog`

### E2 — Render path for publication figures
- **Question** — Are publication figures exported from the browser's SVG, or rendered on the Python side from the same serialised per-type payloads (for example with matplotlib), and for which figure kinds does each hold?
- **Why it matters** — SVG is exportable but matplotlib parity was never tested; a server-side path means a second, print implementation of the renderer switch, and `CLAUDE.md` rule 1 forbids matplotlib below `UI/`, so the rule would need restating for `webui/server/`.
- **Source** — `ui-prototypes/REPORT.md` §7 "Plotting" bullet; `docs/adr/0001-web-ui-stack.md` "Plotting approach" (last two sentences); `CLAUDE.md` rule 1.
- **Status** — `ticketable now`

### E3 — The Library atlas density test
- **Question** — Does the chosen stack pass the density test the visual-target ticket set: the Library atlas, about 22 line plots and a histogram on a shared y-scale, rendered interactively and exported as vectors?
- **Why it matters** — It was set as a stack criterion but neither prototype exercised it, and it is the cheapest single piece of evidence for both F10 and E2.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Decisions so far" (visual target); `ui-prototypes/REPORT.md` §8.2 dense-plot row ("Untested at that density").
- **Status** — `ticketable now`

### E4 — What a run export contains and where it lands
- **Question** — What does *Export run* write, and where, given the prototype writes only JSON (recipe, timings, payloads; no rendered figures) under `runtime/<stamp>/exports/` inside the throwaway runtime?
- **Why it matters** — An export written into a directory with no retention policy (T8) is buried or lost, and export is how the Library's findings leave the tool.
- **Source** — `ui-prototypes/REPORT.md` §1 checklist 7 ("partial"); `prototyping/UI_REVIEW_BACKLOG.md` "Done" › Settings (Export page).
- **Status** — `ticketable now`

### E5 — Vector export from canvas renderers
- **Question** — When a renderer falls back to canvas (F10), how does its export stay vector: a parallel SVG/PDF path, Python-side rendering, or accepting raster for those figures?
- **Why it matters** — Canvas has no vector output, so the escape hatch and the publication-export criterion collide on exactly the densest figures (recurrence, all detections across a recording), which are the likeliest report figures.
- **Source** — `docs/adr/0001-web-ui-stack.md` "Plotting approach" (escape hatch); `ui-prototypes/REPORT.md` §8 "Additional findings" bullet 1; [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Constraints settled while charting" (publication-quality static export).
- **Status** — `fog`

## Tooling, tests and safety

### T1 — Make pytest safe against the real DATA
- **Question** — Do tests redirect every write root to a temp directory through fixtures (`STEP_CACHE_ROOT`, `MODEL_ROOT`, the encodings root, `DATA/derived/channels`), or must every worktree get a copied, never junctioned, `DATA/`?
- **Why it matters** — The suite assumes a worktree-local fixture `DATA/`; run through a junction it re-wrote 5 step-cache files, added 5 encoding texts and 4 classifier joblibs, and overwrote an existing joblib in the real data. Writers: `tests/test_step_cache.py`, `tests/test_encoding_view*.py`, the classifier tests, and `tests/test_materialize_channels.py` (writes `DATA/derived/channels/<stem>/`). Root cause shared with C10.
- **Source** — `ui-prototypes/REPORT.md` §7 open question 1 ("Worth a ticket"), §4 "The pytest gate"; `ui-prototypes/DECISIONS.md` §10; `ui-prototypes/REAL_DATA_WRITES.md`; `tests/test_materialize_channels.py:9-14`.
- **Status** — `ticketable now`

### T2 — Files already written into the real DATA
- **Question** — Which files in `REAL_DATA_WRITES.md` does the researcher remove: the new ones (5 `UNITTEST_encoding_view*` texts, 4 pytest classifier joblibs, and the reader subagent's `catalogue_classifier_153815b9dea451b2.joblib`), and what is done about the overwritten `…f918586712c715e2.joblib` (present since 2026-09-04) and the 5 re-written step-cache files?
- **Why it matters** — Nothing was deleted, by rule; the stray joblibs sit in `DATA/derived/models` where a model picker could list them, and the overwritten joblib's original bytes are gone.
- **Source** — `ui-prototypes/REAL_DATA_WRITES.md`; `ui-prototypes/REPORT.md` §7 open question 1, §4 A round 1 P0 and round 2 P0; `ui-prototypes/DECISIONS.md` §7, §10, §14.
- **Status** — `ticketable now`

### T3 — A standing DATA write check
- **Question** — Should a before/after snapshot of every file under `DATA/` and `Results/` (the prototype's closing check) become a standard step for any agent session or smoke run that executes adapters, asserted by `webui/smoke.py`?
- **Why it matters** — "Read-only" in a brief is not enforced by the core: the first real-data write came from a reader subagent timing an adapter before any redirect existed, and the mid-way check covered only two paths.
- **Source** — `ui-prototypes/DECISIONS.md` §7 (lesson and extended closing check); `ui-prototypes/REPORT.md` §4 A round 1 P0.
- **Status** — `ticketable now`

### T4 — Tests for the bridge itself
- **Question** — Where do tests for `webui/server/` live and what runs them — SSE with its polling fallback, cancel between steps, reload re-attach, the meta sidecar on cache hits, 423 on every held-out route, the runtime redirect assertions — given pytest collects only `tests/`?
- **Why it matters** — The report names the bridge as the part that needs its own tests; the smoke gate reaches it only end-to-end through a browser.
- **Source** — `ui-prototypes/REPORT.md` §7 ("The bridge is the part that needs its own tests"), §4 "The pytest gate"; [Define the new tree's test gates][test-gates] "Where the gates run from".
- **Status** — `ticketable now`

### T5 — How the two gate sets relate, and a gate that cannot silently not-run
- **Question** — Does one command run the headless pytest suite and the webui gates (smoke, `tsc -b`, `vite build`), or are they deliberately separate; and does the smoke gate fail, rather than pass, when Playwright, chromium or the server is missing?
- **Why it matters** — "No tests ran" must never read as a pass; `CLAUDE.md` states that property for `pytest -m ui`, and nothing yet states it for the new gates.
- **Source** — [Define the new tree's test gates][test-gates] "How the two suites relate" and constraints; `CLAUDE.md` "Panel surfaces" (last paragraph).
- **Status** — `ticketable now`

### T6 — The import-boundary test at the new boundary
- **Question** — Should rule 1's enforcement test be extended so `Working/`, `Adapters/` and `Pipelines/` may not import FastAPI, uvicorn or Starlette, and `webui/server/` may not import `UI/` or Panel?
- **Why it matters** — "Nothing below the boundary may know a browser exists" is what makes the rebuild possible; it is enforced only for Panel, HoloViews, Bokeh and matplotlib below `UI/`, and "nothing in `webui/` imports `UI/`" is true by inspection, not by test.
- **Source** — `CLAUDE.md` non-negotiable rule 1; [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Standing preferences"; [Decide how the frontend reaches the core and the database][frontend-core] "Constraints".
- **Status** — `ticketable now`

### T7 — Provisioning the new toolchain in agent worktrees
- **Question** — How does a fresh worktree get `webui/client/node_modules` (~97 MB) and `webui/.venv` (FastAPI and uvicorn over conda via `--system-site-packages`): a per-worktree install, a shared cache, or a junction, without writing into the main checkout?
- **Why it matters** — Development runs in worktrees on a shared conda environment, a build-artefact directory that breaks provisioning was named as a real failure mode, and a junction is what caused the real-DATA writes (T1).
- **Source** — [Decide where the new tree lives and how both trees are served][tree-location] "Constraints"; `docs/adr/0001-web-ui-stack.md` "Consequences"; `ui-prototypes/REPORT.md` §8.1 footprint table.
- **Status** — `ticketable now`

### T8 — Retention of runtime directories
- **Question** — What retention policy applies to `webui/runtime/<stamp>/` (DB copy, step cache, results, models, logs, exports): keep the last N, age out, or clean on start?
- **Why it matters** — Nothing cleans them; after one night they held 772 MB for A and 502 MB for B, and a single 20 h matrix-profile session reached 285 MB.
- **Source** — `ui-prototypes/REPORT.md` §8.1 footprint table and following paragraph, §8 "Additional findings" bullet 2.
- **Status** — `ticketable now`

### T9 — Start scripts fail loudly on a busy port
- **Question** — Should `webui/start.ps1`, `webui/start.sh` and `webui/run_server.py` refuse to start when port 8765 is already bound?
- **Why it matters** — The benchmark found the default ports held by hand-started servers; a smoke run against a stale server tests old code and passes.
- **Source** — `ui-prototypes/REPORT.md` §8 "Additional findings" bullet 3; `ui-prototypes/DECISIONS.md` §15.
- **Status** — `ticketable now`

### T10 — Restore strict unused-code checks
- **Question** — When parallel builders stop sharing the client tree, should `noUnusedLocals` and `noUnusedParameters` be turned back on?
- **Why it matters** — They were relaxed deliberately so parallel builders would not break each other's build, and the loosening carried into `webui/` (`webui/client/tsconfig.app.json:21-22`).
- **Source** — `ui-prototypes/DECISIONS.md` §4 (TypeScript bullet); `webui/client/tsconfig.app.json`.
- **Status** — `ticketable now`

### T11 — `detection.wavelet_scattering` fails on this machine
- **Question** — Is the kymatio/scipy run-time failure an environment incompatibility to fix (a dependency change needing sign-off), or is the adapter withdrawn from the registry?
- **Why it matters** — It is listed and flagged "known broken" in the insert modal; a registered block that always fails erodes trust in every refusal reason.
- **Source** — `ui-prototypes/REPORT.md` §5 "Backend gaps" (wavelet scattering); `CLAUDE.md` "Environment".
- **Status** — `ticketable now`

### T12 — Apply the UI_CONTEXT.md corrections
- **Question** — Apply the four corrections (nothing rasterises; recordings are 282–721 h; the suffix is not executed selectively; the boundary leaks), the scale numbers and one-line type summaries, and G7's "z-normalised overlay" contradiction with §4.1.
- **Why it matters** — Every session loads `docs/agents/UI_CONTEXT.md` as required reading; as written it sends sessions hunting for a rasteriser and understates scale by about 60×.
- **Source** — [Correct the four factual errors in UI_CONTEXT.md][ui-context]; `prototyping/UI_REVIEW_BACKLOG.md` D5 and B27 (G7 handed to the correction ticket).
- **Status** — `ticketable now`

### T13 — Agent orchestration under usage limits
- **Question** — Should long agent tasks on this project standardise on incremental on-disk progress and resumable briefs, given usage limits cut off readers, fixers and critics during the prototype night?
- **Why it matters** — A wall-clock usage cap, not the stack, was the largest single delay, and one critique round's work was lost entirely.
- **Source** — `ui-prototypes/DECISIONS.md` §8, §9, §11; `ui-prototypes/REPORT.md` §2 "Orchestration friction".
- **Status** — `fog`

## Legacy tree

`UI/`, its tests and `tests/ui/` stay intact but ignored; nothing in `webui/` imports `UI/`. These items are the consequences of keeping it.

### L1 — The `LibraryGrid(conn)` versus `LibraryGrid(app)` contract mismatch
- **Question** — Is the test (`tests/test_ui_responsiveness.py::_empty_grid` calls `LibraryGrid(conn)`) or the code (`UI/workspaces/library/grid.py:74-76` expects an app exposing `.conn`) right, and is it fixed inside a frozen tree?
- **Why it matters** — It explains most of the 41 failures pre-existing on `main` @ 208e72c (library-grid, library-detail, motif-browser and responsiveness tests); "nothing that passed before now fails" is a weak gate with 41 reds, and no session may weaken a Panel test to pass.
- **Source** — `ui-prototypes/REPORT.md` §4 "The pytest gate"; `ui-prototypes/DECISIONS.md` §10; [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Standing preferences".
- **Status** — `ticketable now`

### L2 — Windows file locks at test teardown
- **Question** — Should tests that memory-map temp `.npy` files or hold `.sqlite` handles release them before teardown (`PermissionError [WinError 32]` in `test_library_grid` and `test_materialize_arbitrary_file`, reproduced serially)?
- **Why it matters** — The remainder of the 41 failures; they are test-hygiene bugs on the only platform this project runs on, not xdist artefacts, and they hide real regressions.
- **Source** — `ui-prototypes/REPORT.md` §4 "The pytest gate"; `ui-prototypes/DECISIONS.md` §10.
- **Status** — `ticketable now`

### L3 — Retirement trigger and the archival branch
- **Question** — The settled trigger ("the slice confirms the stack") has arguably fired, yet `UI/` stays because deletion is not trivial: what is the concrete trigger now, when is `archive/panel-ui` created (it does not exist yet), what is kept on `main`, and does `tests/ui/` move or die?
- **Why it matters** — Until this is sharp the old tree sits on `main` unmaintained but still inside the pytest gate, so every core change can break a tree nobody works on.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Constraints settled while charting" and "Not yet specified" (retirement mechanics); [Decide where the new tree lives and how both trees are served][tree-location] "The retirement mechanics".
- **Status** — `ticketable now`

### L4 — Tests that mix core assertions with UI imports
- **Question** — How are the `UI`-importing test files split so their core assertions survive deletion of `UI/` — notably `test_heldout_lock`, `test_manifest`, `test_export`, `test_import_drop_motifs`, `test_compare` and `test_run_groups` — and which purely UI tests die with it?
- **Why it matters** — A grep on 2026-09-16 finds 37 `tests/test_*.py` files plus `tests/ui/harness.py` and `tests/_session_isolation.py` importing `UI`; deleting without splitting drops core coverage of the held-out lock, manifests, export and imports, and `tests/test_plots_perf.py`'s decimator pin (C8).
- **Source** — grep of `tests/` for `from UI` / `import UI`; `docs/adr/0001-web-ui-stack.md` "Consequences" (last bullet).
- **Status** — `ticketable now`

### L5 — The UI snapshot inside `Working/`
- **Question** — Is `Working/Detection/sax/dsax_python/UI_snapshot_20260810-0512/` archived with the old tree, moved out of `Working/`, or deleted?
- **Why it matters** — Its `app.py:48-52` and `run_panel.py:38` import `UI.*` from inside the UI-free core's directory, so it breaks the moment `UI/` goes and contradicts rule 1 in spirit.
- **Source** — `Working/Detection/sax/dsax_python/UI_snapshot_20260810-0512/app.py`, `run_panel.py`; `CLAUDE.md` rule 1.
- **Status** — `ticketable now`

### L6 — Panel-era tooling and agent instructions
- **Question** — Which of `scripts/dev_serve.py`, `docs/UI_VERIFICATION.md`, `tests/ui/` and `CLAUDE.md`'s Layout table and "Panel surfaces" section are rewritten for `webui/`, archived or kept, and which general findings (construction is not painting; layered canvases fool naive paint checks) carry forward?
- **Why it matters** — `CLAUDE.md` is loaded by every agent and still defines "done" for a UI ticket as `pytest -m ui` plus Panel screenshots, which now points agents at the ignored tree.
- **Source** — [Define the new tree's test gates][test-gates] (reusability of `tests/ui/`); `ui-prototypes/REPORT.md` §8.2 "fit with the existing repo", §3 B (layered canvases); `CLAUDE.md` "Layout" and "Panel surfaces".
- **Status** — `ticketable now`

### L7 — Prototype B no longer runs
- **Question** — Is the runner-up kept runnable (for example, pinning its own copy of the service modules it imported by path from `ui-prototypes/A-react-fastapi/server/`), or accepted as frozen evidence only?
- **Why it matters** — The ADR names B as "the real alternative to start from" if the choice is refuted; since A was promoted to `webui/` and `ui-prototypes/` frozen (commit f0c8f13), a refutation would start from a fallback that does not start.
- **Source** — `ui-prototypes/DECISIONS.md` §5 (B imports A's service modules by path); `docs/adr/0001-web-ui-stack.md` "Considered Options" B.
- **Status** — `ticketable now`

## Out of scope (not fog)

Ruled out, not open. Listed so they are not rediscovered as fog; each returns only if its ruling is redrawn.

### O1 — Reimplementing anything under `Working/`
- **Question** — Should the rebuild change the algorithms it displays?
- **Why it matters** — No: the algorithms are the science and the rebuild only displays them (UI_CONTEXT §4.1). Adding public read or declaration surfaces (C1, C3, C8) is adding, not reimplementing.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Out of scope" bullet 1.
- **Status** — `out of scope`

### O2 — `Pipelines/` as code
- **Question** — Is `Pipelines/` part of the rebuild?
- **Why it matters** — Not as code; it is in scope only as the visual reference corpus for export and report output (E1).
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Out of scope" bullet 2.
- **Status** — `out of scope`

### O3 — Multi-user, accounts, authentication, hosting, deployment
- **Question** — Does the interface support more than one researcher or run anywhere but localhost?
- **Why it matters** — No: single researcher, single machine, no auth. Every "who" records "this installation"; named accounts, per-user blind state and a second registration sign-off are recorded as future scope only.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Out of scope" bullet 3 and "Constraints settled while charting"; `prototyping/UI_FUNCTIONAL_SPEC.md` §11 bullet 1.
- **Status** — `out of scope`

### O4 — Schema changes without independent justification
- **Question** — Does the rebuild change the storage model?
- **Why it matters** — Not without a reason that serves the interface; additive migrations through an idempotent `init_db()` remain available (A12, A13 may need them), and the `recordings`-row-is-a-channel inversion is recorded, not renamed.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Out of scope" bullet 4 and "Vocabulary".
- **Status** — `out of scope`

### O5 — Feature development of the old `UI/` tree
- **Question** — Does the Panel tree gain features while it coexists?
- **Why it matters** — No: frozen, kept green, retired on the trigger (L3). Fixing its pre-existing test failures (L1, L2) is maintenance, not features.
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Out of scope" bullet 5.
- **Status** — `out of scope`

### O6 — Relaxing evaluation protection
- **Question** — Can `M4_aug_concat_fs1.mat` be opened, or the two `M2_aug` sample rates split across train and test?
- **Why it matters** — No: M4 stays held out and refused without an explicit, typed and logged unlock, and the two `M2_aug` rates are one recording (B30 applied the same rule to Library scope).
- **Source** — [Map: rebuild the Pipeline GUI interface on a stack chosen by evidence][map] "Out of scope" bullet 6; `prototyping/UI_REVIEW_BACKLOG.md` D6, B30; `prototyping/UI_FUNCTIONAL_SPEC.md` §12 P19.
- **Status** — `out of scope`

### O7 — Human-labelled windows as a chain source
- **Question** — Can windows humans have already labelled be a chain source, skipping sliding windows?
- **Why it matters** — Sketched in training frame 0b but explicitly out of scope now; the related split question for supplied window sets (A11) stays open.
- **Source** — `prototyping/UI_REVIEW_BACKLOG.md` B3; `prototyping/UI_FUNCTIONAL_SPEC.md` §12 P13.
- **Status** — `out of scope`

### O8 — Text wrapping in the `.pen` mockups
- **Question** — Are the 14 caption paragraphs that overrun their containers a UI requirement?
- **Why it matters** — No: `.pen` text nodes have no width and do not wrap, so it is a mockup artifact; the copy is correct, the line breaks are not.
- **Source** — `prototyping/UI_FUNCTIONAL_SPEC.md` §11 bullet 5.
- **Status** — `out of scope`

### O9 — Discovery compare's heuristic explanatory sentence
- **Question** — Does the stage-by-stage compare explain divergence in prose?
- **Why it matters** — Replaced by stage pictures and divergence numbers; if ever reinstated it must be derived from both runs' cached stage artifacts, never a heuristic.
- **Source** — `prototyping/UI_FUNCTIONAL_SPEC.md` §11 bullet 6.
- **Status** — `out of scope`

### O10 — FitzHugh–Nagumo's interpretive claim
- **Question** — Does a FitzHugh–Nagumo fit claim anything about mechanism?
- **Why it matters** — No: its parameters are descriptors like peakedness; the block itself is fog (A9), the interpretation is out.
- **Source** — `prototyping/UI_FUNCTIONAL_SPEC.md` §11 bullet 3.
- **Status** — `out of scope`

### O11 — Prototype B's left-open fixes
- **Question** — Are B's unresolved items (RangeTool grips and move-drag, rich modal cards, whole-line threshold drag, row thumbnails versus §6.8, corpus rail details, per-session debug evidence, icon buttons' accessible names) carried forward?
- **Why it matters** — No: B lost and is frozen evidence (L7 covers whether it stays runnable).
- **Source** — `ui-prototypes/REPORT.md` §4 B round 1 "Fix pass" ("Left open"); `docs/adr/0001-web-ui-stack.md`.
- **Status** — `out of scope`

### O12 — Stacks ranked out before building
- **Question** — Are Dash/NiceGUI, Qt/PySide6 with pyqtgraph, or webview wrappers still candidates?
- **Why it matters** — No: ranked out before building (same family as B; no web output path with every renderer custom; answer no open question). A refutation of the chosen stack restarts from B.
- **Source** — `docs/adr/0001-web-ui-stack.md` "Considered Options"; `ui-prototypes/REPORT.md` §2 "Pre-build ranking".
- **Status** — `out of scope`

[map]: https://github.com/mitchbradshaw/CNN/issues/4
[visual-target]: https://github.com/mitchbradshaw/CNN/issues/9
[signal-reduction]: https://github.com/mitchbradshaw/CNN/issues/10
[ui-context]: https://github.com/mitchbradshaw/CNN/issues/11
[frontend-core]: https://github.com/mitchbradshaw/CNN/issues/13
[tree-location]: https://github.com/mitchbradshaw/CNN/issues/14
[test-gates]: https://github.com/mitchbradshaw/CNN/issues/15
