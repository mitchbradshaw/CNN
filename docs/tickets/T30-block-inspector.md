---
id: 30
title: "Block inspector"
model: opus
size: L
blocked_by: [14, 29]
mutex: [14, 29, 34, 47]
files: ["UI/workspaces/analyse/inspector.py"]
flags: ['human-verify', 'done']
level: 5
unblocks: 1
budget_minutes: 120
---
# 30 — Block inspector

**Model:** [O] · **Size:** [L] — **kept large deliberately**

**What to build:** open one step and see its parameters, its recommended defaults for the current span,
its live derived readouts, its side-input bindings, and its cached result — and retune it without
rerunning the chain.

**Blocked by:** 14, 29

**Files/modules touched:** new `UI/workspaces/analyse/inspector.py`; reads the extracted parameter-UI
generation, `_apply_recommended_defaults`, `_refresh_derived`, `_on_param_widget_changed` and
`_widget_for_param` from ticket 17's split; reads the ticket 15 cache.

**Merge risk:** **MEDIUM vs 29** (same workspace, adjacent state) and **MEDIUM vs 14** — the
side-input picker must emit exactly ticket 14's binding structure, not a parallel one. **MEDIUM vs 47**,
which reuses the picker for rebind prompts.

**Why it stays `[L]`:** this slice spans the parameter-spec system, generated UI, span-aware
recommendation, live derived readouts, cache reads and binding resolution. Splitting it yields a
parameter form with no results, or results with no controls — neither demos anything, and neither can
be reviewed against a spec. Give it one full session with a person present. If it must shrink, the only
clean cut is deferring the side-input picker to a follow-up blocked by this ticket, since seeded search
is the only chain that needs it — but that defers the seeded-search research question, so prefer not to.

**Acceptance criteria:**
- [ ] Opening a step shows controls generated from its `ParamSpec` list, with the existing widget
      mapping preserved for int, float, str, bool, choices and min/max.
- [ ] `recommend` is applied for the currently selected span, and re-applied when the span changes.
- [ ] `derive` readouts recompute live as parameters change, without running anything, with the
      existing `""` / `"warn"` / `"error"` severity styling.
- [ ] Side-input pickers appear for each declared `side_inputs` entry, offering only sources of the
      declared type, and emit ticket 14's binding structure.
- [ ] That step's cached result from ticket 15 is displayed when present, labelled as cached.
- [ ] Changing a parameter and rerunning reuses every earlier step — verified by a person watching the
      run complete in cache-hit time, and by ticket 15's artifact-identity test underneath.
- [ ] The existing SAX `recommend`/`derive` behaviour is unchanged; `tests/test_sax_details.py` passes.
