# Analyse and Discovery — settled decisions

Settled across three grilling rounds, 13 September 2026, plus a follow-up pass on block
structure. Concept pages: `prototyping/UI_analyse_discovery_v3.pen`.

Generators: `build_blocks.py` (the ten Analyse pages), `build_v3.py` (assembles the document
and holds the two Discovery pages), on top of `pen_kit.py` (primitives) and `pen_widgets.py`
(charts and controls).

---

## Standing context

This work sits **after** the 28 August feature freeze and carries no deadline. The goal is a
usable tool rather than thesis scope, so `pipeline-gui-prd.md`'s cut list and its "four
workspaces, nine tabs is a filing cabinet" constraint are advisory here rather than binding.
Anything below that exceeds the frozen build is specified future work.

---

## The three Analyse "modes" are not modes

Detection, interrogation and training are not application states the user switches between.
They are consequences of a chain's **terminal type**: a chain ending in `SpanSet` is a
detector, one ending in features over a `SpanSet` is an interrogation, one ending in `Model`
is a training chain. The surface reconfigures around the terminal type. The three names
survive only as filters over saved templates.

This removes a mode switch the user would otherwise have to make before knowing what they are
building, and makes it structurally impossible to treat a training chain as a detector.

## There are exactly two kinds of Analyse screen

**The chain page.** Where a chain is built: one row per block, each row carrying its own
stage-appropriate plot, a `cached` / `stale` / `new` status badge, and a settings icon.
Insert points sit between rows. A chain can also be **imported from an existing template**
rather than built from nothing.

**A block page.** Opened by clicking a block's settings icon. Every block page has the same
shape:

    toolbar    source chip  ·  "‹ back to the full chain"  ·  primary action
    ribbon     the whole chain, this block highlighted, any block clickable
    body       this block's settings and this block's output

Nothing else is a page. Results are not a separate screen from settings — a block's output is
part of that block's page, because the output is how you judge whether the settings are right.

**Inserting a stage is a modal over the chain**, opened from the `+ insert a stage` control
between two rows. It leads with the **type contract**, drawn as three pills: what the previous
stage outputs, what the new stage must accept and emit, and what the next stage requires.
Inserting between two blocks has two constraints; inserting at the end has one, and changes the
chain's terminal type — and therefore what kind of template it saves as.

Blocks are shown as cards with a thumbnail of what the block does, its type signature, and a
one-line description. **Incompatible blocks stay visible and disabled, each carrying its
reason** — "needs Signal · this point carries Encoding", "emits SpanSet · stage 03 requires
Encoding". This is PRD story 8 made literal: the type system is easier to learn by being
refused with an explanation than by never seeing the option. A `show incompatible` toggle can
hide them once the shape is known.

The detail panel for the selected block shows its defaults, estimated cost, whether it has a
surrogate-compatible null, and which downstream stages the insertion makes stale. Two commit
actions: **Insert**, and **Insert and open settings →**.

## Chains start from a source block

The spine stays linear and chain validation is untouched. The root is always a source block,
of which there are two kinds: one loads a signal span, one emits a `SpanSet` from a Library
family, a prior run, or a Review selection.

**"Analyse events"** is the universal verb that sends a `SpanSet` into Analyse. It appears on
the detection block page, on both Discovery pages, in the Library, and anywhere else a set of
spans is in hand.

Span identity is content-based — source file, channel, sample range — so members keep their
identity across the hand-off, measurements written downstream land back on the right member,
and re-running the same recipe is idempotent rather than accumulating orphans.

A consequence worth stating: when the source is already a family, a training chain is
*already grouped*, so the clustering stage is skipped rather than optional. The source block
is what makes that visible instead of silently wrong.

## A saved detection algorithm is a template

No second store. It is the PRD's existing `templates` row, with `kind` derived from terminal
type. That inherits naming, export, cross-machine re-running and carry/rebind for free, and is
what populates Discovery's algorithm picker.

---

## The three chains, and their blocks

### Detection

    ● Source  ›  01 Baseline  ›  02 Encoding  ›  03 Noise floor  ›  04 Detection

`02 Encoding` is the reference block page: symbol strips and slope bars as the output,
generated controls, and a **surrogate sweep folded into the settings** — the same parameter at
eight values with each value's own null, so a setting is chosen against chance rather than by
counting detections.

`04 Detection` shows the detections in context plus each kept detection as a card, with
parameters beside them. Its dedupe parameter is called out as the one that most changes the
count. Hand-offs: **Save template**, **Analyse events →**, **Pass to Review →**.

### Interrogation

    ● Library family  ›  01 Resolve spans (slope analysis)  ›  02 Aggregate

`● Library family` picks which members are in scope, with per-member include/exclude.
Excluding a member scopes the analysis and is recorded on the run; it does not change the
Library entry.

`01 Resolve spans` is where the geometry is measured: the anatomy of one event (onset, trough,
steepest sample, chord, depth) and the rose that turns each fall into one angle, with
event-by-event navigation. Its three rules — onset, trough, steepest window — define every
number on the page, which is exactly why measurements are stored against the recipe hash.

`02 Aggregate` holds the distributions: drop depth, inter-event interval, max slope, and an
occurrence timeline coloured by position in the recording. Everything here is a view.

### Training

    ● Source  ›  01 Sliding windows  ›  02 Window matrix  ›  03 Cluster  ›  04 Encode  ›  05 Model

`02 Window matrix` is a channels-by-time feature heatmap, z-scored and clipped at ±3σ, with
feature groups (CNN scores, Random Forest, Entropy, Catch22) as **collapsible rows** so
Catch22's 22 features are one line until opened. The signal sits underneath on the same time
axis, because a regime change visible in every feature group at once is the thing the matrix
exists to show. The compute panel offers **Create SLURM script** and **Upload a computed
matrix**, so a span already computed elsewhere skips the compute entirely.

`03 Cluster` is the dendrogram with a **draggable cutline**, each class represented by its
medoid plus two members, and a windows-per-class bar chart that flags classes too small to
train on. The linkage/silhouette/cophenetic tension is stated on the page: the selection
criterion must be fixed before any cluster-derived label set is reported, or the choice of k
becomes the finding.

`04 Encode` lets you **browse windows** and see all four encodings of the selected one —
GASF, GADF, recurrence, fusion — with per-encoding include checkboxes. Existing encoders are
kept rather than substituted, to avoid a silent encoding mismatch with already-trained models.

`05 Model` builds the job. Stages are **individually tickable**, with cached stages shown as
skippable — so if the window matrix already exists, the generated script runs
`--from-stage 03 --to-stage 05` and three hours of compute does not happen twice. The held-out
recording stays locked.

---

## Interrogation stores per-event rows only

One row per `(span, recipe_hash)` in a derived features table, separate from the Library's own
rows. Roses, histograms and interval statistics are views recomputed on demand and are never
stored — storing aggregates creates a second thing to invalidate every time the onset
definition changes, and the onset definition will change.

Writing measured features onto Library rows was rejected: it would make a row's meaning depend
on whichever interrogation last ran.

## FitzHugh-Nagumo

Permitted as a feature-producing block — a fit whose parameters are descriptors, identical in
kind to measuring peakedness. The interpretive claim stays out of scope. Not built.

---

## Discovery earns its own workspace

Analyse is where a recipe is **built**, at a scope small enough to see every intermediate,
costing seconds. Discovery is where finished recipes are **applied**, at a scope where
intermediates are unviewable, costing minutes to hours and routing to the cluster.

**Explore's Agreement mode folds into Discovery** as the n=2 case where one "algorithm" is the
human annotation store. This keeps the total at five workspaces rather than six, and avoids
two screens computing the same overlap.

Comparison is **n-way for counts, pairwise for inspection**: an n-row coverage ribbon over the
section answers "where do they disagree"; the drill-down picks two and reuses the existing
Compare view.

The pairwise compare leads with **what differs between the two recipes**, not with the output.
Both chains are drawn as ribbons with the differing stages highlighted, because comparing
detections without comparing recipes produces a result nobody can attribute. Where two stages
differ at once — a bandpass *and* a different noise floor — the page says so, since the
difference in output then cannot be attributed to either change alone. Below that: aligned
fire tracks with only-A / both / only-B derived from them, a proportional set-overlap bar, and
a stepper through the disagreements showing the same window drawn twice, once per algorithm.

Whole-channel sections **preview on a sample first**, showing the hit rate and an extrapolated
estimate, before explicit cluster routing above the ceiling.

## Discovery browses; Review judges

Discovery does **not** adjudicate. It browses candidates and offers three run-level acts:

- **Send all to Review** — pushes the run to the top of Review's queue, each candidate tagged
  with the run id.
- **Discard run** — marks the run superseded and writes **no adjudications**.
- **Analyse events** — sends the `SpanSet` to Analyse for interrogation.

Returning to Discovery after reviewing refreshes the score. Embedding Review's queue into
Discovery was considered and rejected as overwhelming; the tagged-queue hand-off gets the same
human-in-the-loop verification without a second adjudication surface.

The bulk-discard distinction matters: whole-run discard writing thousands of `not_interesting`
human verdicts would poison the RQ5 divergence measurement, and the corruption would be
invisible until it reached a finding.

## Scoring a discovery run

**Precision is labelled precision**, never "accuracy" or "effective rate". Precision alone
selects for timidity — an algorithm finding 5 events and getting all 5 right scores 100% and
beats one finding 200 and getting 60.

**Recall appears only where the section intersects human-reviewed coverage**, scoped explicitly
to that intersection ("recall 0.71 over the 14 h of this section that has been reviewed").
Where there is no reviewed overlap, recall shows as unavailable rather than being omitted — an
absent denominator is information. The surrogate count sits beside both. The scoreboard also
reports how many detections were **already judged** before this run.

**Matching rule**: reciprocal overlap IoU ≥ 0.5 with onset agreement scaled to the candidate's
own duration — not an absolute tolerance, since durations here span seconds to hours. The rule
is recorded on the run, because the precision figure is a function of it and an unstated
matching rule makes the metric unfalsifiable. Reducing duplicate detections of the same motif
is the priority the rule serves. A rediscovery writes a **new** detection row belonging to this
run, carrying a pointer to the prior adjudication so the same span is never put to the
researcher twice.

Scores are computed **per run** and aggregated onto a template only with scope attached —
channels, hours, reviewed coverage. Never a bare number on a template card.

## Seeded discovery

Per `rq2-seeding-decision.md`: MASS distance profile at the exemplar's native length, no scale
bank, with an explicit ~m/2 exclusion zone. The acceptance threshold surfaces as a **match
distance histogram with the surrogate's distribution drawn behind it** and the threshold as a
draggable line, with the trivial-match zone shaded and labelled. You see how many matches
chance alone would give at the moment you choose where to cut.

---

## Open

- Cross-channel / multivariate remains parked.
- FitzHugh-Nagumo block design not started.
- The Library workspace is not yet designed. Review concept B ("contact sheet") reads closer to
  the Library than to Review and is the starting point when it is.
