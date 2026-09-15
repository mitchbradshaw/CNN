# webui/DECISIONS.md — decisions from the overnight build (2026-09-15 → 16)

Every non-trivial call made while landing prototype A as `webui/` (Task 1) and building every concept page as
a working, empty shell (Task 2). Newest at the bottom of each part. The prototype night's own log is
`ui-prototypes/DECISIONS.md`.

## Part 1 — landing A, retiring the old tree, closing the map

### 1.1 Fast-forward merge
`main` had not moved since `proto/ui-stack-slices` was cut (merge base = `main` = `208e72c`), so
`git merge --ff-only` succeeded and no merge commit or conflict resolution was needed.

### 1.2 A's screenshots stay in the archive, not in `webui/`
The brief's default was `git mv ui-prototypes/A-react-fastapi webui`, but it also said the screenshots stay in
`ui-prototypes/` as evidence. Moving the whole directory would have carried A's night-of screenshots into
`webui/` and broken every path in REPORT.md §6. I moved the directory and then moved `screenshots/` back to
`ui-prototypes/A-react-fastapi/screenshots/`, so the archive's references resolve and `webui/screenshots/`
holds only the product's own smoke output.

### 1.3 Path fixes, and one addition
`runtime.py` now takes the repo root as the parent of `webui/` (`WEBUI_DIR`; `PROTO_DIR` kept as an alias so
`app.py` did not need a second edit). Environment variables became `WEBUI_PORT` / `WEBUI_URL`. Titles and log
names lost "prototype A". I added one behaviour: `run_server.py` refuses to start on a busy port with a clear
message, because REPORT §8 found stale prototype servers silently occupying 8765/8766 and recommended exactly
this. `.gitignore` rules moved into `webui/.gitignore` (node_modules, .venv, dist, runtime, logs, *.big.png);
`ui-prototypes/.gitignore` is left for B. Smoke passed on the first run in the main checkout (19 screenshots,
0 failures).

### 1.4 The old Panel tree `UI/` stays (deletion is not trivial)
Assessed in ~10 minutes against the brief's two conditions. **Condition 1 fails:**
`Working/Detection/sax/dsax_python/UI_snapshot_20260810-0512/{app.py,run_panel.py}` imports `UI`, and that
path is under `Working/`, which this night may not edit. **Condition 2 fails:** 39 files under `tests/` import
`UI`, and at least six mix core assertions with UI imports in the same file — `test_heldout_lock.py`
(`execute_recipe` raising `HeldOutRecordingLocked`, beside `UI.viewer.ViewerApp`), `test_manifest.py`
(`Working.manifest` beside `UI.admin.ManifestImport`), `test_export.py`, `test_import_drop_motifs.py`,
`test_compare.py` and `test_run_groups.py` — plus `tests/_session_isolation.py`, which ten test files import.
Deleting them would lose core assertions; splitting them is test surgery beyond "trivial". So `UI/`, its
tests and `tests/ui/` are left exactly as they are, no `archive/panel-ui` tag was created, and CLAUDE.md marks
them legacy. `webui/` imports nothing from `UI/` (checked by grep).

### 1.5 CLAUDE.md
Layout table gains `webui/` and `ui-prototypes/` and marks `UI/`, `tests/ui/` and `scripts/dev_serve.py`
legacy. Rule 1 now says which tree may import which UI libraries (Panel family → `UI/` only; browser libraries
→ `webui/client/` only; FastAPI → `webui/server/` only; core → none). A new "Web UI" section gives the start
commands and the gate (type-check + build + `webui/smoke.py`, plus pytest when Python outside `webui/`
changed). The Panel-surfaces section is kept but headed "legacy `UI/` only", matching 1.4.

### 1.6 Running pytest without touching the real DATA
The previous night's pytest run wrote into the real `DATA/` through a junction. The tests read
`DATA/derived/channels/{M2_aug_concat_fs1, Fig2A_dt0p1, L_LM_Jul_26_J_raw_fs10}`, the fixture and seed
directories and `DATA/db/*.json`, and write `DATA/derived/{step_cache, encodings, models, channels}`. Those
reads total ~1.2 GB, under the brief's 2 GB bound, so the suite ran in a temporary detached worktree
(`C:/Users/mmebr/Documents/CNN-pytest`) whose `DATA/` is a **real copy** of exactly those paths (verified not
to be a reparse point). Nothing collected by pytest differs from `208e72c`.

**Result.** 41 failed / 1296 passed. Two failures were my copy missing an input (`Plots/drop_motifs9_fig2a/`,
46 MB, and `DATA/derived/channels/Mushroom_260720_0509_4hrs_CH14_fs1/`); after copying them, both pass. The
other 39 are the two pre-existing classes the prototype night documented: the `LibraryGrid(conn)` test/code
mismatch and Windows `WinError 32` file locks at teardown (the lock failures in `test_plots_perf.py` and
`test_library_edges.py` reproduce serially). The baseline file only listed its last 14 failures, so a full
set comparison was not possible; instead every failure was classified, and none is attributable to this
night because no collected file changed. The failure list is `webui/PYTEST_GATE_TASK1.txt`.
`test_materialize_arbitrary_file` failed in the baseline and passed here — a lock flake, not a fix.
