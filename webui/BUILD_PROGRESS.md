# BUILD_PROGRESS.md — resume point for the overnight build

Read this first on resume; continue from "Next action". Do not restart finished steps.
Scratchpad (session): `C:/Users/mmebr/AppData/Local/Temp/claude/C--Users-mmebr-Documents-CNN/08616d91-3198-4e54-a453-92e3fff331d1/scratchpad/`
(BRIEF.md = the overnight brief; DATA_MTIMES_START.txt = the start snapshot; issues.md = map + child issue bodies).

- **Session start:** 2026-09-15 23:50 +10:00. annotations.sqlite mtime 1789297374 (2026-09-13 11:02:54 UTC), size 4349952.
- **Servers I started:** bridge `webui/run_server.py --port 8765` (bg task), Vite dev `npx vite` on 5173 (bg task). Stop both before finishing.
- **Temp worktree:** `C:/Users/mmebr/Documents/CNN-pytest` (detached, real copied DATA subset ~1.25 GB) — reuse for the final pytest, then `git worktree remove --force` it (may be blocked by the classifier; then leave + log).
- **Old worktree** `CNN-ui-proto`: junction removed; `git worktree remove --force` blocked by classifier → left for the user (DECISIONS 1.7).

## Task 1
| step | status | commit |
|---|---|---|
| 1a merge ff | done | e81b486 |
| 1b promote A → webui, archive README, delete brief | done | f0c8f13 |
| 1c old tree: not trivial, UI/ kept; CLAUDE.md | done | ca9e30d |
| 1d pytest (39 pre-existing failures) + smoke green; junction removed; push #1 | done (worktree removal blocked) | pushed ca9e30d |
| 1e ADR 0001 written; tracker comments/closures | ADR done; tracker writes WAIT for fog file | |
| 1f docs/wayfinder/fog-of-war.md | background agent drafting | |

Tracker plan once fog file is committed + pushed (push #2): comment+close Select-the-stack (#12, link ADR + REPORT),
where-tree-lives (#14), test gates (#15), frontend↔core (#13, resolved part + carry-forward §Core seam), signal
reduction (#10) and UI_CONTEXT corrections (#11) ("carried forward to docs/wayfinder/fog-of-war.md §…"), then map #4:
append Decisions-so-far lines (name-linked), replace "Not yet specified" with pointer, closing comment, close.
gh = "/c/Program Files/GitHub CLI/gh.exe" (authenticated as mitchbradshaw). Refer to tickets by name.

## Task 2
| step | status |
|---|---|
| foundations (me): Route.parts/query + setQuery; Header demo chip/search/need-you; kit/store.ts, kit/sim.ts, kit/notWired.ts, api/seam.ts, fixtures/canon.ts; nav default routes | done, uncommitted, tsc clean |
| inventory workflow wf_66d54a22-952 → webui/pages/inventory/<group>.md (7 groups) | running |
| kit agent → webui/client/src/kit/** + #/kit gallery | running |
| skeleton: every route reachable (lazy-loaded workspaces), smoke extended | todo |
| PAGES.md assembled from inventory | todo |
| depth workflow: build → 2 critics → fix ≤2 → record | todo |
| final pass: smoke all states, tsc, build, pytest, DATA check, stop servers, reports | todo |

### Depth plan (decided)
Builders own disjoint dirs: src/explore, src/analyse (chain+block+glyph pages), src/interrogation, src/training,
src/discovery, src/models, src/review, src/library, src/jobs, src/settings, each with src/api/<ws>.ts and
src/fixtures/<ws>.ts, plus webui/smoke_pages/<ws>.json (states manifest for the smoke). ≤4 builders at once.
Critics: fidelity + function per critique unit, scores per page, findings JSON → webui/critique/<unit>/r<N>-<lens>.json,
screenshots → webui/screenshots/critique/<unit>/r<N>-<lens>/ (gitignored). Page score = min; accept ≥8; ≤2 re-ratings.

## Next action
Wait for inventory + kit + fog agents. Then: commit foundations+kit; skeleton; tracker writes after fog file.
