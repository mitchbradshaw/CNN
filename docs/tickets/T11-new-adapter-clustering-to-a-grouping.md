---
id: 11
title: "New adapter: clustering to a Grouping"
model: opus
size: M
blocked_by: [5, 7]
mutex: [5, 12]
files: ["Adapters/catalogue_cluster.py", "Working/Catalogue/dendrogram/dendrogram_cluster.py", "tests/test_grouping_adapter.py"]
flags: []
level: 3
unblocks: 2
budget_minutes: 60
---
# 11 — New adapter: clustering to a Grouping

**Model:** [O] · **Size:** [M]

**What to build:** a block that takes a `WindowSet` and produces a `Grouping` — the missing link
between the window matrix and a label set, without which RQ1's chain cannot be composed at all.

**Blocked by:** 05, 07

**Files/modules touched:** new `Adapters/catalogue_cluster.py`; reads
`Working/Catalogue/dendrogram/dendrogram_cluster.py` (not modified); new `tests/test_grouping_adapter.py`.

**Merge risk:** **MEDIUM vs ticket 12** — both are new adapters on the same chain segment and will each
be tempted to write a window-set-to-feature-matrix helper. This ticket owns it; 12 imports it.
**Do not edit `Adapters/base.py`** or `dendrogram_cluster.py` (121KB, and not this ticket's blast radius).

**Why [O] and why this ticket exists:** no adapter in the repository produces a `Grouping`. The PRD's
build order says "remapping the twenty adapters", which reads as though the block set is complete —
it is not. `dendrogram_cluster.py` exists as a `Working/` module with no adapter, so the typed chain
from signal through window set and grouping to a model, which the PRD names as what RQ1 needs, is
currently unbuildable. The judgement here is which of that module's many entry points to expose and
which linkage/k parameters to surface, and the thesis plan records that linkage and k are unresolved —
so the adapter must expose them as parameters rather than bake in a choice.

**Acceptance criteria:**
- [ ] A registered adapter declares `input_kind="WindowSet"`, `output_kind="Grouping"`.
- [ ] Linkage and cluster count are `ParamSpec` parameters, not hardcoded — the selection criterion is
      an open research decision and must stay tunable from the block inspector.
- [ ] The adapter exposes a `derive` readout showing the resulting cluster sizes for the current
      parameters, so the effect of changing k is legible before running.
- [ ] A `Grouping` produced from a synthetic window set with three obvious clusters recovers three
      groups, asserted by group membership rather than by silhouette score.
- [ ] The `Grouping` round-trips to disk and back unchanged.
- [ ] `dendrogram_cluster.py` is unmodified.
