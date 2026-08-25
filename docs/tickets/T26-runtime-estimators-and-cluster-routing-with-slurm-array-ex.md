---
id: 26
title: "Runtime estimators and cluster routing with SLURM array export"
model: sonnet
size: M
blocked_by: [5, 25]
mutex: [12]
files: ["Adapters/detection_matrix_profile.py", "Adapters/preprocessing_window_matrix.py", "Working/config.py", "Working/hpc/job_export.py", "tests/test_job_export.py"]
flags: ['done']
level: 7
unblocks: 5
budget_minutes: 60
---
# 26 — Runtime estimators and cluster routing with SLURM array export

**Model:** [S] · **Size:** [M]

**What to build:** the chain estimates its own cost, heavy sweeps route themselves to the cluster, and
a fan-out exports as one array job instead of N scripts.

**Blocked by:** 05, 25

**Files/modules touched:** `Adapters/detection_matrix_profile.py` and
`Adapters/preprocessing_window_matrix.py` (declare `estimate`, wrapping the existing cost functions);
`Working/hpc/job_export.py` (generalise `export_mp_job` and `export_wm_job` into one array-job
exporter); `Working/config.py` (routing ceiling); `tests/test_job_export.py`.

**Merge risk:** **MEDIUM vs 12**, which also declares an `estimate`. **Do not edit `Adapters/base.py`**
(frozen at 05). **Note this is smaller than it looks:** `Working/Detection/matrix_profiling/cost.py`
and `Working/Preprocessing/window_matrix/cost.py` already provide `estimate_seconds`, `routing_tier`
and `max_span_samples_for_background`, and `job_export.py` already has `_slurm_time_from_estimate` with
its ×3 safety factor. This ticket wires existing pieces together and generalises two bespoke exporters
into one.

**Acceptance criteria:**
- [ ] Both expensive adapters declare `estimate`, delegating to their existing cost module.
- [ ] The chain estimate is the sum of per-step estimates multiplied by fan-out width; a block with no
      estimator contributes zero.
- [ ] Above the configured ceiling, the routing decision returns "cluster" — as a value the run surface
      reads, not as a UI behaviour buried in a widget callback.
- [ ] One generic exporter replaces `export_mp_job` and `export_wm_job`; both call sites use it.
- [ ] A fan-out over N targets exports as a single SLURM array job whose task index selects its target
      from the recipe's list.
- [ ] The existing ×3 wall-time safety factor is preserved.
- [ ] `tests/test_job_export.py` passes, extended to cover the array case.
