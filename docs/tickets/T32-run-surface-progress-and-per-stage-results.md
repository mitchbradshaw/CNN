---
id: 32
title: "Run surface: progress and per-stage results"
model: opus
size: M
blocked_by: [24, 31]
mutex: [29, 31, 34, 44]
files: ["UI/workspaces/analyse/run_surface.py"]
flags: ['human-verify', 'done']
level: 9
unblocks: 3
budget_minutes: 60
---
# 32 — Run surface: progress and per-stage results

**Model:** [O] · **Size:** [M]

**What to build:** a slow run is visibly distinguishable from a hung one, and an early stage is
inspectable before the chain finishes.

**Blocked by:** 24, 31

**Files/modules touched:** `UI/workspaces/analyse/run_surface.py` (same file as 31 — sequential).

**Merge risk:** **HIGH if parallel with 31.** Sequence strictly.

**Why [O] and why a person looks:** per-stage results arriving into a live pane is exactly the dynamic
map pattern that fails silently in this codebase.

**Acceptance criteria:**
- [ ] A progress indicator with an estimated finish appears once the predicted runtime exceeds the
      configured threshold, and not before.
- [ ] Adapters driving the finer `run_kwargs["on_progress"]` callback additionally show intra-step
      progress; adapters that do not still show step-level progress.
- [ ] Each stage's result renders as it lands, and an earlier stage stays inspectable while a later one
      is still running.
- [ ] A person runs a real multi-stage chain and confirms no pane blanks as results arrive.
