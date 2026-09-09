# UI context — what exists, and what it is for

**Audience:** any agent session working the UI rebuild wayfinder map. Read this once, at the start of
the session, before choosing or resolving a ticket. It is the low-resolution view of what has already
been built and what the interface is *for*; it deliberately does not tell you how to build anything.

**Why this file exists.** The authority on the current application is `docs/PIPELINE_PRD.md`, 607
lines across two parts. That document was written to justify *building the thing that now exists*, so
a session that reads it cold inherits its mechanisms as though they were requirements. They are not.
This file separates the two: what the interface must let a researcher **do** (fixed) from **how the
current build does it** (open). Where you need detail, this file tells you which PRD section to open
and what to distrust in it.

---

## 1. The project in three sentences

Underground Brains is a mycelium bio-electric signal analysis project. The application loads long
univariate electrical recordings of fungal networks, lets a researcher compose typed analysis blocks
into chains, run them over a channel or a selected span, adjudicate the resulting candidates by hand,
and accumulate what survives into a persistent cross-recording **motif library**. The library is the
deliverable; templates are how it gets populated; exports are how it gets communicated.

Its thesis claim is that recurring patterns in fungal electrical recordings can be automatically
detected and characterised. Every design decision in the current build traces back to making that
claim defensible rather than merely plausible.

---

## 2. What has already been built

### 2.1 The core, beneath the UI

This is the asset. It is UI-free by construction and the rebuild consumes it.

| Path | What it holds |
|---|---|
| `Working/` | Config, execution, recipes, chain validation, comparison, distances, export, templates, side-inputs, artifacts, encoding cache, run groups, cross-channel, library, HPC submission |
| `Working/types/` | The seven interchange types: `Signal`, `SpanSet`, `WindowSet`, `Encoding`, `Grouping`, `Model`, `Scores`. Frozen dataclasses with disk serialisation |
| `Working/database/schema.py` | The whole schema and its migrations, plain SQL, 22 tables |
| `Adapters/` | 22 algorithm adapter modules (6 catalogue, 10 detection, 6 preprocessing) plus `base.py`, the adapter contract, and `registry.py` |
| `Pipelines/` | Headless figure-generation pipelines. **Not part of the application** — see §5.2 |

The seven types gate which blocks may connect. A single chain-validation function answers "can this
output feed this block, and if not, why not", and is consumed at two layers — composition and
execution — so a hand-edited or cluster-generated recipe hard-fails before any computation.

A chain is a **linear spine with named side-inputs**: each step draws its primary input from the
previous step and may declare additional typed inputs bound to the root signal, an earlier step's
output, or a library exemplar. No fan-out. No merges. Not a general node graph.

Every run carries a **recipe hash** identifying the exact parameters and ordering that produced it —
any cached artifact, any saved plot, any library edge. Side-input bindings hash **by content, not by
database id**, so a recipe stays stable when local identifiers change and an exported template
resolves on another machine.

### 2.2 The interface, as it stands

`UI/` is 54 Python modules, roughly 13,800 lines, organised as four workspaces plus admin.

| Surface | Where | What it does today |
|---|---|---|
| **Explore** | `UI/viewer/` (14 modules) | The signal viewer. Rasterised zoom driven by visible range, vectorised annotation overlays, coverage and density ribbons, drag modes, filters, keyboard shortcuts, cross-channel peek, session persistence |
| **Analyse** | `UI/analyse/` (18), `UI/workspaces/analyse/` (7) | Chain builder, block inspector, scope selector, run surface, run history sidebar, two-run Compare, window matrix, export |
| **Review** | `UI/workspaces/review/` (3) | The candidate adjudication queue |
| **Library** | `UI/workspaces/library/` (4) | Motif grid, entry detail, cross-channel classification |
| **Admin** | `UI/admin.py`, `UI/file_import.py` | Vocabulary administration, recording import, cluster-job import |
| Shell | `UI/app.py`, `UI/serve.py`, `UI/plots.py`, `UI/motif_browser.py` | App assembly, serving, shared plotting |

Built on Panel / HoloViews / Bokeh. Tickets T01–T48 are merged; T49 and the Part 2 wave (T50+) are
partially landed.

### 2.3 What the current build got right, and is worth preserving as *intent*

Three properties make the tool trustworthy rather than merely convenient. They are requirements, not
mechanisms, and they survive any rebuild:

- **Detections are candidates, never results.** Nothing enters the library without human
  adjudication, and machine and human judgement live in physically separate tables so neither can
  contaminate the other.
- **Every result carries a null.** Surrogate testing runs by default on every analysis, so "we found
  motifs" upgrades to "we found more motifs than chance" without anyone remembering to do it.
- **Every chain is reproducible**, by recipe hash.

---

## 3. Top-level goals — the jobs the interface must do

**This is the section that fixes scope.** Each goal states a job. Beneath it, in italics, is how the
current build does that job — recorded so you know what exists, and explicitly **not** a requirement.
A rebuild satisfies the goal; it is free to discard the mechanism.

### G1. Navigate a long recording without lying about it

See a multi-hour signal at any zoom level without downsampling artifacts hiding structure, and move
between regions of interest quickly.

*Current mechanism: rasterised rendering driven by the visible range, with coverage and density
ribbons for orientation, and keyboard shortcuts for traversal.*

### G2. Compose a chain, and have it read as a chain

Assemble typed analysis blocks into an ordered pipeline where data visibly flows left to right, with
incompatible blocks **disabled and the reason stated** rather than hidden, and steps insertable
mid-chain rather than only appended.

*Current mechanism: a horizontal canvas of fixed-width block cards with a `+` between each pair,
opening a picker. This replaced a vertical staged list that failed — see §5.1.*

### G3. See what each step did to the signal

Every stage of a chain is rendered, not just its final output. Understanding what a technique does to
a signal is the point of the tool, and that understanding lives in the intermediate states.

*Current mechanism: a filmstrip — chain input at top, one plot per step in order, whole
transformation as a single scroll — plus a focus mode for any single block at full size.*

### G4. Render every interchange type, always

No value in the system is unplottable. All seven types have a rendering, including the ones with no
natural plot.

*Current mechanism: one function, given a type + value + adapter metadata, returns a renderable
element; every plot-centric surface goes through it and nothing switches on type locally. An optional
per-adapter detail hook adds richness where it exists (initially only the SAX blocks).*

**This goal is load-bearing and its rationale must survive the rebuild:** it is what stops
"plot-centric" from degrading into "blank for half the blocks".

### G5. Edit a parameter without paying for the whole chain

Changing step N recomputes N onward and nothing before it, automatically when cheap and on request
when expensive.

*Current mechanism: step cache keyed on a recipe-prefix hash; suffix derived from recipe and changed
index; the existing estimator and routing threshold decide auto-versus-ask. On any chain containing a
matrix profile this is the difference between instant and hours.*

### G6. Tell two runs apart, and tell two chains apart

A run is identifiable by something a human chose. Comparing two runs answers **what was different
about the two chains**, not only whether their detection sets overlap — most comparisons on this
project are one-parameter sweeps, where that is the only question.

*Current mechanism: a nullable editable name on the run (a label, never an identifier — the recipe
hash remains identity), and two stacked chain canvases with the per-step diff highlighted above the
existing overlap output.*

### G7. Adjudicate candidates fast, and never contaminate the ground truth

One candidate at a time in context with configurable padding, its analytical score, and a
z-normalised overlay; verdicts on single keys with auto-advance and undo. Adjudicating writes an
adjudication row against a detection and **never** an annotation row. Regions the algorithms missed
are marked as annotations in Explore. Both directions of divergence are then queryable with equal
standing.

*Current mechanism: the Review queue, filterable by run, run group, method, score range, channel and
adjudication status.*

### G8. Browse the library along two independent axes

Group by **provenance** (which recording or spike train a motif came from) to ask "what came out of
this recording", and by **shape** (computed across all motifs regardless of origin) to ask "what
recurs across recordings". The finding is only visible when both exist and can be seen to disagree.
Entries exist at two scales — event (one spike) and train (a spike train) — so a train is a row an
edge can attach to.

*Current mechanism: thumbnail grid with a group-by selector and scope summary; entry detail showing
exemplar, members, all-members overlay on a shared relative-time axis, and the edge list.*

### G9. Get results out in a form a thesis can use

Export a run group or a library entry as a folder containing a manifest, a spans table as **CSV**,
and copied plots. The CSV is not negotiable — thesis tables come out of a spreadsheet, not a JSON
blob. Exports state a null surrogate explicitly rather than omitting the field, so a missing control
is visible.

### G10. Save a chain as a reusable method

A template is a chain's steps with recording and span stripped. Each side-input binding declares
either *carry* (the exemplar travels with it — reapply this exact search) or *rebind* (prompt on
apply — reapply this method).

---

## 4. The boundary — what the rebuild may and may not touch

### 4.1 Frozen

- **Algorithm implementations under `Working/`** — detection, catalogue, execution, recipes,
  comparison, distances, HPC. The methods are the science; the rebuild displays them, it does not
  reimplement them.
- **Recipe-hash provenance semantics.** Content-addressed side-inputs, prefix-keyed step cache,
  hash-as-run-identity.
- **The detection/annotation separation.** Detections are machine-only, annotations are human-only,
  separate tables, no code path writes a human verdict into a machine row or the reverse. The PRD
  calls this a one-way door; it survives any rebuild, on any stack.
- **The rendering rule for motif waveforms.** Clustering z-normalises so that "same shape" has a
  definition. **Figures do not.** Thumbnails and overlays draw detrended millivolts, unnormalised,
  with a shared y-scale within a family so relative depth is real. This is not a style preference —
  the project's submission language is that normalising amplitude destroys the evidence of scaling
  laws for depolarisation events. No ticket may "improve" the cards by normalising them.
- **Evaluation protection.** `M4_aug_concat_fs1.mat` is held out, named in configuration, and both
  viewer and runner refuse it without an explicit unlock flag. `M2_aug_concat_fs1.mat` and
  `M2_aug_concat_fs2.mat` are the same recording at two sample rates and must never be split across
  train and test.

### 4.2 Open

- **All of `UI/`.** Every surface, every module, the whole stack it sits on.
- **`Adapters/base.py` and every adapter.** The contract may change if a new frontend needs a
  different shape from it. What the adapters *compute* is frozen; how they declare themselves is not.
- **Any new serialisation, API or transport layer.** The core currently has no network surface. If a
  stack decision requires one, writing it is in scope and should be named explicitly on the map
  rather than smuggled in as an implementation detail.
- **Information architecture.** The four-workspaces-plus-admin split has held up, but it is a
  decision, not an axiom.

### 4.3 Negotiable, with justification

- **The database schema** (`Working/database/schema.py`). Additive migrations only, applied through
  an idempotent `init_db()`, and only where a change demonstrably serves the interface. There is no
  standing reason to change the storage model.
- **Bulk arrays never enter the database.** They live on disk, referenced by path. Any proposal to
  change this needs to argue against the reason it exists.

### 4.4 Out of scope

- **`Pipelines/`.** Not an interface. See §5.2 for its role as *reference*.
- The old `UI/` tree's continued development. It is frozen at whatever state it is in, kept green,
  and retired at the end.

---

## 5. Reference material, and how to read it

### 5.1 `docs/PIPELINE_PRD.md`

Two parts. **Part 1** (lines 1–340) specifies the pipeline; **Part 2 — The Usability Wave** (from
line 341) specifies the Analyse/Library rework and supersedes Part 1 wherever a Part 1 passage
carries a `[SUPERSEDED by Part 2]` marker.

**Read it for goals and rationale. Distrust it for mechanism.** Two specific traps:

1. Part 1 describes the chain builder as a **vertical staged list**. That is exactly what Part 2
   replaced, because it failed: the composition surface for a pipeline tool did not look like a
   pipeline, so chains did not get composed. Any Part 1 passage describing a surface is describing a
   build that has since been judged.
2. Part 2's diagnosis of the assembled application is the single most useful passage in the document
   for a rebuild, because it is the only part written *after* seeing the thing work. Its four
   observed failures — the chain builder doesn't show a chain; the analysis isn't visible; results
   can't be told apart; the library is empty — are the reason this rebuild exists. Read Part 2's
   `## Problem Statement` first.

Suggested reading order for a session: Part 2 Problem Statement → Part 2 Solution → §3 of this file →
whichever Part 1 or Part 2 Implementation Decision your ticket names.

### 5.2 `Pipelines/` as a visual reference corpus

The figure pipelines are **out of scope as code and in scope as reference**. They are what the
researcher currently produces by hand, and they are a strong statement of what the interface should
be able to produce. Do not read them unbidden: `Pipelines/drop_motifs/` alone holds around sixty
modules, many of which are numbered iterations of one another (`figures11_s2`, `figures12b_s2`,
`clusterfigs7`/`73`/`8`/`9`), and an agent browsing it unaided will pick the wrong generation.

**Which figures define the visual target is a decision ticket on the map**, resolved with the
researcher, who brings selected images to the discussion. Until that ticket is closed, treat the
directory as unsurveyed. Note also that `DATA/`, `MODELS/`, `MATRICES/` and `Plots/` are gitignored —
if rendered outputs rather than figure code are the reference, their location is part of that
ticket's answer.

`Pipelines/drop_motifs/DETECTION_AND_FIGURES.md` is the one entry point worth reading first.

### 5.3 Seed data

`DATA/library_seed/` is tracked on purpose — everything else under `DATA/` is gitignored. Its
generator was deleted and it cannot be regenerated; see its `PROVENANCE.md`. It holds 410 extracted
drop motifs across 16 spike trains and 7 channels. Clustering the pooled set yields twelve shape
families at a cophenetic correlation of 0.63, eleven of them drawing members from more than one spike
train. That is cross-recording shape recurrence — the thesis claim — sitting in data already on disk.
It is the natural payload for any vertical slice that needs real data in front of it.

---

## 6. Standing constraints on the rebuild

1. **The existing `pytest` suite stays green.** ~1049 tests as of 2026-08-31. The old `UI/` tree
   stays alive and passing until the new one supersedes it; no session deletes or weakens a Panel
   test to make something pass. Do not chase a fixed number — the gate is "nothing that passed
   before now fails".

   *Practical note:* the suite is slow (about six minutes serial, five with `pytest -n auto`). A
   session that touches only new-tree files does not need to run it every loop; a session that
   touches anything shared — `Working/config.py`, `execution.py`, the schema, `Adapters/base.py` —
   does, before calling anything done.

2. **The new tree gets its own gates**, appropriate to whatever stack is chosen. Defining them is a
   decision on the map, not an assumption.

3. **The UI-free core rule gets stronger, not weaker.** Today: no module below `UI/` may import
   Panel, HoloViews, Bokeh or matplotlib, and a test enforces it. That rule is what makes this
   rebuild possible at all — the core does not know a UI exists. Whatever the new boundary turns out
   to be, nothing below it may know a browser exists.

4. **Do not install packages or change dependencies** without explicit sign-off. The conda
   environment is shared across worktrees. A stack decision that adds a toolchain to a
   conda-on-Windows setup is exactly the kind of thing to stop and report on, and it belongs on the
   map as a ticket rather than in a commit.

5. **Panel's characteristic failure mode, recorded because it cost this project twice:** a broken
   dynamic map renders as a *silently blank pane*, not an error. Tests passed, review passed, the
   feature was missing. Whatever stack replaces it, the lesson generalises — a construction test
   proves a pane is *present*, never that it *painted*. `docs/UI_VERIFICATION.md` documents the
   browser-driven suite added in response.
