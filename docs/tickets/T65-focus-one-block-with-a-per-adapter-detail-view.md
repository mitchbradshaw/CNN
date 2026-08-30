---
id: 65
title: "Focus one block, with a per-adapter detail view"
model: opus
size: M
blocked_by: [62]
mutex: [64, 66]
files: ["Adapters/base.py", "UI/analyse/results.py", "tests/test_adapter_spec.py", "tests/test_run_panel.py"]
flags: ['human-verify', 'done']
level: 2
unblocks: 0
budget_minutes: 60
---
# 65 — Focus one block, with a per-adapter detail view

**Model:** [O] · **Size:** [M]

**What to build:** A block can be focused: opened larger, on its own, without losing the chain
around it.

What focus shows depends on the block. For most, it is that step's input and output
at full size through the type renderer. For the SAX blocks it is much more — the
signal, the PAA segmentation, the quantised trace, the cutlines and the symbol
strip — because *that* is where the encoding decision is visible, and the output
symbols alone do not show it.

That richness is **per-adapter knowledge, not per-type knowledge**, so it does not
belong in the type renderer. The adapter spec gains an **optional detail-view hook**:
focus mode uses it when a block declares one and falls back to the type renderer
when it does not. This is the established extension pattern on that spec, which
already carries optional hooks for plotting, estimation, recommendation, derived
readouts and persistence.

**Only the SAX blocks declare one in this ticket.** Every other block shows the type
renderer in focus, and that is the intended end state for this wave rather than a
shortfall — the point of the hook is that adding a rich view for the wavelet block
later is one adapter file and zero UI changes.

The existing SAX encoding panels already exist and are already wired into the run
panel. Route them through the hook; do not rebuild them.

**Blocked by:** 62

**Files/modules touched:** `Adapters/base.py`, `UI/analyse/results.py`, `tests/test_adapter_spec.py`, `tests/test_run_panel.py`.

**Merge risk:** **MEDIUM-HIGH.** Touches the adapter contract, which every adapter reads —
keep the hook optional and defaulted so no existing adapter needs changing.
Mutually exclusive with T64 and T66. The SAX panels are linked views with a shared
x-axis and have broken silently before.

**Acceptance criteria:**
- [ ] The adapter spec carries an optional detail-view hook, defaulting to absent.
- [ ] Every existing adapter continues to load and validate without declaring one.
- [ ] Focusing a block with no hook renders its input and output through the type renderer.
- [ ] Focusing a SAX block renders its signal, PAA, quantised and cutline panels.
- [ ] The SAX panels are reused from the existing implementation, not reimplemented.
- [ ] A headless construction test asserts focus mode returns non-`None` panes for both a hooked and an unhooked block.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
