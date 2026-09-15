# Overnight brief: land the web UI on main, close the map, then build out every page

I'm asleep while you work. You're fully autonomous: make every call yourself with your best reasoning, log each
one in a decisions file, and never stop to ask. Where this brief states a default, follow it unless you
find evidence against it. If you override a default, write down why.

There are two tasks, in order. **Task 2 is the important one.** Task 1 should be done cleanly and
quickly so Task 2 gets most of the night.

## Context you need

- **The stack is chosen.** Prototype A is React 19 + TypeScript + Vite + d3 scales with hand-written SVG,
  over a FastAPI bridge to the untouched core. It lives on branch `proto/ui-stack-slices`
  (worktree `C:/Users/mmebr/Documents/CNN-ui-proto`) under `ui-prototypes/A-react-fastapi/`.
  - Read `ui-prototypes/REPORT.md` first: §1, §3 (A), §5, §7 and §8.
  - Then `ui-prototypes/DECISIONS.md`.
  - Prototype B (Panel) lost. I chose A.
- The map is issue #4, "Map: rebuild the Pipeline GUI interface on a stack chosen by evidence".
  - Its destination (a thin vertical slice running on the selected stack) has been reached by A.
  - Its open children are #10, #11, #12, #13, #14 and #15.
  - Follow the `wayfinder` skill, and `docs/agents/issue-tracker.md` → "Wayfinding operations", for how this repo records resolutions.
- **The design target** is the concept pages. Read these three files first:
  - `prototyping/imgs/INDEX.md`: 96 single-page PDFs, one per frame, by workspace.
  - `prototyping/UI_FUNCTIONAL_SPEC.md`: the behaviour spec. §0 is the placeholder canon, §2 the workspaces, §3 the shared conventions, §11 the open items.
  - `prototyping/UI_REVIEW_BACKLOG.md`.
  - You can view a PDF frame with the Read tool.
  - The `.pen` files are the source of truth, but the PDFs are sufficient. Don't edit anything in `prototyping/`.

## Ground rules (binding for both tasks)

1. **Core untouched.** Don't edit `Working/`, `Adapters/` or `Pipelines/`, and don't change the repo-root dependency files. Bridge gaps inside the web UI's own server layer.
2. **Never touch real data.**
   - The main checkout's `DATA/` is the real data. The web UI must keep running against a DB copy with every writable path redirected, as A's `server/runtime.py` already does.
   - No mock or UI write may reach any database: not the copy, not the real one. The one exception is behaviour A already had.
   - `M4_aug_concat_fs1.mat` stays held out and refused.
   - Record the mtimes of `DATA/db/*.sqlite` and `DATA/derived/` at the start and at the end. `ui-prototypes/check_data_untouched.sh` is the pattern.
   - **Never create a junction to `DATA/`, and never run pytest or adapters through one.** Last time that wrote into the real data.
   - Delete nothing under `DATA/`.
3. **No shared-environment changes.** No installs into `C:\ProgramData\anaconda3`, no `npm -g`, no system installs.
   - Project-local installs inside the web UI tree are allowed: `node_modules`, and a `.venv` created with `--system-site-packages`. My choice of A is the sign-off for that toolchain.
   - Prefer no new npm dependencies: the bespoke design was reproduced faithfully by hand, and a component kit would fight it. Any dependency you do add goes in the decisions file with its reason.
4. **Work in the main checkout** `C:/Users/mmebr/Documents/CNN`. Don't use `isolation: "worktree"` for subagents, because a fresh worktree has no `DATA/` and the web UI can't start.
   - Another session may be editing `prototyping/`. Never stage, commit, revert or stash changes there that you didn't make.
5. **Commits.**
   - Prefix Task 1 commits with `webui:` and Task 2 commits with `webui-pages:`.
   - Commit after every meaningful step. In Task 2 that means at least once per page.
   - Push `main` to `origin` at the two points marked **[push]** below, and nowhere else. No PRs, no force-pushes.
6. **Tracker writes are limited to:**
   - resolution or carry-forward comments on #10–#15 and #4;
   - closing #10–#15 and #4;
   - editing #4's body.
   - Create no new issues, and don't touch any other issue.
7. **Suite.**
   - pytest is the gate for "nothing that passed before now fails". The baseline is `ui-prototypes/pytest_result.txt`: 1,296 passed and 41 failures that already existed on main (the `LibraryGrid(conn)` mismatch plus Windows file locks).
   - Compare failure *sets*, not counts.
   - Run pytest so it cannot write into the real `DATA/`. Work out from `Working/config.py` and the tests which roots they write: the step cache, `MODEL_ROOT`, encodings.
     - Prefer running the suite in a temporary worktree whose `DATA/` is a **real copy** of only what the tests read.
     - If that copy would exceed ~2 GB, run in the main checkout and inventory every file under `DATA/` newer than the start snapshot, deleting nothing.
8. **Stop every server you started before you finish.**
   - Never kill a process you didn't start. If a default port is busy, use another one and say so.
   - Last night I left prototype servers running on 8765 and 8766.

## Task 1: land A on main, retire the old tree, close the map

**1a. Merge.**
- Run `git merge --ff-only proto/ui-stack-slices` in the main checkout. `main` hasn't moved since the branch was cut, and every change is under `ui-prototypes/`.
- If fast-forward fails, do a normal merge and resolve it with the `resolving-merge-conflicts` skill.

**1b. Promote A into the product tree.**
- **Default:** `git mv ui-prototypes/A-react-fastapi webui`, so the tree is `webui/server`, `webui/client`, `webui/run_server.py`, the start scripts and `webui/smoke.py`.
- Fix everything that assumed the old location or the old worktree root: `runtime.py`'s repo-root detection, the start scripts, `smoke.py`, `.gitignore`, and any absolute path.
- Recreate `webui/.venv`, run `npm install` and a build, then run `webui/smoke.py` until it's green against a DB copy in the main checkout.
- Leave B, the reports and the screenshots in `ui-prototypes/` as a frozen evidence archive. Add a short `ui-prototypes/README.md` saying:
  - A moved to `webui/`;
  - B imports A's old path and is no longer expected to run;
  - `REPORT.md` is the decision evidence.
- Delete `ui-prototypes/NEXT_SESSION_PROMPT.md` (this file) from the tree. Git history keeps it.

**1c. The old Panel UI (`UI/`).** I'm not going to use it again.
- **Delete it only if that is trivial.** "Trivial" means both of these hold:
  - Nothing outside `UI/`, `tests/`, `scripts/dev_serve.py`, `docs/UI_VERIFICATION.md` and `Experimentation/` needs it.
  - Removing the UI-importing tests loses no assertion about the core.
- **What I found:**
  - 38 test files import `UI`, including `tests/_session_isolation.py` and tests that look core-relevant: `test_heldout_lock.py`, `test_manifest.py`, `test_export.py` and `test_chain_state.py`.
  - A stale snapshot under `Working/Detection/sax/dsax_python/UI_snapshot_20260810-0512/` also imports it.
  - So I expect this to be **not trivial**. Verify that quickly, spending no more than ~20 minutes on the assessment.
- **If not trivial:** leave `UI/`, its tests and `tests/ui/` exactly as they are. The old app stays intact but ignored.
- **If trivial:**
  - First tag the pre-deletion commit `archive/panel-ui` so the reference implementation stays one checkout away.
  - Then delete `UI/`, `tests/ui/`, the UI-only tests, `scripts/dev_serve.py`, `docs/UI_VERIFICATION.md` and the `ui` marker in `pytest.ini`.
  - Keep the test that forbids Panel, HoloViews, Bokeh and matplotlib imports below the UI layer.
- **Either way:** nothing in `webui/` may import `UI/`.
- **Then update `CLAUDE.md`:**
  - the layout table (`webui/`, `ui-prototypes/` as the archive);
  - which trees may import UI libraries;
  - the new UI gate (`webui/smoke.py` plus a type-check and build);
  - how to start the web UI;
  - a Panel-surfaces section that is either removed or marked legacy, matching what you did to `UI/`.

**1d. Gates, then remove the old worktree and branch.**
- Run the suite (rule 7) and the web UI smoke. Both must pass.
- Then remove the old worktree safely. Its `DATA` is a **junction to the real `DATA/`**:
  1. Remove only the link: `cmd /c rmdir "C:\Users\mmebr\Documents\CNN-ui-proto\DATA"`, with no `/s`.
  2. Confirm `C:\Users\mmebr\Documents\CNN\DATA\db\annotations.sqlite` still exists with its mtime unchanged.
  3. Run `git worktree remove --force C:/Users/mmebr/Documents/CNN-ui-proto`.
  4. Run `git branch -d proto/ui-stack-slices`.
- If files are locked because a server I left running holds them, don't kill it. Skip the removal and log it for me.
- Leave every other branch and worktree alone. **[push]**

**1e. Close the map.**
- **#12, "Select the stack for the rebuilt interface":**
  - Write an ADR using the `domain-modeling` skill's format in `docs/adr/`. It covers:
    - the stack;
    - the plotting approach, including the canvas escape hatch for dense plots from REPORT §8;
    - that nothing is inherited, and which ideas were;
    - the toolchain consequence;
    - the runner-up (B) and why it lost.
  - Post the resolution comment linking the ADR and REPORT, then close the issue.
- **#14 (where the new tree lives) and #15 (the new tree's test gates):** Task 1 answered both. Post resolution comments saying what was done and what remains open, then close them.
- **#13 (how the frontend reaches the core):**
  - Resolve the part A's bridge proves: HTTP plus SSE with a polling fallback, the seven interchange types as the wire contract, and the frontend never touching SQLite.
  - Everything still open goes into the carry-forward file (1f): the public step-output read API in the core, `init_db` cost per connection, adapter self-description, reload-mid-run versus `runs.current_step`, and the detection/annotation write guard.
  - Comment, then close.
- **#10 (signal reduction) and #11 (the UI_CONTEXT.md corrections):** don't work them. Comment "carried forward to `docs/wayfinder/fog-of-war.md` §…", then close.
- **The map, #4:**
  - Append each closed ticket to "Decisions so far" (name-linked, one-line gist).
  - Replace "Not yet specified" with a pointer to the carry-forward file.
  - Post a closing comment saying the destination is reached and giving the ADR link, then close.
  - Refer to tickets by name in everything I'll read.

**1f. Carry-forward file: `docs/wayfinder/fog-of-war.md`.**
This will seed a future wayfinder map that covers the **whole pipeline and project**; the current map is one subsection. Collect every question that is still open from these sources:
- the bodies and sub-questions of #10, #11, #13, #14 and #15;
- map #4's "Not yet specified" and "Out of scope" sections (keep them separate, because out of scope is not fog);
- REPORT §4 "left open", §5 backend gaps, §7 open questions and §8 additional findings. These include:
  - the time-axis convention;
  - SAX cutlines as a parameter;
  - pausing an over-ceiling stage and handing it to HPC versus refusing to run it;
  - within-step progress;
  - retention of runtime directories;
  - the real-`DATA/` writes from the last run, and making pytest safe against them;
- `UI_FUNCTIONAL_SPEC.md` §11 "Open" and §12 (PRD departures that need confirming);
- the open decisions D1–D3 and any unfinished B-items in `UI_REVIEW_BACKLOG.md`;
- whatever the Task 1 decision on the old tree left behind.

Group the items by area: core seam and data; analysis semantics; frontend design; export and reporting; tooling, tests and safety; legacy tree. For each item give:
- the question, as sharply as it can honestly be phrased;
- why it matters;
- its source (a link or path);
- one of `ticketable now`, `fog` or `out of scope`.

Commit, then **[push]**.

## Task 2 (the main one): build the rest of the frontend as a working, empty shell

**Goal.** Every page in `prototyping/imgs/` exists in `webui/` and looks like its concept frames. It behaves as a
working frontend: it navigates, opens and closes pop-ups, modals and drawers, switches tabs, accepts and
validates input, updates selections and dependent panels, and shows the disabled, empty, running and failed
states the frames show.

**Not the goal:** the analysis behind it. Don't implement algorithms and don't add core behaviour.

**Don't regress what already works.** Explore › Corpus, Explore › Signal and Analyse › Chain are live against the bridge. Extend them with their missing frames, and keep them wired.

### Data for the empty frontend
- **One seam.** Every new read goes through typed async functions in `webui/client/src/api.ts`, or a sibling `api/` module per workspace.
  - Until it is wired, a function resolves fixture data from `webui/client/src/fixtures/<workspace>.ts` and marks it `demo`.
  - A later ticket can then replace fixtures with endpoints without touching any component.
- **Fixtures follow the spec §0 placeholder canon.** The frames use it, so the screenshots should match them.
- **A page showing fixture data shows a small "demo data" chip in the header.**
- **Writes stay in memory.** Save, register, verdict, apply and import go to an in-memory client store and survive navigation, but not a reload.
- **Actions that would run analysis** move through a plausible queued → running → done state on a timer, ending in fixture results. If that makes no sense for a control, it shows a toast: `not wired yet: <what it would call>`.
- **No dead clicks.** Every control visible in a frame does something visible.
- **Plots follow §3 conventions:** light grounds, mV never normalised, hours since recording start, small multiples capped per P8. They draw fixture data through the existing chart primitives and the seven-type `Renderer.tsx` seam.

### Order of work
Work breadth first, so a cutoff at any point still leaves a navigable app.

1. **Inventory.** Write `webui/PAGES.md`, mapping all 96 frames to pages.
   - A *page* is one route or screen. A frame showing a state of that screen (popover open, drawer tab, running, failed, empty) is a state of the page, not a separate page.
   - For each page, record: its route, the frames it covers, the spec section, every region and interaction the frames and spec call for, the fixtures it needs, and a status and score column.
2. **Shared kit.**
   - Pull the components that recur across frames into `webui/client/src/kit/`: chips, badges, segmented controls, tabs, popover, modal, drawer, table, stepper, toast, glyph registry (chain 6b), small-multiple grid and form fields.
   - Reuse A's existing components rather than duplicating them.
   - Extend `useDismiss` so Escape, outside click and the focus trap work everywhere.
3. **Every route reachable.** Every nav-rail item and every in-page link routes to a page skeleton: the shell, the correct header, and the frame's main regions laid out and labelled.
   - Extend `webui/smoke.py`: every route renders, the console is clean, nothing is blank.
   - Commit.
4. **Depth, one workspace at a time**, running the critique loop below on each page. Default order, which follows the researcher's workflow:
   1. Explore (remaining frames)
   2. Analyse › Chain (1c, 1g, 1h, 1i and the block pages 3, 4, 5, 6, 6b, 7, 8)
   3. Review
   4. Library
   5. Discovery
   6. Models
   7. Jobs
   8. Analyse › Interrogation
   9. Analyse › Training
   10. Settings (16 sub-pages; lower interaction density, so it goes last)
5. **Final pass.**
   - Full smoke with a screenshot of every page and state, type-check, build.
   - pytest per rule 7, and the DATA check.
   - Stop the servers.
   - Final report.

### Build and critique loop (use a workflow and subagents)
Use a workflow, orchestrating multiple subagents. Scale it to the job: well over the usual size guideline is justified here.

- **Builders.**
  - After step 3, builders may run in parallel, but only on disjoint directories: each owns `webui/client/src/<workspace>/` and its fixtures file.
  - The orchestrator alone edits shared files (router, `api.ts` types, `kit/`, theme, smoke) and does so serially. Run at most ~4 builders at once.
  - Builders don't start servers. The orchestrator runs one Vite dev server with HMR, proxied to one bridge, for the whole night, and a separate production build for the final pass.
- **Critics.** When a page is built, two fresh critic subagents review it independently, in parallel. Neither sees the builder's self-assessment.
  - **Design fidelity.** Reads every frame PDF for the page and screenshots the page in each of its states at 1440 × 900 (Playwright, conda Python). It compares layout, hierarchy, components, copy, spacing, colour and plot conventions.
  - **Function.** Drives the page. It clicks every control the frames and spec show, opens and closes every pop-up by button, Escape and outside click, types into every input (including invalid values), checks disabled states carry reasons, checks navigation in and out, reloads, and watches the console.
  - Each critic returns a **score from 1 to 10** and findings tagged P0, P1 or P2, with screenshots. The rubric:
    - **10:** design and functionality are the same as the concept intended, or better.
    - **8–9:** every region and interaction is present; only minor visual differences.
    - **6–7:** most things are present, but several states or interactions are missing or visibly off.
    - **5:** some of the functionality and design is there, with a few errors and missing features.
    - **3–4:** the layout skeleton is recognisable, but most interactions are missing.
    - **1:** nowhere near the page.
- **Acceptance.**
  - A page's score is the **lower** of the two critic scores. It is accepted at **≥ 8**.
  - Otherwise a builder fixes the findings, P0 and P1 first, and two *fresh* critics re-rate the page. They get the previous findings to verify but score independently.
  - Cap: **one initial rating and two re-ratings per page.** Then record the final score and move on, even if it is below 8, with the reasons.
  - Don't spend a third round on polish while pages elsewhere are still skeletons.
- **Record** every page's score history, findings summary, commit and screenshot paths in `webui/PAGES.md`.
- **Fog of war.** Whenever a frame assumes something the core or data cannot provide, or the spec is ambiguous, append it to `docs/wayfinder/fog-of-war.md` under "frontend design". Don't block on it.

### Resilience
The account's usage limit cut agents off repeatedly last night, so:
- Keep `webui/BUILD_PROGRESS.md` current: phase, page, round, last commit, next action.
- Every subagent writes its partial results to a file as it goes, so a killed agent's work survives.
- On resume, read the progress file and continue from there. Don't restart.
- Commit per page.

### Deliverables
- **`webui/DECISIONS.md`:** every non-trivial decision from both tasks, with a one-paragraph justification each. For example: the old-tree call, route structure, fixture design, where a frame and the spec disagreed, what you left out.
- **`webui/PAGES_REPORT.md`:**
  - a summary table: workspace, page, frames covered, fidelity score, function score, final score, rounds, main remaining gaps, screenshot folder;
  - overall statistics;
  - pages below 8 and why;
  - what needs my input.
- **Updated files:** `CLAUDE.md`, the ADR, `docs/wayfinder/fog-of-war.md`, and a green `webui/smoke.py`.
- **Merge and push:** all of Task 2 on `main` (or merged into it) and pushed. Branching is up to you, but finish on `main`.
- **Final chat message:**
  - what Task 1 did, in particular what happened to the old tree;
  - the page scores table;
  - the five most consequential decisions;
  - the pages below 8;
  - the questions waiting for me;
  - how to start the app.
