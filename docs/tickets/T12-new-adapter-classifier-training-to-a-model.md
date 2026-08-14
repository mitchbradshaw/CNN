---
id: 12
title: "New adapter: classifier training to a Model"
model: opus
size: M
blocked_by: [5, 11]
mutex: [5, 11, 14, 26]
files: ["Adapters/catalogue_classifier.py", "Working/Catalogue/aeon_classification/classification.py", "Working/Catalogue/cnn/apply_cnn.py", "tests/test_model_adapter.py"]
flags: []
level: 4
unblocks: 1
budget_minutes: 60
---
# 12 — New adapter: classifier training to a Model

**Model:** [O] · **Size:** [M]

**What to build:** a block that takes a `WindowSet` plus a `Grouping` side-input and produces a
`Model` — the last segment of RQ1's chain.

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
- [ ] A registered adapter declares `input_kind="WindowSet"`, `output_kind="Model"`, and one
      `side_inputs` entry of type `Grouping`.
- [ ] The same adapter trains from a cluster-derived `Grouping` and from a manual-label-derived
      `Grouping` with no branch in its `run` — only the binding differs.
- [ ] The produced `Model` serialises by path reference, not by pickling into the database.
- [ ] The adapter declares an `estimate` callable, since training is one of the expensive stages
      cluster routing exists for.
- [ ] A test composes `window_matrix → cluster → classifier` and asserts the chain validates and runs
      end to end on a synthetic signal.
- [ ] `classification.py` and `apply_cnn.py` are unmodified.
