# BUILD_PROGRESS.md — resume point for the overnight build

Read this first on resume; continue from "Next action". Do not restart finished steps.

- **Session start:** 2026-09-15 23:50 +10:00. DATA start snapshot: scratchpad `DATA_MTIMES_START.txt`
  (copied to `webui/DATA_MTIMES_START.txt` at the end). annotations.sqlite mtime 1789297374, size 4349952.
- **Servers I started:** bridge on 8765 (background task). Stop before finishing.
- **Temp worktree:** `C:/Users/mmebr/Documents/CNN-pytest` (detached, real copied DATA subset) — remove at the end.

## Task 1
| step | status | commit |
|---|---|---|
| 1a merge ff | done | e81b486 |
| 1b promote A → webui, archive README, delete brief | done | f0c8f13 |
| 1c old tree assessment → not trivial, UI/ kept; CLAUDE.md | edits written, uncommitted | |
| 1d pytest (copied DATA worktree) + smoke; remove CNN-ui-proto worktree + branch; push | in progress | |
| 1e ADR 0001, close #12 #14 #15 #13 #10 #11, map #4 | ADR written | |
| 1f fog-of-war.md | agent drafting | |

## Task 2
Not started.

## Next action
Wait for pytest (scratchpad `pytest_task1.txt`), compare failure set, commit 1c/ADR, remove old worktree, push.
