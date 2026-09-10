# Open-source projects worth inheriting from — survey for ticket #6

Wayfinder ticket [#6](https://github.com/mitchbradshaw/CNN/issues/6), under map
[#4](https://github.com/mitchbradshaw/CNN/issues/4) (rebuild the Pipeline GUI on a stack chosen by
evidence).

## Fixed context this survey was run against

- Single researcher, `localhost`, no auth, no deployment. A desktop-app candidate is not automatically
  disqualified by this constraint; a SaaS/multi-tenant one is.
- `Working/` and `Adapters/` are frozen. Anything inherited sits **above** that boundary — UI/rendering
  layer only, never algorithms.
- The chain is a **linear spine with named side-inputs**: no fan-out, no merges, seven typed
  interchange values gate what connects to what (`docs/PIPELINE_PRD.md:316`, restated unchanged at
  `:462`). This is deliberately **not** a general node graph, and Part 2 has already committed to its
  rendering: a horizontal canvas of fixed-width cards (T57), a filmstrip of every step's plot (T61/T62),
  and a single `render_value`-style dispatch of interchange-type → renderer (T56, `PIPELINE_PRD.md:478`).
  Anything proposed below is judged against a target that is already decided, not a blank page.
- Publication-quality static export is a stack-selection criterion (G9, `docs/agents/UI_CONTEXT.md:171`).

## Method

License and activity came from the GitHub API (`gh api repos/<owner>/<repo>`, `pushed_at` used as the
"is it alive" signal — it is last-commit date, not tagged-release date, which is the more honest signal
for a project's pulse). Architecture claims came from each project's own README/docs, fetched directly.
Twenty-four candidates were checked; the eleven below get a full write-up because they map onto the
issue's four categories and are genuinely close neighbours. Everything else is dispatched in a line.

---

## Category 1 — Scientific signal / time-series UIs

### phy — [cortex-lab/phy](https://github.com/cortex-lab/phy)

- **License**: BSD-3-Clause. Copying into a thesis project is unproblematic — permissive, attribution only.
- **Stack**: Python, Qt (PyQt/PySide), moving toward a "Qt-native" build per its 2.1.0 notes; OpenGL for
  the waveform views. Installed via `uv`, Python 3.12.
- **Alive**: yes — last commit 2026-09-09 (the day before this survey). Current release 2.1.0,
  July 2026, described in its own README as "maintenance-focused."
- **What it would give**: it is the closest domain match in the whole list — manual curation of
  large-scale electrophysiology (spike sorting) with three GUI entry points (Template, Kwik, Trace) and
  a plugin system for custom views. Its curation workflow is the same shape as this project's G7
  (adjudicate one candidate at a time, verdict, move on).
- **What it costs**: it's a Qt desktop application, not a web surface — a different rendering paradigm
  from the horizontal-canvas-in-a-browser target already committed to in Part 2. Its views are built for
  spike-sorting-specific data shapes (waveforms, templates, correlograms), not the seven generic
  interchange types this project defines. There is nothing here that isn't already answered by
  `docs/agents/UI_CONTEXT.md`'s G7 mechanism (Review queue, one-at-a-time, keyboard verdicts,
  auto-advance, undo) — phy is a second implementation of the same idea, not a new one.
- **Verdict**: idea-level validation only, not a component.

### SpikeInterface / spikeinterface-gui — [SpikeInterface/spikeinterface](https://github.com/SpikeInterface/spikeinterface) · [SpikeInterface/spikeinterface-gui](https://github.com/SpikeInterface/spikeinterface-gui)

- **License**: MIT on both. No restriction on copying.
- **Stack**: Python. `spikeinterface-gui` ships **two interchangeable backends**: desktop (PySide6/PyQt5
  + pyqtgraph) and **web (Panel + Bokeh)** — the same rendering stack this project's old `UI/` tree is
  built on. Views are dockable across eight configurable zones, with layouts persisted to JSON.
- **Alive**: very — core library pushed 2026-09-10 (today), GUI pushed 2026-09-08. 846 and 71 stars
  respectively; small but genuinely maintained.
- **What it would give**: this is a **live neighbour solving the same problem on the same stack**. If
  the stack decision (still open per the map) keeps Panel, `spikeinterface-gui`'s dockable multi-zone
  layout with persisted JSON view-configs is a directly relevant reference implementation for the
  filmstrip/block-canvas surfaces — MIT license means literal code reading or borrowing, not just idea
  theft, is legally clean. If the stack decision moves off Panel, this drops to "idea only": proof that
  a scientific multi-view GUI can be built with a thin web layer over a typed analysis-object core,
  which is exactly this project's own `Adapters/` boundary.
- **What it costs**: it is architected around `SortingAnalyzer`, a single rich domain object with named
  computed "extensions" (waveforms, templates, quality metrics) — not a chain of typed interchange
  values passed step to step. The docking/zone system solves "many simultaneous views of one object,"
  this project needs "one view per step of a linear sequence." The mapping is not 1:1.
- **Verdict**: the one candidate in this category worth a second look once the stack ticket lands,
  specifically for its Panel-based layout code if Panel survives.

### MNE-QT-Browser — [mne-tools/mne-qt-browser](https://github.com/mne-tools/mne-qt-browser)

- **License**: BSD-3-Clause.
- **Stack**: Python, PyQtGraph (itself Qt-based). Not standalone — requires MNE-Python.
- **Alive**: yes, pushed 2026-09-08. This is the backend that replaced MNE-Python's old matplotlib
  scrolling browser specifically because matplotlib couldn't hold up against multi-hour multichannel
  EEG/MEG at interactive frame rates — the same problem this project's `UI/plots.py` bucketed min/max
  decimation solves with plain numpy instead of a GPU toolkit.
- **What it would give**: confirms, from a second serious neuro-tooling project, that
  view-range-triggered decimation is the standard answer to "browse a very long trace honestly" — this
  project already has that (12.1 ms on 2.6M samples per the existing implementation). Nothing to take
  beyond that validation, since the two use different toolkits (PyQtGraph GPU canvas vs. HoloViews/Bokeh
  or whatever the new stack turns out to be).
- **What it costs**: Qt desktop again, and MNE-Python's own architecture (Raw/Epochs objects) doesn't
  map onto this project's typed-block model.
- **Verdict**: idea validation only.

### Plotly-Resampler — [predict-idlab/plotly-resampler](https://github.com/predict-idlab/plotly-resampler)

- **License**: MIT.
- **Stack**: Python. Core deps are `plotly` and `tsdownsample` (a Rust-backed downsampling library);
  Dash is optional. It offers `FigureWidgetResampler` for a **standalone Jupyter/IPython-widget**
  deployment with no server, and `FigureResampler` for a Dash-callback deployment.
- **Alive**: yes, pushed 2026-08-26, 1,209 stars — the most popular single-purpose candidate in this
  survey.
- **What it would give**: the reusable idea is not the MinMaxLTTB algorithm itself (this project's own
  bucketed min/max decimation already does the job the map's corrections describe, and changing it
  isn't in scope) — it's the **wrapping pattern**: a function that takes any figure and auto-attaches a
  "re-aggregate on viewport-range-change" callback, so every new plot gets zoom-honest rendering for
  free instead of every call site remembering to decimate. If the stack decision lands on Plotly/Dash
  specifically, the library becomes a straight pip dependency (MIT, no copying question at all) rather
  than something to port.
- **What it costs**: only pays off if the stack choice is Plotly/Dash. On any other stack (Panel/
  Bokeh, a React frontend with a custom renderer) it's irrelevant as a dependency, though the wrapping
  pattern still transfers as an idea.
- **Verdict**: contingent — real component if Plotly/Dash wins the stack decision, otherwise a pattern
  worth remembering, not code worth copying.

### NWB tooling — [NeurodataWithoutBorders/nwbwidgets](https://github.com/NeurodataWithoutBorders/nwbwidgets) (BSD-3-Clause, ipywidgets, pushed 2026-02-23) · [flatironinstitute/neurosift](https://github.com/flatironinstitute/neurosift) (Apache-2.0, browser/TypeScript, pushed 2026-09-04) · [magland/sortingview](https://github.com/magland/sortingview) (Apache-2.0, TypeScript, pushed 2025-09-04 — a year stale)

All three dispatch on NWB data-type to pick a widget/view, which is the same shape as this project's
already-decided `render_value` (interchange-type → renderer). That's validation, not something to
import. `nwbwidgets` is Jupyter-only (no standalone app). `neurosift` is a full browser-based app with
its own DANDI-archive cloud integration — a much bigger dependency surface than a localhost tool needs.
`sortingview` depends on `kachery-cloud`, a distributed content-addressed storage service — architected
for sharing results across labs, which is the opposite of this project's single-researcher-on-localhost
constraint, and it's the least actively maintained of the three. None of the three offer a component
worth lifting; the dispatch-by-type idea is already independently decided in this project's own PRD.

### NeuroScope / Neurosuite — [neurosuite/neuroscope](https://github.com/neurosuite/neuroscope)

GPL-2.0, C++/Qt4. Last commit 2020-05-19 — over six years stale, effectively dead. GPL is also the
license that actually matters here: copying GPL code into this project would obligate the whole
rebuild under GPL, which is a real cost for a thesis project whose final licensing isn't yet decided.
Dismissed on both staleness and license grounds.

### EDFbrowser — [teuniz.net/edfbrowser](https://www.teuniz.net/edfbrowser/)

GPL-3.0 (confirmed on the author's own page), C++/Qt5/Qt6, claimed actively maintained by its original
author (current version 2.15). Same GPL copying problem as NeuroScope. It's also a generic
EDF-format file viewer, not an analysis-chain tool — no architecture here maps onto this project's
problem beyond "render a long multichannel trace," already solved. Dismissed.

---

## Category 2 — Visual pipeline / chain builders

**The issue's own warning proved out under research**: a targeted search for a linear-only,
typed-connection, no-fan-out pipeline *editor* turned up nothing — every actively maintained visual
pipeline tool in this space is a general node graph (search: "open source linear pipeline step editor
UI 'no fan-out' typed connections scientific workflow", no on-point results beyond generic DAG/CI
tools). That absence is itself a finding: this project's shape has no ready-made OSS analogue to
inherit from, which matches the map's framing that the chain builder's rendering (T57/T61/T62) was
worked out from first principles, not borrowed.

### The general node-graph editors — dismissed as a group

[Rete.js](https://github.com/retejs/rete) (MIT, TypeScript, pushed 2026-07-24, 12.2k★),
[LiteGraph.js](https://github.com/jagenjo/litegraph.js) (MIT, JavaScript, pushed 2024-08-01 — over two
years stale, 8.1k★), [React Flow / xyflow](https://github.com/xyflow/xyflow) (MIT, TypeScript, pushed
2026-09-09, 38.3k★, the most active and popular of the three), and [Node-RED](https://github.com/node-red/node-red)
(Apache-2.0, JavaScript, pushed 2026-09-09, 23.6k★) all solve "let a user wire arbitrary typed nodes
into an arbitrary graph." Rete.js's socket system does support typed sockets that refuse an
incompatible wire — conceptually identical to this project's chain-validation function
(`docs/PIPELINE_PRD.md:466`) — but that's an idea this project has already implemented correctly for
its narrower (linear, no-fan-out) case. Adopting any of these means adopting general-graph affordances
(drag nodes anywhere, wire any output to any input, save arbitrary topologies) this project has
deliberately ruled out. Using one here doesn't save effort, it adds a canvas-state machine only to
immediately constrain it back down to a straight line — strictly worse than the horizontal
fixed-width-card canvas already decided. All four are otherwise healthy, permissively-licensed
projects; none fit.

### Orange3 and KNIME — heavier general node-graph platforms, dismissed

[Orange3](https://github.com/biolab/orange3) is GPL-3.0+ (confirmed from its own `LICENSE` file — the
GitHub API reports "NOASSERTION" because the license text isn't a byte-for-byte SPDX match, but it is
GPL-3.0+ in substance), Python/Qt, pushed 2026-09-09 — alive and popular (5.7k★). KNIME Analytics
Platform is GPL-3.0 with a node-API exception permitting proprietary extensions (per
[knime.com/open-source-story](https://www.knime.com/open-source-story)), Java/Eclipse RCP, a large and
actively developed commercial-backed desktop platform. Both are visual-programming widget-canvas tools
for data mining, both carry GPL obligations, and both are enormous dependency trees (a full desktop
RCP application, in KNIME's case) for a single-researcher localhost tool that needs one narrow,
linear chain type. Clear overshoot on every axis; the issue's warning about general graph editors
applies most strongly here.

### Elyra — [elyra-ai/elyra](https://github.com/elyra-ai/elyra)

Apache-2.0, Python, pushed 2026-09-10 (today), 1,995★. A JupyterLab extension with a visual pipeline
editor for chaining notebooks/scripts, targeting Kubeflow Pipelines, Apache Airflow, or local execution
as runtimes. Still a general DAG editor (drag notebooks onto a canvas, wire arbitrary dependencies), and
its whole reason for existing — targeting Kubernetes-based orchestrators — has no bearing on a
single-machine tool. Dismissed on fit, not on health (it's well-maintained).

### Kedro-Viz — [kedro-org/kedro-viz](https://github.com/kedro-org/kedro-viz)

- **License**: Apache-2.0. **Stack**: React frontend (published standalone as `@quantumblack/kedro-viz`),
  Python backend as a Kedro plugin. **Alive**: pushed 2026-09-10 (today), 759★.
- **What's actually interesting**: it is **not** a visual editor. Kedro pipelines are declared in
  Python code (nodes, named inputs/outputs, a typed dataset catalog); Kedro-Viz only *renders* the
  DAG that declaration implies, read-only, with a metadata panel for parameters and plots. That's the
  right shape of tool — declare structure in code, render it, don't let a human drag wires — and it's
  the same philosophy this project's `ChainState` + block registry already follow. But Kedro's
  "catalog" types data by *dataset class* (CSVDataset, ParquetDataset, …), not by the seven fixed
  interchange types this project uses to gate connections, so there's no typed-compatibility mechanism
  to lift — the type-checking function already in `docs/PIPELINE_PRD.md:466` does something Kedro's
  catalog doesn't attempt (refusing a wire, not just labelling a dataset's format).
- **Verdict**: validates the "code declares, UI only renders" philosophy already in place. Nothing to
  copy; worth citing if that philosophy is ever challenged.

### The sklearn Pipeline diagram, as a rendering idea, not a project

scikit-learn's `set_config(display='diagram')` renders any `Pipeline` as a static HTML/CSS stack of
named-step boxes (BSD-3, [scikit-learn.org/stable/modules/compose.html](https://scikit-learn.org/stable/modules/compose.html)) —
non-interactive, expandable nested estimators, no JS framework. It's not a project to inherit (there's
no separable component — it's ~a few hundred lines of `estimator_html_repr` inside a much larger
library) but it's worth naming as the cleanest existing proof that "a linear chain of named steps"
looks best as a plain stacked-box rendering rather than a graph layout — which is exactly the direction
T57's horizontal-card canvas already took. Idea-only, and already acted on.

---

## Category 3 — Provenance-tracking tools

### DVC — [iterative/dvc](https://github.com/iterative/dvc)

- **License**: Apache-2.0. **Stack**: Python, CLI-first, optional cloud-storage backends
  (`dvc-s3`, `dvc-azure`, …) that this project would never need. **Alive**: pushed 2026-09-07, 15.9k★.
- **What it would give**: `dvc.yaml` pipelines can be linear or a general DAG — DVC doesn't force
  fan-out, it just doesn't forbid it either (per [doc.dvc.org/user-guide/pipelines/defining-pipelines](https://doc.dvc.org/user-guide/pipelines/defining-pipelines):
  "its topology should be acyclic" is the only real constraint). Its caching model — content-hash each
  stage's declared deps/outs, skip stages whose hash hasn't changed — is conceptually identical to this
  project's own recipe-prefix-hash step cache (`docs/PIPELINE_PRD.md:490`, already implemented). This
  is the strongest single validation in the whole survey that this project's own caching design is the
  industry-standard shape, not an oddity.
- **What it costs**: DVC's deps/outs are typed only as file paths — there is no analogue to this
  project's seven fixed interchange types gating what can connect to what. Its pipeline "view" is a
  read-only text/graph dump derived from YAML, not an editable canvas, so there's no UI component here
  either. Everything genuinely useful about DVC's design, this project has already built independently.
- **Verdict**: idea already converged on; nothing left to take.

### MLflow — [mlflow/mlflow](https://github.com/mlflow/mlflow)

Apache-2.0, Python, pushed 2026-09-10 (today), 27.9k★ — and its own GitHub description has shifted
from "experiment tracking" to "the open source AI engineering platform for agents, LLMs, and ML
models," which is a useful signal on its own: the project has grown well past the narrow
metric-and-artifact tracking UI this ticket might have wanted, into a much heavier general MLOps
platform. `mlflow ui` can run against a local file store without a real tracking server, which keeps
the localhost/no-deployment constraint satisfiable — but its UI is built around tabular runs with
scalar metrics and hyperparameters (loss curves, parameter tables), not a chain of typed intermediate
values with per-step plots. Dismissed: the domain mismatch is bigger than the license or activity
picture would suggest.

### Sacred + Omniboard — [IDSIA/sacred](https://github.com/IDSIA/sacred) + [vivekratnavel/omniboard](https://github.com/vivekratnavel/omniboard)

Sacred (MIT, Python, pushed 2025-10-22 — eleven months stale, low velocity) captures rich experiment
provenance (config, a source-code diff, dependency versions, RNG seeds) automatically on every run,
which is a genuinely nice idea for reproducibility. But its companion UI, Omniboard (MIT, JavaScript),
hasn't been pushed since 2023-02-01 — over three and a half years stale, effectively abandoned — and it
requires a MongoDB backend, which is real infrastructure for a single-researcher localhost tool that
currently just uses plain SQL. Dismissed: the provenance idea is fine, but the dependency and staleness
cost of the only UI that surfaces it rules it out, and this project's plain-SQL runs table with a
recipe-hash identity already captures the same kind of provenance more simply.

### Weights & Biases — [wandb/wandb](https://github.com/wandb/wandb)

The client library is MIT and genuinely open source (pushed 2026-09-10, 11.2k★). But the piece that
would matter here — the dashboard/UI — only exists as the hosted SaaS product or, for self-hosting, as
[wandb/server](https://github.com/wandb/server), whose base is MIT but which requires a "production
license" from Weights & Biases for features like external MySQL, cloud storage, or SSO
(per [docs.wandb.ai/guides/hosting/hosting-options/self-managed](https://docs.wandb.ai/guides/hosting/hosting-options/self-managed/)).
This is exactly the licence nuance the issue asked to get right: "the open parts" are real, but they
are the SDK, not the viewer — there is no meaningfully inheritable open-source UI here, only a
logging client this project has no reason to add.

---

## Category 4 — Adjudication / labelling queues

This category is worth reading against G7, which is **already built**: the old `UI/` Review queue does
one-candidate-at-a-time review with padding, a score, a z-normalised overlay, single-key verdicts,
auto-advance and undo, writing adjudication rows that never touch the annotation table
(`docs/agents/UI_CONTEXT.md:149-158`). The question for this category isn't "should we build this
workflow," it's "does an OSS labelling tool do it enough better to be worth adopting."

### Label Studio — [HumanSignal/label-studio](https://github.com/HumanSignal/label-studio)

- **License**: Apache-2.0 on the core repo (confirmed in its own README). Enterprise features are
  gated separately (a "Starter Cloud edition" is referenced but not detailed in the OSS README) — the
  core annotation engine itself is unambiguously open.
- **Stack**: React + MobX-State-Tree frontend, Django backend, SQLite for light local use or Postgres
  for production, with Nginx/MinIO in the full Docker Compose. **Alive**: pushed 2026-09-10 (today),
  28.2k★ — by far the most active project in this whole survey.
- **What it would give**: a mature, configurable labelling-interface engine (label configs, hotkeys,
  review workflows) if this project ever needed a second, more general-purpose labelling surface.
- **What it costs**: it's a multi-project, multi-user labelling **platform** — projects, permissions,
  a real database-backed server — built for teams labelling arbitrary data types. This project needs
  one queue, one researcher, one machine, and already has the exact interaction pattern implemented
  against its own domain objects (detections, not a generic annotation schema). Standing up Label
  Studio's server/DB stack to get a feature this project's `UI/` already has would be net negative.
- **Verdict**: not worth adopting; the existing Review queue is already the right shape and scale.

### doccano — [doccano/doccano](https://github.com/doccano/doccano)

MIT, Python (Django) + Vue frontend, pushed 2026-04-14 (~5 months stale relative to this survey),
10.8k★. Purpose-built for text annotation (NER, classification, sequence labelling) — the domain
mismatch is total, and like Label Studio it's a multi-user server platform. Dismissed on fit.

### CVAT — [cvat-ai/cvat](https://github.com/cvat-ai/cvat)

MIT, Python, pushed 2026-09-10 (today), 16.7k★. Purpose-built for image/video bounding-box and
segmentation annotation with AI-assisted labelling. Even further from this project's domain than
doccano; mentioned only because the issue named it as a category example. Dismissed on fit.

---

## Shortlist

Judged plainly: **most of this survey validates decisions already made rather than surfacing anything
to take.** That is a legitimate finding, not a failure of the search — the project's own architecture
(typed interchange values, prefix-hash step caching, a render-by-type dispatch function, a
linear-spine chain with no fan-out) turns out to already match the shape that DVC's caching, Kedro's
typed catalog, and the NWB ecosystem's per-type widget dispatch all converge on independently. None of
that is a reason to import code; it's a reason for confidence that the existing design isn't an
outlier.

Two items are worth carrying forward as live options, both contingent on the still-open stack decision:

1. **`spikeinterface-gui`** (MIT) — if Panel survives the stack decision, its Panel-based dockable
   multi-view layout is a real, actively maintained, same-stack reference implementation worth reading
   before building the filmstrip/block-canvas layout code, and its MIT license permits literal borrowing
   with attribution, not just idea-reading.
2. **`plotly-resampler`**'s wrapping pattern (auto-attach re-aggregation to any figure on
   viewport-range-change) — if the stack decision lands on Plotly/Dash, the library itself is a clean
   MIT pip dependency; on any other stack, the pattern (not the code) is worth keeping in mind when the
   new render layer is designed, though this project's own decimation already meets the immediate need.

Everything else surveyed — every general node-graph editor, every heavier orchestration/provenance
platform, every multi-user labelling platform, every GPL-licensed neuro-viewer — is a poor fit for a
single-researcher, `localhost`, no-deployment tool whose chain is a linear spine, not a graph, and whose
adjudication and provenance mechanics are already built and already the right size. **No project in
this survey is worth inheriting wholesale; the two items above are the only genuinely open questions,
and both wait on the stack ticket, not on this one.**
