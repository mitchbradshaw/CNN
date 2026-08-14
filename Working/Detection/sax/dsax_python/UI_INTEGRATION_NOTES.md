# dSAX UI integration — notes

Written against `DSAX_UI_PROMPT.md`, executed autonomously on 2026-08-10.
Companion to `IMPLEMENTATION_NOTES.md`, which remains the specification for
what dSAX *does*; this document only covers what changed to get it on
screen.

**All six phases are complete. Nothing was cut.** 46 new tests, 0 failures,
no regressions, and `test_encoding_view` is still **10/10** — the number
§7.1 named as the one to protect.

Three things I want you to read before anything else:

1. **I found a pre-existing crash in your uncommitted `UI/run_panel.py`**
   and fixed it as an unavoidable side effect. §7.1 below. It would have
   hit any encoding over 500 symbols.
2. **The k=5 letter change altered one existing test's expectation.** §4.1.
   Flagged rather than buried, per §9 of the brief.
3. **You need to decide whether `min_same_halfwidth` becomes a default**
   now that the button to measure it exists. §8.

---

## 1. Snapshot and git state

### 1.1 Snapshot path (§0.1)

```
Working/Detection/sax/dsax_python/UI_snapshot_20260810-0512/
```

Taken as the **first action of the session**, before any edit, with
`Copy-Item -Recurse`. It contains all eight files that were in `UI/` at
that moment (`app.py`, `plots.py`, `run_panel.py`, `admin.py`,
`file_import.py`, `run_history.py`, `README.md`, `__init__.py`, plus
`__pycache__`). It is your rollback.

### 1.2 `git status --porcelain` — before vs. after

The diff between the two is **exactly two lines**, both additions:

```
> ?? "Experimentation/Detection experiments/build_ui_previews.py"
> ?? tests/test_encoding_view_dsax.py
```

**That understates what changed, and the understatement matters**, so be
clear on why: `Adapters/`, `Working/Detection/sax/dsax_python/`, and the
`UI/*.py` files you have in flight were *already* dirty or untracked before
I started, so editing them does not move their porcelain status character.
Git status alone cannot tell you which `UI/` files I touched.

### 1.3 What I actually touched under `UI/` — proven against the snapshot

```
CHANGED  UI/plots.py       (+327 / -44)
CHANGED  UI/run_panel.py   (+550 / -32)
SAME     UI/app.py
SAME     UI/admin.py
SAME     UI/file_import.py
SAME     UI/run_history.py
SAME     UI/README.md
SAME     UI/__init__.py
```

**Only the two files Phase B–F require.** `app.py` — which you had modified
most recently before this session — is byte-identical to the snapshot, as
are all four of your untracked files. I audited every one of the 76 deleted
lines across the two changed files; each is a line I replaced with an
extended version, and nothing was dropped.

---

## 2. What changed, file by file

| File | Change |
|------|--------|
| `Adapters/detection_sax_dsax.py` | **NEW** (promoted). The draft, with module-level `register(SPEC)` restored, `register_dsax_adapter()` deleted, and the "why this is not under Adapters/" docstring replaced by a `detection_sax_psax.py`-style one — **keeping** the paragraph on why `plot` points at `plot_trend_encoding`, which is still live. Adds the noise-floor budget constants, `noise_floor_surrogate_count()`, and `delta_diagnostic_rows()`. |
| `Working/Detection/sax/dsax_python/adapter_draft.py` | **DELETED** (filesystem delete, not `git mv`, per §0.2). |
| `Working/Detection/sax/dsax_python/dsax.py` | Adds `cutline_domain: "delta"` to `details`; `SYMBOL_LETTERS`; and a post-hoc analysis block — `same_band_halfwidth`, `same_fraction_under_halfwidth`, `working_domain_array`, `trend_diagnostic_rows`, `degeneracy_explanation`. `dsax_letters` now reads `SYMBOL_LETTERS` (this is the k=5 change, §4.1). **No numerical behaviour changed** — `dsax()`'s symbol output is bit-identical, pinned by the unmodified `test_dsax_engineered.py`. |
| `Adapters/_sax_common.py` | **One line**, the permitted `-0.0` entropy fix (§4.2 of `IMPLEMENTATION_NOTES.md`), with a comment. Nothing else. |
| `UI/plots.py` | `cutline_domain`, `quantised_values`, `value_axis_label`, `symbol_cmap_name`, `symbol_letters`, `symbol_names`, `same_symbol_index`, `symbol_label`; `letters=` on `symbols_to_string`/`symbols_to_rle`; `cmap_name=` on `symbol_colors` + the diverging delta palette; `HighlightStream` + `ENCODING_HIGHLIGHT_CAP`; and `build_encoding_panels` made domain-aware across panels 2, 3 and 4. |
| `UI/run_panel.py` | Morphology-search widgets + 6 handlers; noise-floor button, alpha control and threaded worker; trend diagnostics appended to the shared rows; letters threaded through the string box, RLE box, colour key, legend, strip and motif seed; `Rise range` legend column + SAME-row highlight + even-alphabet notice; `min_same_halfwidth` gating; `encoding_type` carried to `_show_encoding_string_only`; `_persist_sax_encoding` takes `details`. Plus the incidental import fix in §7.1. |
| `tests/test_dsax.py` | Discovery assertion inverted; three adapter tests repointed and renamed (`_draft` dropped); letters test split (§4.1). |
| `tests/test_encoding_view_dsax.py` | **NEW**, 46 tests. |
| `Experimentation/Detection experiments/build_ui_previews.py` | **NEW**, builds the two static HTML previews. |
| `.../dsax_validation/{dsax,csax}_ui_preview.html` | **NEW** outputs. |
| `.../dsax_validation/metrics.json` + PNGs | Regenerated, so dataset 6's string reads `dDSUu` consistently with the new k=5 letters. |
| `BASELINE.md` | Section 2 appended (§7.1). Section 1 untouched. |

---

## 3. Every judgement call, with justification

### 3.1 Option (b), fully — the panels are driven off the arrays, not branched

§2.1 asked for (b) and warned against a half-done version. (b) is what is
there. The mechanism is two functions:

```python
cutline_domain(details)   # "delta" | "amplitude"
quantised_values(details) # deltas_raw | paa_raw  -- the array the cutlines decided on
```

Panel 3 — the quantisation panel, the one that would be dimensionally wrong
— has **no domain branch at all**. It reads `quant_values` and plots it. The
y-range logic, the band construction, the cutline `HLine`s, the label
placement are the identical code in both domains; only the array and two
strings differ. Panel 4's hover is likewise one code path over
`quant_values` plus a `level` field.

Only panel 2 genuinely branches, and it has to: a flat PAA bar and a sloped
trend line are different geometry, not different data. That is one `if`, at
the point where the geometry is built.

A future value+trend encoder (1d-SAX, TVA) therefore needs to populate
`paa_raw` *and* `deltas_raw` and declare a domain, and everything except
panel 2's `if` already works.

### 3.2 The domain is resolved once, outside the per-frame callbacks

`details` cannot change over a DynamicMap's lifetime, so the branch is
hoisted above the callbacks. This is not a style preference: `UI/plots.py`'s
own docstring (bug 3) records that a callback returning different element
*types* across frames raises an `AssertionError` that Panel silently
swallows, leaving the pane frozen. Resolving the domain at build time makes
that failure structurally impossible, and
`test_strip_composition_is_stable_across_frames_and_highlight_states`
asserts the element composition is identical with matches, without matches,
and across the letter-threshold branch.

### 3.3 The quantisation panel keeps the `"amplitude"` vdim name

Tempting to rename the delta panel's vdim to `"rise"`. I did not, for the
reason that file already documents: every element in one Overlay must share
a dimension name, or the *Overlay's* inferred axis label is corrupted
regardless of which element wins. The **displayed** label changes instead,
via the `ylabel` opt that was already being set explicitly. Cross-panel
`Range1d` sharing is prevented by the existing leaf-level `axiswise=True`,
which is unchanged and still pinned by
`test_encoding_panels::test_leaf_level_axiswise_prevents_cross_panel_range_sharing`.

### 3.4 A hand-built diverging palette, not `coolwarm`

§5 asked me to check `SYMBOL_CMAP_NAME` and change it *for the delta domain
only* if unsuitable. Viridis is sequential and correct for an ordered
amplitude alphabet; it is wrong for a zero-anchored one, where SAME is not
"the middle amount of rise" but "no rise", and deserves a neutral centre.

I did **not** use a stock diverging map (`coolwarm`, `RdBu`). Every one of
them is near-white at its midpoint, and the symbol strip draws its per-cell
letters in **white** — so the SAME cell's letter would be invisible, and
SAME is the most common symbol and the padding every morphology pattern is
stripped of. Instead: three hand-picked stops,

```
#2b5d9e  (blue)  ->  #6e6e6e  (neutral grey)  ->  #b03a2e  (red)
```

chosen so every interpolated bin has relative luminance ≤ 0.16, i.e.
contrast ratio ≥ 4.4 against white.
`test_delta_palette_is_diverging_and_dark_enough_for_white_text` computes
the WCAG luminance of each bin and asserts ≥ 4.0, and separately asserts the
middle bin is the least saturated — so "diverging with a neutral centre" is
a pinned property, not a claim.

Built on demand via `LinearSegmentedColormap.from_list`, **not** registered
in matplotlib's global registry: registering would be a process-wide side
effect of importing a plotting module, and would raise on re-import.

**The amplitude palette is untouched**, asserted by
`test_amplitude_encodings_get_no_letters_and_no_same_row`.

### 3.5 k=5 letters: `d D S U u`, as specified

I implemented the brief's scheme. Case encodes magnitude, letter encodes
direction, so `[Dd]` matches any fall and `[Uu]` any rise, and a
case-insensitive k=3 vocabulary pattern still matches at k=5 unrewritten.

I considered inverting the case (`D d S u U`, uppercase = *stronger*) on the
argument that uppercase is visually heavier, so the extreme excursions would
pop in the strip and the string — which is what you actually scan for. I
did not adopt it: it is a marginal aesthetic gain against an explicit spec.
**If you prefer it, it is a one-line change** to `SYMBOL_LETTERS` in
`dsax.py` and one test expectation; everything else derives from it.

Only k=3 and k=5 have declared letters. Every other size — **including every
even size** — falls back to a/b/c rather than inventing a scheme. Even sizes
are deliberate: they have no SAME bin at all, so a D/S/U-shaped mnemonic
would assert a symbol that does not exist.

### 3.6 Highlight cap: 500, on what is *drawn*, not on what is *found*

`re.finditer` over a 100k-symbol string is cheap; several thousand extra
Bokeh `Rectangles` per frame is not. So the run panel keeps the **full**
match list — the counter is exact and Prev/Next steps through all of them —
and passes only the first 500 to the highlight stream. The status pane says
so when the cap bites, and says that stepping still covers everything.
`test_morphology_search_announces_the_highlight_cap` uses the 3000-segment
noise fixture (822 matches) to prove the cap fires, is announced, and does
not truncate `_search_matches`.

500 is a judgement, not a measurement: it is roughly the point at which the
strip's own per-segment rectangles already dominate a frame, so the
highlights stop being the marginal cost.

### 3.7 Noise floor: flex the surrogate *count*, never the span

§4.3 offered "disable above a threshold, or run a documented subsample". I
did neither exactly, because **subsampling would be quietly wrong**:
phase-randomised surrogates preserve the magnitude spectrum, and the
spectrum *is* the null hypothesis. Subsample the signal and you change the
null, so the number returned would answer a different question while looking
like the right one.

Instead the surrogate **count** flexes against a fixed total-samples budget:

```
n_surrogates = clip(10_000_000 // n, 8, 50)
```

The pooled quantile is over `n_surrogates × n_segments` deltas, and a long
span already has many segments — 8 surrogates of a 2.6M-sample span pools
far more deltas than 50 of a 6k one. So the statistic stays well-supported
while the FFT cost stays bounded. A hard ceiling of 5M samples disables the
button entirely, with a message pointing out that the noise floor is a
property of the *signal*, not of the span, so estimating it on a shorter
stretch of the same channel is a valid thing to do.

Runtime is reported in the status pane. The work runs on a worker thread
with an immediate "Computing surrogates ..." indication.

### 3.8 α is a control, defaulting to 0.95

§4.3 called it "cheap if possible". It was, so it is there — a `FloatInput`
next to the button with a tooltip saying what the number means ("a rise this
big happens by chance in 5% of trend-free segments") and that the right
false-positive rate is a scientific choice. Hard-coding it would hide
exactly the decision `IMPLEMENTATION_NOTES.md` §6.3 says is yours.

### 3.9 The button fills the control in but suppresses the watcher chain

Setting `min_same_halfwidth` from the completion callback fires the widget's
normal `value` watcher, which schedules an auto-preview and refreshes the
derive table. Both are wrong here:

- an auto-preview would make a **diagnostic silently recompute the encoding
  it just measured** — the one thing §4.3 says not to do;
- `_refresh_derived`/`_sync_segment_mode_controls` read `self.conn`, and the
  callback runs on the *worker* thread whenever there is no live Bokeh
  document to defer to (`_run_on_ui_thread` falls back to calling directly).
  SQLite rejects that outright. **I hit this as a real traceback**, not a
  hypothetical: `sqlite3.ProgrammingError: SQLite objects created in a
  thread can only be used in that same thread.`

So there is a named `_suppress_param_watchers` guard, mirroring the existing
`_syncing_segment_controls` one, with the reasoning in a comment. The status
pane tells the user the value was set and that **a re-run is required**,
which is the deliberate action this replaces.
`test_noise_floor_button_reports_and_does_not_recompute` asserts the wording
is present and that neither the symbols nor the cutlines changed.

### 3.10 The match summary survives stepping

First implementation set a "N matches (cap notice)" status, then immediately
called `_focus_morphology_match(0)`, which overwrote it — so the cap notice
flashed once and vanished. Caught by the cap test. The summary is now held
in `_search_summary` and re-rendered above the per-match line on every step,
so the count and the cap notice are always visible.

### 3.11 Search is offered for *every* encoding, not just trend ones

§6 says "visible for any encoding" and I agree with the reasoning: a cSAX
string is just as searchable. Gating it on the domain would be an arbitrary
restriction on something that costs nothing. The default pattern `UD{3,}` is
dSAX-shaped, but it is a placeholder in an editable box, not a constraint.

### 3.12 Zero-width regex matches are dropped

`re.finditer` on a pattern like `U*` yields a zero-width match at every
position — thousands of them, each producing a zero-width highlight. They
are filtered (`m.end() > m.start()`) and the count reported reflects the
filter. A zero-width match is not a morphology.

### 3.13 The `level` hover field is present in both domains

§2.3 asked for it in both. In the amplitude domain it duplicates the PAA
value by construction, which I considered dropping as redundant — but kept,
because a consistent field set across encoders is worth more than removing
one duplicated row, and someone switching between cSAX and dSAX should not
have to re-learn the tooltip. Noted as a deliberate small redundancy.

### 3.14 dSAX constants live in the adapter, not `Working/config.py`

House style puts UI tuning constants in `Working/config.py`. I put the
noise-floor budget in `Adapters/detection_sax_dsax.py` and the highlight cap
in `UI/plots.py` instead, to avoid editing another of your uncommitted files
for four constants. They are all dSAX-specific and sit beside the code that
owns them. Move them if you prefer the convention; nothing depends on where
they live.

### 3.15 `_show_encoding_string_only` names the alphabet rather than guessing it

§3.3 anticipated this being unreachable. It was reachable: the cached row's
`encoding_type` is available at the point `_gather_encoding_display_data`
reads the file, so it is carried through in the display-data dict. The
string itself is displayed **verbatim** — it was written with the correct
letters by `_persist_sax_encoding`, so it is already right — and the
`encoding_type` is used only to *name* the alphabet in the length line
("dSAX trend alphabet (D = down, S = same, U = up)"). No lookup was
invented.

### 3.16 `encoding_type` needed no extension at all

§3.3 asked me to find how `algorithm_short` is derived and extend it. It is
already derived generically — `recipe["steps"][-1]["algorithm"]`, gated on
`startswith("sax_")` — so `detection.sax_dsax` becomes `"sax_dsax"` with no
special case. The only real change at the persist site was threading
`letters` in, so the cached `.txt` matches the display.
`test_persisted_string_matches_the_displayed_string` compares the file on
disk against `enc_string_pane.value` byte for byte.

---

## 4. Deviations from the brief

Four, all small, all called out here rather than buried.

### 4.1 `dsax_letters` at k=5 changed, and one existing test expectation with it

**This is the one to look at.** §0.5 says the dSAX tests must pass
unmodified except for the two §1 requires. Phase E mandates a k=5 letter
scheme. Those two requirements conflict:
`test_dsax_letters_other_alphabets_use_the_repo_convention` pinned
`dsax_letters([0,1,2,3,4], 5) == "abcde"`, and Phase E requires `"dDSUu"`.

I resolved it in favour of Phase E, because the alternative — defining the
k=5 letters only in the UI and leaving `dsax_letters` on a/b/c — would make
the headless string and the UI string **disagree**, which §3.1 of the brief
explicitly legislates against ("define it once in the dsax module beside
`SYMBOL_NAMES` and derive the UI from it") and which §3.3 forbids for the
cached `.txt`.

So: the expectation was changed, the test renamed
`test_dsax_letters_five_symbol_alphabet`, and a comment in it records that
it changed, why, and where to read about it. A second test
(`test_dsax_letters_undeclared_alphabets_use_the_repo_convention`) now pins
the a/b/c fallback for k=4 and k=7, so the fallback is still covered rather
than merely dropped.

**No numerical behaviour changed.** `dsax()`'s symbol arrays are
bit-identical; `test_dsax_engineered.py` is unmodified and still 17/17.

I also regenerated `dsax_validation/metrics.json` and its PNGs so dataset 6's
recorded string reads `dDSUu` rather than a stale `abcde`.

### 4.2 `git mv` replaced by copy + delete

Per §0.2, which explicitly instructs this. Recorded so the promotion is not
mistaken for a rename in history.

### 4.3 `build_encoding_panels` gained one keyword, not a new return value

Phase F needs a way to push match spans into the strip after construction. A
sixth return value would have broken `tests/test_encoding_panels.py`, which
unpacks five — and §7 says extend, don't rewrite. So the caller passes a
`highlight_stream` **in** (defaulting to a private one that is never
triggered), and the return signature is unchanged. `test_encoding_panels.py`
is untouched and still 6/6.

### 4.4 Noise-floor guard is a flexing surrogate count, not a subsample

§3.7 above. §4.3 offered "a documented subsample"; I judged that
scientifically wrong and did something else, documented in the button's
tooltip as the brief requires.

---

## 5. A real bug I introduced and caught

Worth recording because the test caught it, not inspection.

`HighlightStream` was first defined as
`hv.streams.Stream.define("EncodingHighlight", spans=())`. `Stream.define`
infers a parameter type from the default, so `()` became a `param.Tuple` —
which pins its **length** to the default's. The first
`.event(spans=((3, 7),))` raised:

```
ValueError: Attribute 'length' of Tuple parameter 'EncodingHighlight.spans'
is not of the correct length (1 instead of 0).
```

Fixed with an explicit `param.Parameter(default=())`, which accepts any
length. Tuples (not lists) are still passed so the value stays hashable for
HoloViews' frame keying. The comment in `plots.py` records the failure so
nobody "simplifies" it back.

---

## 6. Test results

### 6.1 New and changed tests

| File | Tests | Result |
|------|------:|--------|
| `tests/test_encoding_view_dsax.py` | **46** | **46/46 pass** |
| `tests/test_dsax.py` | 33 (was 32) | **33/33 pass** |
| `tests/test_dsax_engineered.py` | 17, **unmodified** | 17/17 pass |
| `tests/test_encoding_view.py` | 10, **unmodified** | **10/10 pass** |
| `tests/test_encoding_panels.py` | 6, **unmodified** | 6/6 pass |

Of the 46 new tests, 20 run unconditionally (pure `UI.plots`/`Working`
logic, no DB, no real data) and 26 are real-channel gated in the same way
`test_encoding_view.py` is. All 46 ran here — the gate was satisfied.

Coverage against §7.2/§7.3, item by item:

| Required | Test |
|---|---|
| cSAX/pSAX → `cutline_domain == "amplitude"` | `test_cutline_domain_all_three_resolution_paths` |
| Panel 3 amplitude still plots `paa_raw`; HLines == `cutlines_raw` | `test_amplitude_panel3_still_plots_paa_and_exact_cutlines` |
| `symbols_to_string(symbols)` byte-identical | `test_symbols_to_string_default_is_byte_identical` |
| Existing `test_encoding_view` unmodified | verified, 10/10 |
| `cutline_domain` all three paths | `test_cutline_domain_all_three_resolution_paths` |
| Delta panel 3: `deltas_raw`, rise label, band count, cutline positions | `test_delta_panel3_plots_deltas_with_the_rise_label` |
| Panel 2 delta: `n_symbols` segments, rise == `deltas_raw[i]` | `test_delta_panel2_draws_one_trend_segment_per_symbol` |
| `symbols_to_string(..., letters=("D","S","U"))`; RLE likewise | `test_symbols_to_string_default_is_byte_identical`, `test_five_symbol_alphabet_resolves_letters_and_names`, `test_delta_letters_reach_the_panels` |
| End-to-end dSAX through the run panel | `test_running_dsax_populates_the_encoding_section` |
| Noise → SAME warn; drift → mean-delta warn; constant → degeneracy error naming the case | `test_pure_noise_trips_the_same_fraction_warning`, `test_undetrended_drift_trips_the_mean_delta_warning`, `test_constant_signal_names_the_right_degenerate_case`, `test_straight_ramp_names_the_other_degenerate_case` |
| Regex: sharkfin count/spans, invalid reported, cap fires and announced | `test_morphology_search_*` (6 tests) |
| Noise-floor button: ~3× ratio, no mutation | `test_noise_floor_on_the_section_6_3_fixture_reports_roughly_three_times`, `test_noise_floor_button_reports_and_does_not_recompute` |
| k=5/k=4: single-char unique letters; even reports no SAME bin and disables the control | `test_declared_letter_maps_are_single_character_and_unique`, `test_even_alphabet_has_no_same_bin`, `test_even_alphabet_legend_says_so_and_disables_the_halfwidth_control` |

§7.4's Bokeh-model verification is used where it is the only honest check —
`hv.render(frame, backend="bokeh")` then asserting on `yaxis[0].axis_label`,
`title.text`, and `y_range.start/end` — alongside structural assertions on
the materialised HoloViews Overlay (element composition, and the actual
plotted arrays via `.dframe()`), which are stronger where available.

### 6.2 Diff against `BASELINE.md`

Both sections. Section 2 has been appended to `BASELINE.md` with the full
table.

**Nothing regressed. No file lost a passing test. The only counts that
moved, moved upward.**

- `test_encoding_view`: **10/10, unchanged** — the number §7.1 protects.
- `test_encoding_panels`: 6/6, unchanged.
- `test_sax_adapters`: 15/15, unchanged. It enumerates adapters but asserts
  no count, so promotion needed no edit there (§1 asked me to check).
- `test_analysis_modules`: still exit 1, identical pre-existing cp1252
  console crash after its own 195/195 pass. Untouched, unrelated.
- Every other file: identical exit code and identical `[PASS]` count.

---

## 7. Things I found and did not go looking for

### 7.1 A pre-existing crash in `UI/run_panel.py` — fixed incidentally

**`_visible_symbol_slice` called `segment_time_edges` without importing
it.** Verified against the snapshot: the name appears once, at what was line
1282, and never in the import block.

This is a `NameError` on any path that reaches it — and `_show_encoding`
reaches it automatically:

```python
self.enc_view_toggle.value = (
    "Visible range only" if n_symbols > ENCODING_STRING_INLINE_THRESHOLD else "Whole span"
)
self._refresh_encoding_string_display()   # -> _visible_symbol_slice -> NameError
```

`ENCODING_STRING_INLINE_THRESHOLD` is 500, so **any encoding producing more
than 500 symbols would have raised**, and by Panel's usual behaviour the
failure would surface as the section simply not updating rather than as an
error.

I did not go looking for this (§0.8), and I did not fix it as a separate
act: `segment_time_edges` is a name Phase F needs anyway, to map a regex
match back to a time span for the "Match n of m — 0.0s to 599.0s" readout.
Importing it was unavoidable, and importing it fixes the crash. Saying
nothing would have been worse than fixing it.

Pinned by `test_long_encoding_defaults_to_visible_range_and_still_renders`,
which drives a 1500-symbol encoding through `_show_encoding` and asserts the
string renders.

### 7.2 Noted, not touched

- **The ribbon-pane x-range linking issue** — explicitly out of scope
  (§0.8). Not looked at, not touched.
- **`motifs.sax_string` now holds two alphabets.** Flagged as §3.3 asks: a
  D/S/U string and an a/b/c string are indistinguishable by inspection, and
  the column has no alphabet field. It *is* recoverable — the motif's
  detection → run → config chain reaches the recipe, whose last step's
  `algorithm` gives `sax_dsax` — but that is a four-join round trip to
  answer "what alphabet is this". **My suggestion:** an `alphabet` or
  `encoding_type` column on `motifs`, denormalised from the recipe at insert
  time. Not done here; a schema change is well outside this work order.
- **`_find_sax_string_for_span`** matches `encoding_type.startswith("sax")`
  and returns the *first* span match. With three SAX encoders now writing
  for the same span, a motif saved from a detection can pick up a cSAX
  string when the user was looking at dSAX. Pre-existing (cSAX vs pSAX had
  the same ambiguity), but dSAX makes it more likely and more confusing,
  since the alphabets now differ visibly. Not touched — fixing it means
  deciding a precedence rule, which is your call.
- **`absolute_threshold` / `same_fraction` / `endpoint_k` are always
  enabled**, even when their `threshold_mode` / `trend_estimator` makes them
  inert. The same "only the active control is live" treatment
  `_sync_segment_mode_controls` gives the segmentation controls would suit
  them. I did only `min_same_halfwidth`, which §5 required, to keep the
  change surface tight.

---

## 8. What you need to decide

### 8.1 Should `min_same_halfwidth` become a default? (§8 step 6 of the prior notes)

The button now exists to measure it, and the measurement is stark. On pure
noise, at α = 0.95:

| | value |
|---|---:|
| learned SAME half-width | 0.336 |
| surrogate noise floor | 1.041 |
| **ratio** | **3.10×** |
| SAME fraction, learned | 46.5 % |
| SAME fraction, floor imposed | 94.6 % |

A trendless signal is currently labelled UP or DOWN in **53 % of segments**,
and scores 97 % of its occupancy-entropy ceiling doing it — it looks
excellent by every diagnostic the shared code offers.

**My recommendation, which I deliberately did not implement:** make it a
default *per channel*, not per run — estimate once per channel at a chosen
α, store it, and apply it to every dSAX run on that channel. Two reasons for
not doing it here: (a) the brief is explicit that `dsax()` stays
deterministic and must not call the surrogate estimator, so a default would
have to live in the adapter or the recipe, which changes what a recipe hash
covers; and (b) the correct α is a false-positive-rate decision about your
science, not mine. The hook, the estimator, the button and the projected-SAME
readout are all in place for you to choose.

### 8.2 Smaller ones

- **k=5 letter case** — keep `d D S U u`, or invert to `D d S u U`? §3.5.
- **Highlight cap of 500** — a judgement, easily changed.
- **α default of 0.95** — currently a control, defaulting to 0.95.
- **Where the new constants live** — adapter/plots vs. `Working/config.py`. §3.14.

---

## 9. Follow-on work

1. **`motifs` alphabet provenance** — §7.2. The clearest real schema smell.
2. **`_find_sax_string_for_span` precedence** across three SAX encoders — §7.2.
3. **Gate the remaining inert dSAX controls** the way `min_same_halfwidth`
   is now gated — §7.2.
4. **A vocabulary of saved patterns.** The search box takes a regex and the
   motif seed records the pattern that matched, but there is no library —
   "sharkfin", "rollinghill", "crestedwave" as *named* patterns you pick
   from a dropdown, rather than retyping a regex, is the obvious next step
   and would make §6's payoff real rather than latent. The `vocabulary`
   table already exists for element tags and looks like the right home.
5. **Search across spans/channels.** The search is whole-span, which is the
   right fix for the "only what's on screen" trap, but the actual question
   is usually "where does this morphology occur in this *recording*". That
   needs the cached `.txt` encodings, which are already keyed by span in the
   `encodings` table — so it is mostly plumbing.
6. **`min_same_halfwidth` per channel**, if you take §8.1.
7. **The two upstream fixes still outstanding** from `IMPLEMENTATION_NOTES.md`
   §4: the cp1252 crash in `tests/test_analysis_modules.py` (one-line diff
   there; still the only failing file in the suite). The `-0.0` entropy fix
   from that same section **has** now been applied, as §4.2 of this work
   order permitted.
