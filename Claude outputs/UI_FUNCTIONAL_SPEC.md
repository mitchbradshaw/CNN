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
| `UI_discovery_v1.pen` | Discovery | algorithms, compare, compare by stage, seeded search |
| `UI_review_v1.pen` | Review | the inspector |
| `UI_library_v2.pen` | Library | recurrence, atlas, family, regroup |
| `UI_settings_v1.pen` | Settings | vocabulary, datasets, analysis, storage, display |

Generators live in `prototyping/generators/`: `pen_kit.py` (primitives),
`pen_widgets.py` (charts and controls), `build_blocks.py` (Analyse pages + shared
chrome), then one builder per document — `build_explore_flow.py`,
`build_analyse_files.py`, `build_discovery.py`, `build_review.py`, `build_library.py`,
`build_settings.py`. Editing a page means editing its function and re-running its
builder; builders write their `.pen` to the parent folder. `verify_pen.py` is the check
harness: recursive geometry-overflow, duplicate ids, node-type whitelist, and a
text-width estimate.

The `.pen` files are **mockups, not assets**. Use them for layout, information
hierarchy and copy. Do not extract the placeholder traces — every waveform in them is
synthetic.

---

## 2. Workspaces

Five, in this nav order: **Explore · Analyse · Discovery · Review · Library**, with
**Settings** as a gear at the foot of the nav rail, separated from the five.

Settings is not a sixth workspace — it configures the other five and is never part of a
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
populates Discovery's algorithm picker.

### 4.6 Matching rule

Reciprocal overlap **IoU ≥ 0.5** with onset agreement scaled to the candidate's own
duration — not an absolute tolerance, since durations here run from seconds to hours. The
rule is recorded on the run, because the precision figure is a function of it and an
unstated matching rule makes the metric unfalsifiable. Reducing duplicate detections of
the same motif is the priority it serves.

The default is editable in one place only — Settings › Analysis defaults (§9.3) — and
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
the clustering stage is **skipped rather than optional**. The source block is what makes
that visible instead of silently wrong.

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

The saved template is what populates Discovery's algorithm picker (§4.5).

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
twice. Held-out recording stays locked — the lock itself lives in Settings › Datasets (§9.2).
Results return through the **manifest inbox** (Settings › Storage, §9.5), and the trained
model then appears as a `Model` artifact any detection chain or Discovery algorithm can
reference.

---

## 7. Discovery

Purpose: apply finished recipes at a scope where intermediates are unviewable. Different
scope, different cost model, different output from Analyse.

### 7.1 Algorithms at scale

Section slider across the channel with draggable handles. An **n-row coverage ribbon**
shows where each algorithm fires, with the human annotation store as just another row.
Browse-only detection viewer with `‹ n / N ›`.

**The scoreboard** is the centrepiece: algorithm, found, already judged, reviewed,
interesting, precision, recall, surrogate.

- **Precision is labelled precision**, never "accuracy" or "effective rate". Precision
  alone selects for timidity — an algorithm finding 5 events and getting all 5 right scores
  100% and beats one finding 200 and getting 60.
- **Recall appears only where the section intersects human-reviewed coverage**, scoped
  explicitly to that intersection ("recall 0.71 over the 14 h of this section that has been
  reviewed"). With no reviewed overlap it reads `no reviewed overlap`, not blank.
- An algorithm with nothing reviewed reads `not yet scored`.
- **Already judged** is its own column — how many of this run's detections had a verdict
  before the run started. Without it, a high precision on a re-run of familiar ground
  looks like a property of the algorithm.
- Scores are per run, and aggregate onto a template only with scope attached (§4.8).

Comparison is **n-way for counts, pairwise for inspection**.

Whole-channel sections **preview on a sample first**, showing hit rate and an extrapolated
estimate, before explicit cluster routing above the ceiling.

### 7.2 Discovery browses; Review judges

Three run-level acts:

- **Send all to Review** — pushes the run to the top of Review's queue, each candidate
  tagged with the run id. Returning to Discovery refreshes the score.
- **Discard run** — marks the run superseded and writes **no adjudications**.
- **Analyse events →** — sends the SpanSet to Analyse.

The bulk-discard distinction matters: whole-run discard writing thousands of
`not_interesting` human verdicts would poison the RQ5 divergence measurement, and the
corruption would be invisible until it reached a finding.

Embedding Review's queue into Discovery was considered and rejected as overwhelming.

### 7.3 Comparing two algorithms

Opens with **what differs between the two recipes**, not with the output — both chains as
ribbons with differing stages in amber. Where two stages differ at once, the page says so,
because a difference in output then cannot be attributed to either change alone.

Then the **section signal with each algorithm's fires ticked along its edges**, and the
five tracks beneath on the same axis: A, B, both, only A, only B. A fire only means
something next to the signal it fired on.

Then the proportional set-overlap bar and a stepper through the disagreements.

The stepper ends in `⌄ compare every stage for this window`, which opens the stage-by-stage
view: two columns, five aligned rows, the same window pushed through both chains, with the
row where the pictures stop matching amber-bordered. Underneath, a divergence readout with
the numbers that make it non-interpretive — min slope, σ, cut, segments qualifying.

### 7.4 Seeded search

MASS distance profile at the exemplar's **native length**, no scale bank, with an explicit
~m/2 exclusion zone. The acceptance threshold surfaces as a **match-distance histogram with
the surrogate's distribution drawn behind it** and the threshold as a draggable line, the
trivial-match zone shaded and labelled. You see how many matches chance alone would give at
the moment you choose where to cut.

Rediscoveries follow §4.7 — a new detection row on this run, pointing at the prior
adjudication — so the same span is never put to the researcher twice.

---

## 8. Library

Purpose: the deliverable. A persistent, cross-recording catalogue of exemplar shapes with
everything matched to them.

### 8.1 Flow

`recurrence → atlas → family`. Grouping is chosen first; scope second.

### 8.2 Grouping bases

Six: **Shape · Scale · Amplitude · Polarity · Tag · Custom**.

Plus event-type and filter controls that apply to all of them: `single motifs` /
`sequences`; `adjudicated only`; `≥ N members`; `exclude artifact-binned`.

**Custom** is a clustering exported from Analyse's cluster block. It arrives as just another
basis, on equal footing with shape or tag, and shows its source: `cluster_k6 · run 131 ·
Ward 10.1`.

A custom grouping **records its scope**. A whole-channel clustering assigns every window in
that channel; a section clustering only assigns windows inside it. The Library shows members
outside the scope as an explicit **unassigned** count rather than silently dropping them.

Extending a section-scoped clustering beyond its scope is a **different act** —
nearest-centroid assignment — and produces a `Model`, which already has a type. Do not let a
scoped grouping pretend to cover more than it does.

### 8.3 Recurrence — the entry point

Families × channels, grouped by recording, with `‹ datasets 1–3 of 5 ›` arrows to page
through more datasets than fit.

Rows are whatever the active grouping produces; counts recompute with it. Cell darkness is
member count. **Red cells are cross-channel artifacts and stay visible** rather than being
filtered out, because a family that is mostly artifact should look alarming rather than
small.

**Checkboxes per channel and per dataset** build a selection; selected columns outline
through the whole matrix. The rail totals the selection and offers **Browse N channels →**.
Checkboxes scope what you browse next; they never change the grouping.

The rail warns when two selected channels are a known shared-ground pair for a family in
view, because browsing both double-counts it.

Reading rule stated on the page: a row dark in one recording and empty in the others is a
property of that recording, not of the organism.

### 8.4 Atlas — browse the selection

Contact sheet of family cards grouped under headings from the active basis, with a scope bar
of removable channel chips and `‹ back to recurrence`.

**Changing the grouping regroups the whole catalogue and clears the scope.** The page says
this out loud rather than doing it silently.

Detail rail: medoid (a real member, not an average), all members z-normalised on a shared
relative-time axis, amplitude distribution, variance / SNR / mean member distance /
adjudicated fraction, cross-channel bins, and edge provenance — distance function, threshold,
recipe hash. Actions: **Open all N members →**, **Stage N for Review**, Analyse events,
**Search at other durations** (scale invariance, PRD story 38), Export entry.

### 8.5 Family — every member

Member cards with checkbox, distance to medoid, channel and time, and verdict dot or
`unadjudicated`. Sort by distance, time, amplitude, or unadjudicated first.

**An unadjudicated family says so at the top**, in an amber banner: *"68 of 112 members have
never been adjudicated — a family whose members are unjudged is a proposal, not a finding"*,
with **Stage all 68 for Review →**.

Member detail rail: enlarged shape, in-context strip, provenance, **revisions** (§4.2),
verdict, tags, class, notes. Actions: **Stage for Review →**, **Open in Explore to redraw**,
**Remove from family**.

Batch bar: stage selected, add tag, assign class, remove from family.

### 8.6 Regroup — optional

The same entries under two bases at once, with flow lines between them and the families that
move called out. PRD story 35 asks to *compare* what each basis produces, which is a
comparison rather than a setting. Reachable from the grouping control; delete it if the
Library should be strictly three steps.

---

## 9. Settings

`UI_settings_v1.pen` — five screens spanning one long scroll. Purpose: everything whose
value changes what a *result means*, in one place, with the consequence of changing it
stated beside the control.

**Shape.** Left rail of section links under four group headings — DATA · ANALYSIS ·
FILES · INTERFACE — each section a collapsible header in the main column. Adjacent
sections are shown collapsed (`› Vocabulary · 5 verdicts · 6 tags`) so the scroll's
structure is visible without scrolling it.

**Nothing here writes until save.** Every screen carries a sticky save bar: an amber dot,
`N unsaved changes`, a one-line statement of the *consequence* — not a restatement of the
edit — then Discard and Save changes. `renaming a verdict rewrites 3,424 rows`.
`IoU threshold changed — existing precision figures will recompute`.

### 9.1 Vocabulary

The verdict table: name, key, role, **count in `annotations`, count in `adjudications`**.
Two count columns, not one, because §4.1 keeps the stores physically separate and a
vocabulary edit lands in both.

One vocabulary spans both stores — there is no translation table, so none can drift.

Three rules the UI must enforce:

- **Renaming is atomic across both stores.** The inline editor shows the row count it
  will rewrite before you commit. A half-applied rename splits one verdict into two.
- **Removing a verdict that is in use asks where its rows go** — reassign to another
  verdict, or fall back to unreviewed. It never silently drops them.
- Existing exports keep the old name. Stated on the page, because the alternative
  — rewriting exports — is not on offer.

Morphology tags are a second table (families, members, first used). Tags are
**many-to-many on library entries and never a primary key**, so renaming or merging one
does not touch family identity. **Merging keeps both names as aliases** so old exports
still resolve.

Verdict keybinds are set here, not in Interaction. Interaction says so and links back.

### 9.2 Datasets

The recording registry: name, file, fs, channels, duration, recorded, species, status.
Import a recording.

**Linked recordings.** M2 fs1 and fs2 are one recording at two sample rates. They carry a
link, and **the runner refuses to split a linked pair across training and test.** Stated
on the row and again in the metadata editor.

**Metadata travels with every export**: display name, species, substrate, electrode
config, temperature, humidity, notes, and **noise floor**. Noise floor lives on the
recording rather than in a chain, because it gates the minimum detectable drop and every
detector reads it from the same place — a per-chain noise floor would make two chains
disagree about what is detectable in the same signal.

Notes are free text and are where the lab-book gaps get recorded: *"chamber door opened
around 148 h — the step in CH4 at that point is almost certainly mechanical."*

**The held-out recording lock.** M4_aug reads `HELD OUT · locked`. The viewer and the
runner both refuse it. Unlocking requires typing the recording name and is recorded with
a timestamp on the run log. The lock is what makes the methods claim true by
construction rather than by memory.

### 9.3 Analysis defaults

These travel into every recipe hash.

- **Surrogate control — locked on.** Realisations, method, seed are editable; *whether
  surrogates run* is not. Default-on is what makes "every result has a null" true in
  practice rather than merely likely.
- **Matching rule** (§4.6): reciprocal overlap IoU 0.50, onset tolerance 0.25 × duration,
  seed-search exclusion m/2. Editable here and nowhere else.
- **Step cache**: write artifacts above 2.0 s, location, size in use, clear.
- **Cluster routing**: promote cluster export above 600 s, local concurrency. Above the
  ceiling, `export cluster job` becomes the primary action and local execution is demoted
  rather than removed.

### 9.4 Compute & HPC

SLURM job generation, with a **guided / raw template** toggle. Guided keeps the template
valid; raw exists for cluster-specific quirks the fields do not cover. Fields: account,
partition, gres, cpus, memory, time limit, array task limit, email on finish.

Beneath them, a **live preview of the generated script**, so the fields and the artifact
are never out of step.

### 9.5 Storage & repository

Six roots, each with its own action: recordings (`scan`), artifacts (`scan`), window
matrices / matrix profiles / models (`scan · pull`), and a **manifest inbox**
(`./cluster_out`, `import`) — which is how cluster results re-enter the tool, and the
destination §6.7's Model block hands off to.

**Naming convention** is built from removable tokens — `<recording> <channel> <fs>
<window> <stride> <hash8>` — with a live preview:
`M2_aug_fs1_CH4_1Hz_600s_300s_a7f39c.npz`. The hash is the recipe prefix, so a file name
says which settings produced it.

### 9.6 Export & reporting

**Motifs and families**: xlsx catalogue, CSV, JSON manifest, atlas plot PDF, atlas plot
SVG. Include-toggles for medoid, all members, edges, scope, tags, notes, recipe hash.
One workbook with a sheet per family, or one file per family.

**Run reports**: a table of runs with an `export` action per row, and a layout choice —
one document with stages in sequence, or one file per stage. Each stage exports its plot
**with the parameters that produced it printed beneath**, at figure resolution.

**Recipe hash and code version are always included and not optional.** An export that
cannot be traced to a repository state is not evidence.

### 9.7 Display

**Two independent profiles — `across site` and `for report`** — with a live preview
trace. The screen can be dense and dark while figures stay light and sparse. Panel
background, palette (colourblind-safe), trace line width, grid opacity, time axis,
amplitude axis, figure font, export DPI.

**Units apply site-wide, not only to plots.** Every readout on every page follows the
time and amplitude units set here. Stated on the page because "plot settings" implies
otherwise.

### 9.8 Interaction

Keyboard map: next / previous candidate, undo last verdict, open in Explore, mark
viewport reviewed, toggle both rails. Verdict keys are not here — they are in Vocabulary.

Three adjudication safety toggles, and the defaults are the design:

| Toggle | Default | Why |
|---|---|---|
| auto-advance after a verdict | on | the fast path |
| auto-advance after a **batch** verdict | **off** | a mis-keyed batch otherwise commits across every member and moves on |
| cluster-aware undo | **locked on** | one keystroke reverses a whole batch, not the last write |

These implement §10.1. They are exposed rather than hard-coded so the behaviour is
discoverable, but the one that protects the data is not switchable.

---

## 10. Review

Purpose: adjudicate candidates. The only surface besides Explore that writes a human verdict.

Both side rails collapse and are **collapsed by default**, giving the motif the canvas. The
queue rail keeps cluster sparklines; the evidence rail keeps four micro-stats.

**Three signals sit beside the title, always visible**: adjudication status, family affinity
(`F-03 d 0.19`), member cohesion (`mean d 0.24`). These are promoted out of the collapsible
evidence rail deliberately — a waveform can look dull and still sit at low distance to a known
family, and if that signal hides inside a collapsed panel, the case it exists for is the case
you miss.

The verdict row sits **below** the plot rather than inside the evidence column, so the fast
path survives the rails being shut. It carries `‹ ›` navigation showing the prior verdict, five
keycaps (S seed, I interesting, N not interesting, A artifact, U unsure), a
`[ ] Verdict for all N members` checkbox for clusters, and undo.

The annotation row beneath is the deep-work path: morphology tags, class, notes.

The context card carries **Edit span in Explore →**, which returns here when done.

### 10.1 Cluster batch verdicts

Undo must be **cluster-aware** — one keystroke reverses the whole batch — or the batch action
must not auto-advance. A mis-keyed press otherwise commits across every member and advances,
and a naive undo reverses one write.

---

## 11. Open

- Cross-channel / multivariate remains parked; Explore's cross-channel mode is a placeholder.
- FitzHugh-Nagumo is permitted as a feature-producing block in interrogation — a fit whose
  parameters are descriptors, identical in kind to measuring peakedness. The interpretive
  claim stays out of scope. Not designed.
- Recording import and cluster-job import have a home (§9.2, §9.5) but no designed flow.
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

## 12. Provenance

| Source | Status |
|---|---|
| `analyse-discovery-decisions.md` | **merged into this document**; superseded |
| `rq2-seeding-decision.md` | still authoritative for §7.4 |
| `PIPELINE_PRD.md`, `claude/pipeline-gui-prd.md` | authoritative for the data model except where §4.2 marks a supersession |
| `claude/review-workspace-design-directions.md` | earlier Review exploration; §10 is the settled version |

Design settled 13–14 September 2026 across three grilling rounds plus follow-up passes on
block structure, span revisions, the Library, and Settings.
