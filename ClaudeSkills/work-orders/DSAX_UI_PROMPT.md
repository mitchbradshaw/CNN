# Work order: bring dSAX into the UI

You are working autonomously in the CNN repo. **I have stepped away from the computer and will not answer questions.** Do not stop to ask anything. Where this brief is ambiguous, or where you disagree with it, make a reasonable decision, implement it, and justify the choice in the summary document. Never block; never leave the work half-finished waiting for input.

This is the follow-up to `DSAX_IMPLEMENTATION_PROMPT.md`. **Read `Working/Detection/sax/dsax_python/IMPLEMENTATION_NOTES.md` in full before writing any code** — especially §6.3 (Lloyd-Max is not a noise floor), §7 (known limitations) and §8 (promotion checklist). §8 step 5 is the core of this work order. That document is the specification for everything dSAX already does; this one only covers what changes.

---

## 0. Hard constraints

1. **Snapshot `UI/` before touching it.** First action of the session, before any edit:
   `cp -r UI "Working/Detection/sax/dsax_python/UI_snapshot_<YYYYMMDD-HHMM>/"` (or the PowerShell equivalent). Record the exact path at the top of the summary. `UI/` contains uncommitted work of mine — `app.py`, `plots.py`, `run_panel.py` are modified and `admin.py`, `file_import.py`, `run_history.py` are untracked. That snapshot is my only rollback.
2. **No git state changes.** No `commit`, `push`, `checkout`, `stash`, `reset`, `clean`, `mv`. `git status` / `git diff` for inspection only. Where §8 of the notes says `git mv`, use a plain filesystem copy + delete instead and say so.
3. **Do not modify `Working/Detection/sax/csax_python/csax.py` or `psax_python/psax.py`.** Both are dirty with my own edits, and §8 step 5(a) of the notes proposes adding a `cutline_domain` key to them. **Do not do that.** §2.2 below specifies a resolution that needs no encoder change.
4. **Do not modify `Adapters/_sax_common.py`** beyond what §4.2 explicitly permits (the `-0.0` entropy fix), and do that only as a separate, clearly-labelled one-line change.
5. **Do not change dSAX's numerical behaviour.** `dsax()`'s outputs must stay bit-identical. You may add keys to its `details` dict and add new helper functions to its module; you may not alter existing values, cutline placement, or estimator maths. `tests/test_dsax.py` and `tests/test_dsax_engineered.py` must continue to pass unmodified, except for the two assertions §1 requires you to invert.
6. **No package installation.** numpy, scipy, matplotlib, panel, holoviews, datashader, bokeh — all already present. Nothing new.
7. **Do not touch** the real SQLite database, any `.npy` memmap, any `.mat` file, or `Results/`. Tests build their own temp fixtures; follow whatever `tests/test_encoding_view.py` already does.
8. **Do not attempt to fix unrelated known bugs.** In particular the ribbon-pane x-range linking issue is out of scope. If you notice something, write it in the summary.
9. **House style.** Read `UI/plots.py`'s module docstring and `build_encoding_panels`'s docstring first. That file records *why* each HoloViews decision was made and what was empirically confirmed. Match it. Any new panel logic must respect the same rules: `axiswise=True` on every leaf element, sizing opts set once on the DynamicMap, `hooks` combined into one list inside the per-frame callback, `"time_s"`/`"amplitude"` kdim/vdim names.

---

## 1. Phase A — promote the adapter

Follow §8 steps 1–4 of `IMPLEMENTATION_NOTES.md`. Concretely:

- Copy `Working/Detection/sax/dsax_python/adapter_draft.py` → `Adapters/detection_sax_dsax.py`, then delete the draft.
- Restore module-level `register(SPEC)`; delete `register_dsax_adapter()`.
- Replace the module docstring (which currently explains at length why the file is *not* under `Adapters/`) with a `detection_sax_psax.py`-style one-paragraph description. Keep the note explaining why `plot` points at `plot_trend_encoding` rather than the shared renderer — that reasoning is still live.
- Invert `tests/test_dsax.py::test_discover_adapters_does_not_register_dsax` to assert presence, and repoint `test_adapter_draft_spec_is_well_formed`, `test_adapter_draft_run_and_derive_actually_work` and `test_adapter_draft_zero_sentinels_mean_unset` at `Adapters.detection_sax_dsax`. Rename them if `_draft` in the name is now misleading.
- Check `tests/test_sax_adapters.py` — it enumerates registered adapters and may assert on a count. Update if so.

---

## 2. Phase B — make the encoding view render dSAX correctly

**This is the substance of the work order.** `UI/plots.py::build_encoding_panels` currently assumes amplitude-domain quantisation throughout. Read `IMPLEMENTATION_NOTES.md` §8 step 5 for the full statement of why it cannot render dSAX as it stands; the short version is that `paa_raw` is a level in mV and `cutlines_raw` is a threshold on a rise in mV-per-segment, and drawing them on one y axis is dimensionally meaningless — on a real fungal channel the delta cutlines would collapse to a sliver near zero and it would look like a dSAX bug.

### 2.1 Take option (b), not option (a)

The notes offer a minimal fix (branch the quantisation panel) and a better one (drive the panels off whichever of `paa_raw`/`deltas_raw` is present, so a future value+trend encoder can show both). **Implement (b).** dSAX already populates `paa`/`paa_raw` specifically so this costs nothing, and (a) would have to be rewritten to get there. If while implementing you find (b) genuinely does not work in this architecture, fall back to (a), implement it fully, and explain the blocker in the summary — do not deliver a half-done (b).

### 2.2 How to know which domain you are in — no encoder change

Add to `dsax()`'s `details` (its own file, permitted by §0.5): `cutline_domain = "delta"`. Then in the UI resolve it with a documented duck-typed fallback:

```python
def cutline_domain(details):
    """Which quantity the cutlines are a threshold on. Declared by newer
    encoders; inferred for cSAX/pSAX, whose details dicts predate the key
    and which must not be edited (they carry unrelated uncommitted work).
    Absence of a `deltas` key is a reliable negative: no amplitude-domain
    encoder in this repo produces one."""
    return details.get("cutline_domain") or ("delta" if "deltas" in details else "amplitude")
```

Put it in `UI/plots.py` next to `_band_edges`, and unit-test all three paths (declared delta, inferred delta, inferred amplitude).

### 2.3 What each panel does in each domain

| Panel | amplitude (cSAX/pSAX) — **must not change** | delta (dSAX) |
|---|---|---|
| 1 Signal | unchanged | unchanged |
| 2 "PAA over signal" | grey signal + red PAA bars | grey signal + **per-segment trend lines**, one line per segment from `seg_slope_raw`, coloured by symbol. Title "Segment trends over signal". Same `hv.Segments` construction as the PAA bars — endpoints are `(seg_t[i], level - rise/2)` to `(seg_t[i+1], level + rise/2)`, centred on `paa_raw[i]` so the line sits on the signal it describes. |
| 3 Quantisation | PAA step curve + cutline HLines + shaded bands, y = amplitude | **`deltas_raw` step curve + cutline HLines + shaded bands, y = rise per segment.** Same code path, different arrays. Axis label "rise per segment"; title "Quantisation — segment rise vs. learned cutlines". Bands and labels are otherwise identical. |
| 4 Symbol strip | unchanged shape | unchanged shape, but letters and hover come from §3 |

Panel 3's y-range logic (union of visible values and *all* cutlines, padded) is correct as written — it just needs `deltas_raw` substituted for `paa_raw`. Keep the existing comment explaining why all cutlines are included.

**Panel 4's hover tuple** currently reads `cutlines_raw[symbols[i]-1] … paa_raw.min()/max()` for the band bounds and `paa_raw[i]` for the value. In delta mode all three must come from the delta arrays. Add the segment's `paa_raw[i]` as an *additional* hover field labelled "level" in both modes — knowing the absolute level a trend occurred at is exactly the context a reader needs, and it is free.

### 2.4 Do not regress the amplitude path

The single largest risk in this phase is silently changing how cSAX/pSAX render. Structure the change so the amplitude path is the same code it is today, taking the same arrays, and add tests that pin it (§6.2).

---

## 3. Phase C — letters, strings, legend, persistence

### 3.1 D/S/U instead of a/b/c

`symbol_to_letter` / `symbols_to_string` / `symbols_to_rle` are shared by cSAX and pSAX and **their default behaviour must not change**. Add an optional alphabet:

```python
def symbols_to_string(symbols, letters=None): ...
def symbols_to_rle(symbols, letters=None): ...
def symbol_label(i, letters=None): ...   # letters[i] if given, else symbol_to_letter(i)
```

`letters=None` reproduces today's output exactly. Then add a resolver:

```python
def symbol_letters(details):
    """The per-symbol display letters for an encoding, or None for the
    default a/b/c convention. dSAX at k=3 reads D/S/U, which is the whole
    point of a trend alphabet being regex-searchable."""
```

Source it from `Working.Detection.sax.dsax_python.dsax.SYMBOL_NAMES` — take each name's first character (`DOWN`→`D`, `SAME`→`S`, `UP`→`U`; at k=5, `DOWN2`/`DOWN1`/`SAME`/`UP1`/`UP2` collide on first characters, so use the §5 mapping instead). Return `None` for any encoding without a declared alphabet.

Thread `letters` through: the string box, the RLE box, the colour key, the legend table, panel 3's band labels, panel 4's strip letters, and the motif seed string.

### 3.2 Legend table

`_build_legend_html`'s "Value range" column is labelled in raw amplitude units. In delta mode it must read from the delta cutlines and be labelled "Rise range". Add a `SAME` row highlight (the middle bin at odd `alphabet_size`) so the zero-anchored band is visually obvious. Keep the column set and layout otherwise identical.

### 3.3 Persistence

`_persist_sax_encoding` writes `encoding_type` `"sax_csax"` / `"sax_psax"`. Extend to `"sax_dsax"` — find how `algorithm_short` is derived and extend that, don't special-case at the call site.

Two real problems to solve, not paper over:

- The cached `.txt` must contain the same string the UI displays, so pass the dSAX letters into `symbols_to_string` at the persist site as well as the display site.
- `_show_encoding_string_only` renders a cached string with **no `details`**, so it cannot know the alphabet. The `encoding_type` on the cached row is available — use it to recover the alphabet. If that is not reachable at that call site, display the string as stored (it was written with the right letters, so it is correct) and note the asymmetry in the summary rather than inventing a lookup.

Also: the `motifs` table's `sax_string` column will now hold two different alphabets. `encoding_type` makes it recoverable, but flag it in the summary as a schema smell I may want to address later.

---

## 4. Phase D — diagnostics and the noise-floor button

### 4.1 Extra diagnostic rows for delta encodings

`Adapters._sax_common.diagnostic_rows` is shared and mostly domain-agnostic (occupancy entropy, self-transition rate). Do **not** rewrite it. Add a dSAX-specific supplement — a new function in `Adapters/detection_sax_dsax.py` or in the dsax module, called by the run panel and appended to the shared rows:

- **SAME fraction**, with severity `"warn"` when it falls in 0.40–0.60, and the note: *"roughly half of segments are labelled UP or DOWN. Pure noise produces 53% by MSE-optimal quantisation alone — see IMPLEMENTATION_NOTES §6.3. Check against a noise-floor estimate before reading this as structure."*
- **SAME band half-width**, in raw units, and whether `min_same_halfwidth` was applied (`details["min_same_halfwidth_applied"]`).
- **Mean delta**, raw units, with severity `"warn"` when `|mean| > 0.25 × SAME half-width` and the note that this indicates residual drift and that detrending is not optional on electrode data (§7.3 of the notes).
- **Cutline degeneracy** flag when set, with an `"error"` severity and a plain-language explanation of which of the two degenerate cases fired (§2.4/§2.5 of the notes distinguish them — surface that distinction, don't collapse it).

### 4.2 The `-0.0` entropy fix

Apply the one-line fix from `IMPLEMENTATION_NOTES.md` §4.2 to `Adapters/_sax_common.py`. This is the only permitted change to that file. Keep it as an isolated edit, and confirm no existing test asserts on the `-0.0`.

### 4.3 "Estimate noise floor" button

The most important scientific gap in the current UI. Add a button to the encoding section, visible only for delta-domain encodings, that on click:

1. Runs `surrogate_same_halfwidth` on the exact array that was encoded (`self._last_encoding`'s `x`), with the run's own `trend_estimator` and `samples_per_symbol`, at α = 0.95.
2. Reports, in a status pane: the learned SAME half-width, the surrogate half-width, the ratio, and the SAME fraction that would result if the floor were imposed.
3. Offers the surrogate value as a number the user can copy into the `min_same_halfwidth` control — and if the control is trivially settable from code, set it directly with a message saying it has been set and the run must be repeated for it to take effect. **Do not silently re-run** anything.
4. Makes an explicit recommendation only in the form the evidence supports: if the ratio exceeds ~1.5, say the learned band is materially narrower than the noise floor and that a large share of UP/DOWN labels are likely to be noise.

Guard it: surrogates are `n_surrogates × FFT` on the whole span. Disable the button above a span-length threshold you choose, or run a documented subsample, and say which in the button's tooltip. Report the runtime in the status pane. Never block the UI thread without a "computing…" indication.

Add an α control (default 0.95) next to it if that is cheap; the correct false-positive rate is a scientific choice, and hard-coding it hides the choice.

---

## 5. Phase E — 5-symbol alphabet polish

`alphabet_size` is exposed 2–9 and §6.5 of the notes confirms the cutline pipeline is not hard-wired to 3, but nothing in the UI is written for k≠3.

- Letters for k=5: use `d`/`D`/`S`/`U`/`u` — lower case for the outer (stronger) bins, upper for the inner, `S` for SAME. Pick a different scheme if you can justify a better one; the constraints are that it must be single-character (the string/RLE/strip all assume one char per symbol), unambiguous, and visually orderable. Whatever you choose, define it once in the dsax module beside `SYMBOL_NAMES` and derive the UI from it.
- Legend and colour key must show the full name (`DOWN2`, `UP1`, …) alongside the letter.
- Even alphabet sizes have **no SAME bin** (§7.7 of the notes). The legend and diagnostics must say so plainly rather than showing a SAME row that does not exist, and the `min_same_halfwidth` control should be visibly inert (disabled with a tooltip) at even sizes.
- Colours must stay perceptually ordered and diverging about the centre — check `SYMBOL_CMAP_NAME` is suitable for a zero-anchored alphabet and change it *for the delta domain only* if not, justifying the choice.

---

## 6. Phase F — regex morphology search

The payoff feature: it turns my tag vocabulary (sharkfin, rollinghill, crestedwave, …) into detectors.

- A text input in the encoding section, visible for any encoding (not just delta — cSAX strings are searchable too), taking a Python regex over the symbol string.
- On submit, find all matches over the **whole-span** string (not the visible slice — searching only what is on screen is a trap) and:
  - highlight the matching segment spans in panel 4, as an overlay that does not disturb the existing `Rectangles`-only branch structure (see the DynamicMap type-switching note in `UI/plots.py` — do not introduce a branch that returns a different element type on different frames);
  - report a match count and let the user step through matches, recentring the x-range on each via the existing `range_stream`;
  - show the time span of the current match in seconds.
- Handle an invalid regex by showing the error next to the box; never raise into the Panel callback.
- Seed the box with a `UD{3,}` placeholder and a one-line hint that this is the sharkfin pattern, so the feature explains itself.
- **Cap the work**: `re.finditer` over a 100k-character string is fine, but rendering 10k highlight rectangles is not. Cap the rendered highlights at a documented number, and say in the UI when the cap was hit.

Wire the matches into the existing "Save this encoding as a motif seed" flow if it is cheap — saving the *matched pattern* alongside the string is the natural next step. If it is not cheap, leave it and note it as follow-on work.

---

## 7. Tests

Extend, do not rewrite. Read `tests/test_encoding_view.py` first — it already drives the run panel end-to-end headlessly and is the established pattern. Follow the same conventions as `tests/test_dsax.py`: repo-root `sys.path` bootstrap, plain `assert`, `_run_all()` runner, ASCII-only output (the cp1252 issue from `BASELINE.md`), explicit seeding.

### 7.1 Baseline again

Re-run the full suite and refresh `Working/Detection/sax/dsax_python/BASELINE.md` (append a second dated section; do not overwrite the first). `test_encoding_view` was 10/10 at the end of the last session — that is the number to protect.

### 7.2 Regression pins for the amplitude path — the important ones

- For a cSAX and a pSAX run, `cutline_domain(details) == "amplitude"`.
- Panel 3 in amplitude mode still plots `paa_raw`, and its cutline HLine positions still equal `details["cutlines_raw"]` exactly.
- `symbols_to_string(symbols)` with no `letters` argument is byte-identical to its pre-change output for a fixed symbol array.
- The existing `test_encoding_view` tests pass unmodified.

### 7.3 New coverage

- `cutline_domain` across all three resolution paths.
- Delta mode: panel 3 plots `deltas_raw`, its y-axis label is the rise label, band count equals `alphabet_size`, cutline positions equal `details["cutlines_raw"]`.
- Panel 2 in delta mode draws exactly `n_symbols` trend segments and each one's rise equals `deltas_raw[i]`.
- `symbols_to_string(symbols, letters=("D","S","U"))` produces `"DSU…"`; RLE likewise.
- End-to-end: run the dSAX adapter through the run panel the way `test_encoding_view` runs cSAX, and assert the encoding section populates — panels, string, RLE, colour key, legend, diagnostics.
- Diagnostics: a pure-noise dSAX run trips the SAME-fraction warn; an undetrended drift run trips the mean-delta warn; a constant signal trips the degeneracy error with the correct one of the two cases named.
- Regex search: a known sharkfin fixture with `UD{3,}` returns exactly the expected match count and spans; an invalid regex is reported rather than raised; the highlight cap fires and is announced.
- Noise-floor button: on the §6.3 fixture it reports a ratio in the region of 3× and does not mutate the encoding.
- k=5 and k=4: the letter map is single-character and unique; the even-size path reports "no SAME bin" and disables `min_same_halfwidth`.

### 7.4 Headless verification of what actually renders

Do not trust "it constructed without error". Verify the Bokeh model, the way `UI/plots.py`'s own docstring records doing:

```python
fig = hv.render(dmap[key], backend="bokeh")
```

then assert on axis labels, renderer counts, and `Range1d` start/end. That docstring documents two real bugs found exactly this way; use the same technique.

Also produce a **static HTML preview** for me to open when I get back: a synthetic dSAX run (use the sharkfin and mixed_sine_noise fixtures from `tests/test_dsax_engineered.py::ENGINEERED` — import them, do not redefine them) rendered at a fixed x-range and saved to `Experimentation/Detection experiments/dsax_validation/dsax_ui_preview.html`, plus the cSAX equivalent beside it as `csax_ui_preview.html` so I can compare the two domains side by side. If `DynamicMap` will not save cleanly, render the four panels at one fixed range as plain Overlays and save those.

---

## 8. Summary document

`Working/Detection/sax/dsax_python/UI_INTEGRATION_NOTES.md`, same standard as `IMPLEMENTATION_NOTES.md` — that document was genuinely good, match it. Required sections:

1. **Snapshot path** (§0.1) and the `git status --porcelain` before and after, so I can see exactly which of my uncommitted `UI/` files you touched.
2. **What changed, file by file**, with a short diff summary per file.
3. **Every judgement call, with justification.** The k=5 letter scheme, the highlight cap, the noise-floor span threshold and α, the (b)-vs-(a) outcome, the colour map decision — all of it.
4. **Deviations from this brief**, separately and prominently.
5. **Test results**, and the diff against both `BASELINE.md` sections. State plainly whether anything regressed, and specifically whether `test_encoding_view` is still 10/10.
6. **Anything I need to decide**, particularly whether `min_same_halfwidth` should become a default (§8 step 6 of the notes) now that the button exists to measure it.
7. **Follow-on work** — including anything you noticed in `UI/` and deliberately did not touch per §0.8.

---

## 9. Definition of done

- dSAX appears in the run panel's algorithm list and produces a correct, dimensionally honest encoding view.
- cSAX and pSAX render exactly as they did before — pinned by tests, not by inspection.
- All dSAX tests, all encoding-view tests, and the full pre-existing suite pass with no regressions against `BASELINE.md`.
- `dsax_ui_preview.html` and `csax_ui_preview.html` exist and open.
- The `UI/` snapshot exists at the path recorded in the summary.
- `UI_INTEGRATION_NOTES.md` is complete.

**Do not leave failing tests.** If a test cannot pass because its expectation was wrong rather than the code, fix the expectation and flag it prominently — a silently weakened test is worse than a failing one. You handled this correctly last time (§2.13 of the notes); do the same.

If you run short on time, cut in this order and say so in the summary: Phase F (regex search) → Phase E (5-symbol polish) → §4.3's α control → the `csax_ui_preview.html` comparison. **Never cut:** Phase A, Phase B, the §7.2 amplitude-path regression pins, or the summary document. A half-finished Phase B is worse than no Phase B — if you cannot complete it, revert your `UI/` changes from the snapshot and say why.
