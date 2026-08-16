# Runner fix — run-20260816-1943 post-mortem

The orchestrator's first real run failed for harness reasons, not ticket reasons. Five defects were
found and fixed on 2026-08-16. This file was originally the prompt that drove that work; it has been
rewritten to record what was actually true, because the original carried a wrong root cause and a
defect 4 that would have re-broken the build.

## What happened

Run `runs/run-20260816-1943`. T01 passed the red-proof gate (the agent did real TDD), then failed the
suite gate with ten collection errors and was quarantined, which put 36 tickets into
`BLOCKED_UPSTREAM`. T01 was greenfield `Working/types/` and could not have broken
`tests/test_filters.py`.

## Root cause — corrected

**The original diagnosis was wrong.** It blamed the `REAL_CHANNEL_PATH` constants declared in
`tests/test_filters.py:40` and nine siblings, on the theory that the missing path raised
`FileNotFoundError` at collection. Those constants are not the mechanism, and one fact falsifies it:
`tests/test_motif_browser.py` was in the failing set and contains **no `DATA/` reference at all**.

The actual mechanism is `UI/app.py:2279`:

```python
create_app().servable(title="Mycelium Signal Viewer")
```

That runs at **module import**. Importing `UI.app` constructs a full `ViewerApp`, which opens the
database, takes `source_files[0]`, and mmaps its `npy_path`. The ten failing files are exactly the ten
that import `UI.app`. Their `_channel_available()` skip guards are correct and never get to run,
because collection never completes.

So the import needs two things, and fails differently depending on which is missing:

| fixture DB | `DATA/derived` junctioned | `import UI.app` |
|---|---|---|
| real copy (as shipped) | no | ❌ `FileNotFoundError` — **this is what happened** |
| real copy | yes | ✅ |
| **empty** | yes | ❌ `RuntimeError: No recordings in the database` |
| empty | no | ❌ `RuntimeError` |

The third row is why the original defect 4 was wrong: an empty fixture re-breaks the same ten files
with a different exception. The fixture must be small but **not empty**.

## The defects

**1. The baseline was measured in the wrong place.** `capture_baseline()` ran `run_suite(git.root,
...)` in the main repo, which has `DATA/derived/`. The gate then compared that against a worktree,
which did not. The comparison was meaningless from the first ticket, and `baseline.txt` was empty, so
all ten collection errors read as T01's regressions.

*Fixed:* the baseline is captured inside a throwaway provisioned worktree via the same `provision()`
path the agents get, then torn down with its branch. Provisioning verification is now automatic on
every run. `--run` refuses to start, with a reason, if the baseline worktree cannot be provisioned or
if its suite fails in a way that names no node ids.

**2. The junction landed in the wrong place.** `worktree.py` did `_junction(path / source.name,
source)`, so a source of `DATA/derived/channels/X` created `<worktree>/X`, where no root-relative path
constant in the suite looks.

*Fixed:* the link preserves the source's path relative to the repo root. A source outside the repo
root is now a `ProvisionError` rather than a guess.

**3. `recordings = []`, so nothing was junctioned at all.**

*Fixed:* `recordings = ["DATA/derived/channels/M2_aug_concat_fs1"]` — 317 MB, against 1.3 GB for all
of `channels/` and 2.3 GB for all of `derived/`. Derived from evidence: that is the only real-data
path any test file references, and it is needed because of `UI/app.py:2279`, not because of the
constants.

**4. The fixture was the real database.** `DATA/fixture/annotations.sqlite` was a byte-identical copy
of `DATA/db/annotations.sqlite`: 2,908,160 bytes, 11,266 annotations, 11,319 tag links.

*Fixed:* rebuilt as 126,976 bytes — schema-current from `init_db()`, 16 recording rows for the
junctioned channels, **zero** annotations. Rebuilt by `python -m orchestrator.make_fixture`, which is
also the definition of what the fixture contains. `DATA/` is gitignored, so the rebuild had to be
reproducible rather than a one-off command.

**5. Teardown would have destroyed the junctioned data.** Not in the original list — found by writing
the safety test first, exactly as intended.

`teardown()` carried the right comment ("Junctions must be unlinked before the tree is removed, or a
recursive delete walks into the shared read-only recordings and deletes those too") but only iterated
the worktree's **immediate children**. A repo-root-relative junction sits four levels down at
`DATA/derived/channels/M2_aug_concat_fs1`, so it was never found. The first ticket teardown of the
night would have deleted 317 MB of real channel data.

The test provisioned a worktree junctioned to a scratch directory holding a sentinel file, tore it
down, and asserted the sentinel survived. It failed by deleting the sentinel.

*Fixed:* teardown walks the tree, checking for a reparse point **before** recursing — `os.walk`
descends through Windows junctions even with `followlinks=False`, which is the traversal the check
exists to prevent.

## Recorded tradeoff

Junctioning real channel data means an agent can reach and **write to**
`DATA/derived/channels/M2_aug_concat_fs1`. The database stays protected; the signal data does not.
Accepted because everything under `derived/` is regenerable from `raw/` plus code, and because
`M2_aug_concat_fs1` is held-out-safe (`M4` is the locked one). Recorded in
`docs/ORCHESTRATOR_SPEC.md §Isolation` and inline in `config.toml`. Widening `recordings` re-opens the
decision and should be argued again, not inherited.

## Verification

- Orchestrator suite: **239 passed** (228 before, plus 11 added; no regressions).
- `python -m orchestrator.run --plan` renders the wave plan and dispatches nothing.
- Baseline capture alone: **green in 348s, measured inside a provisioned worktree**. Afterwards no
  `T00` worktree, no `baseline/` branch, 317 MB and 16 files intact, real DB still 2,908,160 bytes.
- The provisioning acceptance test asserts `import UI.app` succeeds inside a freshly provisioned
  worktree — the tightest statement of "this worktree is usable", ~19s against the suite gate's four
  minutes. Verified against a negative control: `rc=1` without the junction, `rc=0` with it.

## Left open

`UI/app.py:2279` is an architectural defect in application code, out of scope for the harness work and
recorded in `FOLLOWUPS.md` for triage into a ticket. Moving the `create_app().servable(...)` call
behind a `__main__` guard or into a `serve.py` entry point would let the ten files' real-data gating
become a plain module-level skip, and would let `recordings` be emptied again — closing the tradeoff
above rather than merely recording it. It is very likely also why `tests/_session_isolation.py` had to
exist.

## Cleanup still pending

Nothing merged and `main` is untouched. `integration/run-20260816-1943` is at the same commit as
`main` (`7d90a42`), so it holds nothing. The worktrees under `../.wt/`, the `ticket/T01..T03`
branches, and the integration branch were all left in place pending confirmation;
`runs/run-20260816-1943/` stays on disk as the record. `ticket/T01` in particular holds a commit that
genuinely passed the red-proof gate.
