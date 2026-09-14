# Slice checklist (from the task brief) — the same for every prototype

**Must**
1. Shell matching the nav rail and header frames. Explore and Analyse live; the others visible but inert.
2. Explore › Corpus (explore-1-corpus): coverage heatmap of M2_aug_concat_fs1.mat from real annotation and detection rows per channel and time bin; the colour-by toggle; channel selection populating the bottom bar; "Open channel".
3. Explore › Signal (explore-2-signal): the full 721 h with smooth pan and zoom; peak-preserving decimation re-run for each viewport; annotation and detection spans as tinted bands; selecting a span and sending it to Analyse as the chain source.
4. Analyse › Chain (chain-1-chain):
   - Composition: a source row from that span, and an insert-stage modal (chain-2) listing real adapters; incompatible ones disabled with the reason.
   - Rows: one row per block on a shared time axis; each row shows its status badge (cached/stale/new/running/failed) and a one-line summary.
   - One dispatch seam keyed on output type, covering all seven types; at least one awkward type (Scores, Grouping, Encoding image stack, or Model) exercised for real; the rest honest placeholders.
   - Run: against the untouched core on the database copy, with live per-row progress and cancel; running, failed-block and invalid-junction states (chain-1d/1e/1f).
   - Suffix re-run: edit a parameter on a later block and re-run; earlier rows show cached (0 s step timings), proving the prefix cache is hit.

**Should**
5. One block page (e.g. chain-3): settings and output together, with a draggable cutline or threshold on a plot that updates the parameter and marks downstream rows stale.
6. Run history popover, and Save template (stub fine).

**Could**
7. Export run as a simple report.
8. Cross-channel view.

**Hard rules**: core untouched (Working/, Adapters/, UI/, tests/, scripts/, repo-root dependency files); never touch real data (DB copy, redirected step cache, DATA/ read-only, M4 refused); no shared-environment installs; only the worktree/branch; no deletion of the worktree, junction or DATA; pytest suite still passes; servers stopped at the end.
