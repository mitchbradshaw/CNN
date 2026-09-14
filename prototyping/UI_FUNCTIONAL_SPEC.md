# Underground Brains — pipeline GUI functional spec

Reference for building the UI from the concept pages in this folder. Written for
an agent or developer who has the `.pen` files open alongside it.

**Scope.** This is the single document. It absorbs `analyse-discovery-decisions.md`
(three grilling rounds, 13 September 2026, plus the block-structure follow-up) in full —
that file is superseded and can be deleted. Where a decision below is marked *rationale*,
it records why an alternative was rejected; those are the lines most likely to be
re-litigated by someone who wasn't in the room.

**Status.** Design only. This work sits after the 28 August 2026 feature freeze and
carries no deadline, so `pipeline-gui-prd.md`'s cut list and its "four workspaces,
nine tabs is a filing cabinet" constraint are advisory here rather than binding.
Everything below that exceeds the frozen build is specified future work.

**Authority.** Where this document and `PIPELINE_PRD.md` / `claude/pipeline-gui-prd.md`
disagree about the data model, the PRD wins and this document is wrong — except where a
decision below is explicitly marked as superseding it.

---

## 1. The files

| File | Workspace | Screens |
|---|---|---|
| `UI_explore_flow_v2.pen` | Explore | corpus, signal, signal + drawer, cross-channel, span edit |
| `UI_analyse_chain_v1.pen` | Analyse | chain, insert stage, encoding block, detection block |
| `UI_analyse_interrogation_v1.pen` | Analyse | library family, slope analysis, aggregate |
| `UI_analyse_training_v1.pen` | Analyse | window matrix, cluster, encode, model |
| `UI_discovery_v1.pen` | Discovery | 1 runs (multi-channel), 1b add-template picker, 1c six channels paged, 2 seed search, 3 compare two runs, 3b compare every stage |
| `UI_models_v1.pen` | Models | 1 launch, ~~2 jobs~~ (removed; moved to Jobs), 3 results + calibration, 4 compare A/B (manual vs cluster labels), 5 registry (§7b) |
| `UI_jobs_v1.pen` | Jobs | 1 all jobs, 2 paused run + continue, 3 upload results and continue, 4 cluster job + manifest inbox (§7c) |
| `UI_review_v1.pen` | Review | 1 candidate, 1b other channels, 2 cluster member strip, 3 queue rail open, 4 evidence rail open, 5 blind model-verification queue, 6 seed promoted, 7 batch undone (§10) |
| `UI_library_v2.pen` | Library | 1 recurrence, 2 atlas (single motifs), 2b atlas (sequences, omitted flagged), 3 family, 4 edit grouping, 5 empty + import, 6 window sets, 7 templates (§8) |
| `UI_settings_v1.pen` | Settings | 16 pages: datasets, channels & events, vocabulary, nulls, analysis defaults, compute & HPC, blocks, review queues, models & registration, library groupings, storage & backups, export, audit log, about, display, keyboard & behaviour (§9) |

Generators live in `prototyping/generators/`: `pen_kit.py` (primitives),
`pen_widgets.py` (charts and controls), `build_blocks.py` (Analyse pages + shared
chrome), then one builder per document — `build_explore_flow.py`,
`build_analyse_files.py`, `build_discovery.py`, `build_review.py`, `build_library.py`,
`build_settings.py`. Editing a page means editing its function and re-running its
builder; builders write their `.pen` to the parent folder. **The generators are retired
(14 Sep 2026):** the `.pen` files are now edited directly through the pencil MCP, and
re-running a builder would overwrite those edits. The paragraph above is kept as history.
Layout and consistency findings live in `UI_SWEEP_2026-09-14.md` and the backlog.

The `.pen` files are **mockups, not assets**. Use them for layout, information
hierarchy and copy. Do not extract the placeholder traces — every waveform in them is
synthetic.

---

## 2. Workspaces

Six, in this nav order: **Explore · Analyse · Discovery · Models · Review · Library**, with
**Jobs** (§7c) and **Settings** at the foot of the nav rail, separated from the six. *(Models added
14 Sep 2026 — see §12 P14. The five-workspace rationale below is kept for history.)*

Settings is not a sixth workspace — it configures the six workspaces and is never part of a
task flow. It absorbs what earlier drafts called Admin: vocabulary, recording import and
cluster-job import all live there (§9).

*Rationale — Agreement mode was removed from Explore.* Comparing a detector against the
human annotation store is the n=2 case of Discovery's algorithm comparison, so it lives
there rather than existing twice. This keeps the total at five rather than six, and
avoids two screens computing the same overlap.

*Rationale — Analyse and Discovery are separate workspaces.* Analyse is where a recipe is
**built**, at a scope small enough to see every intermediate, costing seconds. Discovery
is where finished recipes are **applied**, at a scope where intermediates are unviewable,
costing minutes to hours and routing to the cluster. Different scope, different cost
model, different output.

---

## 3. Shared conventions

**Two kinds of Analyse screen, and only two.** The chain page, where a chain is built
or imported; and a block page, opened from a block's settings icon. Every block page has
the same shape: toolbar with source chip and `‹ back to the full chain`, a chain ribbon
with the open block highlighted and every block clickable, then that block's settings
*and* that block's output together. Results are never a separate screen from settings,
because the output is how you judge whether the settings are right.

**Colour semantics, used consistently.**

- blue — active, selected, machine-origin, the primary action
- green — human annotation origin, "above chance", cached
- amber — needs attention, stale, differs, unadjudicated
- red — artifact, excluded, destructive
- purple — a second algorithm in a comparison; family affinity
- grey / muted — inactive, unavailable, explanatory
- family identity — a categorical palette that avoids the hues above (no pure red, green
  or blue), so a family's colour never reads as a verdict or origin *(D8, 14 Sep)*

**Plots are drawn on a light ground**, raw signal and motif waveforms included *(D7, 14 Sep)*.

**Waveforms are never normalised on screen.** Thumbnails, overlays, candidate-vs-medoid
and member samples draw detrended mV on a shared y-scale within a family (UI_CONTEXT §4.1,
frozen). Shape distance may be z-normalised as a *number*; the picture is not *(D5, 14 Sep)*.

**Plain-language captions are load-bearing.** Every stage row and most cards carry one
sentence saying what the thing did or means. That is the product thesis: the researcher
should not have to read the code to know whether a stage is doing the right thing. Keep
them.

**Nothing claims more than it knows.** Where a figure is unavailable, show it as
unavailable rather than omitting it — an absent denominator is information.

---

## 4. Data model decisions

These are load-bearing. Several exist to protect a research claim, not for convenience.

### 4.1 Human and machine spans stay physically separate

`annotations` is human-only. `detections` is machine-only and foreign-keyed to runs.
`adjudications` holds a human verdict against a detection. `v_spans` unions them with an
origin column so every read surface has one path while writes stay separated.

Consequence enforced throughout the UI: **no screen outside Review and Explore writes a
verdict.** Analyse, Discovery and the Library all hand off. A model that labels spans
produces candidates, and candidates go to Review.

### 4.2 Motif identity, and span revisions

**Supersedes the PRD, which does not address span editing.**

A `motif_member` row is the **identity of a motif**. It carries a current span pointer
and a revision list. Revisions are spans, not edits to a span:

```
member m-1846
  rev 1   detection d-0412   run 128    machine   what re-runs match
  rev 2   annotation a-2077  human edit           current
```

Rules:

- A human edit to a span's extent writes a **new annotation**, with a provenance pointer
  to the span it was derived from. It never mutates the detection. The detection stays on
  its run, so the run still reproduces from its recipe.
- The member's current pointer moves to the new revision. **The family view shows one
  card, not two** — it lists members, not spans.
- `v_spans` must filter superseded revisions by default, or Explore overlays and
  Discovery's matcher will both double-count.
- When a later run produces a span matching **rev 1**, it resolves to this same member
  rather than creating a new one. Rev 1 is what the matcher compares against; rev 2 is
  what the researcher sees.
- Editing an extent invalidates that member's `motif_edge` distance and may change the
  family's medoid and mean member distance. Recompute on save with a new recipe hash, or
  mark the family partially stale.

### 4.3 Where span editing happens

**Explore only.** It already owns span drawing, rasterized zoom and the annotation store,
so human geometry lands in the human store by construction rather than by a rule someone
has to remember.

Review offers **Edit span in Explore →**, which opens Explore in editing mode focused on
that span, with a persistent amber banner naming the candidate and offering
**Save and return to Review →** and **Return without saving**.

If editing turns out to be frequent, that is a signal the detector is mis-framing and the
fix belongs in the detector, not in the spans.

The Library does **not** edit extents. Its member actions are `Stage for Review →`,
`Open in Explore to redraw`, and `Remove from family`. A catalogue does not redraw its
own sources.

### 4.4 Interrogation writes per-event rows only

One row per `(span, recipe_hash)` in a derived-features table, separate from the Library's
rows. Roses, histograms and interval statistics are **views**, recomputed on demand, never
stored. Change the onset rule and every derived figure changes with it — which is exactly
why measurements are keyed by recipe rather than written onto the Library row.

*Rationale.* Storing aggregates creates a second thing to invalidate every time the onset
definition changes, and the onset definition will change. Writing measured features onto
Library rows was rejected outright: it would make a row's meaning depend on whichever
interrogation happened to run last.

### 4.5 A saved detection algorithm is a template

No second store. It is the PRD's `templates` row with `kind` derived from terminal type.
That inherits naming, export, cross-machine re-running and carry/rebind, and is what
populates Discovery's template picker (§7.5) — including saved seed searches.

### 4.6 Matching rule

Reciprocal overlap **IoU ≥ 0.5** with onset agreement scaled to the candidate's own
duration — not an absolute tolerance, since durations here run from seconds to hours. The
rule is recorded on the run, because the precision figure is a function of it and an
unstated matching rule makes the metric unfalsifiable. Reducing duplicate detections of
the same motif is the priority it serves.

The default is editable in one place only — Settings › Analysis defaults (§9.5) — and
changing it is a versioned act, because every precision figure already computed was
computed under the old rule.

### 4.7 A rediscovery writes a new row

When a run re-finds a span that has already been adjudicated, it writes a **new detection
row belonging to this run**, carrying a pointer to the prior adjudication. The run stays
reproducible from its own recipe, the score counts the detection, and the same span is
never put to the researcher twice. This is the same mechanism §4.2 uses to resolve a
re-run onto an existing member.

### 4.8 Scores belong to runs, not to templates

Precision, recall and surrogate counts are computed **per run**. They aggregate onto a
template only with scope attached — which channels, how many hours, how much reviewed
coverage. **Never a bare number on a template card.** A template card showing "precision
0.82" with no scope invites comparison between two figures computed over different
recordings, which is not a comparison at all.

---

## 5. Explore

Entry point for a dataset. Purpose: find things by eye, mark them, and hand spans to
Analyse or Discovery.

### 5.1 Corpus

Full-page **channels × time density map**, bird's-eye across every channel of the
selected recording. The right rail is a filter/options list, not a legend: Show
(annotations, detections, reviewed coverage, unreviewed only), Verdict (seed,
interesting, not_interesting, artifact, unsure, each with its colour dot), Morphology tag
(sharkfin, spike-train, slow-drift, burst, plateau, biphasic). It reads out how many spans
match and across how many channels, because the useful question about a tag is whether it
clusters or spreads.

Selecting a channel populates the bottom bar with its counts and **Open CH… →**.

Structured so a future multivariate dataset drops in as extra rows.

### 5.2 Signal mode

Three tiers on one time axis:

1. **Channel overview** with coverage and detection-density ribbons, and a span selection
   carrying **draggable edge handles** (blue grips with centre grooves).
2. **The span**, with motifs as coloured caps above the trace — blue detected, green
   annotated, orange open — and `‹ 233 / 344 ›` navigation.
3. **The selected motif**, with its own **Send motif to Analyse →**.

A span-action row saves a span with tags and a note and runs nothing; the caption says so
outright. `Save + send to Analyse →` is the other path.

Four collapsed ribbons along the bottom: Filters & search, Annotations, Detections,
Keyboard shortcuts.

### 5.3 Signal mode, drawer open

The drawer overlays the lower screen rather than compressing it, so the overview stays put.
Ten filter fields, match count, CSV/JSON export, the annotation table with colour-coded
verdicts and real `source` values, staging and bulk actions, and **Send selected to
Review →**. This is where the original draft's wall of controls lives without being on
screen all the time.

### 5.4 Cross-channel mode

Deliberately loose. Holds the slot and the future multivariate direction. Carries the
channel stack with lag, waveform-identity and bin readouts, plus an explicit open-questions
card. Do not over-build it.

### 5.5 Span edit

Reached from Review. Amber banner names the candidate and the run it came from. The span
is shown large with draggable handles, the **original extent drawn in grey behind the new
one in blue**, and an extent card with numeric start/end, nudge steppers, duration, and
`snap to` options (steepest sample, trough, zero crossing, free) — snapping to the same
rule that produced the original keeps the edit comparable with the rest of the family.

A revision card states what saving writes, per §4.2.

---

## 6. Analyse

Purpose: build and tune a chain, at a scope small enough to see every intermediate.

### 6.1 Modes are not modes

Detection, interrogation and training are **consequences of a chain's terminal type**, not
application states:

| Terminal type | What the chain is |
|---|---|
| `SpanSet` | a detector — saves as a detection template |
| features over a `SpanSet` | an interrogation |
| `Model` | a training chain |

The surface reconfigures around the terminal type. The three names survive only as filters
over saved templates. This makes it structurally impossible to treat a training chain as a
detector.

### 6.2 Chains start from a source block

The spine stays linear; chain validation is untouched. The root is always a source block,
of which there are two kinds: one loads a **signal span**, one emits a **SpanSet** from a
Library family, a prior run, or a Review selection.

**"Analyse events"** is the universal verb that sends a SpanSet into Analyse. It appears on
the detection block page, both Discovery pages, the Library, and anywhere a set of spans is
in hand.

Members keep identity across the hand-off (content-based: file, channel, sample range), so
measurements write back per member and re-running a recipe is idempotent.

Consequence: when the source is already a family, a training chain is *already grouped*, so
the clustering stage is **absent** — not a greyed "skipped" row (P15). The source block's
output type is what makes that visible instead of silently wrong.

### 6.3 The chain page

One row per block, each with its own stage-appropriate plot, a `cached` / `stale` / `new`
badge, a settings icon, and its type signature. `+ insert a stage` between every pair.
Toolbar: source chip, surrogate toggle (**on by default**), estimate, **Import template**,
**Save as template**, **Run chain**. Footer states the terminal type and what follows from
it, and offers `Export run`, `Analyse events →`, `Pass N to Review →`.

### 6.4 Inserting a stage

A modal over the chain. It **leads with the type contract**, drawn as three pills: what the
previous stage outputs, what the new stage must accept and emit, and what the next stage
requires. Inserting between two blocks has two constraints; inserting at the end has one,
and **changes the chain's terminal type** — and therefore what kind of template it saves as.

Blocks are cards with a thumbnail of what the block does, its type signature and a
one-line description. **Incompatible blocks stay visible and disabled, each carrying its
reason** — "needs Signal · this point carries Encoding", "emits SpanSet · stage 03 requires
Encoding". This is PRD story 8 made literal: the type system is easier to learn by being
refused with an explanation than by never seeing the option. A `show incompatible` toggle
hides them once the shape is known.

The detail panel gives defaults, estimated cost, whether the block has a
surrogate-compatible null, and which downstream stages the insertion makes stale. Two
commit actions: **Insert**, and **Insert and open settings →**.

### 6.5 Block pages, detection chain

    ● Source  ›  01 Baseline  ›  02 Encoding  ›  03 Noise floor  ›  04 Detection

**Encoding** is the reference block page. Output is the symbol strips and slope bars;
controls are generated from the adapter spec; and a **surrogate sweep is folded into the
settings** — the same parameter at eight values, each with its own null, so a setting is
chosen against chance rather than by counting detections. The derived readout is in plain
English: *"The 8σ cut puts 'd' at −0.0767 mV/s — falling faster than the noise can
explain."*

**Detection** shows detections in context plus each kept detection as a card, with
parameters beside them. Dedupe is called out as the parameter that most changes the count,
with a breakdown of what it removed. Hand-offs: Save template, **Analyse events →**,
**Pass N to Review →**.

The saved template is what populates Discovery's template picker (§4.5, §7.5).

### 6.6 Block pages, interrogation chain

    ● Library family  ›  01 Resolve spans (slope analysis)  ›  02 Aggregate

**Library family** picks which members are in scope, with per-member include/exclude.
Excluding scopes the analysis and is recorded on the run; it does not change the Library
entry.

**Resolve spans** measures the geometry: the anatomy of one event (onset, trough, steepest
sample, chord, depth), the rose that turns each fall into one angle, and event-by-event
navigation. Its three rules — onset, trough, steepest window — define every number on the
page.

**Aggregate** holds the distributions: drop depth, inter-event interval, max slope, and an
occurrence timeline coloured by position in the recording. Everything here is a view.

### 6.7 Block pages, training chain

    ● Source  ›  01 Sliding windows  ›  02 Window matrix  ›  03 Cluster  ›  04 Encode  ›  05 Model

**Window matrix** — channels-by-time feature heatmap, z-scored and clipped at ±3σ, with
feature groups (CNN scores, Random Forest, Entropy, Catch22) as **collapsible rows** — so
Catch22's 22 features are one line until opened. The signal sits underneath on the same
time axis, because a regime change visible in every feature group at once is what the
matrix is for. Compute panel offers **Create SLURM script** and **Upload a computed
matrix**, so a span already computed elsewhere skips the compute entirely.

**Cluster** — dendrogram with a **draggable cutline**, each class as its medoid plus two
members, and a windows-per-class bar chart flagging classes too small to train on. The
linkage/silhouette/cophenetic tension is stated on the page: the selection criterion must
be fixed before any cluster-derived label set is reported, or the choice of *k* becomes the
finding.

Also carries **Save as a custom grouping** with a scope control — `whole channel` or
`this section only`. See §8.2.

**Encode** — browse windows, see all four encodings of the selected one (GASF, GADF,
recurrence, fusion) with per-encoding include checkboxes. Existing encoders are kept rather
than substituted, to avoid a silent encoding mismatch with already-trained models.

**Model** — stages are **individually tickable**, with cached stages shown as skippable, so
a job can run `--from-stage 03 --to-stage 05` and three hours of compute does not happen
twice. The held-out lock is off for now (P19) — it lives in Settings › Datasets (§9.1).
Results return through the **manifest inbox** (Settings › Storage & backups, §9.11), and the trained
model then appears as a `Model` artifact any detection chain can reference. *Superseded in
part by P11/P14/P16: Analyse builds and trials the template; the real training run, its
results and the registry live in Models; detecting with a model is a Model stage inside a
detection template.*

### 6.8 The block contract — what every analysis block must supply

A new algorithm is added to the site by filling in this contract, not by designing a page.
The intent is that blocks are built from a small number of **generalised classes keyed on
the type signature** (e.g. `Signal → Scores`), each class owning its row thumbnail, its
block-page layout and its null presentation, so an adapter supplies only the algorithm and
its declared outputs. Worked examples live in the Analyse `.pen` files (column *Template
page* below).

#### Every block, whatever its types

| Surface | Required | Notes |
|---|---|---|
| Insert-stage modal | **Algorithm glyph** — a small static thumbnail representative of *the algorithm* (not of any data), plus name, type signature, one-line description, cost class, null badge | Registered with the adapter. Same glyph everywhere the algorithm is listed (insert modal, Discovery picker, template cards). Drawn in a 44 × 26 box, shown at 44 × 26 on cards and 272 × 96 in the detail panel. Colour key: grey input/context · blue what the block emits · green found/kept · amber cut/threshold · red discord/excluded · purple exemplar/second input. Registry of 21 examples: chain file frame 6b. |
| Chain row (filmstrip) | **Result thumbnail** drawn by the output type's renderer; status badge (`cached` / `stale` / `new` / `running` / `failed` / `on cluster`); one-line summary stat; open · bypass · duplicate · delete | Time-aligned outputs share the chain's time axis. The row shows the result only (P5). |
| Block page — toolbar | source chip, `‹ full chain`, run name, null chip, estimate, primary action | Shared shell. |
| Block page — ribbon | whole chain, this block highlighted, every block clickable, type signature under each | Shared shell. |
| Block page — process | the block's **intermediates**: what it looked at, what it computed, the output | "Show the process" (P5). Capped views per P8. |
| Block page — parameters | controls generated from the adapter's parameter spec; **recommended** marker (source: D4); info pop-over per parameter (P9); units | Changing a parameter marks this block and downstream stale. |
| Block page — null | either a **parameter-vs-null plot** (the parameter swept, output measured against its surrogate) or an explicit "no null for this block" declaration with the reason | Surrogate compatibility is declared by the adapter. |
| Block page — cost | time estimate, **disk size estimate** for bulk outputs, local-ceiling check → *Create SLURM script* / *Upload computed artifact* (P4) | |
| Block page — hand-offs | what the output type allows next (e.g. `SpanSet` → *Analyse events*, *Pass to Review*) and *Save template* | |
| States | empty, running (progress + cancel), failed (error in place), invalid junction (fix actions) | Built once on the chain page (frames 1c–1g); blocks inherit them. |

#### Additional requirements by type signature

| Signature | Chain-row thumbnail | Block page must add | Null presentation | Template page |
|---|---|---|---|---|
| `Signal → Signal` (transform: baseline, bandpass) | output curve, input ghosted behind | before/after overlay, removed component, residual or spectrum | the transform is applied identically to surrogates; show output statistic vs surrogate | chain 01 Baseline |
| `Signal → Signal` + estimate (noise floor, thresholds) | curve with the estimate band | estimate drawn on the signal, estimate stability across the span, which downstream parameter consumes it | estimate on surrogate for comparison | chain 03 Noise floor |
| `Signal → Encoding` (symbolic: SAX, dSAX) | symbol strip | signal + reduction (e.g. PAA), derived quantity with **draggable cutlines**, quantised strip; alphabet/segment sliders; noise-floor parameters | **parameter sweep vs null** (same parameter at N values, each with its own surrogate) | chain 02 Encoding |
| `Signal → Scores` (matrix profile, distance/novelty profiles) | series against time, top locations marked | the signal with the subsequence length drawn to scale, one worked **distance profile** for a selected subsequence, the profile with exclusion zone, top-k motif pairs / discords; length and exclusion parameters | score distribution vs **surrogate profile** distribution; parameter sweep where the length is a choice | chain 1h (row) + 7 Matrix profile (block page) |
| `Scores → SpanSet` (threshold) | interval overlay on the scores | score histogram with **draggable threshold** over the null distribution, count-vs-threshold curve with null, min duration / merge gap | expected false spans at the chosen threshold | to build (backlog B10) |
| `Encoding → SpanSet` (detection) | interval overlay on the signal | detections in context, each kept detection as a card, dedupe breakdown | surrogate detection count beside real count | chain 04 Detection |
| `SpanSet → SpanSet + Features` (feature block: slope, spike shape, FHN fit) | per-member thumbnails (≤10, sliding) | one event's anatomy with the rules that define each number, per-event table, sliding strip, sampled overlay; **declares each Feature (name, unit, kind)** so Aggregate can wire it | matched random windows (P10) | interrogation 4b |
| `Features → views` (Aggregate) | small distribution | generic: histograms, switchable scaling relationship with β ± CI, timeline, colour-by — all driven by the declared Features | null β / null distribution behind every plot | interrogation 4c, 4c-c |
| `Signal → WindowSet` (sliding windows) | window index ticks over the signal | length / stride / **gap ≥ window length**, blocked split plan and boundary close-up, per-split counts, human-verdict coverage, *Send unseen to Review* | — (declared: split integrity checks instead) | training 01 |
| `WindowSet → WindowSet` (+ feature matrix) | feature heatmap aligned to the signal | collapsible feature groups, aligned signal, **label-derived groups flagged and off by default**, compute + disk estimate | per-feature vs shuffled-window baseline (optional) | training 02 |
| `WindowSet → Grouping` (clustering) | class-per-window strip / cluster-size summary | dendrogram or embedding with the cut, selection criterion (B4), class cards (medoid + samples), time occupancy, bootstrap stability, contingency vs human verdicts | stability vs resampled data; ARI vs label shuffle | training 03, 2b |
| `WindowSet → Encoding` (image: GASF, GADF, RP, fusion) | a **2-D image per window** for 3–4 sample windows | the selected window's signal beside each encoding with colour scale, include checkboxes, parameters (size, encoder version), **disk size estimate** (images × px × channels), **samples per class** of the window set with per-split counts | — (declared) | training 04 |
| `Encoding + labels → Model` (template builder) | text card (PRD: a model has no natural plot) | stage ticks for the trial job, label source, training options, pre-training checks, trial script, *Train in Models* | label-shuffle null — shown in Models, not here | training 05 |
| `Model + WindowSet → Scores` (inference) | series against time | to design — listed for completeness | — | not built |

A signature not in this table needs a row here before its first block is built.

### 6.9 Saved window sets (P18)

Building a window set that is **safe to train on** — windows far enough apart, blocked by
recording and time, with enough human verdicts — is expensive, and several uses want the same
one (training arms in Models, clustering, image encoding, Review queues, a later model's
inference). So a window set is a **saveable, reusable artifact**, not a by-product of one chain.

- **Every block whose output type is `WindowSet` offers *Save window set*** on its chain row
  and block page (the block contract, §6.8, gains this for the `→ WindowSet` rows).
- A saved window set records: name and version; source recordings and channels; window
  length, stride and gap; the **split assignment** of every window (train / validation / test
  block) and the split rule; the **spacing check** result (min gap between windows, whether it
  is ≥ one window length, how many windows were dropped at block edges); human-verdict
  coverage per split and per class at save time; the producing chain's recipe hash. Window
  bounds live on disk; the database holds the row and the path (§4, rule 4).
- It is **retrievable anywhere a `WindowSet` source is accepted**: as a chain source in
  Analyse (the frame 0b case — it arrives with its split, so the split-leakage problem in
  backlog B7 is solved by construction when the set was saved from a sliding-windows block),
  as a training input in Models, and as a queue source in Review.
- It is browsable in the Library beside templates, filterable by recording, window length,
  split rule and whether it passes the spacing check. A set that fails the check is saveable
  but badged **not train-safe**.
- Verdict coverage is live, not frozen: reopening the set shows coverage now and at save time.
- Human-annotated windows (not from a sliding-windows block) can be saved as a set too; they
  have no split until the split filter of B7 is applied, and are badged so.

---

## 7. Discovery

Purpose: apply finished recipes, and seed searches, at a scope where intermediates are
unviewable. Different scope, different cost model, different output from Analyse. Discovery
runs **detection templates and seed searches**. A trained model reaches Discovery by being a
stage inside a detection template built in Analyse (P16); Discovery never lists a bare model.

### 7.1 One page, two ways to add a run (P17)

A Discovery session holds a list of **runs**. A run is either a template applied to the
scope, or a seed search over it — the two are peers everywhere below. The page is:

- **Toolbar** — session name, scope chip, null chip (circular shift 200× by default), a cost
  chip (time, and whether it routes to the cluster), History.
- **Scope** — one recording, one or more channels (removable chips, *+ channel*), one
  section brush drawn across every channel's overview strip at once. Strips are tall enough
  to keep the signal's shape (≈32 px each). **At most three strips show at a time**; with more
  channels, up/down arrows page through them three at a time (`4–6 of 6`), the section stays
  the same on all, and the chips of the visible page are highlighted. *Where each run fires*
  follows the same page (frame 1c). *Preview on a 4 h
  sample* runs the selected templates on a sample and extrapolates hit count and cost
  before anything is committed (whole-channel sections above the ceiling route to cluster).
- **Runs list** (left) — human annotations as a fixed reference row, then each run with its
  algorithm glyph (§6.8), colour, type badge (template / seed / draft), version, status or
  progress, and a compare box that turns into **A** / **B** when picked. *Apply template* and
  *Seed search* sit at the top.
- **Results** (right) — where each run fires, scoreboard, detection browser, run acts.

### 7.2 Where each run fires — multi-channel display

Small multiples **by channel**, rows **by run** within each channel, all on one time axis.
At section scale a span is thinner than a pixel, so rows show **detection density per 3 h
bin** (colour by run, opacity by count, with a scale); a *density · spans* toggle switches to
spans when zoomed in. The human row also shows **reviewed hours** as a grey underlay, so it
is visible where recall can be computed. A running run shows its unfinished part as empty.
The detection currently in the browser is marked on its channel.

### 7.3 Scoreboard

Columns: run, found, already judged, reviewed, interesting, precision, recall, null expects,
× null. A run row expands into **one row per channel**.

- **Precision is labelled precision**, never "accuracy" or "effective rate". Precision
  alone selects for timidity — an algorithm finding 5 events and getting all 5 right scores
  100% and beats one finding 200 and getting 60.
- **Recall is per channel, scoped to that channel's reviewed overlap** ("0.71 over 14 h").
  With no reviewed overlap it reads `no reviewed overlap`, not blank. The run total states
  the hours it pooled.
- An algorithm with nothing reviewed reads `not yet scored`; a running or queued run says so
  across the row.
- **Already judged** is its own column — how many of this run's detections had a verdict
  before the run started. Without it, a high precision on a re-run of familiar ground
  looks like a property of the algorithm.
- **Null expects / × null** replace the bare "surrogate" count: how many detections the null
  gives on the same scope, and the ratio.
- Scores are per run, and aggregate onto a template only with scope attached (§4.8).

Comparison is **n-way for counts, pairwise for inspection**.

### 7.4 Browse; Review judges

The detection browser picks run and channel, steps `‹ n / N ›`, and shows the detection on
its signal with depth, score, prior verdict and which other runs also found it. Browse only.

Three run-level acts, on the run named in the footer:

- **Send N unjudged to Review** — pushes the run's unjudged detections to the top of
  Review's queue, each tagged with the run id. Returning to Discovery refreshes the score.
- **Discard run** — marks the run superseded and writes **no adjudications**.
- **Analyse events →** — sends the SpanSet to Analyse.

The bulk-discard distinction matters: whole-run discard writing thousands of
`not_interesting` human verdicts would poison the RQ5 divergence measurement, and the
corruption would be invisible until it reached a finding.

Embedding Review's queue into Discovery was considered and rejected as overwhelming.

### 7.5 Adding template runs (frame 1b)

A picker lists saved templates filtered to those that fit the scope's type (default
`Signal → SpanSet`), each with its **stage glyph strip**, signature, and last score. Saved
seed searches are templates too (badge *seed*; *carry* or *rebind*). Templates already in the
session are disabled. A notice says models run inside detection templates and links to
Analyse to add a Model stage.

The detail pane shows the stages with their **locked** parameters (a template's parameters
come from the template; *Open in Analyse* to change them), per-channel scope and cost,
compute / disk / null stats, and the sample-preview result. Each template becomes **one run
across all channels in scope**.

**Cost decides the primary action.** When the estimate is within the local ceiling the footer
offers *Add runs* and *Add and run*. Above it, *Add and run* is **disabled** and the primary
action becomes **Create SLURM script** (cluster colour); results return through the manifest
inbox (§9.11) and fill the run rows in. The same rule applies to the toolbar's run button on
the runs page.

### 7.6 Seed search (frame 2)

A seed run is set up in place, as a *draft* row in the runs list.

- **Seed source** — *Library exemplar*, *Explore selection* (a span selected in Explore) or
  *Family medoid*. The card shows the seed's shape, provenance (recording, channel, samples,
  content hash) and *change seed*. On save as a template: **carry** (the exemplar travels with
  the template) or **rebind** (ask for an exemplar when applied).
- **Multiple seeds** — the page must support a search taking several seeds (e.g. every
  medoid of a family) once an algorithm does. MASS takes one; the *+ seed* control is shown
  disabled with its reason. No concept frame is needed for the multi-seed case yet.
- **Parameters** — algorithm (MASS, z-normalised Euclidean), window at the exemplar's
  **native length** (locked), scale bank (none), exclusion zone (m/2, the trivial-match
  guard), match threshold with a recommended marker, overlap policy. *Revert to recommended*.
- **Where to cut** — the match-distance histogram with the **null's distribution behind it**,
  kept bins in the run colour, the self-match bin shaded, the threshold as a draggable line
  labelled with kept count and what the null gives. You see how many matches chance alone
  would give at the moment you choose where to cut.
- **Distance profile** — one channel and a zoomed view at a time: clean signal, the distance
  profile with the threshold line, and a matches track beneath (new vs already judged). No
  marks are drawn on the signal itself.
- **Matches** — cards sorted by distance, paged, each overlaying the match on the seed with
  its distance, channel, time and judged status.
- **Apply bar** — unapplied changes, *Save as template*, *Run seed search*. A run seed search
  becomes a normal run row.

Rediscoveries follow §4.7 — a new detection row on this run, pointing at the prior
adjudication — so the same span is never put to the researcher twice.

### 7.7 Comparing two runs (frame 3)

Any two runs — template × template, seed × seed, or seed × template — with human annotations
allowed as either side.

Opens with **what differs**: both chains laid out in **columns by role** (Source ·
Preprocess · Encode · Score / estimate · Detect) with glyphs, identical stages grey, differing
stages amber, and an empty slot where one chain has no stage in that role. A badge counts
differing roles; where more than one differs, its info popover says a difference in output
cannot be attributed to any single stage.

Then **where A and B fire**, per channel: the signal is drawn **clean** — no ticks or marks
over it — with three tracks beneath on the same axis: A, B, and one **agreement** track (grey
both, blue only A, purple only B). Hover draws a crosshair through signal and tracks with a
readout; the only thing behind the signal is a faint band on the disagreement currently
selected in the stepper.

Then **set overlap**: proportional only-A / both / only-B bars for all channels and each
channel, beside A and B precision and × null.

Then **step through the disagreements**, filterable to all / only A / only B: one clean
signal for the window, A's span track, and B's own score at that place (for a seed run, its
distance profile against its threshold — "nearest d 3.6, threshold 3.1, near miss"), so the
non-firing side shows how close it came. *Compare every stage* opens 3b.

### 7.8 Compare every stage (frame 3b)

The same window pushed through both runs: two columns, rows aligned **by role**, each row the
block's chain-row thumbnail from the block contract (§6.8) so any chain renders. Rows are
badged identical / differs / absent; an absent role is an empty card saying what the other
run does instead. The stepper bar names the **first stage whose output differs** — not a
causal claim. Underneath, *what each stage decided here*: a role × A × B table of the numbers
behind each picture. *Open in Analyse* on either column opens that chain on this window.

---

## 7b. Models

Purpose: train the templates Analyse builds, judge them against baselines and nulls, compare
them, and register the ones worth using (P14). Four tabs: **Launch · Results · Compare · Registry** (`UI_models_v1.pen`, frames 1, 3–5). Training
jobs are followed on the global **Jobs** page (§7c, P24); frame 2 has been removed from the Models file (frames keep their numbers), and each tab row ends with an *open in Jobs* link filtered to training jobs. A registered model is used for detection by
inserting it as a Model stage in an Analyse chain (P16).

### 7b.1 Launch (frame 1)

1. **Training template** — picked from Analyse templates whose terminal type is `Model`,
   shown as its stage glyph strip. The classifier stage decides whether the model is binary or
   multi-class; the page states which and how many classes.
2. **Sources — decided by the template's source type.** A template that starts from `Signal`
   (and makes its own window set with sliding windows) takes **channels** as sources, one row
   per recording × channel with hours, windows produced, human verdicts and classes seen. A
   template that starts from `WindowSet` takes a **saved window set** (§6.9). The other option
   is shown disabled with the reason. When the template builds a window set mid-chain, *Save
   window set* is offered here with a name; the saved set includes its split.
3. **Label arms** — one or more label sources trained as a **paired** job: manual labels
   (Review verdicts), cluster labels (the template's cluster stage), and a random-forest
   baseline on the window-matrix features that is always on. *Train every arm on* defaults to
   the windows labelled in every arm, so arms differ only in their labels.
4. **Evaluation** — a test block and a validation block set aside **before training**,
   **blocked by time within each channel** with a gap ≥ one window, never a random sample of
   windows: adjacent or overlapping windows would put near-copies of test windows into
   training. The test block is scored once, after training; validation drives early stopping
   and calibration. The locked held-out recording (M4) is an option, off for now. A per-class
   × per-split count table flags classes with too few test windows — **multi-class models need
   more windows** (default warning below 50 test windows per class).
5. **Options** — repeat with different seeds (**off** by default; count when on), epochs,
   batch, early stopping, and the null: **label shuffle on the RF baseline (200×) plus a few on
   the full model (5×)**, since every full-model shuffle is a full retrain.

**Before launch** lists pass/warn checks (test block unseen, gap ≥ window, label-derived
features off, arms paired, class counts). **Where it runs:** local training is allowed when
the local estimate is **≤ 2 h**; above that *Train locally* is disabled and **Create SLURM
script** is the primary action, with the script shown, copyable and saveable.

### 7b.2 Jobs — moved to the Jobs page (§7c)

Frame 2 of the Models file is superseded (P24). Launching a training job adds it to Jobs;
Models links to its jobs with a filter. The rules below are unchanged and now live in §7c:
hand-marked HPC status, the 3× estimate reminder, the manifest inbox and its import checks.

### 7b.3 Results (frame 3)

One arm at a time (switch A / B / RF baseline):

- headline: macro F1 on the test block with a bootstrap CI over test blocks, balanced
  accuracy, RF baseline F1, label-shuffle null F1 with p, the full-model shuffles, test
  window count;
- **against baseline and null** on one axis: RF null histogram, full-model shuffle dots, RF
  line, the arm with its CI;
- confusion matrix (row-normalised, counts shown) and per-class precision / recall / F1 /
  test n, flagging classes with few test windows;
- **calibration per class** (validation block): reliability curve and a **suggested
  threshold** per class at a target precision, with precision, recall and ECE. The suggested
  threshold is what Analyse's `Scores → SpanSet` threshold stage shows as its recommended value
  when this model feeds it (§6.8, D4);
- training curves with the early-stop epoch;
- **held-out checks** (the registration gate, §7b.5) with their current state.

### 7b.4 Compare A / B (frame 4)

Any two models; the concept frame shows the major use case, **manual labels vs cluster
labels** from one paired job.

- Pickers for A and B, and **what differs** as pills: template, window set, split, classifier
  and options should be equal; the label source differs. With exactly one difference the
  comparison is marked attributable; with more, it says the difference cannot be attributed.
- **Both arms are scored against human verdicts on the same test windows.** Cluster classes
  are mapped to manual classes by majority on training windows, shown as a contingency
  heatmap with the mapping and purity; an impure cluster is flagged.
- Macro F1 for A, B and each arm's RF baseline, with CIs, over the label-shuffle null band.
- **Paired difference** A − B: bootstrap distribution with CI and zero line, McNemar p, and
  per-class ΔF1 with CIs (grey where the CI crosses zero).
- Per-window agreement 2 × 2 (both right / only A / only B / both wrong).
- Per channel: A and B macro F1 for each source channel.
- **Step through the disagreements** (only A right / only B right / both wrong): the
  window's signal and encodings, the human verdict, A's and B's predictions with scores, and
  *Open window in Review* to re-check the verdict.

### 7b.5 Registry (frame 5)

A list of models (candidate / registered / retired / rejected) with test F1 and **used by**.
Registering is a three-part gate, and **the researcher has the final say**:

1. **Held-out checks, automatic.** At minimum: beats the label-shuffle null (p < 0.01),
   beats the RF baseline (ΔF1 CI excludes 0), test windows unseen in training, calibration
   ECE ≤ 0.10 per class. A failure blocks registration; a warning requires a written reason.
2. **Human verification.** A stratified sample of test-block predictions is judged in Review;
   the page shows progress and agreement overall and per class, with *Add more*.
3. **Decision.** Registered name, version, classes, the reason for any accepted warning, an
   explicit confirmation, *Register* or *Reject*. The sign-off is recorded with the model.

A registered model appears in Analyse's insert modal as a Model stage (backlog B13) with its
calibration thresholds. **Retire is blocked while a template uses the model**; the page lists
those templates and the Discovery runs that used them. Retired models can be restored;
rejected models keep their failed checks.

---

## 7c. Jobs

`UI_jobs_v1.pen`, frames 1–4. Purpose: **every job across workspaces in one place** — runs
paused on the cluster, cluster jobs, local jobs and Review queues — sorted by what needs the
researcher first (P24). Reached from the nav rail (`Jobs · N`, N = jobs that need you) and the
header chip.

### 7c.1 All jobs (frame 1)

- Header counts: need you · running locally · on each cluster · review queues; *Manifest inbox*.
- Filters: all · needs you · paused · cluster · local · review queues · finished; workspace.
- **Needs you** cards on top: a run paused on cluster results, a result that has arrived and
  can continue, a cluster job past 3× its estimate, a manifest waiting to import.
- One table grouped as **Paused · waiting on cluster results**, **Cluster jobs · status marked
  by hand**, **Running locally** (progress, time left, Cancel), **Review queues** (left of
  total, progress, pace, blind badge, Open) and a collapsed **Finished and cancelled today**.
  Each row: id, workspace icon, job and what it belongs to, where (this machine or cluster ·
  profile), status, time, one action.
- Rail for the selected job; for a paused run: its stages with states, what it is waiting
  for and where the result is expected, *Open run detail*, *Look again*, *Upload results and
  continue*, *Run stage locally* (disabled over the workspace limit, §9.6), *Cancel run*.

### 7c.2 A paused run (frame 2)

When an Analyse or Discovery stage is over its local limit, the run **pauses at that stage**
and its SLURM script becomes a cluster job. The run page shows:

- **Where the run stopped**: every stage with its state — done, cached, *sent to the cluster*
  / *result arrived*, waits — and a timeline (started, paused with script created, marked
  submitted, marked running, result found).
- **The stage result**: the path the run expects (built from the naming convention, §9.11),
  when it was found, and the **checks before the run can continue** — in the expected place,
  produced by this run's script (recipe hash), one result per channel, length matches the
  signal, values finite, null draws included.
- **Continue from stage N+1** stores the file as the stage artifact, marks the cluster job
  finished, and runs the remaining stages under the usual limits. The run then appears in its
  workspace as if it had never paused.
- **Other ways forward**: upload results and continue; create the script again (replaces a
  failed or cancelled job); run the stage locally (disabled over the limit); cancel the run
  (cached stages are kept).

A result is recognised either **already in its root** (e.g. `./PROFILES`) or **in the
manifest inbox**; the run's workspace page shows the same paused state with a link here.

### 7c.3 Upload results and continue (frame 3)

For a result copied off the cluster by hand. Choose the file; the page shows **where it will
be placed** (locked, from the naming convention) and runs the same checks. **Nothing is placed
until every check passes.** A file made with different parameters (recipe hash or a parameter
such as `m` differs) is **refused** — continuing would give the run a recipe it did not follow
— with *Choose another file* or *Start a new run with those parameters*. A file without null
draws can pass; the null then runs as its own step under the workspace limit.

### 7c.4 A cluster job and the manifest inbox (frame 4)

- **Status is marked by hand** (the site cannot see the queue): script created (automatic) →
  submitted → running → finished, each step with when it was marked; *Mark finished*, *Mark
  failed*. *Finished* is also set when the job's manifest is imported.
- A job marked running past **3× its estimate** raises a reminder — *Mark finished*, *Mark
  failed*, *Still running · remind me later*; never changed automatically.
- Cluster job id (free text), profile, results return path (→ inbox), estimate, the script
  (*Copy*, *Save .sh*), and a link to the job's workspace (e.g. Models › Results).
- **Manifest inbox** (watched every 5 min, §9.6): each arrived manifest lists its contents and
  import checks (recipe hash matches the launch, every arm and null present, test windows
  identical across arms, no test window in training) before *Import results*. Stage results
  for paused runs are listed with *Open*.

---

## 8. Library

Purpose: the deliverable. A persistent, cross-recording catalogue of exemplar shapes with
everything matched to them — plus the other reusable artifacts the pipeline produces.
`UI_library_v2.pen`, frames 1–7.

### 8.1 Three sections

The toolbar switches **Motifs · Window sets · Templates** (P22), each with its count. Motifs
keeps the flow `recurrence → atlas → family`; grouping is chosen first, scope second. The
regroup comparison of the first draft is dropped.

### 8.2 Groupings — the Library runs its own (frame 4)

A grouping is computed **by the Library**, from what the researcher asks for, and saved with an
id (`g-07`). The grouping bar on every Motifs page shows the unit, the basis and its parameters,
the active filters, an **omitted · flagged** count, and *Edit grouping*.

**1 · What to group** — `single motifs` · `sequences` · `spike trains`. The unit decides which
entries take part at all.

**2 · Group by** — three kinds of basis:

| Kind | Bases | How groups form |
|---|---|---|
| distance | shape distance (z-normalised, scale-invariant, Ward cut); sequence similarity (events in order + gaps, sequences only) | a cut on a linkage tree |
| feature bins, no distance | amplitude, timescale (duration), frequency content (e.g. dominant frequency, Welch), polarity | bins on one feature — quantiles, log-spaced or fixed edges |
| labels | tag; **provenance** (recording · run · spike train); custom (a clustering exported from Analyse) | one group per label |

A basis that does not apply to the unit is shown disabled with its reason (sequence
similarity for single motifs).

**3 · Parameters** for the basis, with the feature's distribution and the bin edges or cut
drawn on it.

**4 · What does not fit** is **omitted from that grouping round and flagged**, never deleted:
motifs outside every bin, motifs whose nearest family is past the cut, groups under the
minimum size — and, when the unit is `sequences`, every single motif that belongs to no
sequence. Omitted entries stay listed (a strip under the matrix or atlas, *Show omitted*,
*Send omitted to Review as a queue*).

**Preview** before applying: groups, members, omitted, recompute cost, and what happens to hand
edits. *Save as grouping* keeps it without switching; *Apply* regroups the whole catalogue and
clears the scope (stated on the page). Earlier groupings stay saved.

Frames 2 and 2b show the same catalogue under two groupings: single motifs by shape distance
(10 families, 38 omitted) and sequences by sequence similarity (6 sequence families; 1,188
single motifs and 17 unfitting sequences omitted).

### 8.3 Hand edits survive regrouping

Adding a member, removing one, making an exemplar, tags and class are **hand edits**, stored
apart from the computed grouping and badged `hand` wherever they show. Re-computing a grouping
**re-applies** them: a hand edit whose family still exists applies; one that points at a family
the new grouping lacks is kept as a hand group (e.g. "F-03 additions"). The preview counts
both. A member removed by hand stays out of that family on every regroup until restored.

Custom groupings from Analyse **record their scope**; members outside it show as an explicit
unassigned count. Extending a section-scoped clustering beyond its scope is nearest-centroid
assignment — a `Model` — not a grouping.

### 8.4 Recurrence (frame 1)

Families × channels, grouped by recording, `‹ recordings 1–3 of 5 ›`.

- Cells show **members per hour of recording** (toggle to count); count on hover.
- Under each channel, a **reviewed-coverage bar**; a cell with no reviewed coverage and no
  members shows `?` rather than empty, so "absent" and "never looked" differ.
- **Red cells are cross-channel artifacts and stay visible**; the artifact filter is
  *flagged*, not *excluded*.
- Row: exemplar sparkline, id, name, and how many recordings the family spans (PRD 45).
- Checkboxes per channel and per recording build a selection outlined through the matrix. The
  rail totals it (recordings, channels, hours, members, reviewed %) and offers **Browse N
  channels →**. A shared-ground pair in the selection raises a warning with *Deselect*.
- Reading rule behind an info icon: dark in one recording only is a property of that recording.

### 8.5 Atlas (frames 2, 2b)

Scope chips and `‹ back to recurrence`; a card per family. Cards draw **exemplar and medoid**
together in **mV on a shared scale** (PRD 46–47), with recordings, hand-edit and artifact
badges, duration, depth and judged fraction. Sequence families add their **composition**
(`F-03 · F-09`).

Detail rail: exemplar vs medoid with their distance; members sampled to 10 with *resample*;
amplitude histogram with axes; duration, mean member distance, SNR, judged; cross-channel
counts; edge provenance (distance, cut, recipe). For sequences: composition with the gap
between events and order consistency. Actions:

- **Open all N members →**
- **Seed search in Discovery →** — the family's exemplar (or medoid) as the seed; disabled for
  sequence families until an algorithm takes several seeds (§7.6);
- **Interrogate in Analyse →** — the family as the source;
- **Send N unjudged to Review →** — a named queue `Library · F-03 unjudged` (P20);
- Export entry.

### 8.6 Family (frame 3)

- **Exemplar and medoid both shown** — the exemplar is the human anchor (a seed from Review, or
  *Make exemplar*); the medoid is computed — with their distance and the family stats.
- **Amber banner** while members are unjudged: *a family whose members are unjudged is a
  proposal, not a finding*, with *Send N to Review as a queue*.
- Members paged 10 at a time; sort by distance, time, amplitude, unjudged first; *hand edits
  only*. Cards on a shared mV scale with exemplar / medoid / `added by hand` badges, distance
  (purple past the cut) and verdict.
- **Removed by hand** strip with *Restore*.
- Batch bar: send to Review, add tag, assign class, remove from family, export.
- Member rail: shape over the medoid, ±30 s context, recording, onset, found by, the hand-edit
  record with *Undo*, revisions (§4.2), **verdict read-only with *Open in Review*** (P6), tags
  and class **editable**, note, *Make exemplar*, *Redraw in Explore*, *Remove from family*.

### 8.7 Empty library and import (frame 5)

Empty, the Motifs section names the two ways in: judge candidates in Review (S creates an
exemplar, P21) or import extracted motifs. The import is a **dry run first**: bundle and
provenance file; counts (motifs, spike trains, recordings, channels); checks (provenance
complete, sample ranges inside recordings, **a content hash per motif so a second run skips
what exists**, overlaps with existing annotations linked not duplicated, inferred sampling
rates flagged); what it will create (unjudged entries — imports are not verdicts — spike-train
entries, a first grouping); a sample; and *then send to Review as a queue*.

### 8.8 Window sets (frame 6)

Every saved window set (§6.9) in a table: name, source, window · stride · gap, windows, split
bar, labelled %, used by, and a check badge — `train-safe`, `test sample`, or the reason it is
not (`no split`, `gap < window`, `fs inferred`). Filter by train-safety, recording, labelled,
used. Detail rail: what made it and its recipe hash, the **split plan per channel** (train /
validation / test blocks and gaps), spacing checks, class counts with artifacts excluded, used
by, and *Use as source in Analyse*, *Train in Models*, *Send unlabelled to Review*, Export.
**Delete is blocked while anything uses the set.** Not-train-safe sets explain why and offer
*Re-split in Analyse*.

### 8.9 Templates (frame 7)

Every saved chain: name, version, signature, **stage glyph strip** (§6.8), badges (`seed ·
carry` / `rebind`, `model <name>` when it contains a Model stage, training, interrogation), the
latest score **with its scope** (§4.8) and run count. Filter by kind and *contains a Model
stage*. Detail rail: signature, recipe, null; stages with their locked parameters; versions
with what changed and *diff*; **scores by run** (scope, precision, recall, × null — recall `—`
where there is no reviewed overlap); *Apply in Discovery*, *Open in Analyse*, Duplicate,
Export JSON, Archive (runs keep their template version).

---

## 9. Settings

`UI_settings_v1.pen` — one page per section, frames 1–16. Purpose: everything whose value
changes what a *result means*, in one place, with the consequence of changing it stated
beside the control (P23).

**Shape.** A left rail of pages under two scopes:

- **Project · recorded with runs** — Data (Datasets, Channels & events, Vocabulary) ·
  Analysis (Nulls, Analysis defaults, Compute & HPC, Blocks) · Workspaces (Review queues,
  Models & registration, Library groupings) · Files (Storage & backups, Export) · Record
  (Audit log, About).
- **Personal · this browser** — Display, Keyboard & behaviour.

A rail item carries an amber dot when its page **differs from default**. Every page has a
title with its scope badge and *Reset page to defaults*.

**Project settings write on save.** A sticky save bar shows `N unsaved changes` and the
**consequence**, not a restatement of the edit (`noise floor 0.08 → 0.10 mV marks 4 runs on
M2_aug fs1 stale`). Project settings are snapshotted into every export and backup.
**Personal preferences apply immediately** to this browser and are never recorded with runs.

**Single researcher for now.** Entries that name who did something record "this
installation". User accounts are future scope (§11).

A **locked** control (lock icon, greyed) shows a rule the UI enforces rather than a preference.

### 9.1 Datasets (frame 1)

The recording registry: name, file, **sampling rate with its source (`read` from the file
header / `inferred`)**, channels, duration, **start time**, species, linked recording, status
(`in use` / `provisional` / `available`). *Import a recording…* (flow still open, §11).

Metadata editor, travelling with every export: display name, species, substrate, electrode
config, start time and time zone, sampling rate (locked when read from the file), **noise
floor** (lives on the recording because every detector reads it from one place), temperature,
humidity, linked recordings (**never split across train / validation / test**), notes. Timed
events do not go in notes — they go in Channels & events.

**Held-out recording.** The lock feature stays; it is **off** with M4_aug selectable. When on,
every workspace refuses the recording; turning it off needs the name typed and is written to
the audit log.

### 9.2 Channels & events (frame 2)

**Per channel**, per recording: name, electrode and position, gain, **shared-ground partner**
(drives the Library's double-count warning), status (`ok` / `bad from t`), excluded spans,
noise floor (recording's unless overridden).

**Event log**: a timeline of the recording with event markers and shaded exclusions, and a
table — time or span, kind (watering, mechanical, light, temperature, electrode, stimulus,
unknown; user-extensible), channels, **effect** (`show on plots` / `exclude span` / `exclude
and mark channel bad`), note. Excluded spans are skipped by every new run; runs that covered
them are marked stale, never silently changed.

### 9.3 Vocabulary (frame 3)

**Verdicts**: name, key, colour, role, count in `annotations`, count in `adjudications`. The
**core five** (seed, interesting, not_interesting, artifact, unsure) can be renamed or rekeyed
but **never removed** — Review keys, seed promotion and training exclusions depend on them. A
rename rewrites both stores atomically and shows the row count first; exports keep the old
name. Added verdicts must declare a role.

**Classes**: key (1–9), name, colour, **informative** flag, what it implies (locked to
`interesting` when informative), label count, models that use it. Renaming rewrites labels;
models keep their own class-map snapshot.

**Morphology tags**: name, **definition**, an example shape, families, members, aliases
(merges keep both names), rename · merge.

### 9.4 Nulls (frame 4)

One null per analysis kind, **always on**; method, draws and seed are editable and travel
into the recipe hash:

| Kind | Method | Draws |
|---|---|---|
| detection chains | circular shift | 200 |
| seed search | circular shift of the channel | 200 |
| interrogation · distributions | matched random windows | 200 |
| interrogation · intervals | shuffled onsets | 200 |
| training · baseline | label shuffle on the random forest | 200 |
| training · full model | label shuffle, full retrain | 5 |
| library groupings | bootstrap resample of members | 100 |

**Significance**: α (0.01), multiple-channel correction (none / Holm / Benjamini–Hochberg),
show × null beside counts. **Running**: reuse draws while the recipe is unchanged; null draws
count toward local limits (locked).

### 9.5 Analysis defaults (frame 5)

- **Matching rule** (§4.6): reciprocal overlap IoU 0.50, onset tolerance 0.25 × duration,
  seed-search exclusion m/2.
- **Recommended values** (resolves D4 as option c): **Settings holds the rule, the block
  evaluates it on its span** and shows the value with the green recommended marker. A table of
  block · parameter · rule · evaluated on · example value, with history per rule; rules that
  encode a guarantee (gap ≥ window, the recording's noise floor) are locked.
- **Artifact likelihood**: coherence flag, clipping, step change, and the low / medium / high
  bands.
- **Step cache**: write artifacts for stages slower than 2.0 s, keep stale artifacts 14 days,
  location and size, *Clear cache*.

### 9.6 Compute & HPC (frame 6)

- **This machine**: detected cores / GPU / memory, *Run benchmark* (calibrates estimates),
  local jobs at once.
- **Local limits per workspace** — Analyse stage 20 min · Discovery run 20 min · Models
  training 2 h · Library grouping 10 min · Review queue build 5 min — each with what happens
  above it (Analyse offers *Create SLURM script*; Discovery and Models disable local and make
  the script primary; Library and Review run in the background).
- **Clusters**: name, login host, scheduler, account. More than one is allowed — each keeps
  its own profiles and return path (to confirm with the researcher).
- **Job profiles** per cluster: partition, nodes, gres, cpus, memory, time, array limit, and
  which jobs use it (e.g. `gpu-single` for training, `cpu-array` for matrix profiles, a
  flagged `gpu-multinode`). Profile editor, guided or raw: environment setup, working
  directory, **results return path → manifest inbox**, email on finish, and a live script
  preview.
- **Job status** is marked by hand (locked — the site cannot see the queue); remind after
  3 × estimate; watch the manifest inbox every 5 min.

### 9.7 Blocks (frame 7)

The registry read from `Adapters/`: block, signature, version, adapter, declared null, used
by, enabled. A disabled block leaves the insert modal; runs and templates that used it stay
readable. Blocks not yet built (Model stage, B13) are listed.

### 9.8 Review queues (frame 8)

Defaults per queue source — blind, verdict keys (full / binary + classes), cap, order, write
target (P20). **Clusters**: cohesion limit 0.45, what a sequence is (same run and channel,
gap ≤ 6 min, at least 2 events — shared with Library), largest batch, undo reverses the whole
batch (locked). **Promotion**: S promotes (locked, P21), suggest the nearest family when
d ≤ 0.30.

### 9.9 Models & registration (frame 9)

Split (test 20 %, validation 10 %, blocked by time within each channel — locked, gap ≥ window
plus an optional extra, linked recordings never split — locked, class warning below 50 test
windows). Training (label arms with the RF baseline always on, train on windows labelled in
every arm, seed repeats off, early-stopping patience). Calibration (suggested threshold at
precision 0.80, reliability bins). **Registration gate** with each check's threshold and
consequence: null p < 0.01 blocks; beats RF (ΔF1 CI excludes 0) blocks; unseen test windows
blocks (locked); ECE ≤ 0.10 warns with a reason; verification sample 40 stratified;
agreement ≥ 80 % warns with a reason; sign-off required (locked). Retiring a model a template
uses is blocked.

### 9.10 Library groupings (frame 10)

Default grouping (unit, basis, cut). **What does not fit**: omit motifs with nearest family
d > 0.50, omit groups under 10 members, omitted entries are never deleted (locked).
**Sequences**: gap and minimum events, similarity weights (event shapes vs gaps). **Feature
bases**: amplitude, timescale, frequency content, polarity — feature, bin method, count,
range. **Hand edits**: re-applied on regroup (locked); orphaned edits kept as a hand group or
held.

### 9.11 Storage & backups (frame 11)

Roots with path, size and actions: database (schema version), recordings, step cache, window
matrices, matrix profiles, models, **window sets**, templates (in the database), library
exports, manifest inbox. *pull* copies finished results from the cluster return path. Naming
convention tokens with a live file-name preview (the hash is the recipe prefix). **Backups**
of the database, project settings and hand edits: schedule, destination, how many to keep,
*Back up now*, *Restore…*; bulk arrays are not copied. A free-space warning threshold.

### 9.12 Export (frame 12)

**Always included, not optional**: recipe hash, code version, schema version, recording
metadata, settings snapshot. Per artifact kind: motifs and families (formats, include
toggles incl. hand edits and the omitted list, workbook layout); window sets (npz or parquet
with a JSON manifest, split plan, labels, class map); templates (JSON, carry exemplars for
seed templates); models (weights format, model card with checks, calibration and sign-off —
locked); run reports (layout; parameters printed beneath each plot — locked; figures use the
report profile in Display). **Reproducibility bundle**: recipe, environment lock, code commit,
input file hashes.

### 9.13 Audit log (frame 13)

Append-only: when, kind (settings, sign-off, hand edit, HPC status, vocabulary, events, lock,
batch undo), what, where (linked), by. Filter by kind, *Export CSV*. Entries cannot be edited
or deleted.

### 9.14 About (frame 14)

Code version and whether it matches the last export, schema version, blocks, environment
(lock file), project and settings file, *Copy diagnostics*, and the **future scope** list:
user accounts, multi-seed search, cross-channel analysis.

### 9.15 Display — personal (frame 15)

Theme (system / light / dark), density; **units site-wide** (hours since start / clock time /
both; mV / µV; sample indices beside times); role colours (run A, run B, human, artifact,
blind, hand edit) and the family palette (colourblind-safe); view sizes (channels per page 3,
Review padding ±120 s, members per page 10, recurrence per hour / count); the **report figure
profile** (line width, grid, font, dpi, background) with a preview.

### 9.16 Keyboard & behaviour — personal (frame 16)

Key map with a conflict check: verdict and class keys shown but set in Vocabulary; skip
(Space), next / previous, undo / redo, confirm promotion (Enter), open in Explore, mark
viewport reviewed, toggle both rails, search. **Adjudication behaviour**: auto-advance after a
verdict; after a batch, auto-advance waits for the whole batch to write (locked); undo
reverses a whole batch (locked); pause after a seed promotion; confirm before discarding a
run or leaving unsaved settings.

---

## 10. Review

Purpose: adjudicate candidates. The only surface besides Explore that writes a human verdict
(P6). `UI_review_v1.pen`, frames 1–7.

### 10.1 Named queues (frame 3)

Review works **one named queue at a time** (P20). Each queue has one source, so each can
carry its own verdict options, blinding and write target:

| Queue | Comes from | Unit | Blind by default | Verdict writes |
|---|---|---|---|---|
| Discovery run | *Send N unjudged to Review* (§7.4) | detection | no | `adjudications` |
| Seed search run | the same, from a seed run | detection, grouped by match | no | `adjudications` |
| Explore spans | *Take span for Review* (P6) | human span | no | `annotations` |
| Training windows | *Send unseen windows to Review* (P13), cap 20,000 | window | yes | window verdicts (B15) |
| Model verification | the registration sample (§7b.5) | test-block window | yes | window verdicts (B15) |

The toolbar always shows the queue, whether it is blind, which store the verdict writes,
progress with pace, auto-advance and Shortcuts.

The **queue rail** is collapsed by default (sparklines of what is next, judged items dimmed
with a verdict dot, a purple bracket on cluster members). Open, it lists the queues with
counts and blind badges (*New queue*), the filters for the active queue — run, method,
channel, score range, status (unjudged / judged / all) and **group** (none / sequence /
family) — and an *Up next* list where clusters are collapsible groups.

### 10.2 The inspector (frames 1, 1b)

Both rails are **collapsed by default**; each has its open frame (3, 4).

- **Title row**: candidate id, unit badges, and pills that are always visible — status,
  score with × null, family affinity (`F-03 d 0.19`), **artifact likelihood**. A waveform can
  look dull and still sit near a known family; that signal must not hide inside a closed rail.
- **Context**: the signal drawn clean, with time and mV axes and the candidate as a shaded
  band. Padding ±30 / ±120 / ±300 s (default in Settings › Display, personal). *Other channels* and
  *Edit span in Explore →* (§4.3, returns here).
- **Shape**: the candidate z-normalised over the nearest family's medoid, with σ axis.
- **Nearest families**: medoid sparkline, id, name, member count, and distance on a 0 → 1 scale
  (a longer bar is farther). *Open in Library*. Low distance is not a verdict (info popover).

**Other channels (frame 1b)** is one click away, not on the page: every channel over the same
window with the span band and each channel's coherence in the span, then the **artifact
likelihood** and its factors — cross-channel coherence, clipping, step change, electrode flag —
and *Open all channels in Explore*. Artifact likelihood is **never blinded**: artifacts are
noted and kept out of training data (unless the model being trained classifies artifacts).

### 10.3 Verdicts, classes and annotation

The verdict row sits below the plots so the fast path survives both rails being shut: `‹ ›`
through prior verdicts, keycaps **S** seed · **I** interesting · **N** not interesting · **A**
artifact · **U** unsure · **Space** skip (no write), auto-advance, and **Ctrl Z** undo.

- **A binary verdict is the minimum** for a motif to count as annotated.
- **Class is optional.** Number keys are bound to the class list in Settings › Vocabulary.
  Giving a class **implies interesting**, unless the class is marked **non-informative** (an
  artifact class, for example), in which case it implies that class's verdict (§9.3).
- `artifact` verdicts are excluded from training window sets by default.
- Tags and a note stay optional.

### 10.4 Seed promotes to the Library (frame 6)

**S writes the verdict and creates the Library exemplar automatically** (P21) — there is no
separate promote act. A panel then offers the family: nearest family (default), new family, or
no family yet. The exemplar keeps span, recording, channel, content hash and the run's recipe
hash. Auto-advance pauses until **Enter** confirms; **Ctrl Z** removes both the exemplar and
the verdict.

### 10.5 Clusters (frames 2, 7)

A cluster is a set of candidates judged together, of one of two kinds:

- **sequence** — detections from one run that fall close together in time;
- **family set** — matches from a seed search, or members thought to be one family.

The **member strip** shows every member (paged at ~10, P8) with an include box, its shape, its
distance to the medoid and its prior verdict, sorted by distance. The cohesion pill shows mean
and worst distance. **A member whose distance exceeds the cohesion limit (default 0.45) is
flagged and excluded by default**; *Include all* overrides.

The batch is `[x] Verdict for the N included members`. **Undo is cluster-aware**: one Ctrl Z
reverses the whole batch — a mis-keyed press otherwise commits across every member and a naive
undo reverses one write. Frame 7 shows the result: a banner naming the batch, members back to
unadjudicated, auto-advance paused, *Redo*. Auto-advance waits for the whole batch to write.

### 10.6 Blind queues (frame 5)

Blind by default for **training windows** and **model verification**; visible for Discovery,
seed-search and Explore queues. The toggle is per queue and **the blind state is stored with
every verdict**, so an analysis can separate blind from sighted labels.

- **Hidden until the verdict**: score and × null, family affinity and nearest families, prior
  machine calls, the model's prediction; the evidence rail's machine sections.
- **Never hidden**: the signal, other channels, artifact likelihood.
- After each verdict the **previous window is revealed** — your call beside the model's.
  Running agreement is shown only in Models › Registry, so it cannot steer the next verdict.

### 10.7 Evidence rail (frame 4)

Open, the right rail holds what the title pills summarise:

- **Origin** — run and type, template and version, stage strip, recipe hash, when and by
  whom it ran, scope, *Open run in Discovery*;
- **Detection** — score, threshold (and recommended), rank, null expects on the scope, sample
  indices and sampling rate;
- **Also found by** — other runs, overlapping human annotations, prior adjudication (a
  rediscovery points at it, §4.7);
- **Family** — nearest by shape, not a verdict;
- **Artifact likelihood** — the factors;
- **History** — span revisions, verdicts, queues that contain it;
- the **write target** ("writes one adjudication row on d-88213").

Collapsed, it keeps labelled micro-stats (score, × null, family d, artifact, history).

---

## 11. Open

- **User accounts are future scope.** For now one researcher uses the site and every "who" (verdicts, hand edits, HPC status, sign-offs, audit log) records "this installation". Accounts would add named researchers, per-user blind state and a second sign-off for registration (§9, P23).
- Cross-channel / multivariate remains parked; Explore's cross-channel mode is a placeholder.
- FitzHugh-Nagumo is permitted as a feature-producing block in interrogation — a fit whose
  parameters are descriptors, identical in kind to measuring peakedness. The interpretive
  claim stays out of scope. Not designed.
- Recording import has a home (§9.1) but no designed flow (backlog B20). Cluster-job import is designed in Jobs (§7c.3, §7c.4).
- Text wrapping across the `.pen` mockups is unresolved: 14 caption paragraphs in
  `UI_analyse_chain_v1` (5), `UI_analyse_training_v1` (4), `UI_analyse_interrogation_v1` (3)
  and `UI_discovery_v1` (2) overrun their container. `.pen` text nodes have no width and do
  not wrap, so this is a mockup artifact, not a UI requirement. Copy is correct; line breaks
  are not.
- The explanatory sentence on Discovery's stage-by-stage compare ("B's bandpass removes the
  slow component this fall rides on") was replaced by the stage pictures and the divergence
  numbers. If it is ever reinstated, it must be derived from both runs' cached stage
  artifacts, not from a heuristic.

---

## 12. Decisions that depart from the PRD

Recorded during the page-by-page prototype review (from 14 September 2026). Each row names
the PRD passage it overrides so a builder can see the conflict rather than rediscover it.
Open questions and the working backlog live in `UI_REVIEW_BACKLOG.md`.

| # | Decision | PRD passage it departs from | Why |
|---|---|---|---|
| P1 | The chain page is **vertical rows**, each row carrying that block's result plot; the horizontal ribbon is kept only for moving between block pages. | Part 2 "Chain shape, revised" / stories 1–3: horizontal block canvas with a separate filmstrip beneath. | The rows *are* the filmstrip — one surface instead of two — and the layout fits the page. The spine is still linear; `ChainState` is still untouched. |
| P2 | Run history is a **pop-up behind a History button** beside Import on the chain page, not a sidebar. It lists past runs with *Apply to source*, disabled with the reason when the run's source type does not fit the current source. | Part 2 stories 29–32: collapsible run-history sidebar, collapsed by default. | Keeps the full width for the chain; history is a lookup, not a working surface. |
| P3 | **Analyse is single-channel.** A span or one whole channel, never a channel list or band list. Fan-out and multi-channel application of templates live in Discovery. | Part 1 stories 16–17 and the Analyse scope selector ("recordings, channels, span, bands"). | Analyse is where a recipe is built and every intermediate is viewable; Discovery is where it is applied at scale (§2). |
| P4 | A stage whose estimate exceeds the local ceiling is **not run locally by default** — the row offers *Create SLURM script* / *Upload computed artifact*, downstream stages wait, and the result re-enters through the manifest inbox. Applies to one whole channel inside Analyse (e.g. a full-channel matrix profile). | Part 1 "Cluster routing" describes routing at run-panel level for the whole chain. | Routing per stage means cached cheap stages are never re-sent and only the heavy stage goes to the cluster. |
| P5 | **Block pages show process, chain rows show result.** A block page shows its internals (for SAX: signal + PAA, slope + cutlines, quantised and dSAX strips); its row on the chain page shows only the output. | Part 2 story 14 places SAX internals in "focus mode". | Focus mode *is* the block page; the chain row stays a thumbnail of the result. |
| P6 | **Verdicts are given in Review only.** Explore offers *Take span for Review* and *Review this motif* rather than verdict buttons. | Part 1 stories 4–5 and "Explore … gains seed as a fifth verdict". | One adjudication surface keeps the human store's write path single. Explore still saves tags and notes. |
| P7 | **One block per analysis type.** Slope geometry, spike shape and a FitzHugh–Nagumo fit are separate blocks with separate pages. The Aggregate block is generic and wired to whatever Features its upstream block emits. | §6.6 described interrogation as one fixed chain. | Generalisable pages; a new feature block needs no new aggregate page. |
| P8 | **Show-all views cap at ~10.** Strips slide with navigation; overlays draw a seeded random sample with *resample*. | — (new) | Families run to hundreds of members. |
| P9 | **Explanatory text sits behind info icons and pop-overs**, not on the page. Plain-language captions stay to one line. | §3 "plain-language captions are load-bearing". | Walls of text were crowding the surfaces; the content is kept, relocated. |
| P10 | Interrogation carries a **null by default** (matched random windows, 200×; shuffled onsets for interval statistics), and every fitted scaling exponent shows its CI beside the null exponent. | Part 1 surrogate protocol applies to runs, not to interrogation views. | "Every result carries a null" should hold for distributions and fits too. |
| P11 | **Analyse builds the training template; Models trains the model.** The training chain is built and trialled on one channel in Analyse (optional trial HPC job). *Train in Models* runs it across channels and recordings, runs the paired cluster-label vs manual-label comparison on one shared split and test set, and holds the results. *(Revised 14 Sep: was "Discovery trains"; see P14.)* | Part 1 story 16 / RQ1 row: training chain and evaluation in Analyse. | A useful classifier needs many channels (P3), and a fair comparison needs both arms on the same split — both are scale jobs. |
| P12 | **Leakage guards are parameters, not assumptions.** Sliding windows carry an editable *gap between blocks* (must be ≥ window length) and a blocked-by-time split; random splits are marked as leaking. Label-derived feature groups (CNN scores) are **off by default** in the window matrix. | Part 1 does not address split leakage or label-derived features. | Overlapping windows and features trained on manual verdicts would both inflate or contaminate the RQ1 comparison. |
| P13 | **Unreviewed windows go to Review from the training chain** (*Send N unseen windows to Review*, queue cap 20,000, binary verdicts sufficient). A future source type — windows humans have already labelled — is sketched but not built. | — (new) | The manual-label arm needs verdicts on the same windows the cluster arm uses. |
| P14 | **Models is a sixth workspace** — Explore · Analyse · Discovery · Models · Review · Library. It launches training jobs from Analyse templates, holds results and nulls (including the paired label-source comparison), and keeps the model registry. *(Revised 14 Sep, P16: a model reaches Discovery only as a stage inside a detection template.)* | §2 "five workspaces" and the decisions doc's five-not-six rationale; P11's first draft put training in Discovery. | Discovery's output is candidates judged in Review, scored by precision/recall; training outputs a `Model` scored against held-out labels and a label-shuffle null, with a register/version lifecycle. Folding it in would blur what Discovery means. |
| P15 | **A stage the source makes redundant is absent, not skipped.** The source's output type decides where the chain starts: a `WindowSet` source feeds straight into the window matrix, with no greyed "sliding windows — skipped" row. The blocked split and its gap stay **inside the sliding-windows block**; how a split applies to a supplied window set is an open implementation question (backlog B7). | §6.2 said clustering is "skipped rather than optional" when the source is a family. | A skipped row implies a stage that could be switched back on; the type contract says it cannot. |
| P16 | **Models reach Discovery only inside detection templates.** Discovery lists templates and seed searches, never a bare model. To detect with a model, build a detection chain in Analyse with a Model stage (`Model + WindowSet → Scores`, then `Scores → SpanSet`), save it as a template, and apply it in Discovery like any other. *(Revised 14 Sep: first draft said models are applied only in Models.)* | P14's first draft: "a registered model reappears in Discovery as a detection algorithm". | One path, not two: the threshold that turns model scores into spans is a chain stage with its own null, and the run compares against seeds and templates for free. |
| P18 | **A window set is a saved, reusable artifact** (§6.9). Any block outputting `WindowSet` offers *Save window set*; the set carries its split, spacing check and verdict coverage, and is accepted as a source in Analyse, Models and Review. | Part 1 treats windows as an intermediate of one chain. | A train-safe window set is expensive to build and shared by several uses; saving it with its split also removes the leakage problem of supplied window sets (B7) when it came from sliding windows. |
| P19 | **Model evaluation uses a blocked test portion of the window set, set aside before training** — not a random sample of windows — and registration needs automatic held-out checks plus human verification and sign-off. Local training only when the estimate is ≤ 2 h; HPC job status is marked by hand. | Part 1 names the held-out recording as the test set and does not specify registration. | Random hold-out of overlapping windows leaks near-copies into training. *(Revised 14 Sep, D6: the held-out lock stays **on** and M4 is refused in every workspace, Models Launch included; unlocking needs the recording name typed and is logged.)* The site cannot observe the cluster queue. |
| P20 | **Review works in named queues, one source each, with per-queue blinding** (§10.1, §10.6). Machine opinion — score, family affinity, model prediction — is hidden until the verdict by default in training-window and model-verification queues, and the blind state is stored with every verdict. Artifact likelihood is never hidden. | Part 1 "Review — the candidate queue" (one filterable queue, analytical score shown with each candidate). | Where the human verdict is the measurement (manual-label arm, registration verification, RQ5 divergence), showing the machine's call first anchors it. |
| P21 | **The seed verdict promotes to the Library automatically**; a class is optional and implies `interesting` unless the class is non-informative; a binary verdict is the minimum for "annotated". | Part 1 story 32 and "only explicit promotion creates a library entry". | Pressing S *is* the explicit act; a second promote step duplicated it. Classes feed multi-class models without making every verdict slower. |
| P22 | **The Library computes its own groupings and holds three sections — Motifs, Window sets, Templates.** Groupings are chosen by unit (single motifs / sequences / spike trains) and basis (distance, feature bins such as amplitude, timescale or frequency content, or labels incl. provenance); entries that do not fit are omitted from that round and flagged; hand edits survive regrouping. The regroup comparison frame is dropped. | Part 1 "Library — thumbnail grid with a group-by selector"; §8 first draft (six fixed bases, Custom from Analyse only, optional Regroup). | Grouping is a question the researcher asks of the catalogue, not a setting; window sets and templates are reusable artifacts that need one place to be browsed, checked and retired. |
| P23 | **Settings are pages in two scopes — project (recorded with runs, written on save with the consequence stated) and personal (this browser, applied immediately).** Nulls get one page with a method per analysis kind, always on; local compute limits are per workspace (Analyse 20 min, Discovery 20 min, Models 2 h); several clusters with job profiles; per-channel metadata and a timed event log that can exclude spans; recommended values are rules held in Settings and evaluated by each block (D4 option c); an append-only audit log. User accounts are future scope. | §9 first draft: one long scroll of five screens; a single surrogate setting (19 phase randomisations); one cluster-routing ceiling (600 s); one SLURM template; notes as the only place for lab events. | The settings grew to sixteen sections as each workspace was designed; the single-ceiling and single-null settings contradicted P4, P10 and P19. |
| P24 | **Jobs is one global page for every job across workspaces**, including Review queues, and replaces the Models Jobs tab. A stage over its local limit **pauses the run** at that stage; the run continues from the next stage once its result is found in place or uploaded and passes checks (recipe hash, per-channel shape, length, finite values). A result made with other parameters is refused. | Part 1 "Cluster routing" (export a cluster job, re-import through the manifest); §7b first draft (Jobs as a Models tab). | Cluster work comes from Analyse, Discovery and Models alike; a run that stops halfway must be resumable in the right place without re-running cached stages or accepting a result that breaks its recipe. |
| P17 | **A seed search is a run.** Discovery has one page with two ways to add a run — *Apply template* and *Seed search* — and a shared results area (runs list, where-each-run-fires, scoreboard, browser, run acts). Any two runs compare pairwise, including a seed run against a template run. Scope is one recording × one or more channels. | §7 treated algorithms, compare and seeded search as separate pages, single-channel. | Comparing a seed to a hand-built template is one of the more informative comparisons; separate pages made it impossible. |

## 13. Provenance

| Source | Status |
|---|---|
| `analyse-discovery-decisions.md` | **merged into this document**; superseded |
| `rq2-seeding-decision.md` | still authoritative for §7.6 |
| `PIPELINE_PRD.md`, `claude/pipeline-gui-prd.md` | authoritative for the data model except where §4.2 marks a supersession |
| `claude/review-workspace-design-directions.md` | earlier Review exploration; §10 is the settled version |

Design settled 13–14 September 2026 across three grilling rounds plus follow-up passes on
block structure, span revisions, the Library, and Settings.
