# Fable 5.1 seed prompt — chart the UI rebuild

Paste everything below the line into a fresh Fable 5.1 session at the repo root.

Prerequisite: `gh` must be installed and authenticated (`winget install --id GitHub.cli`,
then `gh auth login`). Wayfinder writes the map to GitHub Issues on `mitchbradshaw/CNN`.

---

Run `/wayfinder` in **chart mode** for the effort described below. Chart it and stop — do not resolve
any ticket except research tickets, which you should fire as parallel subagents per the skill.

## Read first

Two files, in this order, before you grill me about anything:

1. `docs/agents/UI_CONTEXT.md` — what already exists in this repo, what the interface is *for*, and
   what the rebuild may and may not touch. It separates goals (fixed) from mechanisms (open). It is
   the file every later session on this map will load, so if it is wrong or thin, say so now.
2. `docs/agents/issue-tracker.md`, specifically the **"Wayfinder effort: GitHub Issues"** section at
   the bottom. It carries the wayfinding operations for this repo. Everything above that section
   governs build tickets and code review, not this map — do not follow it here.

Read `docs/PIPELINE_PRD.md` only as `UI_CONTEXT.md` §5.1 directs: Part 2's Problem Statement first,
and treat every passage describing a *surface* as a build that has already been judged, not a
requirement. Do not read `Pipelines/` — §5.2 explains why, and makes surveying it a ticket.

## The effort

The Pipeline GUI's interface is being rebuilt from scratch. The core beneath it — the algorithms,
the type system, the recipe/provenance layer, the database — is staying, untouched. The current
`UI/` tree, 54 Panel/HoloViews modules, is being replaced rather than refactored.

**The stack is genuinely open.** Panel, HoloViews and Bokeh are candidates for replacement, not
givens; so are the plotting approach, the frontend language, and the dependency set. React and other
web frontends are live options, as is inheriting architecture or components from an existing open
source project rather than writing from nothing. Staying on Panel and rebuilding the architecture
above it is also a live option — it should win or lose on evidence, not on inertia. Choosing among
these is work the map does; it is not decided.

**What is not open** is the set of jobs the interface must do. `UI_CONTEXT.md` §3 lists them as G1–G10
— navigating a long recording without downsampling artifacts, composing a chain that reads as a
chain, seeing what each step did, rendering every interchange type, suffix-only recomputation,
telling runs and chains apart, adjudicating without contaminating ground truth, browsing the library
along two axes, exporting for a thesis, saving a chain as a template. Those survive. The *visual
design* does not: the rebuilt interface may end up looking substantially different, and should, if
that serves the jobs better.

## Destination

**A thin vertical slice of the rebuilt interface, running.** One real recording loaded out of the
existing database, one chain composed, one run executed against the untouched `Working/` core, and
every step's output rendered — on whatever stack the map selects.

Not the full rebuild. Not a spec alone. The slice is the destination because a stack chosen on paper
can be wrong in ways only real data reveals: a twelve-hour recording that must zoom without lying,
seven interchange types that must all render, a step cache that must invalidate a suffix rather than
a chain. When that slice runs, the way is clear and the rest is execution.

## Notes for the map body

Put these in the map's `## Notes`, in your own words:

- **Domain:** mycelium bio-electric signal analysis; thesis instrumentation, post-thesis rebuild, no
  deadline. The library is the deliverable.
- **Required reading, every session:** `docs/agents/UI_CONTEXT.md`. Its §4 boundary (frozen / open /
  negotiable / out of scope) binds every ticket.
- **Skills every session should consult:** `grilling` and `domain-modeling` by default;
  `prototype` where the question is how something should look or behave; `research` for anything
  outside this working directory.
- **Standing preferences:** the existing `pytest` suite stays green throughout and the old `UI/` tree
  stays alive until the new one supersedes it — no session deletes or weakens a Panel test to make
  something pass. No package installs or dependency changes without explicit sign-off; a stack
  decision that adds a toolchain is a ticket, not a commit. Whatever boundary the new stack
  introduces, nothing below it may know a browser exists.

## Charting instructions

Grill me to name the destination precisely and then again breadth-first to map the frontier, as the
skill directs. Two things to get right while you do:

**One ticket is required, and I have already decided it exists.** Create a `wayfinder:prototype`
ticket for identifying the visual target from the existing figure corpus. I will bring manually
selected images to that session and we will discuss them there. Its question is roughly: *which
existing figures define what the rebuilt interface should be able to produce, and what do they imply
about rendering, density and layout?* Do not attempt to answer it now and do not survey `Pipelines/`
to prepare for it.

**Fire research tickets generously.** Frontend stack comparison, existing open source projects worth
inheriting from, and plotting libraries capable of multi-hour time-series at interactive zoom are all
questions with real answers outside this repo, and they are the ones the stack decision waits on.
They parallelise; use that.

Beyond those, chart what you can actually see. Areas I can see fog in, offered as raw material rather
than as a ticket list — how the Python core gets exposed to a non-Python frontend, whether the
four-workspace information architecture survives, where the new tree physically lives and how it is
served alongside the old one, what the new tree's test gates are, and whether the frontend reaches
the database through the core or otherwise. Some of those are sharp enough to ticket now and some are
not; you decide which, and leave the rest in **Not yet specified**.

When the map and its tickets exist and the research subagents are away, stop and tell me what the
frontier looks like.
