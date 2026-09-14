# Concept frame exports

One single-page vector PDF per concept frame, exported from the `.pen` files on 2026-09-14,
after commit `40a38af`. Text in the PDFs is real text, so `pdftotext` and search both work.
The `.pen` files remain the source of truth. These are read-only snapshots, so agents can see
the design without the pencil editor. Re-export after any pen edit.

**Naming.** `<workspace>-<label>-<slug>.pdf`, where `<label>` is the frame number printed on
the pen canvas. That is also the number the spec and backlog cite ("Chain 7b", "Models 4b").
The pen node name sometimes differs from the canvas label (Explore and Chain were renumbered),
so both are listed below. Settings labels are zero-padded so they sort.

All frames are 1440 × 900 unless the caption says the page scrolls. The spec is
[`../UI_FUNCTIONAL_SPEC.md`](../UI_FUNCTIONAL_SPEC.md), and §0 holds the placeholder canon every
frame follows.

## shell/ (shared across every workspace)
| file | pen node |
|---|---|
| shell-nav-rail.pdf | `shell/nav-rail` (component; every pen holds an identical copy) |
| shell-header.pdf | `shell/header` (component; the title text differs per workspace; this copy is from Explore) |

## explore/ (`UI_explore_flow_v2.pen`)
| file | pen node | canvas caption |
|---|---|---|
| explore-1-corpus.pdf | explore-0-corpus | corpus: pick a channel |
| explore-1b-corpus-menus.pdf | explore-0b-corpus-menus | corpus, with the recording menu and legend open |
| explore-2-signal.pdf | explore-1-signal | Signal mode |
| explore-2a-signal-popovers.pdf | explore-1b-signal-popovers | Signal mode, with the detections picker and span legend open |
| explore-2b-signal-drawer.pdf | explore-1b-signal-drawer | Signal mode, drawer open |
| explore-2c-drawer-detections.pdf | explore-1c-drawer-detections | drawer, Detections tab |
| explore-2d-drawer-shortcuts.pdf | explore-1d-drawer-shortcuts | drawer, Shortcuts tab |
| explore-3-cross-channel.pdf | explore-2-cross-channel | Cross-channel mode (placeholder) |
| explore-3b-cross-channel-aligned.pdf | explore-2b-cross-channel-aligned | cross-channel, lag-aligned |
| explore-4-span-edit.pdf | explore-2c-span-edit | editing a span, opened from Review |

## analyse-chain/ (`UI_analyse_chain_v1.pen`): Analyse, detection chain
Canonical chain order (B24): Source › 01 Baseline › 02 Noise floor › 03 Encoding › 04 Detection.

| file | pen node | canvas caption |
|---|---|---|
| chain-1-chain.pdf | analyse-1-chain | the chain: build it, or import a template |
| chain-1b-run-history.pdf | analyse-1b-run-history | run history pop-up; apply a past run to this source |
| chain-1c-empty-import-template.pdf | analyse-1c-empty-import-template | empty chain: import a template |
| chain-1d-running.pdf | analyse-1d-running | chain running: results land per stage; cancel between stages |
| chain-1e-invalid-junction.pdf | analyse-1e-invalid-junction | invalid chain: the wrong junction and how to fix it |
| chain-1f-failed-block.pdf | analyse-1f-failed-block | a block failed: error in place, earlier stages stay cached |
| chain-1g-heavy-stage-hpc.pdf | analyse-1g-heavy-stage-hpc | whole-channel run: a stage over the local ceiling exports an HPC job |
| chain-1h-scores-chain.pdf | analyse-1h-scores-chain | Signal → Scores chain (template for every Scores block) |
| chain-1i-paused-result-in-place.pdf | analyse-1i-paused-result-in-place | paused run: stage 02's cluster result is in place; continue from 03 (B22) |
| chain-2-insert-stage.pdf | analyse-6-insert-stage | inserting a stage: the type contract |
| chain-3-block03-symbolic-encoding.pdf | analyse-2-encoding-block | block page: symbolic encoding (stage 03)* |
| chain-4-block04-drop-detection.pdf | analyse-3-detection-block | block page: drop detection (stage 04) |
| chain-5-block01-baseline-removal.pdf | analyse-5-baseline-block | block page: baseline removal (template for any Signal → Signal transform) |
| chain-6-block02-noise-floor.pdf | analyse-6-noise-floor-block | block page: noise floor (stage 02; template for any estimator block)* |
| chain-6b-algorithm-glyphs.pdf | analyse-6b-algorithm-glyphs | algorithm glyph registry |
| chain-7-block-matrix-profile-scores.pdf | analyse-7-scores-block | Scores block page: matrix profile |
| chain-7b-block-threshold-to-spans.pdf | analyse-7b-threshold-block | Threshold to spans block: Scores → SpanSet (B10) |
| chain-8-block-model-stage.pdf | analyse-8-model-stage-block | Model stage block: Model + WindowSet → Scores (B13) |

\* **Known stale text.** The page titles in these two frames still read "02 Symbolic encoding" and
"03 Noise floor". The chain strip and badges on the same pages already use the B24 order, and the
strip is correct: Noise floor is 02 and Encoding is 03.

## analyse-interrogation/ (`UI_analyse_interrogation_v1.pen`): Analyse, family interrogation
| file | pen node | canvas caption |
|---|---|---|
| interrogation-1-family-block.pdf | analyse-4a-family-block | source block: the family being analysed |
| interrogation-1b-source-picker.pdf | analyse-4a-b-source-picker | source block: picking what the chain analyses |
| interrogation-2-block01-slope.pdf | analyse-4b-slope-block | block 01: slope analysis |
| interrogation-2b-slope-large-family.pdf | analyse-4b-b-large-family | block 01 for a large family: strip windows and sampled overlay |
| interrogation-2c-slope-stale-after-edit.pdf | analyse-4b-c-stale-after-edit | block 01 after a rule change: stale, with sensitivity |
| interrogation-3-block02-aggregate.pdf | analyse-4c-aggregate-block | block 02: aggregate |
| interrogation-3b-aggregate-colour-by-recording.pdf | analyse-4c-b-colour-by-recording | block 02 coloured by recording, relationship switched |
| interrogation-3c-aggregate-wired-from-spike-shape.pdf | analyse-4c-c-wired-from-spike-shape | the same aggregate block wired to a different analysis (spike shape) |

## analyse-training/ (`UI_analyse_training_v1.pen`): Analyse, training chain
| file | pen node | canvas caption |
|---|---|---|
| training-0-training-chain.pdf | analyse-5-0-training-chain | the training chain: built on one channel, applied across the corpus in Discovery |
| training-0b-human-window-source-ILLUSTRATIVE.pdf | analyse-5-0b-human-window-source | ILLUSTRATIVE and out of scope: the same chain started from human-labelled windows |
| training-01-block01-sliding-windows.pdf | analyse-5-01-sliding-windows | block 01, sliding windows: windows, stride and the blocked split |
| training-1-block02-window-matrix.pdf | analyse-5a-matrix-block | block 02: window matrix |
| training-2-block03-cluster.pdf | analyse-5b-cluster-block | block 03: cluster |
| training-2b-block03-choose-k.pdf | analyse-5b-b-choose-k | block 03: choosing k, and how clusters line up with human verdicts |
| training-3-block04-encode.pdf | analyse-5c-encode-block | block 04: encode |
| training-4-block05-model.pdf | analyse-5d-model-block | block 05: model |

## discovery/ (`UI_discovery_v1.pen`)
| file | pen node | canvas caption |
|---|---|---|
| discovery-1-runs.pdf | discovery-1-runs | Runs: apply templates and seeds across channels (scrolling page) |
| discovery-1b-add-template.pdf | discovery-1b-add-template | Add runs: template picker (models are applied in Models) |
| discovery-1c-many-channels.pdf | discovery-1c-many-channels | six channels in scope: plots page three at a time (a crop of frame 1) |
| discovery-2-seed.pdf | discovery-2-seed | Seed search: set up a seed run (scrolling page) |
| discovery-3-compare.pdf | discovery-3-compare | Compare two runs: template run A against seed run B |
| discovery-3b-stages.pdf | discovery-3b-stages | Compare every stage: one disagreement pushed through both runs |

## models/ (`UI_models_v1.pen`)
| file | pen node | canvas caption |
|---|---|---|
| models-1-launch.pdf | models-1-launch | Launch a training job: the template decides the source; paired label arms |
| models-1b-launch-from-window-set.pdf | models-1b-launch-from-window-set | launch from a saved window set; the split comes with the set (B14, B12) |
| models-3-results.pdf | models-3-results | Results: one arm on the test block, against baseline and nulls, with per-class calibration |
| models-4-compare.pdf | models-4-compare | Compare A / B: manual vs cluster labels, paired on the same test windows |
| models-4b-compare-both-wrong.pdf | models-4b-compare-both-wrong | compare, stepping through windows both arms got wrong (B14) |
| models-5-registry.pdf | models-5-registry | Registry: registering needs held-out checks and human sign-off; retiring is blocked while templates use the model |

## review/ (`UI_review_v1.pen`)
| file | pen node | canvas caption |
|---|---|---|
| review-1-candidate.pdf | review-1-candidate | one candidate from the Discovery queue, rails collapsed |
| review-1b-other-channels.pdf | review-1b-other-channels | other channels, one click away |
| review-2-cluster.pdf | review-2-cluster | cluster of seed-search matches, with member strip |
| review-3-queue-open.pdf | review-3-queue-open | queue rail open: named queues, filters, up next |
| review-4-evidence-open.pdf | review-4-evidence-open | evidence rail open: origin, detection, family, artifact, history |
| review-5-blind-verification.pdf | review-5-blind-verification | blind queue: model verification sample, class keys |
| review-6-seed-promoted.pdf | review-6-seed-promoted | a seed verdict promotes to the Library |
| review-7-batch-undone.pdf | review-7-batch-undone | after undoing a batch verdict |

## library/ (`UI_library_v2.pen`)
| file | pen node | canvas caption |
|---|---|---|
| library-1-recurrence.pdf | library-1-recurrence | recurrence: where each family occurs, per hour |
| library-2-atlas-motifs.pdf | library-2-atlas-motifs | atlas: grouped as single motifs by shape |
| library-2b-atlas-sequences.pdf | library-2b-atlas-sequences | the same catalogue regrouped as sequences |
| library-3-family.pdf | library-3-family | family: exemplar and medoid, every member, hand edits |
| library-4-edit-grouping.pdf | library-4-edit-grouping | edit grouping: unit, basis, what does not fit, hand edits |
| library-5-empty-import.pdf | library-5-empty-import | empty library and the motif import (dry run) |
| library-6-window-sets.pdf | library-6-window-sets | window sets: saved, reusable, with split and train-safety |
| library-7-templates.pdf | library-7-templates | templates: every saved chain, its versions and scores with scope |

## jobs/ (`UI_jobs_v1.pen`)
| file | pen node | canvas caption |
|---|---|---|
| jobs-1-all.pdf | jobs-1-all | every job across workspaces: paused runs, cluster jobs, local jobs, review queues |
| jobs-2-paused-run.pdf | jobs-2-paused-run | a paused run: where it stopped; its result arrived in place |
| jobs-3-upload-and-continue.pdf | jobs-3-upload-and-continue | upload results and continue: checked before placing; mismatched parameters refused |
| jobs-4-cluster-job-inbox.pdf | jobs-4-cluster-job-inbox | a cluster job (hand-marked status, reminder, script) and the manifest inbox |

## settings/ (`UI_settings_v1.pen`)
| file | pen node | canvas caption |
|---|---|---|
| settings-01-datasets.pdf | settings-1-datasets | datasets: recordings, metadata, held-out lock |
| settings-01b-import-recording.pdf | settings-1b-import-recording | import a recording: a dry run of file, sampling rate, channel map, start time, checks (B20) |
| settings-02-channels-events.pdf | settings-2-channels-events | channels and events: per-channel metadata and a timed event log |
| settings-03-vocabulary.pdf | settings-3-vocabulary | vocabulary: verdicts, classes, tags |
| settings-04-nulls.pdf | settings-4-nulls | nulls: one default per analysis kind, always on |
| settings-05-analysis-defaults.pdf | settings-5-analysis-defaults | analysis defaults: matching rule, recommended values (D4), artifact likelihood, step cache |
| settings-06-compute-hpc.pdf | settings-6-compute-hpc | compute & HPC: this machine, local limits per workspace, clusters, job profiles |
| settings-07-blocks.pdf | settings-7-blocks | blocks: the analysis block registry |
| settings-08-review-queues.pdf | settings-8-review-queues | review queues: blind defaults per source, clusters, promotion |
| settings-09-models-registration.pdf | settings-9-models-registration | models & registration: split, training, calibration, registration gate |
| settings-10-library-groupings.pdf | settings-10-library-groupings | library groupings: defaults, sequences, feature bases, hand edits |
| settings-11-storage-backups.pdf | settings-11-storage-backups | storage & backups: every root with its size, naming, database backups |
| settings-12-export.pdf | settings-12-export | export: what leaves the tool, per artifact kind |
| settings-13-audit-log.pdf | settings-13-audit-log | audit log: locks, sign-offs, hand edits, vocabulary, settings, HPC status |
| settings-14-about.pdf | settings-14-about | about: versions, environment, diagnostics, future scope |
| settings-15-display.pdf | settings-15-display | display (personal): theme, units, colours, view sizes, report figure profile |
| settings-16-keyboard-behaviour.pdf | settings-16-keyboard-behaviour | keyboard & behaviour (personal): key map with conflict check, adjudication behaviour |
