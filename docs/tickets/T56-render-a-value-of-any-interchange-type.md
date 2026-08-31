---
id: 56
title: "Render a value of any interchange type"
model: sonnet
size: M
blocked_by: []
mutex: []
files: ["UI/plots.py", "tests/test_value_rendering.py"]
flags: ['done']
level: 0
unblocks: 3
budget_minutes: 60
---
# 56 — Render a value of any interchange type

**Model:** [S] · **Size:** [M]

**What to build:** One function that turns any value the pipeline produces into something
renderable, given its interchange type, the value, and the adapter's metadata.

There are seven interchange types — Signal, Encoding, Scores, SpanSet, WindowSet,
Grouping, Model — and every plot-centric surface in this wave needs to draw all of
them. Today only Signal and Encoding have renderers, both wired specifically into
the run panel.

    Signal    -> a curve against time
    Encoding  -> a symbol strip
    Scores    -> a series against time
    SpanSet   -> an interval overlay
    WindowSet -> a window index
    Grouping  -> a cluster-size summary
    Model     -> a text card

**Model gets a text card on purpose.** A trained model has no natural plot, and
inventing one produces a decorative lie — a picture that looks like evidence and
is not. State what the model is; do not chart it.

**This is the single entry point.** Nothing downstream may switch on a value's type
locally. That rule is the whole reason this is its own ticket: the alternative is
each surface handling the two types its author happened to test and rendering
nothing for the rest, and a pane that renders nothing does not raise — it is blank,
and it looks exactly like a feature that was never built. This codebase has shipped
that failure twice.

Every type must return something renderable and non-empty, including for a degenerate
value (an empty SpanSet, a one-window WindowSet). Returning `None` is never correct.

**Blocked by:** nothing — can start immediately

**Files/modules touched:** `UI/plots.py`, `tests/test_value_rendering.py`.

**Merge risk:** **MEDIUM.** `UI/plots.py` is shared and large. Add beside the existing builders,
matching their contract — this module imports no Panel and touches no database, and
that must stay true. Reuse the existing curve and symbol-strip builders for Signal
and Encoding rather than writing second ones.

**Acceptance criteria:**
- [ ] One function accepts an interchange type, a value and adapter metadata, and returns a renderable element.
- [ ] All seven interchange types return a non-`None`, non-empty element.
- [ ] A degenerate value of each type still returns something renderable rather than `None`.
- [ ] An unknown type name raises with a message naming the value it was given.
- [ ] A test exercises every one of the seven types directly, with no browser and no database.
- [ ] `UI/plots.py` still imports no Panel and reads no database.

**Notes:** Blocks T62 and, through it, the whole filmstrip. It is on the **never cut**
list in the PRD: without it, half of every plot-centric surface is blank.

**Spec:** `docs/PIPELINE_PRD.md` **Part 2 — The Usability Wave**. Read the subsection relevant to this ticket; a Part 1
passage carrying a `[SUPERSEDED by Part 2]` marker no longer applies, and one
without a marker still does.
