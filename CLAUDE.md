# CLAUDE.md — Underground Brains / Pipeline GUI

Repo context loaded for **every** agent working a ticket. This file carries what is true for all
tickets. Your ticket file carries what is unique to yours. If the two disagree, the ticket wins for
scope; this file wins for standards.

## What this repo is

A Panel/HoloViews application for analysing fungal bio-electric recordings, plus the UI-free core
underneath it. It is thesis instrumentation on a hard deadline: **feature freeze 28 August 2026**.

The work in progress is the Pipeline GUI, specified in `docs/PIPELINE_PRD.md` — the authority on what
is being built and why. Read the section relevant to your ticket; do not read the whole thing.

That file now holds **two parts**. Part 1 specifies the pipeline itself (tickets T01–T49, all merged
bar T49). **Part 2 — The Usability Wave** specifies the Analyse/Library rework (T50+) and supersedes
Part 1 wherever a Part 1 passage carries a `[SUPERSEDED by Part 2]` marker. If your ticket is T50 or
above, read Part 2's section for your ticket **and** any Part 1 passage it points you at — and treat
an unmarked Part 1 passage as still authoritative. The trap this is guarding against is real: Part 1
describes the chain builder as a vertical staged list, which is exactly what Part 2 replaces.

## Layout

| Path | What lives there |
|---|---|
| `Working/` | The UI-free core: config, execution, recipes, database, detection, catalogue, HPC |
| `Working/database/` | Plain-SQL layer. `schema.py` holds the whole schema and its migrations |
| `Adapters/` | The analysis block registry. `base.py` is the adapter contract |
| `webui/` | **The web UI** (ADR `docs/adr/0001-web-ui-stack.md`): `client/` React + TypeScript + Vite, `server/` FastAPI bridge over the untouched core, `run_server.py`, `start.ps1`/`start.sh`, `smoke.py`. See "Web UI" below |
| `UI/` | **Legacy** Panel/HoloViews app. Frozen, kept importable and green, not developed. Nothing in `webui/` may import it |
| `ui-prototypes/` | Frozen evidence archive of the stack prototypes (`REPORT.md` is the decision evidence). Not maintained; B no longer runs |
| `tests/` | pytest, headless. The default gate; `pytest.ini` excludes `-m ui` from it |
| `tests/ui/` | **Legacy** browser-driven Panel tests (`pytest -m ui`). See `docs/UI_VERIFICATION.md` |
| `scripts/` | Dev tooling, not imported by the app. `dev_serve.py` serves the **legacy** Panel UI off a throwaway database |
| `docs/` | PRD, coding standards, ticket backlog, `UI_VERIFICATION.md` |
| `DATA/`, `MODELS/`, `MATRICES/`, `Plots/` | Gitignored. Provisioned into your worktree, not committed |
| `DATA/library_seed/` | The **exception**: tracked on purpose. Irreplaceable inputs to the library importer — its generator was deleted. See its `PROVENANCE.md` |

## The rules that are not negotiable

1. **UI libraries stay in the UI trees.** Panel, HoloViews, Bokeh and matplotlib may be imported only
   under the legacy `UI/`; React, d3 and every other browser library live only in `webui/client/`;
   FastAPI/uvicorn only in `webui/server/` and `webui/run_server.py` (which import none of the Panel
   family either). `Working/`, `Adapters/` and `Pipelines/` import none of them and must never know a
   browser exists. This is what makes cluster execution, headless tests and the reproducibility claim
   possible. The Panel-family rule is enforced by a test.
2. **The suite must pass with no regressions.** `pytest` from your worktree root: 1049 tests as of
   2026-08-31, about six minutes serial (`pytest -n auto` — needs `pytest-xdist`, see Environment —
   cuts this to about five; most of the wall-clock is Panel/HoloViews/numpy/aeon import cost paid
   per worker, so the speedup is real but not linear in core count). Do not chase a fixed number —
   every merged ticket adds tests, so the gate is "nothing that passed before now fails", not "N
   tests pass". If your change breaks one, either your change is wrong or the test encodes a
   behaviour your ticket is deliberately changing — and if it is the latter, say so explicitly in
   your commit message. For a change scoped to one module, running just its matching
   `tests/test_<module>.py` first (seconds, not minutes) is the faster feedback loop — the full
   suite is still the actual gate before calling anything done, especially for a change to
   widely-shared code (`Working/config.py`, `execution.py`, the DB schema).
3. **Plain SQL, no ORM.** Schema changes are additive and applied through `init_db()`, which must stay
   idempotent.
4. **Bulk arrays never enter the database.** They live on disk, referenced by path.
5. **Detections are machine-only; annotations are human-only.** They are separate tables on purpose.
   No code path may write a human verdict into a machine row or the reverse.

## Working a ticket

**Test-first, and it is verified rather than trusted.** Your first commit must touch only `tests/` and
must contain a test that *fails*. The orchestrator checks out that commit and runs the test to confirm
it is red. A ticket whose first test passes on arrival is quarantined before implementation begins,
because a test that never failed asserts nothing.

The loop, per seam: write the failing test → make it pass with the simplest change → refactor → commit.

**Stay inside your declared file list.** Your ticket names the files/modules it expects to touch.
Editing something outside that list is not forbidden, but every out-of-scope file is reported and
handed to the reviewer to justify. If you find yourself needing to change a file another ticket owns,
that is a signal to stop and say so, not to change it.

**Commit messages** start with your ticket id: `T14: bind side-inputs by content, not row id`.

**Do not read other tickets.** You have the one you were given. Reading neighbours produces scope
creep and duplicate implementations of the same helper.

**Prefer importing an existing helper to writing a second one.** Before adding a utility, grep for it.
Your ticket's merge-risk field names the siblings most likely to already own what you are about to
write.

## Environment

Windows, PowerShell, conda. The environment is shared across worktrees — **do not install packages or
change dependencies.** A ticket that genuinely needs a new dependency should stop and report it.
`pytest-xdist` (`pytest -n auto`) was added 2026-08-31 with the user's explicit sign-off for this
reason — it is now available, not an example to follow silently for the next dependency.
`pytest-playwright` plus a chromium binary (`python -m playwright install chromium`) was added the
same day, on the same sign-off, for the browser suite in `tests/ui/`. Both are dev tooling: nothing
under `UI/`, `Working/`, `Adapters/` or `Pipelines/` may import either, and the headless suite must
keep passing on a machine where neither is present.

The web UI adds a second toolchain, signed off with the stack choice on 2026-09-15 (ADR 0001): Node + npm
for `webui/client` (project-local `node_modules`, never `npm -g`) and a project-local `webui/.venv` for
FastAPI/uvicorn. Neither touches the conda environment.

Run tests with `pytest` from your worktree root. Your worktree has its own `DATA/` fixture database;
it is not the real one and you cannot reach the real one. That is deliberate.

## Web UI (`webui/`)

**Start it** (from the repo root, in the main checkout — it needs `DATA/db/annotations.sqlite`):

    webui\start.ps1            # builds the client once, serves http://127.0.0.1:8765
    webui\start.ps1 -Dev       # bridge on 8765 + Vite dev server with HMR on 5173

(`webui/start.sh [port]` from Git Bash.) The first start creates `webui/.venv` (`--system-site-packages`,
fastapi + uvicorn) and runs `npm install` in `webui/client`; both are project-local and gitignored. The
bridge copies the database into `webui/runtime/<stamp>/` and redirects `STEP_CACHE_ROOT`, both adapter
`RESULTS_DIR`s and the classifier `MODEL_ROOT` there before any run, refuses to start if one escapes, and
refuses a busy port. `M4_aug_concat_fs1.mat` is refused on every route. **Never point it, pytest or an
adapter at a junction to the real `DATA/`.**

**The UI gate.** A change under `webui/` is done when all three pass:

1. `npx tsc -b` in `webui/client` (type-check) and `npm run build` (production build);
2. `"/c/ProgramData/anaconda3/python.exe" webui/smoke.py --url http://127.0.0.1:8765` against a running
   bridge — Playwright via the conda python; it fails on any browser console or page error, any pane that
   did not paint, any unexpected server traceback, and a broken core flow, and writes screenshots to
   `webui/screenshots/`;
3. the headless `pytest` suite, if the change touched anything Python outside `webui/`.

Loud failure is structural here: a render error is a red card plus a console error; a server error is a
500 with the traceback. Keep it that way — never catch an error into a blank.

## Panel surfaces (legacy `UI/` only)

`UI/` is frozen and no longer developed; this section applies only if a ticket must touch it.
If your ticket renders a Panel surface, know the failure mode this codebase has hit twice: a broken
dynamic map renders as a **silently blank pane**, not an error. Tests pass, review passes, the feature
is missing. Your acceptance criteria therefore include a headless construction test asserting the
surface returns the expected panes with non-`None` objects. Follow the pattern already in
`tests/test_run_panel.py`, `tests/test_motif_browser.py` and `tests/test_ribbon_panes.py`.

**That is necessary and not sufficient, and since 2026-08-31 it is no longer the whole gate.** A
construction test catches an *absent* pane. It cannot catch a *present* pane that throws in the
browser — which is what actually happened both times — and it cannot see layout, overlap, or whether
the surface is usable. `tests/ui/` drives a real browser against a real Panel server and fails on any
JS error; `pytest -m ui` runs it. **`pytest` alone does NOT run it** (`pytest.ini` excludes the `ui`
marker so the fast loop stays fast), so a green `pytest` is not evidence your surface renders.

A ticket that touches `UI/` is done when: the headless suite passes, `pytest -m ui` passes, and your
report names the screenshots in `runs/ui-screenshots/` a reviewer should look at. **Read
`docs/UI_VERIFICATION.md` before you start** — it covers the setup, `scripts/dev_serve.py` (a browser
you can point at the app, backed by a throwaway copy of the database), the two browser MCP servers in
`.mcp.json`, and three non-obvious findings about what selectors actually work against Panel 1.9
(Bokeh renders into shadow DOM; Panel checkboxes have no accessible label; how to assert a pane
actually painted).

If `pytest -m ui` reports "no tests ran", the browser tooling is not installed on this machine — that
is a missing setup step, not a pass. Stop and report it.

## When to stop

Stop and report rather than guessing if: the ticket contradicts the PRD; a blocking ticket's work is
not present in your base; you need a file another ticket owns; you need a new dependency; or you have
been round-tripping the same failing test for more than a third of your time budget.
