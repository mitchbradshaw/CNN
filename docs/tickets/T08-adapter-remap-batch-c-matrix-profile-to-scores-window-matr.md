---
id: 8
title: "Adapter remap batch C: matrix profile to Scores, window matrix to WindowSet, executor dispatch"
model: opus
size: M
blocked_by: [5]
mutex: [3, 5, 7, 13, 15, 24]
files: ["Adapters/detection_matrix_profile.py", "Adapters/preprocessing_window_matrix.py", "Working/execution.py", "tests/test_execution.py", "tests/test_matrix_profile_store.py", "tests/test_window_matrix_store.py"]
flags: ['done']
level: 2
unblocks: 15
budget_minutes: 60
---
# 08 — Adapter remap batch C: matrix profile to Scores, window matrix to WindowSet, executor dispatch

**Model:** [O] · **Size:** [M]

**What to build:** the two adapters whose declared type is *wrong* get corrected, and the executor
learns to dispatch on seven types instead of three.

**Blocked by:** 05

**Files/modules touched:** `Adapters/detection_matrix_profile.py`,
`Adapters/preprocessing_window_matrix.py`; `Working/execution.py` (the
`output_kind == "signal" / "intervals" / "encoding"` dispatch and the `persist` branch);
`tests/test_execution.py`, `tests/test_matrix_profile_store.py`, `tests/test_window_matrix_store.py`.

**Merge risk:** **HIGH vs tickets 15 and 24** — all three edit `Working/execution.py`. 08 rewrites the
dispatch, 15 inserts the cache walk, 24 extends progress and cancellation. Sequence them 08 → 15 → 24
and do not overlap. **MEDIUM vs 07** on the encoder input convention.

**Why [O]:** both adapters currently declare `"encoding"` and both set `persist`, so the executor's
`elif output_kind == "encoding" and spec.persist is not None` branch is the only thing writing their
artifacts. Splitting them into two different types means that branch has to become two branches
without dropping either adapter's artifact registration — and the matrix profile correction is the
latent bug the whole thresholding chain depends on.

**Acceptance criteria:**
- [ ] `detection.matrix_profile` declares `output_kind="Scores"` and returns a `Scores` whose length
      matches the analysed span, not an `Encoding`.
- [ ] `preprocessing.window_matrix` declares `output_kind="WindowSet"` and returns a window set
      carrying its per-window feature matrix as attached features, with no timepoint alignment.
- [ ] `execute_recipe` dispatches on all seven type names; a `Signal` result feeds the next step,
      a `SpanSet` result writes detection rows, and any type may trigger `persist` if the adapter
      declares it.
- [ ] Both adapters still register an artifact row through `persist` — a test asserts an
      `artifacts` row appears for each after a headless run, as it does today.
- [ ] A generic block exists that takes a `Scores` and a threshold and produces a `SpanSet`, and a test
      chains `matrix_profile → threshold` end to end and asserts detections are written.
- [ ] `tests/test_matrix_profile_store.py` and `tests/test_window_matrix_store.py` pass unmodified.
