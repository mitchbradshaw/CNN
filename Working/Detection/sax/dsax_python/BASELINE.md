# Pre-existing test-suite baseline (before any dSAX work)

Recorded per §1 of `DSAX_IMPLEMENTATION_PROMPT.md`, so that pre-existing
failures can be told apart from anything the dSAX work introduces.

- **Date:** 2026-08-09
- **Branch:** `restructure/four-stage-layout`
- **HEAD:** `13724ab` (working tree dirty — this is a snapshot of the tree
  as handed over, not of a clean commit)
- **Python:** 3.13.6 (CPython, win32) · numpy 2.3.2 · scipy 1.16.1 ·
  matplotlib 3.10.8
- **Command per file:** `python tests/<file>.py` from the repo root

## Is pytest available?

**No.** `python -m pytest tests -q` fails with
`No module named pytest`, and `import pytest` fails likewise. Installing it
is forbidden by §0.5, so the whole suite runs through each file's own
module-level `_run_all()` runner. The two new dSAX test files are written to
work under pytest *if* it is ever installed (plain `test_*` functions, plain
`assert`, no fixtures), but that path is untested here because it cannot be
exercised in this environment.

## Results

| File | Exit | [PASS] | [FAIL]/[ERROR] | Note |
|------|-----:|-------:|---------------:|------|
| test_analysis_modules | **1** | — | — | **Pre-existing failure — see below.** Own summary line reports `195/195 tests passed`; the non-zero exit is a console-encoding crash, not a test failure |
| test_artifacts | 0 | 9 | 0 | |
| test_database | 0 | 18 | 0 | |
| test_encoding_cache | 0 | 6 | 0 | |
| test_encoding_panels | 0 | 5 | 0 | |
| test_encoding_view | **1** | 9 | **1** | **Pre-existing failure — see below** |
| test_execution | 0 | 8 | 0 | |
| test_filters | 0 | 9 | 0 | |
| test_import_10min_labels | 0 | 3 | 0 | |
| test_import_signal_catalogue | 0 | 20 | 0 | |
| test_materialize_arbitrary_file | 0 | 6 | 0 | |
| test_materialize_channels | 0 | 6 | 0 | |
| test_overlay_density | 0 | 10 | 0 | |
| test_recipes | 0 | 16 | 0 | |
| test_reviewed_coverage | 0 | 15 | 0 | |
| test_ribbon_panes | 0 | 8 | 0 | |
| test_run_panel | 0 | 9 | 0 | |
| test_sax_adapters | 0 | 15 | 0 | |
| test_sax_details | 0 | 16 | 0 | |
| test_session_persistence | 0 | 10 | 0 | |
| test_shortcuts_and_view_controls | 0 | 5 | 0 | |
| test_similarity | 0 | 20 | 0 | |
| test_ui_selection | 0 | 13 | 0 | |
| test_vocabulary_and_bands | 0 | 12 | 0 | |

**Totals: 22 of 24 files exit 0. 2 files fail, both for reasons unrelated to
SAX/dSAX.**

`test_analysis_modules` reports no `[PASS]` lines because it uses a different
per-module reporting format (`[tested]`/`[smoke]`) and one final
`SUMMARY: n/n` line, rather than the `[PASS]`/`[FAIL]` convention the rest of
the suite uses.

## The two pre-existing failures, in detail

### 1. `test_analysis_modules` — Windows console encoding, not a test failure

```
File "tests/test_analysis_modules.py", line 904, in run_all
    print(f"\n{'\u2500' * 70}")
  File "C:\Python313\Lib\encodings\cp1252.py", line 19, in encode
UnicodeEncodeError: 'charmap' codec can't encode characters in position 2-71
```

The suite itself passes completely — the crash happens in the *summary
printer*, after every test has run, when a U+2500 BOX DRAWINGS LIGHT
HORIZONTAL is written to a cp1252 stdout. Re-running the identical file with
`PYTHONIOENCODING=utf-8` gives:

```
SUMMARY: 195/195 tests passed
exit=0
```

So this is an environment artefact (Windows default code page), not a code
defect, and it is entirely independent of anything dSAX touches. Fixing it
would mean editing an existing file, which §0.3 forbids; it is recorded under
"Requested upstream changes" in `IMPLEMENTATION_NOTES.md` instead.

**Consequence for the final diff:** the dSAX test files must not print
non-ASCII to stdout, or they will hit the same wall. They print ASCII only.

### 2. `test_encoding_view::test_running_csax_populates_encoding_section`

```
[FAIL] test_running_csax_populates_encoding_section:
9/10 passed
```

A bare assertion failure with no message, in a UI-integration test that
drives `UI/app.py`'s run panel end-to-end against real channel data. The
other nine tests in the same file pass, including the sibling tests that
also call `_channel_available()`, so the data guard is being satisfied and
this is a genuine assertion failure inside the run/refresh path.

It is **not** investigated or fixed here: it lives under `UI/`, which §0.1
puts strictly out of bounds, and dSAX adds no adapter to the registry
(§5) so it cannot influence what the run panel lists or runs.

## Re-run protocol at the end of the work

Re-run exactly the same 24 files with exactly the same command, and diff
against this table. **Expected end state: the same two files failing for the
same two reasons, and every other file still exit 0**, plus two new files
(`test_dsax.py`, `test_dsax_engineered.py`) at exit 0.

---
---

# Section 2 — baseline after the dSAX UI integration

Recorded per §7.1 of `DSAX_UI_PROMPT.md`. **Appended, not overwriting** —
Section 1 above is the pre-dSAX state and stays as written.

- **Date:** 2026-08-10
- **Branch:** `restructure/four-stage-layout` · HEAD `13724ab` (tree still
  dirty; this is a working-tree snapshot, not a commit)
- **Environment:** unchanged from Section 1 — Python 3.13.6, numpy 2.3.2,
  scipy 1.16.1, matplotlib 3.10.8, panel 1.9.3. **pytest is still not
  installed**, so the suite still runs through each file's `_run_all()`.
- **Command per file:** `python tests/<file>.py` from the repo root
- **What changed in between:** dSAX promoted into `Adapters/`, the encoding
  view made quantisation-domain aware, and the run panel given trend
  diagnostics, a noise-floor estimator and a morphology regex search. See
  `UI_INTEGRATION_NOTES.md`.

## Results

| File | Exit | [PASS] | [FAIL]/[ERROR] | vs. Section 1 |
|------|-----:|-------:|---------------:|---------------|
| test_analysis_modules | **1** | — | — | **unchanged** (same cp1252 crash after 195/195 pass) |
| test_artifacts | 0 | 9 | 0 | unchanged |
| test_database | 0 | 18 | 0 | unchanged |
| **test_dsax** | 0 | **33** | 0 | was 32 — +2 new, −1 renamed/merged (see notes §5) |
| **test_dsax_engineered** | 0 | **17** | 0 | unchanged |
| test_encoding_cache | 0 | 6 | 0 | unchanged |
| test_encoding_panels | 0 | 6 | 0 | unchanged |
| **test_encoding_view** | 0 | **10** | 0 | **unchanged — 10/10, the number §7.1 says to protect** |
| **test_encoding_view_dsax** | 0 | **46** | 0 | **NEW** |
| test_execution | 0 | 8 | 0 | unchanged |
| test_filters | 0 | 9 | 0 | unchanged |
| test_import_10min_labels | 0 | 3 | 0 | unchanged |
| test_import_signal_catalogue | 0 | 20 | 0 | unchanged |
| test_materialize_arbitrary_file | 0 | 6 | 0 | unchanged |
| test_materialize_channels | 0 | 6 | 0 | unchanged |
| test_overlay_density | 0 | 10 | 0 | unchanged |
| test_recipes | 0 | 16 | 0 | unchanged |
| test_reviewed_coverage | 0 | 15 | 0 | unchanged |
| test_ribbon_panes | 0 | 8 | 0 | unchanged |
| test_run_panel | 0 | 9 | 0 | unchanged |
| test_sax_adapters | 0 | 15 | 0 | unchanged |
| test_sax_details | 0 | 16 | 0 | unchanged |
| test_session_persistence | 0 | 10 | 0 | unchanged |
| test_shortcuts_and_view_controls | 0 | 5 | 0 | unchanged |
| test_similarity | 0 | 20 | 0 | unchanged |
| test_ui_selection | 0 | 13 | 0 | unchanged |
| test_vocabulary_and_bands | 0 | 12 | 0 | unchanged |

**Totals: 26 of 27 files exit 0. The one failure is `test_analysis_modules`,
identical to Section 1 and unrelated to any of this work.**

## Diff against Section 1

- **`test_encoding_view` went 9/10 → 10/10 between the two sections**, but
  that happened during the *previous* session and was not caused by it
  (see `IMPLEMENTATION_NOTES.md` §5.2). It is 10/10 here too, so the
  regression pin §7.1 asks for holds.
- **`test_analysis_modules` still exits 1**, for the identical
  cp1252-console reason. Unfixed because §0.3 of the first work order
  forbade editing it; the one-line diff is in `IMPLEMENTATION_NOTES.md`
  §4.1 and restated in `UI_INTEGRATION_NOTES.md`.
- **Nothing regressed.** No file lost a passing test. The only counts that
  moved, moved upward.

## Two files' test counts changed deliberately

- `test_dsax.py` 32 → 33: `test_discover_adapters_does_not_register_dsax`
  became `test_discover_adapters_registers_dsax` (inverted, as §1 of the
  UI work order requires), three `test_adapter_draft_*` tests were
  repointed at `Adapters.detection_sax_dsax`, and
  `test_dsax_letters_other_alphabets_use_the_repo_convention` was split
  into a k=5 test (new expectation, see `UI_INTEGRATION_NOTES.md` §4) and
  an undeclared-alphabet test.
- `test_encoding_view_dsax.py` is new: 46 tests, of which 20 run
  unconditionally (pure `UI.plots` / `Working` logic) and 26 are
  real-channel gated in the same way `test_encoding_view.py` is. All 46
  ran and passed here, so the gate was satisfied.
