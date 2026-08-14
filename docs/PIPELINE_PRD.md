# Pipeline GUI — Product Spec

**Project:** Underground Brains — mycelium bio-electric signal analysis
**Status:** Design settled via goals grilling and design grilling. Ready for ticket breakdown.
**Feature freeze:** 28 August 2026. Thesis submission approximately five weeks after freeze.
**Relationship to prior documents:** the goals spec (`pipelineguispec.md`) remains the authority on *what the software is for*. This spec is the authority on *how it is built*. Where the two disagree, the disagreements are marked **[CORRECTION]** and this document wins — each one was made after reading the existing codebase.

---

## Problem Statement

Open-ended exploratory time-series analysis on this project has no structure.

Every technique found in the literature — Gramian encoding into CNN training, matrix profiling into motif discovery, wavelet decomposition into segmentation — arrives as an isolated script. There is no way to navigate between analysis structures, to combine them, or to feed the output of one into the input of another. Past analyses are not saved in any form that can be revisited, compared, or reapplied to a new recording. A promising result is discovered and then lost, because the parameters and the ordering that produced it were never captured as an object that could be re-run.

The consequence for the research is concrete and expensive: findings cannot be reliably compared across methods or across recordings, and every new dataset restarts the work from zero. The thesis needs to claim that recurring patterns in fungal electrical recordings can be automatically detected and characterised. Right now the evidence for that claim lives in scattered scripts, plots that cannot be regenerated, and judgements held in the researcher's head rather than in data.

There is a second, sharper problem underneath the first. The existing manual labels are the only ground truth available, and they are single-rater and subjective. If machine-derived labels ever get written into the same store as human ones, the question "do cluster-derived labels beat manual labels?" becomes permanently unanswerable. That is a one-way door, and nothing currently prevents walking through it.

## Solution

One application that loads a univariate recording, lets the researcher compose typed analysis blocks into chains, run them over a whole channel or a selected span, adjudicate the results by hand, and save the chain as a reusable template.

Results that survive adjudication accumulate into a **motif library**: a persistent, cross-recording catalogue of exemplar shapes with everything matched to them, queryable by shape, by cluster membership, or by human tag, where every match carries the distance function, threshold and recipe that produced it.

The library is the deliverable. Templates are how it gets populated. Exports are how it gets communicated.

Three properties make it trustworthy rather than merely convenient:

- **Detections are candidates, never results.** Nothing enters the library without human adjudication, and human and analytical judgement are stored in physically separate tables so neither can contaminate the other.
- **Every result carries a null.** Surrogate testing runs by default on every analysis, so "we found motifs" upgrades to "we found more motifs than chance" without anyone remembering to do it.
- **Every chain is reproducible.** A recipe hash identifies the exact parameters and ordering that produced any run, any cached artifact, any saved plot, and any library edge.

This is an extension of the existing Panel/HoloViews annotation application, not a new program. The signal viewer, the span selection, the controlled tag vocabulary, the recipe/hash provenance layer and the twenty working algorithm adapters are the assets being preserved. The layout above them is redesigned around the research loop: explore, analyse, adjudicate, catalogue.

## User Stories

**Viewing and annotating**

1. As a researcher, I want to load a univariate recording and view it at any zoom level, so that I can navigate long multi-hour signals without downsampling artifacts hiding structure.
2. As a researcher, I want to see previously recorded regions of interest overlaid on the signal, so that prior work is visible in context rather than in a separate file.
3. As a researcher, I want to select a span of signal and run an analysis on just that span, so that I can experiment cheaply before committing to a full-recording run.
4. As a researcher, I want to mark a region I find interesting by eye even when no algorithm flagged it, so that analytical blind spots are documented rather than invisible.
5. As a researcher, I want to mark a region as a seed exemplar directly from the viewer, so that a shape I recognise by eye can anchor a library entry without an algorithm having proposed it first.

**Composing analyses**

6. As a researcher, I want to compose analysis blocks into a chain where the output of one becomes the input of the next, so that multi-stage workflows are first-class objects rather than sequences of scripts.
7. As a researcher, I want the application to prevent me from connecting incompatible blocks, so that invalid chains fail at composition time rather than after a long run.
8. As a researcher, I want to be told *why* two blocks cannot connect, so that the type system teaches me its shape as I use it instead of just refusing.
9. As a researcher, I want a block to be able to take an extra input besides the previous step's output — the original signal, an earlier step's result, or a library exemplar — so that seeded search and comparison against the raw trace are expressible as chains.
10. As a researcher, I want to open a single block and see its parameters, its inputs, and its results, so that I can tune one stage without rerunning the whole chain.
11. As a researcher, I want parameter defaults that adapt to the span I am about to analyse, so that a fixed default is not silently wrong for most spans.
12. As a researcher, I want a live readout of what a parameter will actually produce before I run anything, so that a control whose effect I cannot picture becomes legible.
13. As a researcher, I want to save a chain — ordering and parameters — as a named template, so that I can apply the same analysis to a different recording.
14. As a researcher, I want to run a saved template against a recording it has never seen, so that I can test whether a workflow generalises.
15. As a researcher, I want to choose, when saving a template, whether an exemplar travels with it or is re-picked on each use, so that "reapply this exact search" and "reapply this method" are different saved things.

**Running**

16. As a researcher, I want to run a chain across a selection of channels in one action, so that a sixteen-channel sweep is not sixteen manual launches.
17. As a researcher, I want to run a chain across a list of frequency bands in one action, so that band decomposition is the same mechanism as channel fan-out rather than a special case.
18. As a researcher, I want to see an estimate of how long a run will take before I start it, so that I can decide between running locally and sending it to the cluster.
19. As a researcher, I want the application to route expensive runs to a cluster job by default, so that I do not accidentally freeze my laptop for six hours.
20. As a researcher, I want a progress indicator with a rough time estimate on longer local runs, so that I can tell a slow run from a hung one.
21. As a researcher, I want each stage's result to appear as it completes, so that I can inspect an early stage without waiting for the whole chain.
22. As a researcher, I want to cancel a running chain, so that a mistaken launch does not have to run to completion.
23. As a researcher, I want a cluster job's results to import back into my local database in one action, so that work done remotely is not stranded there.
24. As a researcher, I want retuning one stage of a chain to reuse the expensive stages before it, so that parameter exploration is not gated on recomputing a matrix profile every time.

**Adjudicating**

25. As a researcher, I want algorithmic detections presented to me as candidates rather than as results, so that nothing enters the library without human adjudication.
26. As a researcher, I want to score a candidate as a seed exemplar, as a real instance, as uninteresting, as an artifact, or as unsure, so that my judgement is recorded as data rather than as a mental note.
27. As a researcher, I want to score candidates with single keystrokes and advance automatically, so that adjudicating hundreds of candidates is a session rather than a project.
28. As a researcher, I want to undo my last verdict, so that a mis-keyed judgement is not permanent.
29. As a researcher, I want human scores and analytical scores stored separately, so that neither can contaminate the other.
30. As a researcher, I want to query the set of candidates where human and analytical judgement disagree, so that divergence becomes a measurable finding.
31. As a researcher, I want to filter the candidate queue by run, method, score range and channel, so that I can adjudicate one method's output at a time rather than an undifferentiated pile.
32. As a researcher, I want to promote an adjudicated candidate into the library as an exemplar, so that scoring and cataloguing are one continuous motion.

**The library**

33. As a researcher, I want to browse a library of motif exemplars as thumbnails, so that I can see the shape vocabulary at a glance.
34. As a researcher, I want to click an exemplar and see every span matched to it, so that a motif family is inspectable as a set.
35. As a researcher, I want to group the library by shape, by cluster membership, or by manual tag, so that I can compare what each grouping basis produces over the same underlying entries.
36. As a researcher, I want to see which recordings and which channels a motif family appears in, so that recurrence has a scope.
37. As a researcher, I want stored similarity edges to record the distance function, threshold, and recipe that produced them, so that a family is a reproducible object rather than a screenshot.
38. As a researcher, I want to search for instances of a motif at durations it was not defined at, so that scale-invariance is testable rather than assumed.

**Controls and confounds**

39. As a researcher, I want to generate surrogate versions of a signal and run an identical chain over them, so that every result has a null.
40. As a researcher, I want the surrogate control to run by default rather than on request, so that a missing null is impossible rather than merely unlikely.
41. As a researcher, I want surrogate generation to be reproducible from its recipe, so that a reported null can be regenerated exactly.
42. As a researcher, I want cross-channel matches classified by inter-channel lag and waveform identity, so that a shared-ground artifact is not counted as a finding.
43. As a researcher, I want two runs compared by set overlap, so that "does the banded chain find things the direct chain misses" is a question the tool answers.

**Getting results out**

44. As a researcher, I want to export a completed chain's structure, parameters, and results as structured data plus saved plots, so that results can go into the thesis without re-running anything.
45. As a researcher, I want to export a library entry with its members, edges and scope, so that a motif family can be reported as a table rather than a description.
46. As a researcher, I want exports to record the code version that produced them, so that a result traces to a state of the repository.
47. As another researcher, I want to run an exported template on my own recording, so that the work is reproducible outside the original machine.

**Protecting the evaluation**

48. As a researcher, I want the held-out recording to be refused by the viewer and the runner until I explicitly unlock it, so that "untouched until the freeze" is enforced by the code rather than by my memory.

**Extending it**

49. As a researcher, I want to add a new analysis technique by writing a single class conforming to a declared interface, so that future methods do not require touching the application.

## Implementation Decisions

### Boundary and reuse

The pipeline extends the existing application. The following are reused as they stand, not rebuilt: the adapter registry and its parameter-spec system; the headless recipe executor with its hash-based idempotence, cancellation and per-step progress; the canonical-JSON recipe hashing; the SQLite schema and query layer; the SLURM job generator; the rasterized signal viewer and every plot builder in the UI plotting module; matrix profiling on STUMPY; the motif-group precompute; the window matrix; the Gramian/recurrence encoders; the SAX ports; the CNN and Catch22 classifiers; ruptures, kymatio and aeon integrations; and the 195 existing tests.

A hard rule already present in the codebase is preserved and load-bearing: **no module below the UI layer imports a UI library.** This is what makes cluster execution, headless testing and the reproducibility story possible.

Three libraries named in the goals spec are deliberately **not** adopted. **pyts** is rejected because the existing hand-rolled Gramian and recurrence encoders produce exactly the images every trained model expects, and substituting them risks a silent encoding mismatch. **MNE-Python** is rejected as a dependency but adopted as a *vocabulary* — its onset/duration/description annotation semantics and its epoch semantics inform the schema naming and give the thesis a defensible reason for the data model. **dtaianomaly** remains an architectural reference only.

**[CORRECTION]** The goals spec proposed rewriting block parameters as Param `Parameterized` classes. This is reversed. The existing parameter-spec system already generates the parameter UI *and* carries span-aware default recommendation and live derived readouts, neither of which Param provides. The adapter spec is extended instead of replaced.

### Type system

Seven interchange types gate which blocks may connect: `Signal` (series plus sample rate), `SpanSet` (regions of interest, optionally labelled and scored), `WindowSet` (fixed-length segments, optionally carrying an attached per-window feature matrix), `Encoding` (image or symbolic representation per window), `Grouping` (cluster or class assignment over a window set), `Model` (a trained classifier), and `Scores` (a time-aligned profile, one value per timepoint).

The critical distinction is that `Scores` is time-aligned, which is what makes a single generic "threshold a Scores to obtain a SpanSet" block possible. A window matrix is **not** a `Scores` — it is a feature table with one row per window and no timepoint alignment, and it rides as attached features on a `WindowSet`. Conflating them breaks the thresholding chain.

Each type is a small frozen dataclass with disk serialisation, because the step cache needs a serialiser anyway and putting it on the type makes it free. Arrays serialise to compressed numpy archives, feature tables to parquet, span sets to JSON, models by path reference.

Any method that does not fit these seven types is out of scope, rather than a reason to add an eighth.

**A latent bug is fixed as part of this work:** the matrix profile adapter currently declares an `encoding` output while what it actually produces is a time-aligned score profile. It is remapped to `Scores`.

### Block contract

The adapter spec gains three fields and loses none: a declared `input_kind`, a list of typed `side_inputs` (each naming its type and the sources it may be bound to), and an optional `estimate` callable returning predicted runtime in seconds. The existing output-kind enumeration is replaced by the seven type names, and all twenty existing adapters are remapped.

Adding a technique remains what the goals spec promised: one new adapter file declaring its types, parameters and run function. The block set stays **curated, not open** — the declared contract is the plugin mechanism; there is no third-party registry.

### Chain shape

A chain is a **linear spine with named side-inputs**. Each step draws its primary input from the previous step, and may declare additional typed inputs bound at composition time to the chain's root signal, an earlier step's output, or a library exemplar. There is no fan-out within a chain, no merges, and no node canvas. Comparing two chains is a Compare action over two completed runs — the same mechanism surrogate comparison requires, so one implementation serves two research questions.

Side-input bindings serialise into the step and are **hashed by content, not by database identifier**: a binding records the entry id as a convenience pointer alongside the source file, channel and sample range that constitute its actual identity. This keeps a recipe hash stable when local identifiers change and lets an exported template resolve on another machine.

### Type checking

A single chain-validation function answers "can this output type feed this block, and if not, why not." It is consumed at two layers. At composition, the add-step control lists every block with incompatible ones disabled and the reason stated inline. At execution, recipe construction and the runner both hard-fail before any computation, so a hand-edited or cluster-generated recipe cannot get partway through a long run before failing. Two layers, one function, no possibility of drift.

### Storage

**[CORRECTION]** An earlier design unified human annotations and machine detections into one span table with an origin discriminator. This is reversed. The existing schema already separates them physically — annotations are human-only, detections are machine-only and foreign-keyed to runs — and that structural separation is a stronger guarantee than a discriminator column, because there is no column into which a machine write could place a human verdict. It also avoids migrating roughly eleven thousand existing annotation rows.

The database remains one SQLite file accessed through plain SQL with no ORM, extended additively by numbered migrations applied at startup, consistent with the existing pattern. Bulk arrays never enter the database; they live on disk referenced by path.

New tables:

- **`adjudications`** — a human verdict against a machine detection, one per detection, with a note and a tag join table. This is where human judgement of algorithmic output lives, and it is the only such place.
- **`v_spans`** — a view unioning annotations and detections with an origin column, so every read surface (viewer overlay, library, divergence queries) has one read path while writes stay physically separated.
- **`motif_entry` / `motif_member` / `motif_edge`** — the shape-first library. An entry is an exemplar span identified by recording and sample range, with optional provenance pointers to the detection or annotation it came from. A member is any span matched to it, in **any** recording and **any** channel. An edge carries the distance function, threshold, distance value, recipe hash, and — for cross-channel members — inter-channel lag, waveform correlation and classification bin. Tags attach many-to-many to entries and are never the primary key.
- **`run_groups`** — N sibling runs sharing one recipe, fanned out over a channel list or a band list.
- **`step_artifacts`** — the per-step cache, keyed on the hash of the recipe prefix up to and including that step.
- **`templates`** — saved chains with recording and span stripped.

Changes to existing tables: the annotation verdict constraint gains `seed`; runs gain a run-group reference and a surrogate-pairing reference.

**Why shape-first matters, concretely.** The existing motif table is keyed to a detection, and a detection belongs to one run, and a run is bound to one recording. Under that model a library entry is tethered to the recording it was found in, there is nowhere to record a second span that matched it, no column holds the distance or threshold that produced a match, and a shape spotted by eye can never be an exemplar at all. Making the entry a span instead of a detection is what makes cross-recording membership, persisted edges, and eye-flagged exemplars expressible. Existing motif rows migrate in as entries retaining their detection pointer.

### Verdict vocabulary

One vocabulary across human annotation and machine adjudication: `seed`, `interesting`, `not_interesting`, `artifact`, `unsure`. `interesting` is accept; `not_interesting` is reject; `seed` marks exemplar-worthy; `artifact` is retained as first-class because the cross-channel contamination question needs it. A single shared vocabulary means no translation table exists between the two stores, and therefore none can drift.

### Execution

A run executes on a background thread, with its status, current step and error recorded on the run row and polled by the UI. Cancellation is cooperative and checked between steps. Each stage's result is written and rendered as it lands. A progress indicator with an estimated finish appears once the chain's predicted runtime exceeds a configured threshold; adapters that already drive a fine-grained progress callback additionally show intra-step progress.

**Step caching.** Each step's cache key is the hash of the recipe prefix up to that step, including its side-input bindings. On run, the executor walks the chain and resumes at the first step with no cached artifact. An artifact is only written when the step's measured runtime exceeds a small configured threshold, so trivial filters cost no disk while expensive stages are never recomputed to retune something downstream. No cache eviction is implemented before the freeze.

**Fan-out.** A run over multiple channels or multiple bands creates one run-group row and N run rows. Locally they execute sequentially with per-item progress; on the cluster they become a single SLURM array job whose task index selects its target from a list baked into the recipe.

**Cluster routing.** Every adapter may declare a runtime estimator; two already exist in the codebase for the expensive stages. The run panel sums the chain estimate, multiplies by fan-out width, displays it, and above a configured ceiling promotes "export cluster job" to the primary action with local execution demoted. Blocks without an estimator count as free.

**Cluster round trip.** The headless recipe runner always writes a manifest beside its artifacts: recipe, config hash, run status, step timings, detections, artifact paths, code version and timestamps. The researcher copies cluster output back into the working tree at matching relative paths and triggers a single import action, which reads any manifest and writes the corresponding local rows. One generic importer replaces the two bespoke artifact importers that exist today. The same manifest format is the export payload, so one writer and one reader serve import, export and reproducibility.

### Workspaces

Four workspaces plus an admin group replace today's seven tabs. Nine tabs would be a filing cabinet; four is the research loop.

- **Explore** — the existing viewer, essentially unchanged: rasterized zoom driven by the visible range, vectorised annotation overlays, coverage and density ribbons, drag modes, filters, keyboard shortcuts, cross-channel peek, session persistence. It gains `seed` as a fifth verdict.
- **Analyse** — absorbs the run panel, run history and window-matrix panel. Holds the chain builder (a staged list with type-filtered block addition), the block inspector (generated parameter controls, recommended defaults, live derived readouts, side-input pickers, and that step's cached result), the scope selector (recordings, channels, span, bands), the run surface (estimate, routing, progress, per-stage results, surrogate toggle), a history sidebar that can reload a past chain, and the two-run Compare view.
- **Review** — the candidate queue. Filterable by run, run group, method, score range, channel and adjudication status. One candidate at a time in context with configurable padding, its analytical score, and the z-normalised overlay pattern the motif browser already uses. Verdicts on single keys with auto-advance and undo.
- **Library** — absorbs the motif browser. A thumbnail grid of exemplars with a group-by selector and scope summary; an entry detail showing the exemplar, its members, the all-members overlay on a shared relative-time axis, and the edge list. Actions to search at other scales, classify cross-channel, and export.
- **Admin** — vocabulary administration, recording import, and cluster-job import.

**The central invariant of the Review workspace:** adjudicating a candidate writes an adjudication row against the detection and never an annotation row. Only explicit promotion creates a library entry. Regions the algorithms missed are marked in Explore as annotations. Both directions of divergence are then queryable over the union view with equal standing.

### Analysis semantics

**Distances.** Three named distance functions, each recorded on the edge it produces: a scale-invariant one (resample both spans to a common length, z-normalise, Euclidean) as the primary; a symbolic one (SAX minimum-distance at fixed word length, scale-invariant by construction through piecewise aggregation) as the second arm; and a native-length z-normalised match as the unnormalised control. Elastic distances are deferred — the cost of banded dynamic time warping across sixty-four channel-recordings does not fit the schedule, and the scale-invariance question is answerable without it. "Does this motif recur at other scales" is therefore a query: search at durations the exemplar was never defined at, and compare recall between the scale-invariant distance and the control.

**Surrogates.** Surrogate generation is a signal-to-signal block offering phase randomisation and block shuffling, with an explicit RNG seed among its parameters so the recipe hash reproduces the surrogate exactly. Every run carries a surrogate-control toggle that is **on by default**; when set, a paired run executes the identical chain with the surrogate step prepended, linked to the original by a run reference, and results are always displayed as detected-versus-surrogate counts. Exports state a null surrogate explicitly rather than omitting the field, so a missing control is visible. The surrogate signal is transient and never gets a recording row, which means nothing surrogate-derived can enter the library — it has no recording to attach a span to.

**Cross-channel classification** is a library-level action rather than a block, because the univariate signal type deliberately cannot express multi-channel input and because the classification is a statement about a motif family rather than about a signal. For each pair of members on different channels of one recording it computes inter-channel lag from the cross-correlation peak and waveform identity from the correlation at that lag, then classifies into three bins persisted on the edge: **artifact** (near-zero lag and near-identical waveform — a shared-ground recording error, excluded from counts), **propagation** (small consistent lag with waveform variation — a real network event), and **independent recurrence** (lag scattered across long intervals — counted once per instance). The artifact bin doubles as an internal control: a method that cannot separate a ground artifact from a real event has a diagnosable problem.

**Band decomposition** reuses the existing bandpass adapters. A banded chain is the same chain with a bandpass step prepended, and the band list is a fan-out scope exactly like the channel list. The comparison of direct against banded is the Compare view's set overlap, with the non-overlapping remainder adjudicated by hand.

### Export and templates

Two exporters, each writing a folder containing a manifest, a spans table as CSV, and copied plots. One exports a run group: recipe, config hash, per-run status and timings, detections with their adjudications, surrogate counts, artifact paths, code version and timestamps. The other exports a library entry: exemplar, members with their edges and distances, scope by recording and channel, cross-channel bins, tags, and the recipe behind each edge. The manifest shares its schema with the cluster-job manifest. The CSV exists because thesis tables come out of a spreadsheet, not a JSON blob.

A template is a chain's steps with recording and span stripped, stored in the database and exportable as JSON. Each side-input binding declares either *carry* (the exemplar travels with the template — reapply this exact search) or *rebind* (prompt on apply — reapply this method). Applying a template asks for recording, span and any rebinds, then constructs an ordinary recipe.

### Evaluation protection

The held-out recording is **`M4_aug_concat_fs1.mat`** — the only non-M2 network in the corpus and therefore the strongest available generalisation test. It is named in configuration, its channels are materialised so the freeze-day run is a single action, and both the viewer and the runner refuse it unless an explicit unlock flag is passed. The lock makes the methods-chapter claim true by construction rather than by memory.

**A leakage hazard to state in the thesis:** `M2_aug_concat_fs1.mat` and `M2_aug_concat_fs2.mat` are the same underlying recording at two sample rates. They must never be split across training and test.

## Testing Decisions

A good test here asserts external behaviour that a research claim depends on — that a recipe reproduces, that a cache resumes correctly, that a lagged pair classifies as an artifact — not that a particular function was called. Tests are headless. Visual inspection of the Panel surfaces stays with the researcher, deliberately: it is the review bottleneck this entire design is shaped around, and automating it is not affordable before the freeze.

**Preferred seams, highest first.** Three seams already exist in the codebase and should carry most of the new coverage rather than new ones being invented:

1. **The headless recipe executor** is the highest useful seam. It takes a recipe and a database path and returns run identity, results and timings with no UI anywhere in the chain, which makes an end-to-end assertion possible in a single call. Existing tests already exercise it; the new work extends that file rather than starting a parallel suite.
2. **The recipe hashing layer** is the reproducibility seam. Asserting that a rerun of an identical recipe yields an identical hash, an identical artifact and a reused rather than recomputed run is the concrete form of the reproducibility claim, and it needs no new infrastructure.
3. **The database initialisation function** is the migration seam. It is already written to be idempotent and additive; the new migrations must preserve that property, and the test is simply calling it twice and comparing row counts and tag links.

**Modules under test, and what each test asserts:**

- **Types** — every one of the seven round-trips through its disk serialisation unchanged, including a window set carrying an attached feature table.
- **Chain validation** — the full compatibility matrix, asserting both the boolean and the human-readable reason for each incompatible pair, plus that the three worked chains (CNN, seeded search, banded search) validate end to end.
- **Executor with cache** — changing the parameters of step *k* in an *n*-step chain recomputes steps *k* through *n* and reuses steps 0 through *k*−1, verified by artifact identity rather than by timing.
- **Migrations** — idempotence as above; specifically that the verdict-constraint rebuild preserves every annotation row and every annotation-tag link.
- **Distances** — each of the three against hand-computed cases, including one pair identical in shape but differing in duration, which must be near-zero under the scale-invariant distance and large under the control.
- **Cross-channel classification** — a synthetic pair with a known injected lag classifying into the expected bin. **This is the test to insist on.** Without it a bug in this classifier is indistinguishable from a research finding, and the finding it would fake is precisely the one an examiner will attack.
- **Surrogate generation** — a fixed seed reproducing an identical surrogate and therefore an identical null count.
- **Manifest round trip** — write a manifest, import it into an empty database, and assert the reconstructed run rows match the original.
- **End to end** — synthetic signal through a three-step chain, adjudication, promotion to the library, export; asserting the exported manifest's recipe hash matches the run's.

The 195 existing tests must continue to pass at every milestone. That constraint is doing real work here: it is what turns the adapter remapping from a rewrite into a refactor.

## Out of Scope

- **Multivariate analysis.** No dynamic time warping across channels, no environmental covariates. The type system and library schema must not preclude it — a future signal becomes multi-channel and spans gain sibling context — but nothing multivariate is built or validated.
- **Data import robustness.** Clean, well-formed time-series input is assumed. No format detection, no malformed-file handling.
- **Open plugin architecture.** The declared interface makes a sixth technique possible; a third-party registry, versioning, or dependency isolation is not built.
- **Drag-and-drop node canvas.** Chains execute from a typed recipe rendered as a staged list. The canvas is a stretch goal only if the freeze date arrives early; the typed registry underneath it is the part that actually makes new techniques easy to add.
- **Rendered PDF reports.** Export is structured JSON plus automatically saved plots.
- **Cross-database exemplar sharing.** A stranger runs an exported template against their own database; shared exemplar identity across databases is not solved.
- **Elastic distances.** Dynamic time warping is available through an existing dependency if it ever becomes affordable, but is not built or evaluated.
- **Wavelet-based band decomposition.** RQ4 uses the existing bandpass filters. Further wavelet methods are backlog, explicitly wanted later.
- **Alternative encoding libraries.** The existing Gramian and recurrence encoders stay; no substitution.
- **Cross-domain corpora.** A non-fungal reference corpus was considered as a control and judged unnecessary.
- **Cache eviction.** No garbage collection of cached artifacts before the freeze; buy disk instead.
- **Automated UI testing.** No browser-driven or screenshot-diff tests.
- **Supported release.** Templates are exportable and re-runnable by a stranger; nothing is documented, packaged, or supported as a product.
- **Biological interpretation.** The software measures recurrence and structure. It makes no claim about meaning, signalling, or communication.

## Further Notes

### How the research questions map onto the build

The software exists to make six questions answerable. Two of them cannot be answered without it; two need it; two are strengthened by it.

| Question | What it needs from this spec |
|---|---|
| Do cluster-derived labels produce a classifier that generalises better than manually-derived labels? | The typed chain from signal through window set and grouping to a model; the physical human/machine store separation; the held-out lock |
| Does a human-adjudicated exemplar used as a matrix-profile seed recover instances a human also accepts? | Exemplar side-inputs; the native-length match distance; the Review queue; the surrogate control |
| Is motif identity preserved under scale normalisation? | The three distances; the search-at-other-scales action; the distance function recorded on every edge |
| Does band decomposition followed by symbolic encoding surface regions raw-signal methods miss? | Band fan-out scope; the Compare view's set overlap; hand adjudication of the remainder |
| Where do human and analytical judgement diverge, and is the divergence structured? | The union view; adjudication verdicts; annotations with no overlapping detection; morphology tags on both sides |
| Once contamination and propagation are separated out, does recurrence persist across channels and recordings? | Channel fan-out into run groups; cross-channel classification onto edges; surrogate counts |

A negative result on the scale-invariance question falsifies the library's grouping model, which is itself a finding worth reporting.

### Build order

Six milestones over fourteen days to the freeze. Each is a vertical slice that works end to end.

1. **Foundations** — types and serialisers; the verdict-constraint migration; the new tables and union view; remapping the twenty adapters to typed inputs and outputs; chain validation; side-input resolution; the step cache; migrating existing motif rows; the held-out lock. Entirely headless and fully testable.
2. **Review** — the adjudication store and divergence queries; the queue surface; keyboard verdicts with auto-advance and undo; promotion to the library.
3. **Analyse** — the chain builder; the block inspector; scope selection and run groups; the run surface with progress and per-stage results; estimators and cluster routing; generalised job export with array jobs; the manifest writer, reader and import action; the Compare view; folding in run history and the window-matrix panel.
4. **Library** — the three distances; edge computation and persistence; the entry grid and detail; the members overlay and edge list; grouping selectors; search at other scales; cross-channel classification; absorbing the motif browser.
5. **Controls, export, templates** — the surrogate block; paired runs with side-by-side counts; both exporters; template save, apply and carry/rebind.
6. **Freeze and evaluate** — repository cleanup; the end-to-end test; documentation refresh; then unlock the held-out recording and run the full pipeline on it.

**Review is deliberately built before Analyse.** It needs only the first milestone's adjudication table, and thousands of matrix-profile detections are already waiting to be scored. Adjudication throughput is the rate limiter for two research questions, so every day the queue exists earlier is a day of data that cannot be bought back later.

### Guidance for ticket breakdown

Each milestone above decomposes into work packages that are independently workable. Two properties make them safe to run in parallel by separate agents:

- **Module ownership is exclusive.** Within a milestone, no two work packages own the same module. A package that needs a change in another package's module declares that package as a blocker instead.
- **Acceptance is testable without a human.** Every package's acceptance criterion is a statement a test can assert, with the exception of the Panel surfaces, which are explicitly the ones requiring a person to look at them.

**Model routing.** Most packages are well-scoped, have an existing pattern in the repository to copy, and pass or fail on a test — those are suitable for a Sonnet-class model running unattended. Five are not: the four Panel surfaces involving linked views (chain builder, run panel, review queue, library grid) and the verdict-constraint rebuild. The Panel work needs a stronger model *and* a human looking at the output, because a broken dynamic map renders as a silently blank pane rather than an error — a failure mode this codebase has already hit twice. The constraint rebuild needs care because SQLite cannot alter a check constraint in place; it requires the full table-rebuild procedure against roughly eleven thousand rows with a tag join table to preserve. Back up the database first. If it goes badly, the fallback is to record the seed verdict in the existing free-text status column, which needs no rebuild at all.

### Constraints that shaped these decisions

**Time is the dominant constraint.** Fourteen days to freeze, then roughly five weeks to run every experiment and write the thesis. The failure mode to design against is a polished tool with a thin results chapter. Wherever a design choice traded build time against research output, research output won.

**The real bottleneck is review bandwidth, not code generation.** Prior experience on this project: Panel and HoloViews integration bugs — dynamic maps switching element type between frames, range linking, y-range circular dependencies — do not yield to autonomous agent runs, because they require visual inspection to even detect. This is why the design minimises custom linked views: generated parameter UI rather than bespoke controls, a staged list rather than a node canvas, and reuse of the existing plot builders on every new surface.

**The cut list is decided now rather than at two in the morning on the 27th.** In order: drop the step cache and rerun chains instead; drop the template UI and keep JSON import/export; drop the library grouping selectors and ship shape-only grouping; drop the cross-channel classification UI and run it as a script. Never cut: adjudications, surrogate-by-default, and the exporters — those three are what make the results chapter defensible.

### Decision log

| Decision | Rationale |
|---|---|
| Linear spine with named side-inputs; no fan-out inside a chain | Seeded search and surrogate comparison need extra inputs; a canvas is out of scope and Compare covers the diff case |
| A signal is one channel; multi-channel work is a fan-out, not a type | Keeps univariate typing honest while making sixteen-channel sweeps a single action |
| Extend the existing database; plain SQL, numbered migrations | Data volume is small, bulk arrays already live outside it, and no new dependency reaches the cluster |
| Keep human and machine spans in separate tables; add adjudications and a union view | Physical separation is a stronger one-way door than a discriminator column, and needs no eleven-thousand-row migration |
| One verdict vocabulary across both stores | No translation table exists, so none can drift; the artifact verdict is retained for the contamination question |
| Content-addressed step cache above a small runtime threshold | Makes retuning one stage cheap without spending disk on trivial steps |
| Background thread per run, per-stage results as they land | Single-user application; avoids pickling parameter objects and torch models |
| Preserve the UI-free core | Enables cluster runs, headless tests, and the reproducibility claim |
| Extend the adapter spec rather than migrating to Param | The existing spec already carries recommendation and derived readouts that Param does not |
| Shape-first library identity | Detection-keyed identity cannot express cross-recording membership, persisted edges, or eye-flagged exemplars |
| Seven types on the adapter spec; matrix profile corrected to Scores | Time-alignment is what makes generic thresholding possible |
| Type errors surfaced at composition and enforced at execution, from one function | Two layers, one source of truth |
| Manifest-based cluster round trip | There is no safe merge between two independently auto-incrementing databases |
| Estimator-driven cluster routing | Fan-out multiplies the estimate, so heavy sweeps route themselves |
| Side-inputs hashed by content, not identifier | Local identifiers are not portable; content is |
| Three distances, elastic deferred | Cost, not principle |
| Surrogate on by default, transient, seeded | Default-on is what makes "every result has a null" true in practice |
| Cross-channel classification as a library action, not a block | Keeps multivariate out of the type system and works across runs |
| Four workspaces mirroring the research loop | Nine tabs is a filing cabinet |
| Review built before Analyse | Adjudication throughput is the rate limiter for two research questions |
| Held-out recording enforced in code | Makes the methods claim true by construction |
