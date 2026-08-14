# Ticket backlog — index

49 tickets. This file is generated from the ticket front-matter; the ticket files are the source of
truth. See `docs/ORCHESTRATOR_SPEC.md` for how the scheduler consumes these fields.

**Notation.** Model `[O]`pus / `[S]`onnet. Size `[S]`mall / `[M]`edium / `[L]`arge.

## Flags

| Flag | Tickets | Meaning |
|---|---|---|
| `human-gate` | 04, 49 | Never dispatched. Held in the DAG so dependents are correctly blocked. |
| `solo` | 17 | Runs alone; nothing else in flight. |
| `human-verify` | 17, 18, 20, 21, 22, 23, 29, 30, 31, 32, 33, 34, 37, 38, 39, 42, 44 | Dispatched and merged, but needs your eyes before `main` moves. |

## Dependency levels

Earliest level at which each ticket can start. Depth 13. Width is only 3+ at levels 2–5; the tail
is a single file.

| Level | Width | Tickets |
|---|---|---|
| 0 | 4 | 01, 02, 03, 17 |
| 1 | 4 | 04, 05, 16, 35 |
| 2 | 7 | 06, 07, 08, 13, 18, 19, 36 |
| 3 | 9 | 09, 11, 14, 20, 28, 37, 38, 41, 43 |
| 4 | 6 | 12, 15, 21, 29, 39, 42 |
| 5 | 6 | 10, 22, 24, 30, 34, 40 |
| 6 | 3 | 23, 25, 47 |
| 7 | 2 | 26, 27 |
| 8 | 4 | 31, 33, 45, 46 |
| 9 | 1 | 32 |
| 10 | 1 | 44 |
| 11 | 1 | 48 |
| 12 | 1 | 49 |

**Critical path (13):** 01 → 05 → 13 → 14 → 15 → 24 → 25 → 26 → 31 → 32 → 44 → 48 → 49

**Most-unblocking tickets:** `01` gates 36, `02` gates 32, `05` gates 28, `17` gates 26, `04` gates 21, `13` gates 19.

## Mutexes

Every declared merge-risk pair is a mutual exclusion: never both in flight. Ordering is free — the
constraint is only simultaneity. 64 pairs are declared; 46 are already
ordered by a blocking edge and are therefore redundant (harmless, kept for completeness). The
**18 live pairs** below can otherwise be dispatched concurrently and must be enforced:

| Pair | Why |
|---|---|
| `03 ↔ 08` | both edit `Working/execution.py` |
| `03 ↔ 15` | both edit `Working/execution.py` |
| `03 ↔ 17` | both edit `UI/app.py`, and 17 is dismantling it |
| `07 ↔ 08` | 08 defines how a `WindowSet` carries attached features |
| `07 ↔ 09` | entropy may become a per-window feature |
| `08 ↔ 13` | `execution.py` dispatch vs `recipes.py` validation |
| `12 ↔ 14` | shared feature-matrix / binding surface |
| `12 ↔ 26` | both declare an `estimate` |
| `16 ↔ 17` | **HIGH** — 16 edits four `RunPanel` methods; 17 is splitting that class |
| `18 ↔ 27` | shell mount points vs manifest import action |
| `21 ↔ 39` | shared z-normalised overlay builder |
| `23 ↔ 37` | two of the three library-entry creation paths |
| `25 ↔ 43` | **HIGH** — band list and channel list are the same fan-out mechanism |
| `30 ↔ 34` | same Analyse workspace package |
| `31 ↔ 34` | same Analyse workspace package |
| `32 ↔ 34` | same Analyse workspace package |
| `34 ↔ 38` | both absorb legacy panels |
| `45 ↔ 46` | **HIGH** — same exporter module, same level, no edge between them |

## Single-owner rules

Not expressible as edges. Import, never reimplement.

- The manifest schema is owned by **27**. Tickets 45 and 46 import it.
- The set-overlap computation is owned by **33**. Ticket 44 imports it.
- Library entry creation is owned by **16**. Tickets 23 and 37 call its helper.
- `Adapters/base.py` and `Adapters/registry.py` are frozen after **05**, unfrozen only for **10**.
- The three motif distances go in a new module, **not** in `Working/database/similarity.py` — that
  computes interval IoU for duplicate-annotation warnings and is not shape distance.

## Dispatch order

Most-unblocking first, tie-broken by critical-path length, then id. Deterministic.

```
  01  02  05  17  04  13  18  14  08  15  24  25
  28  35  29  36  16  19  27  26  20  06  31  21
  32  33  22  38  43  07  44  45  23  11  48  30
  12  39  09  41  03  49  46  47  10  34  40  42
  37
```

## The ticket 04 bottleneck

`04` is `human-gate`, and **20 further tickets sit downstream of it** — including `18`,
the four-workspace shell, which gates the whole UI half of the backlog:

```
  18, 19, 20, 21, 22, 23, 29, 30, 31, 32, 34, 37, 38, 39, 40, 42, 44, 45, 47, 48
```

Simulating the scheduler over this DAG (ceiling 3, Opus 2, size-based durations): night one drains
**27 of 49 tickets in about 10 hours** and then stalls against 04. Doing 04 by hand is the single
highest-leverage human action available and should happen before night two.

## Cut list

In the order the PRD says to drop them: **15** (step cache — also on the critical path, so cutting it
shortens the longest chain), **47** (templates; keep JSON import/export), **42** (grouping selectors),
and the UI half of **41** (run cross-channel as a script; 41's core is deliberately UI-free).

**Never cut:** 19 (adjudications), 44 (surrogate-by-default), 45 and 46 (the exporters).

## All tickets

| # | Title | Model | Size | Level | Unblocks | Blocked by | Flags |
|---|---|---|---|---|---|---|---|
| [01](T01-seven-interchange-types-with-disk-serialisation.md) | Seven interchange types with disk serialisation | S | M | 0 | 36 | — |  |
| [02](T02-schema-extension-new-tables-new-columns-union-view.md) | Schema extension: new tables, new columns, union view | S | M | 0 | 32 | — |  |
| [03](T03-held-out-recording-lock.md) | Held-out recording lock | S | S | 0 | 1 | — |  |
| [04](T04-verdict-constraint-rebuild-add-seed.md) | Verdict-constraint rebuild: add `seed` | O | M | 1 | 21 | 02 | `human-gate` |
| [05](T05-adapter-spec-expansion-expand-phase.md) | Adapter spec expansion (expand phase) | S | M | 1 | 28 | 01 |  |
| [06](T06-adapter-remap-batch-a-signal-and-interval-blocks.md) | Adapter remap batch A: signal and interval blocks | S | M | 2 | 5 | 05 |  |
| [07](T07-adapter-remap-batch-b-encoding-blocks.md) | Adapter remap batch B: encoding blocks | S | M | 2 | 3 | 05 |  |
| [08](T08-adapter-remap-batch-c-matrix-profile-to-scores-window-matr.md) | Adapter remap batch C: matrix profile to Scores, window matrix to WindowSet, executor dispatch | O | M | 2 | 15 | 05 |  |
| [09](T09-decide-the-type-of-detection-entropy.md) | Decide the type of `detection.entropy` | O | S | 3 | 1 | 05, 08 |  |
| [10](T10-contract-phase-remove-the-legacy-output-vocabulary.md) | Contract phase: remove the legacy output vocabulary | S | S | 5 | 0 | 06, 07, 08, 09, 11, 12 |  |
| [11](T11-new-adapter-clustering-to-a-grouping.md) | New adapter: clustering to a Grouping | O | M | 3 | 2 | 05, 07 |  |
| [12](T12-new-adapter-classifier-training-to-a-model.md) | New adapter: classifier training to a Model | O | M | 4 | 1 | 05, 11 |  |
| [13](T13-chain-validation.md) | Chain validation | S | M | 2 | 19 | 05 |  |
| [14](T14-side-inputs-and-content-addressed-bindings.md) | Side-inputs and content-addressed bindings | S | M | 3 | 15 | 05, 13 |  |
| [15](T15-step-cache-in-the-executor.md) | Step cache in the executor | O | M | 4 | 12 | 02, 08, 14 |  |
| [16](T16-shape-first-library-migrate-motif-rows-and-redirect-the-sa.md) | Shape-first library: migrate motif rows and redirect the save paths | O | M | 1 | 8 | 02 |  |
| [17](T17-split-the-two-god-class-ui-modules-into-packages.md) | Split the two god-class UI modules into packages | O | M | 0 | 26 | — | `solo` `human-verify` |
| [18](T18-four-workspace-shell.md) | Four-workspace shell | O | M | 2 | 18 | 04, 17 | `human-verify` |
| [19](T19-adjudication-store-and-divergence-queries.md) | Adjudication store and divergence queries | S | M | 2 | 7 | 02, 04 |  |
| [20](T20-review-queue-filters-and-queue-state.md) | Review queue: filters and queue state | S | M | 3 | 5 | 18, 19 | `human-verify` |
| [21](T21-review-queue-candidate-surface.md) | Review queue: candidate surface | O | M | 4 | 4 | 20 | `human-verify` |
| [22](T22-keyboard-verdicts-auto-advance-undo.md) | Keyboard verdicts, auto-advance, undo | O | M | 5 | 3 | 21 | `human-verify` |
| [23](T23-promote-an-adjudicated-candidate-into-the-library.md) | Promote an adjudicated candidate into the library | S | S | 6 | 2 | 16, 19, 22 | `human-verify` |
| [24](T24-background-run-execution-status-cancellation-per-stage-res.md) | Background run execution: status, cancellation, per-stage results | S | M | 5 | 11 | 13, 15, 17 |  |
| [25](T25-scope-selection-and-run-group-fan-out.md) | Scope selection and run-group fan-out | S | M | 6 | 10 | 02, 24 |  |
| [26](T26-runtime-estimators-and-cluster-routing-with-slurm-array-ex.md) | Runtime estimators and cluster routing with SLURM array export | S | M | 7 | 5 | 05, 25 |  |
| [27](T27-manifest-writer-reader-and-one-generic-import-action.md) | Manifest writer, reader, and one generic import action | S | M | 7 | 6 | 24, 25 |  |
| [28](T28-chain-state-model.md) | Chain state model | S | M | 3 | 9 | 13 |  |
| [29](T29-chain-builder-surface.md) | Chain builder surface | O | M | 4 | 8 | 18, 28 | `human-verify` |
| [30](T30-block-inspector.md) | Block inspector | O | L | 5 | 1 | 14, 29 | `human-verify` |
| [31](T31-run-surface-estimate-routing-launch-cancel.md) | Run surface: estimate, routing, launch, cancel | S | M | 8 | 4 | 26, 29 | `human-verify` |
| [32](T32-run-surface-progress-and-per-stage-results.md) | Run surface: progress and per-stage results | O | M | 9 | 3 | 24, 31 | `human-verify` |
| [33](T33-compare-view-two-run-set-overlap.md) | Compare view: two-run set overlap | O | M | 8 | 3 | 25, 27 | `human-verify` |
| [34](T34-fold-run-history-and-the-window-matrix-panel-into-analyse.md) | Fold run history and the window-matrix panel into Analyse | S | M | 5 | 0 | 18, 29 | `human-verify` |
| [35](T35-the-three-distance-functions.md) | The three distance functions | S | M | 1 | 9 | 01 |  |
| [36](T36-edge-computation-and-persistence.md) | Edge computation and persistence | S | M | 2 | 8 | 02, 35 |  |
| [37](T37-seed-an-exemplar-from-the-viewer.md) | Seed an exemplar from the viewer | S | S | 3 | 0 | 16, 18 | `human-verify` |
| [38](T38-library-grid.md) | Library grid | O | M | 3 | 3 | 16, 18, 36 | `human-verify` |
| [39](T39-entry-detail-members-overlay-and-edge-list.md) | Entry detail: members overlay and edge list | O | M | 4 | 1 | 38 | `human-verify` |
| [40](T40-search-at-other-scales.md) | Search at other scales | S | M | 5 | 0 | 35, 36, 39 |  |
| [41](T41-cross-channel-classification.md) | Cross-channel classification | O | M | 3 | 1 | 36 |  |
| [42](T42-library-grouping-selectors.md) | Library grouping selectors | S | S | 4 | 0 | 38 | `human-verify` |
| [43](T43-surrogate-generation-block.md) | Surrogate generation block | S | M | 3 | 3 | 05, 06 |  |
| [44](T44-paired-surrogate-runs-on-by-default.md) | Paired surrogate runs, on by default | O | M | 10 | 2 | 24, 32, 33, 43 | `human-verify` |
| [45](T45-run-group-exporter.md) | Run-group exporter | S | M | 8 | 2 | 19, 27 |  |
| [46](T46-library-entry-exporter.md) | Library-entry exporter | S | M | 8 | 0 | 27, 36, 41 |  |
| [47](T47-templates-save-apply-carry-and-rebind.md) | Templates: save, apply, carry and rebind | O | M | 6 | 0 | 14, 30 |  |
| [48](T48-end-to-end-test-and-repository-cleanup.md) | End-to-end test and repository cleanup | S | M | 11 | 1 | 23, 27, 36, 44, 45 |  |
| [49](T49-unlock-the-held-out-recording-and-run-the-pipeline-on-it.md) | Unlock the held-out recording and run the pipeline on it | O | S | 12 | 0 | 03, 48 | `human-gate` |
