---
id: 12
title: "New adapter: classifier training to a Model"
model: opus
size: M
blocked_by: [5, 11]
mutex: [5, 11, 14, 26]
files: ["Adapters/catalogue_classifier.py", "Working/Catalogue/aeon_classification/classification.py", "Working/Catalogue/cnn/apply_cnn.py", "tests/test_model_adapter.py"]
flags: ['done']
level: 4
unblocks: 1
budget_minutes: 60
---
# 12 — New adapter: classifier training to a Model

**Model:** [O] · **Size:** [M]

**What to build:** a block that takes a `Grouping` plus a `WindowSet` side-input and produces a
`Model` — the last segment of RQ1's chain.

> **Corrected 2026-08-26.** This ticket originally asked for the two the other way round — primary
> `WindowSet`, `Grouping` side-input. That is not buildable: `Working/chain_validation.py` types a
> chain as a linear spine, so a step whose primary input is a `WindowSet` can never follow one that
> produces a `Grouping`, and the `window_matrix → cluster → classifier` chain in AC5 would not
> validate under any ordering. Two runner agents stopped on the contradiction rather than guessing,
> correctly. It is resolved in favour of AC5, the PRD's own statement of the chain ("the typed chain
> from signal through window set and grouping to a model") and the already-shipped
> `test_chain_validation.py::test_cnn_chain_validates_end_to_end`, all three of which agree on
> `signal → windowset → grouping → model`. AC1 and AC2 below are rewritten to match; nothing else
> about the ticket changed, and the design requirement in **Why [O]** is untouched — the label source
> is still a binding rather than a branch. Triage in `FOLLOWUPS.md`.

**Blocked by:** 05, 11

**Files/modules touched:** new `Adapters/catalogue_classifier.py`; reads
`Working/Catalogue/aeon_classification/classification.py` and `Working/Catalogue/cnn/apply_cnn.py`
(not modified); new `tests/test_model_adapter.py`.

**Merge risk:** **MEDIUM vs ticket 11** (shared feature-matrix helper) and **MEDIUM vs ticket 14** —
this is the first adapter to declare a `side_inputs` entry, so it is the first real consumer of the
side-input contract. If 14 has not landed, do not invent a second binding format; block on it or bind
only to `earlier_step` initially and state that in the ticket.

**Why [O]:** the label source is the research question. A classifier trained on a cluster-derived
`Grouping` and one trained on manual labels must be the *same block with a different side-input
binding*, or the comparison RQ1 asks for is not a comparison. Getting that seam right is a design
judgement, not a transcription.

**Acceptance criteria:**
- [x] A registered adapter declares `input_kind="Grouping"`, `output_kind="Model"`, and one
      `side_inputs` entry of type `WindowSet`, bindable to `earlier_step`.
- [x] The same adapter trains from a cluster-derived `Grouping` and from a manual-label-derived
      `Grouping` with no branch in its `run` — only the upstream binding differs, and no parameter
      names the label source.
- [x] The produced `Model` serialises by path reference, not by pickling into the database.
- [x] The adapter declares an `estimate` callable, since training is one of the expensive stages
      cluster routing exists for. It answers `None` ("not calibrated"): the fit is linear in the
      window count, which `job_export` cannot supply to an estimator, and this repo's cost modules
      refuse to guess a constant. Declaring it is still what makes `route_recipe` report `'unknown'`
      rather than skipping the step and costing training at zero.
- [x] A test composes `window_matrix → cluster → classifier` and asserts the chain validates and runs
      end to end on a synthetic signal.
- [x] `classification.py` and `apply_cnn.py` are unmodified.
