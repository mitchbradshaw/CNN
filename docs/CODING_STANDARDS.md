# Coding standards — Underground Brains

This document is the authority for the **Standards axis** of `code-review-two-axis`. Without it that
axis falls back to Fowler's smell catalogue, which the skill itself labels "judgement calls, not hard
violations" — and judgement calls make bad unattended merge gates.

Rules are graded. **`blocker`** stops a merge. **`major`** and **`minor`** are recorded in
`FOLLOWUPS.md` and merged anyway. A reviewer must cite the rule number.

Where a rule is marked **[test]**, it is enforced mechanically and the reviewer should not raise it —
a failing test is a better gate than a comment.

---

## 1. Architectural boundaries

**1.1 — `blocker` [test].** No module outside `UI/` may import `panel`, `holoviews`, `bokeh` or
`matplotlib`, at module scope or inside a function. This is the load-bearing rule of the codebase: it
is what allows the core to run on the cluster, under pytest, and without a display.

**1.2 — `blocker`.** `UI/` modules may call into `Working/` and `Adapters/`. Nothing in `Working/` or
`Adapters/` may import from `UI/`. Dependencies point one way.

**1.3 — `major`.** A module gains behaviour, not breadth. A new capability that fits an existing
module's purpose goes in that module; a new capability that does not gets a new module. "Utils" is not
a purpose.

**1.4 — `blocker`.** Ownership declared in a ticket is real. If ticket N declares itself the owner of
a schema, a helper or a computation, every other ticket imports it and none reimplements it. The
specific single-owner rules for this backlog are listed in `docs/tickets/README.md`.

## 2. Database

**2.1 — `blocker` [test].** `init_db()` is idempotent. Calling it twice against a populated database
leaves every row count and every tag link identical.

**2.2 — `blocker`.** Schema changes are additive: new tables, new nullable columns, new views. The one
exception in this backlog is the verdict-constraint rebuild (ticket 04), which is human-gated
precisely because it is not additive.

**2.3 — `blocker`.** Plain SQL through the existing query layer. No ORM, no query builder, no new
database dependency — nothing in this layer may require a package the cluster does not have.

**2.4 — `blocker`.** No bulk array enters the database. Arrays live on disk; the database stores paths.

**2.5 — `blocker`.** Human and machine judgement stay physically separate. `annotations` is written
only by a human action. `detections` and `adjudications` are written only by machine or by
adjudication of a machine row. No code path crosses this, and no "origin" column is introduced to
paper over it.

**2.6 — `major`.** Any destructive migration backs up the database file first, to a path recorded in
its output.

## 3. The type system and adapters

**3.1 — `blocker`.** The seven interchange types are `Signal`, `SpanSet`, `WindowSet`, `Encoding`,
`Grouping`, `Model`, `Scores`. An eighth is not added. A method that fits none of them is out of scope.

**3.2 — `blocker`.** `Scores` is time-aligned — one value per timepoint. A per-window feature table is
not `Scores`; it rides as attached features on a `WindowSet`. Conflating them breaks generic
thresholding.

**3.3 — `blocker`.** After ticket 05, `Adapters/base.py` and `Adapters/registry.py` are frozen. Only
ticket 10 unfreezes them. An adapter ticket that edits `base.py` is a review blocker regardless of how
reasonable the edit looks.

**3.4 — `major`.** A new technique is one adapter file declaring its types, parameters and run
function. If adding a technique requires touching the application, the contract has been violated.

## 4. Tests

**4.1 — `blocker`.** Tests are headless. No browser driver, no screenshot diffing, no display.

**4.2 — `blocker`.** A test asserts external behaviour a research claim depends on — that a recipe
reproduces, that a cache resumes, that a lagged pair classifies as an artifact. A test that asserts a
particular function was called is not a test, it is a transcription of the implementation.

**4.3 — `blocker`.** Tests do not depend on execution order and do not share mutable global state.
`tests/_session_isolation.py` exists because this rule was broken once and cost two test files. Any
test constructing a `ViewerApp` uses `scratch_session_file()`.

**4.4 — `blocker`.** Prefer the three existing seams over inventing a fourth: the headless recipe
executor, the recipe hashing layer, and `init_db()`. New coverage extends the existing test files for
those seams rather than starting a parallel suite.

**4.5 — `blocker` [test].** A ticket rendering a Panel surface includes a headless construction test
asserting the surface returns its expected panes with non-`None` objects. A blank pane must fail a
test, not a review.

**4.6 — `major`.** Determinism: anything stochastic takes an explicit seed, and the seed enters the
recipe hash.

## 5. Reproducibility

**5.1 — `blocker`.** Anything that affects a result enters the recipe hash — parameters, ordering,
side-input bindings, seeds.

**5.2 — `blocker`.** Side-inputs are hashed by **content** (source file, channel, sample range), not by
database row id. Local identifiers are not portable; content is.

**5.3 — `major`.** One manifest schema serves import, export and reproducibility. A second serialiser
for the same object is a blocker, not a convenience.

## 6. Style

**6.1 — `major`.** Names say what a thing is for. `Working/database/similarity.py` computes interval
IoU for duplicate-annotation warnings — it is not shape distance, and shape distance does not go in it.

**6.2 — `minor`.** No speculative generality. Do not add a parameter, an abstraction or an extension
point for a use case that is out of scope in the PRD. Fourteen days.

**6.3 — `minor`.** Comments explain why, not what. A comment restating the line above it is noise.

**6.4 — `major`.** Duplicated logic across modules is a blocker at the merge boundary, not a style
nit — see the overlap check in `docs/ORCHESTRATOR_SPEC.md`.

## 7. Scope

**7.1 — `major`.** Behaviour the ticket did not ask for is scope creep, even if it is an improvement.
Report it; do not build it.

**7.2 — `blocker`.** The cut list is decided in advance and recorded in the PRD. A ticket does not
quietly implement something the PRD lists as out of scope.
