# UI prototype review — backlog and open decisions

Running log for the page-by-page refinement of the `.pen` prototypes (started 2026-09-14).
The `.pen` files are edited directly through the pencil MCP; `generators/` is retired.

## Open decisions (user to return to)

| # | Page | Question | Context |
|---|---|---|---|
| D1 | Explore › Signal | Bottom ribbons still read *Filters & search · Annotations · Detections · Keyboard shortcuts*. Should they mirror the drawer's three tabs (Annotations · Detections · Shortcuts) with filters inside each? | Drawer was rebuilt as tabs with a collapsible filter section. |
| D2 | Explore › Span edit | Span edit is only reachable as a hand-off from Review. Should Explore also offer "edit extent" on an annotation it already owns, or stay Review-only? | Spec §4.3: editing lives in Explore, entered from Review. |
| ~~D4~~ | Analyse (all block pages) | *Resolved 2026-09-14: option (c) — Settings › Analysis defaults holds the rule, each block evaluates it on its span (spec §9.5, P23).* | PRD Part 1 story 11: defaults adapt to the span. |
| ~~D5~~ | Review, Library | *Resolved 2026-09-14 (sweep): §4.1 wins. Review's `Shape, z-normalised` panel and Library atlas rail's `members, z-normalised` are redrawn in detrended mV on a shared y-scale. Shape distance stays z-normalised, as a number only. UI_CONTEXT G7's "z-normalised overlay" goes to the correction ticket → B27.* | Frozen rendering rule, UI_CONTEXT §4.1. |
| ~~D6~~ | Settings, Models | *Resolved 2026-09-14 (sweep): the held-out lock is on and M4 is refused. Unlocking needs the name typed and is logged. Settings › Datasets and Models Launch are redrawn, and P19 is revised → B27.* | Evaluation protection, UI_CONTEXT §4.1; map out-of-scope. |
| ~~D7~~ | All | *Resolved 2026-09-14 (sweep): all plots light, including raw signal and waveforms. Spec §3 → B27.* | Explore, chain Source row and interrogation used dark grounds. |
| ~~D8~~ | Library (+ detection cards) | *Resolved 2026-09-14 (sweep): the family palette avoids semantic hues (no pure red, green or blue). §3 gains a family-identity entry → B27.* | F-06 green, F-09 red clashed with §3. |
| D3 | Explore (all) | Placeholder numbers assume M2_aug fs1 = 1 Hz (sample indices, 18-sample motif, ±20 s window). Confirm real sampling rates so units are correct. | Recording menu shows fs1 = 1 Hz, fs2 = 2 Hz, Mushroom/L_LM = 10 Hz (L_LM inferred). Settings › Datasets now marks each sampling rate `read` or `inferred` (L_LM_Jul26_J inferred); real rates still to confirm. |

## Done

- **Explore** (2026-09-14): shared shell components; corpus toolbar, axes, colour-by, detections filter, recording menu + legend frame (1b); signal axes, detections picker, motif extent + medoid overlay, Review hand-offs, popover frame (2a); drawer tabs Annotations / Detections (2c) / Shortcuts (2d); cross-channel controls, classification, actions, lag-aligned frame (3b); span-edit fixes.

- **Analyse › Interrogation** (2026-09-14): shell + toolbar (source picker chip, null chip, estimate) + chain ribbon with status/type badges on every frame. 4a members with mV thumbnails, verdict, distance, filters, pagination, sampled overlay, scope table, provenance; 4b decluttered anatomy with axes and marker key, 10-wide sliding event strip, rose with units, rules with info + flags, per-event table; 4c histograms with count axes + null behind, stats instead of claims, scaling panel (relationship switcher, log–log fit, β with CI vs null β), timeline faceted by recording, parameters incl. colour-by and null. New frames: 4a-b source picker, 4b-b large family (212) strip window + sampled overlay, 4b-c stale after rule change with sensitivity preview, 4c-b colour-by-recording + depth~max slope, 4c-c aggregate wired to a spike-shape block (feature-wiring popover).

- **Analyse › Chain** (2026-09-14): shell, toolbar (editable run name, source chip, surrogate chip, History + Import pop-ups, re-run from first stale stage), vertical rows with controls (open · bypass · duplicate · delete), stale veils, shared time axis, compact footer. New frames: 1b run-history pop-up with apply-to-source, 1c empty chain + import template, 1d running with per-stage progress + cancel, 1e invalid junction with fix actions + undo, 1f failed block with error in place, 1g whole-channel matrix profile routed to an HPC job. Block pages: 02 encoding rebuilt with SAX process panels and a labelled null sweep; 04 detection rebuilt with context axes, dropped overlay + breakdown, richer detection cards, template save; new 01 baseline (template for Signal → Signal), 03 noise floor (template for estimator blocks). *(A 07 seeded-search side-input page was built then deleted by the user: seeded search is a Discovery mode, not an Analyse block. User has a screenshot to seed the Discovery seeded-search frame.)* Insert-stage modal rebuilt with a where-it-lands ribbon, type contract, cost/null/side-input badges and fits-first sorting. PRD departures recorded in `UI_FUNCTIONAL_SPEC.md` §12.

- **Analyse › Training** (2026-09-14): all four block pages rebuilt on the shared shell (six-block ribbon, toolbar with label-shuffle null). New frames: 0 training chain page (rows incl. split plan, matrix, class timeline, encodings, model hand-off to Discovery); 0b illustrative human-labelled-window source; 01 sliding windows (blocked split, gap ≥ window, boundary close-up, per-split human coverage, send unseen to Review); 02 matrix with aligned signal, CNN scores off + leakage note; 03 cluster (truncated dendrogram with axis, criterion, class cards, time occupancy, sizes + merge); 2b choose k (silhouette sweep, criterion lock, cluster × verdict contingency, bootstrap stability); 04 encode (window signal, colour scales, browse by class, encoder versioning note); 05 model as template builder (stage ticks, label source, training options, checks, trial job, Apply in Discovery); 4b **preview** of Discovery › Train results (paired arms vs RF baseline vs label-shuffle null, confusion, curves, leave-one-channel-out, register model).

- **Analyse › Training follow-up** (2026-09-14): Discovery results preview removed by user (screenshot kept → B1). Frame 0b: sliding-windows row removed (absent, not skipped), stages renumbered, source typed `— → WindowSet`, split-question flag → B7. Models tab added to this file's nav rail; *Apply in Discovery* → *Train in Models* on chain, 0b, 05 model and header copy. Spec: P11 revised, P14 Models workspace, P15 absent-not-skipped, §2 six workspaces, §6.8 block contract.
- **Analyse › Chain follow-up** (2026-09-14): Models tab in this file's nav rail. New frames: 1h Scores example chain (Source → Matrix profile row with null band and motif/discord markers, suggested `Scores → SpanSet` next row, terminal footer, template notes); 7 Matrix profile block page (signal with subsequence to scale, worked distance profile, profile = min of distance profiles, values vs surrogate, length sweep vs null, parameters, top locations, cost + HPC, Insert threshold); 6b algorithm glyph registry. B9 glyphs applied to the insert modal.

- **Discovery** (2026-09-14): file rebuilt on a new shell with the Models tab. One page, two ways to add a run (P17). New frames: 1 runs — multi-channel scope brush, runs list (reference + template + seed rows, glyphs, compare A/B), where-each-run-fires as channel small multiples with density bins and reviewed hours, scoreboard expanding per channel with per-channel recall and null expects / × null, detection browser with run + channel pickers, run acts; 1b add-template picker (stage glyph strips, fits-type filter, locked parameters, per-channel cost, sample preview, "models live in Models" notice); 2 seed search (seed source Library / Explore selection / family medoid, provenance, carry / rebind, disabled + seed, parameters with recommended threshold, histogram over null, clean distance profile + matches track, match cards, apply bar); 3 compare seed run vs template run (stages aligned by role with absent slots, clean signal + A / B / agreement tracks + hover crosshair, per-channel overlap, disagreement stepper showing B's near-miss score); 3b compare every stage aligned by role with a decided-here table. Spec §7 rewritten; P16, P17. Follow-up: scope strips taller (32 px) with a 3-at-a-time channel pager (new frame 1c, six channels, ribbon follows the pager); cluster-cost runs disable *Add and run* and offer *Create SLURM script*; spec §6.9 saved window sets (P18), P16 revised to models-inside-templates.

- **Models** (2026-09-14): new file `UI_models_v1.pen` with shell + Models tab and five tabbed frames. 1 launch — template (glyph strip, binary/multi-class), sources decided by the template's source type (channels vs saved window set) with *Save window set*, paired label arms (manual, cluster, RF baseline always on; train on windows labelled in every arm), blocked test/validation split with per-class counts and multi-class warning, locked recording off, options (seed repeats off, RF 200× + model 5× shuffle null), before-launch checks, 2 h local limit → SLURM script. 2 jobs — local progress; HPC status marked by hand with a stepper, 3× estimate reminder, manifest inbox with import checks. 3 results — F1 vs RF and nulls, confusion, per-class calibration with suggested thresholds (feed the Threshold stage), training curves, held-out checks. 4 compare — manual vs cluster labels, what-differs pills, cluster→class mapping, F1 vs null, paired ΔF1 + per class, 2×2 agreement, per channel, disagreement stepper. 5 registry — list with used-by, retire blocked while used, register gate (held-out checks, human verification sample in Review, sign-off). Spec §7b, P19.

- **Review** (2026-09-14): file rebuilt on the shared shell with the Models tab (B8). Old generator frame (dark plots, unlabelled rail stats, no provenance) replaced by eight frames. 1 candidate — toolbar with named queue, blind state, write target, progress; labelled collapsed rails; title pills incl. artifact likelihood; clean context plot with axes and padding choice; shape vs family medoid; nearest families with medoid sparklines and a distance scale; verdict keys incl. skip; optional class keys + tags + note. 1b other channels popover with coherence and artifact factors. 2 cluster (seed-search matches) with member strip, include boxes, least-similar member excluded by default, batch checkbox. 3 queue rail open — five named queues, filters, grouping, up next with cluster groups. 4 evidence rail open — origin, detection, also found by, family, artifact, history, write target. 5 blind model-verification queue — machine opinion hidden, previous window revealed after verdict. 6 seed promoted — family choice, paused auto-advance, undo removes exemplar + verdict. 7 batch undone banner with redo. Spec §10 rewritten, §9.1 classes list, P20, P21.

- **Library** (2026-09-14): file rebuilt on the shared shell with the Models tab (B8); regroup dropped by user. Sections Motifs · Window sets · Templates. 1 recurrence — members per hour with reviewed-coverage bars and `?` for never-looked cells, artifact cells kept visible, recordings spanned per family, selection rail with shared-ground *Deselect*, omitted strip. 2 atlas (single motifs × shape distance) — exemplar + medoid in shared mV, badges, detail rail with sampled members and hand-offs (Discovery seed search, Analyse interrogation, Review queue). 2b same catalogue as sequences × sequence similarity — single motifs and unfitting sequences omitted and flagged, composition, multi-seed search disabled. 3 family — exemplar and medoid, unjudged banner, paged members, `added by hand` / removed-by-hand strip, read-only verdict, editable tags/class. 4 edit grouping — unit, basis (distance / feature bins / labels incl. provenance), frequency-content example, what does not fit, preview incl. hand edits. 5 empty library + import dry run. 6 window sets. 7 templates with glyph strips, versions and scores by run. Spec §8 rewritten, P22.

- **Settings** (2026-09-14): file rebuilt as 16 pages on the shared shell with the Models tab; project vs personal scopes (P23). Datasets (fs read/inferred, start time, held-out lock off with M4 selectable), Channels & events (per-channel table with shared ground, event log with exclusions), Vocabulary (core five locked, classes with informative flag, tag definitions), Nulls (per analysis kind, significance), Analysis defaults (matching rule, recommended-value rules — D4 resolved, artifact likelihood, step cache), Compute & HPC (per-workspace local limits, clusters, job profiles, script preview, manual job status), Blocks, Review queues, Models & registration (gate), Library groupings, Storage & backups, Export, Audit log, About (future scope), Display, Keyboard & behaviour. Spec §9 rewritten, §11 user accounts as future scope, P23.
- **Jobs** (2026-09-14): new file `UI_jobs_v1.pen` on the shared shell (Jobs highlighted in the nav rail, header chip "3 need you"). 1 all jobs — needs-you cards, one table grouped paused runs / cluster jobs / local jobs / review queues / finished, rail for a paused run. 2 paused run — stages with states and timeline, stage result found in place with checks, Continue from next stage, other ways forward. 3 upload results and continue — placement from the naming convention, checks, a different-parameters file refused, missing-null note. 4 cluster job (moved from Models) — hand-marked status stepper, 3× reminder, script, manifest inbox with import checks and stage results for paused runs. Spec §7c, §7b.2 superseded, §2 nav, P24.
- ~~**B21 · Models file follow-up:** remove the *Jobs* tab from `UI_models_v1.pen`~~ *done 2026-09-14 — Jobs tab removed from all frames; frame 2 deleted and frames 3–5 moved left (names keep their numbers); an "open in Jobs ↗" link at the right of the tab row (filtered to training jobs, or to the job a result came from); launch notes say the script adds the job to Jobs and results return through Jobs › Manifest inbox; nav rail `Jobs · 3` and header chip `3 need you` match the Jobs file.* **Remainder:** `Jobs · N` / `N need you` in the other files' shells (Explore, Analyse ×3, Discovery, Review, Library, Settings) still show older counts — one Update per file's shell components.
- ~~**B22 · Paused state in Analyse and Discovery:**~~ *done 2026-09-14 — Analyse chain 1i, Discovery runs row.* a run paused on a cluster stage needs its own in-page state (banner on the chain page / runs list row: "paused at stage 3 · waiting on j-0217 · Open in Jobs") in `UI_analyse_chain_v1.pen` (frame 1g is close) and `UI_discovery_v1.pen`.
- **B19 · Confirm clusters:** the researcher may submit to more than one cluster or node; Settings › Compute & HPC allows several clusters and a `gpu-multinode` profile flagged *check the job can use 2 nodes*. Confirm what is actually available.
- ~~**B20 · Recording import flow:**~~ *done 2026-09-14 — Settings frame 1b.* Settings › Datasets has *Import a recording…* (dry run: fs read or entered, channel map, start time, link to an existing recording) but no designed frame.

## Design rules agreed

- Any "show all members/events" view caps at ~10: strips slide with navigation; overlays draw a seeded random sample with a resample control.
- Explanatory text goes behind info icons / popovers, not on the page.
- Each analysis type (slope, spike shape, FitzHugh–Nagumo…) is its own block with its own page. Aggregate is generic: it is wired to whatever Features the upstream block emits.
- Scaling relationships are switchable pairs; depth ~ duration is the default for slope analysis. Every fit shows β with CI beside the null β.
- Interrogation null default: matched random windows (200×); shuffled onsets for interval statistics.
- Group comparison in Aggregate uses colour-by, not small multiples.

## Backlog

- ~~**B1 · Models file**~~ *done 2026-09-14 — `UI_models_v1.pen` frames 1–5, spec §7b, P19.*
- ~~**B2 · Discovery file:** seeded search mode~~ *done 2026-09-14 — frame 2. Multi-seed search is specified in §7.6 (no frame until an algorithm supports it).*
- **B3 · Future source type (out of scope now):** windows from the human-labelled set as a chain source, skipping sliding windows (sketched in frame 0b).
- **B4 · Cluster selection criterion:** placeholder options (fixed k, fixed cut, max silhouette, gap statistic, min class size) — algorithm and default to be decided; nothing is pre-registered yet.
- ~~**B5 · Review file**~~ *queue designed 2026-09-14 — Training windows is a named blind queue (frame 3 list, §10.1); the model-verification queue is frame 5. A training-windows frame of its own is not drawn (same layout as frame 5 without the reveal).* Must accept windows queued from the training chain (up to 20,000, binary verdict mode) and tag them with their originating run.
- **B15 · Where window verdicts are stored:** training and verification windows are machine-produced units with no detection row, yet the verdict is human judgement of machine output. Options: a window-verdict table on the adjudication side keyed by window-set id + window index, or materialising each queued window as a detection row of a "windows" run. Decide at implementation; must keep §4.1 separation (spec §10.1).
- **B17 · Library grouping bases need definitions** *(placeholders in Settings › Library groupings)*: sequence similarity (how events, order and gaps combine), the feature for *frequency content* and *timescale*, what a *spike train* unit is when it was not imported as one, and default cuts / bins / minimum group size. Spec §8.2 names them; nothing is pre-registered. Sequence detection itself (what makes motifs a sequence) is shared with Review's *sequence* clusters (B16).
- **B18 · Hand-edit storage:** hand edits (add, remove, exemplar, tag, class) must be stored apart from computed groupings and re-applied on regroup, with the "points at a family this grouping lacks → hand group" rule (§8.3). Decide the key a hand edit binds to (family id is not stable across groupings; exemplar or member set may be).
- **B16 · Cluster grouping rules** *(placeholders now live in Settings › Review queues and Library groupings: gap ≤ 6 min, ≥ 2 events, cohesion 0.45 — values still to decide)*: *sequence* (max gap between detections, same run and channel?) and the cohesion limit (0.45 placeholder) need defaults, probably in Settings › Analysis defaults.
- **B6 · Encoders:** currently the existing GASF / GADF / RP / fusion at 224 px only; keep the encoder-set selector so new encoders or sizes register as versions.
- **B7 · Implementation problem — splitting a supplied window set:** the blocked split and its gap live inside the sliding-windows block. When windows arrive as a source (e.g. the human-labelled set, frame 0b) there is no sliding-windows stage, so nothing applies the split. Human-labelled windows may be adjacent or overlapping, which is exactly where leakage bites. Candidate: a split *filter* applied to the source windows themselves (blocked by recording and time, gap ≥ one window length, windows straddling a block edge dropped). Decide when the algorithm is implemented; frame 0b carries a flag pointing here. (Spec P15.)
- ~~**B8 · Models tab in every nav rail:**~~ *done 2026-09-14 in Explore and Interrogation, the last two.* added to `shell/nav-rail` in `UI_analyse_training_v1.pen` only (between Discovery and Review, `brain-circuit` icon), and training-chain buttons renamed *Apply in Discovery* → *Train in Models*. Done in `UI_analyse_chain_v1.pen`, `UI_discovery_v1.pen` and `UI_models_v1.pen` too (2026-09-14). Done in `UI_review_v1.pen`, `UI_library_v2.pen` and `UI_settings_v1.pen` (rebuilt, 2026-09-14). Still to update, each file's own `shell/nav-rail` component: `UI_explore_flow_v2.pen`, `UI_analyse_interrogation_v1.pen`. Also check Discovery pages for any training copy, and the chain page's model/HPC wording.
- ~~**B9**~~ *done 2026-09-14 — glyphs on all 12 insert-modal cards + large glyph in the detail panel; registry of 21 in frame 6b. Discovery now reuses them (runs list, template picker, compare). Library template cards done too (Library frame 7).* **Algorithm glyphs in the insert-stage modal (`UI_analyse_chain_v1.pen`):** every block needs a small static thumbnail representative of the algorithm (not of data) for the insert-stage list, reused in Discovery's picker and template cards. Draw examples on the insert modal for the existing blocks (baseline, SAX, noise floor, detection, matrix profile, threshold, sliding windows, window matrix, cluster, image encode, model). (Spec §6.8.)
- ~~**B10 · `Scores → SpanSet` threshold block page:**~~ *done 2026-09-14 — chain frame 7b.* the generic threshold block the `Scores` type exists for (PRD line 130) — histogram with draggable threshold over the null, count-vs-threshold with null, min duration / merge gap. Build after the Scores example.
- **B12 · Save window set (spec §6.9, P18):** add *Save window set* to the sliding-windows row and block page in `UI_analyse_training_v1.pen`, a saved-window-set picker wherever a `WindowSet` source is accepted (Analyse source chip, Models launch, Review queue source), and a window-set shelf in the Library with the **not train-safe** badge (*Library shelf done 2026-09-14 — Library frame 6*). Revisit B7 in the light of it.
- ~~**B14 · Models follow-ups:**~~ *done 2026-09-14 — Models frames 1b and 4b.* a saved-window-set source state for Launch (template that starts from `WindowSet`); a *both wrong* / *only B right* disagreement state; ~~Review must accept the registration verification sample~~ (done: Review frame 5, blind model-verification queue).
- ~~**B13 · Model as a chain stage:**~~ *done 2026-09-14 — chain frame 8, insert modal card, 6b registry.* `Model + WindowSet → Scores` needs a block page and a glyph in the insert modal (§6.8 row currently "not built") so detection templates can contain a registered model (P16).
- **B11 · Block contract:** spec §6.8 lists what every new analysis block must supply, by type signature. Keep it current as each block page is built; a new signature needs a row before its first block.

### From the layout and consistency sweep (2026-09-14)

All 87 frames were exported and checked. Evidence per frame is in
[`UI_SWEEP_2026-09-14.md`](UI_SWEEP_2026-09-14.md); X-numbers refer to it. Order is priority.

- ~~**B23 · One placeholder world**~~ *done 2026-09-14 across all ten pens; canon in spec §0.* *(blocker for handing the pages to an implementation agent)*. Pick one canonical set of placeholder facts and make every file agree:
  - F-03's name, member count, exemplar and medoid ids, and length (X1)
  - one job-id scheme, and j-0212's state (X2)
  - one class vocabulary (X3)
  - the registered models (X4)
  - recording durations: M2_aug fs1 is 721 h in reality (X5)
  - `ws_M2aug_3ch_600s` (X6)
  - verification progress (X7)
  - the template list (X8)
  - the actor, "this installation" (X9)
  - run ids (X10)
  - channel names (X11)
  - Settings' unsaved changes vs values already used elsewhere (X13)

  Suggest writing the canon as a short table at the top of `UI_FUNCTIONAL_SPEC.md` first, then editing the pages to it.
- ~~**B24 · Type signatures for Noise floor and Drop detection**~~ *done 2026-09-14 — decided: Noise floor before Encoding (spec §6.5).* *(blocker)*. Chain rows and block pages say `Encoding → Scores` and `Scores → SpanSet`. §6.5/§6.8, the glyph registry and Discovery 3b say `Signal → Signal + estimate` and `Encoding → SpanSet`. Settings › Blocks says a third thing. Decide once in §6.8, then fix every page. Noise floor's cut "k = sweep knee (block 02)" also runs the dependency backwards.
- ~~**B25 · P3 and Discovery-mode leaks**~~ *done 2026-09-14.* *(blocker)*:
  - Explore cross-channel's "Fan out a chain … opens Analyse with a channel scope"
  - training 0b's "all channels" source
  - Seeded search in the insert modal
  - `seeded_F03_native` importable in chain 1c
  - CNN classifier typed `Encoding → Scores` instead of `Model + WindowSet → Scores` (P16)
- ~~**B26 · Shell remainder, extends B8 / B21.**~~ *done 2026-09-14.* Also:
  - The `M4 held out` header chip is missing from every Jobs, Review, Library and Settings frame.
  - Status badge words differ from §6.8 (`error`, `cluster`, `waiting`, `queued`, `invalid`) (X15).
  - Stale routes in copy: "local ceiling 10 min (Settings › Analysis)"; "Settings › Storage › manifest inbox" (now Jobs); "Settings › Interaction"; the Audit log's "Models › Jobs" (X14).
  - Time display: clock time in Review vs "hours since start" in Settings › Display (X12).
- ~~**B27 · Redraws from D5–D8.**~~ *done 2026-09-14; UI_CONTEXT G7 wording still with the correction ticket.*
  - Review frames 1–5: shape panel in mV.
  - Library 2: rail overlay in mV; family palette.
  - Analyse 3 detection cards: shared mV scale, no normalised look.
  - Settings 1: lock on. Models 1: M4 locked.
  - Dark plot grounds → light: Explore 1, 1b–1d, 2c; chain Source row; interrogation 4a / 4b thumbnails and overlays.
  - Spec: §3 light plots + family identity; P19 revised.
  - UI_CONTEXT G7's "z-normalised overlay" contradicts §4.1 → the map's UI_CONTEXT correction ticket.
- **B28 · Arithmetic and state inside frames.** Numbers that don't reconcile, and block pages that open with changes their chain already shows as applied. Worst offenders: training 01 / 5b / 2b / 5c window and class counts; Models 3 (401 vs 432 test windows, precision column); interrogation 4b-b (F-07 page showing F-03 rows), 4c-b, 4c-c (copied histograms); chain 1h / 7 (markers vs list). Full list per frame in the sweep file.
- **B29 · Layout defects.**
  - Models 3: the arm switcher overlaps "open in Jobs".
  - Chain 6: disabled-reason text overruns the cards.
  - Chain 1e: the banner overlaps a card edge.
  - Explore 1b: two popovers overlap.
  - Library 4: footer touches the modal edge.
  - Label-on-trace collisions (Review 1/1b, Explore 1).
  - Empty regions (Explore 1d, Library 5, chain 1c / 6 detail panels).
  - Settings' "differs" dots follow the open page.
- ~~**B30 · Library scope mixes fs1 and fs2 of one recording**~~ *done 2026-09-14 (atlas scope uses M3_jul).* (atlas scope `M2_aug fs1 · CH3/CH4` + `M2_aug fs2 · CH2`). This double-counts the same events. Either refuse the mix, as the train/test rule does, or state that fs2 is a resample.

### Sweep fixes applied (B23–B30 and per-pen backlog)

Canon written to spec §0; B24 chain order fixed in §6.5 (Noise floor before Encoding).

- **Settings** (2026-09-14):
  - **Shell:** `Jobs · 3`, `3 need you` and the `M4 held out` chip (B26).
  - **Datasets:** 721 h; the lock is on and M4 is "held out · locked" (D6); the note overflow is fixed.
  - **Channels:** CHn_XY names; the excluded-spans column counts the all-channel exclusion.
  - **Vocabulary:**
    - the merge example is now spike-train-short (sharkfin stays a live tag, and gains a tag row);
    - class colours are off the semantic hues (D8);
    - the seed role no longer collides with its count.
  - **Unsaved bars:** hidden where the value is already used elsewhere (Nulls, Compute, Review queues, Models, Library groupings) (X13). "Differs from default" dots are the same on all 16 pages.
  - **Blocks:**
    - added Drop detection, Image encode and Aggregate (15 registered + 1 not built);
    - Noise floor is `Signal → Signal + estimate` and sits before Encoding;
    - Model stage shows 3 templates.
  - **Library groupings:** a sequence is "same run and channel".
  - **Storage:** an 8-char hash and a `<m>` token.
  - **Audit log:** lock turned on, j-0214, `Jobs`, "this installation" unclipped, a batch-undo filter.
  - **Display:** family palette without semantic hues; hand edit colour no longer matches run B.
  - **New frame 1b:** import a recording, with dry run and checks (**B20 done**).
  - **Not done, needs you:** B19 (which clusters actually exist), B16/B17 placeholder values.
- **Models** (2026-09-14):
  - **Classes:** spike-train / burst / slow-drift / plateau throughout (X3).
  - **Ids and counts:** j-0212 everywhere (X2); 2 training jobs; 721 h; CHn_XY; `--sources M2_aug_fs1:…`; 3 seeds; stage names match the Blocks registry.
  - **M4:** locked (D6).
  - **Launch:** saves `ws_M2aug_3ch_600s v2` (X6).
  - **Results:**
    - 432 test windows (X);
    - precision/recall/F1 table and balanced accuracy recomputed from the confusion matrix;
    - the arm switcher no longer overlaps "open in Jobs".
  - **Compare:** 432 windows (283 / 58 / 37 / 54, McNemar p = 0.04); per channel 128 / 209 / 95.
  - **Registry:**
    - verification 33 / 40 judged, 28 agree (X7), and Register stays disabled until it's complete;
    - `cnn_cluster_v1` added as registered (X4);
    - registered name `cnn_windows_v3_manual`.
  - **New frame 1b:** launch from a saved window set, with picker, train-safe badges, split locked, sliding windows absent (**B14 part 1, B12 Models picker done**).
  - **New frame 4b:** compare stepping through *both wrong* (**B14 part 2 done**).
- **Jobs** (2026-09-14):
  - **Shell:** `M4 held out` chip (B26).
  - **Job states (X2):** j-0212 finished and imported; the overdue job is j-0214 (seed repeats, marked running 11:05 per the Audit log, 3.3× a 1 h estimate, within its 04:00 walltime); 2 on hpc-1.
  - **Upload frame 3:** now r-0431's stage 3 (the card that offers upload), 721 h and CHn_XY. The refused file's hashes are 8 characters.
  - **Inbox:** shows j-0212 as imported.
  - **Frame 1:** "4 review queues · 1 idle"; the "Models › Jobs has moved here" footer is removed.
- **Review** (2026-09-14):
  - **Shell:** `Jobs · 3`, `3 need you` and the `M4 held out` chip (B26).
  - **D5:** the shape panel is in mV on frames 1–6.
  - **F-03 (X1):** sharkfin, 112 members, medoid m-1846; F-07 has 212 members.
  - **Classes:** key 9 electrode artifact replaces `0 none` (X3).
  - **Verification queue:** for `cnn_windows_v3 · manual` (X4).
  - **Times:** hours since start everywhere (X12).
  - **Evidence:** "this installation" (X9), recommended 0.62 (X11), 721 h.
  - **Title pills:** frames 3 and 4 have `× null` and the family distance again.
  - **Seed-search cluster (frames 2, 7):** members c-0371–c-0377 (no collision with the r-0412 queue), their own time axis, cohesion mean d 0.21 for the 6 included, "shared y · mV".
  - **Other counts:** cluster 13 has 3 members; frame 6 shows 941 left.
  - **Blind frame 5:** no *Edit span in Explore*.
  - **Labels:** moved off the traces.
- **Library** (2026-09-14):
  - **Shell:** `Jobs · 3`, `3 need you` and the `M4 held out` chip (B26).
  - **F-03 (X1):** sharkfin, 21 s, 3 hand edits; F-07 is "58 of 212".
  - **D5:** atlas rail members in mV.
  - **D8:**
    - family colours moved to the canon palette (recurrence labels, atlas cards and traces, rail, family page, sequence cards);
    - the atlas legend says "family colour".
  - **B30:** atlas scope uses `M3_jul · CH2` instead of fs2 of the same recording; recurrence shows M3_jul at 280 h.
  - **Names and actor:** CHn_XY; "this installation" (X9).
  - **Family page:** medoid m-1846 sorts first; the exemplar card is E-0102 at d 0.07; revision d-88402; header sharkfin.
  - **Sequences 2b:** chip reads "sequence similarity"; S-04 has 10; 1,018 motifs in no sequence and 1,035 omitted, which reconcile with the sequence compositions; S-02 has 42 motifs.
  - **Edit grouping:** 5 groups; "7 motifs · 1 group"; 1,381 / 21; ~10 min; the footer no longer touches the modal edge.
  - **Window sets (X6):** `ws_M2aug_3ch_600s` has 15,660 windows, 14 % labelled, CH2_A1 · CH4_A2 · CH7_B2; the test split is green (matching Models); class bars use the class palette; send 13,520 unlabelled.
  - **Templates (X8):** drop_motifs9 on the list; a "1–7 of 14" pager naming the rest; run scopes 721 h and 280 h.
  - **Follow-up, cross-file:** family colours still use the old hues in Review (nearest-families sparklines, F-03 pill dot) and anywhere in Discovery and Analyse. Fixed as each pen is opened; Review needs a second pass.
- **Discovery** (2026-09-14):
  - **Shell:** `Jobs · 3`, `3 need you` (B26).
  - **Canon:**
    - CHn_XY names (X11);
    - E-0102 is F-03's exemplar, 112 members (X1);
    - `seed_E0102_bank`;
    - badge words `on cluster` / `new`, not `running` / `queued` (X15).
  - **Runs page:** browser "12 / 72"; send 110 unjudged; CH7 "6 h · too few"; sharkfin_v2 at 4 stages everywhere.
  - **1b:** ≈1,435 over 522 h; seed_F03_native disabled as already in session.
  - **Seed draft:** renamed `seed_F03_native_2`.
  - **B24:** Noise floor before Encoding on 3 (roles) and 3b (cards, stage numbers, first-differing chip, decided-here table).
  - **1c:** the duplicate pager is removed.
  - **D7:** scope strips and the seed thumbnail are light, with dark traces and a lighter selection.
  - **B22 (Discovery half):** paused run row `mp_drops_v3 · r-0431 · paused 3/4 · Open in Jobs ↗`, so Jobs' run name now appears in Discovery.
- **Analyse › Chain** (2026-09-14, in progress):
  - **B24 reorder:** Noise floor (02) before Encoding (03) on the chain page, every block-page ribbon, the insert modal, 1b history, 1c import and 1d running. Signatures are `Signal → Signal + estimate` and `Encoding → SpanSet`. The stale edit sits at 03, so "Re-run from 03" holds.
  - **1d running:** 02 running; 03 new, veiled "waits for 02".
  - **1e invalid junction:** now 04 needs Encoding after deleting 03.
  - **Insert modal:** the slot moved to 03 → 04, so every compatibility reason stays true.
  - **B25:** Seeded search disabled as "a Discovery mode · not a chain block"; the CNN classifier card is now **Model stage** `Model + WindowSet → Scores`; 1c import offers sharkfin_v2, not seeded_F03_native.
  - **Routes and wording:** 20 min limit under Compute & HPC; Jobs › Manifest inbox; 721 h; 2,595,600 samples; discords *above* 2.5σ; badge words `failed` / `new` / `on cluster`; 1g time ticks to 721 h with a blue primary; 200 surrogates per value.
  - **D7:** light plot grounds.
  - **Detection page 3:** cards light, dip heights to depth on a shared ±0.4 mV scale, family colours per canon.
  - **New frames:**
    - **7b Threshold to spans block** (scores with cut, histogram over the null, spans vs cut, spans list, parameters incl. recommended cut, hand-offs) (**B10 done**).
    - **8 Model stage block** (`Model + WindowSet → Scores`: windows scored per class over the signal, model card with calibration, scores vs label-shuffle null, top windows, *Insert Threshold · 0.62*) (**B13 done**; the 6b registry and the insert modal now name *Model stage*).
    - **1i paused run** a-0098, stage 02 result found in place, checks, *Continue from 03* / *Open in Jobs* (**B22 done**, both halves).
  - **Chain 1h / 7:** clock times converted to hours since start.
  - **Not done (optional):**
    - the missing 6b glyphs (Span dedupe, Top-k pairs, Peak picker, Spike shape);
    - the rest of B28's chain arithmetic (baseline warning, scores markers, run-history interrogation row, 1c Save template enabled).
- **Analyse › Interrogation** (2026-09-14):
  - **Shell:** Models tab added to its nav rail (**B8 done here**); `Jobs · 3`, `3 need you`.
  - **Recordings (canon):** Mushroom_260720 → M3_jul; L_LM_Jul26_J spelling.
  - **F-03 (X1):** 112 members, 17 within d ≤ 0.35; medoid m-1846; exemplar E-0102.
  - **Families:** F-07 "slow drift"; F-01 "single drop".
  - **Channels:** CH3_A2 / CH4_A2 for M2_aug.
  - **F-07 page 4b-b:** no longer shows F-03's members (s-1203, s-1204, s-1207, m-0231); 9 events flagged both places.
  - **D7:** thumbnails and overlays light.
  - **D8:** member traces in family colour (F-03 teal, F-07 slate).
  - **Not done (optional, B28):** 4c-b impossible stacked histograms, 4c-c copied histograms, 4c "100 % one fall" vs flagged event, the missing null panel on 4b.
- **Analyse › Training** (2026-09-14):
  - **Shell:** `Jobs · 3`, `3 need you`.
  - **Scope:** the chain is framed as a *span 0–45.2 h* of CH4_A2 rather than "whole channel · 45.2 h" (the recording is 721 h), so its 543-window counts stay true (P3 allows a span).
  - **B25 / P3:** 0b's source is `ws_human_labelled_mixed · CH4_A2 · 412 windows`, not "4,812 · all channels"; its image count is 1,236.
  - **P12:** the Random Forest group is unticked and flagged label-derived; the warning names it; the unapplied change is the RF exclusion (CNN scores off is the default).
  - **5d:** the cached Cluster stage is unticked; the trial job runs 04 → 05.
  - **Routes:** 20 min local limit; Jobs › Manifest inbox.
  - **D7:** light plot grounds.
  - **Not done (optional, B28):** 01 block and split counts, 5b class sizes (343 vs 543), 2b contingency sums, 5c window-time and image sums, 0 vs 5b cluster strips.
- **Explore** (2026-09-14):
  - **Shell:** Models tab (**B8 now done in every pen**); `Jobs · 3`, `3 need you` (**B21 remainder done in every pen**).
  - **B25 / P3:** cross-channel "Apply a template across these 6 channels — opens Discovery" replaces "fan out a chain … opens Analyse".
  - **Run ids (X10):** match the Analyse run history and Discovery runs (#128 drop_motifs9, #129 its surrogate, #131 6σ floor, #97 banded_sax_lp, r-0412 mp_drops_v3, r-0415 seed search E-0102); "6 runs · 4 methods" on signal pages.
  - **Duration and routes:** 721 h; *Settings › Keyboard & behaviour*; disagreement described in amber.
  - **D7:** light plots, translucent span bands.
  - **Span edit:** extent boxes redrawn (original grey outline, yours blue); the human revision dot is green; F-03 medoid overlay in canon teal.
  - **Not done (optional, B28):** drawer filters vs rows, MOTIF_233 box scale, span-edit px scale, corpus filter vs map.
