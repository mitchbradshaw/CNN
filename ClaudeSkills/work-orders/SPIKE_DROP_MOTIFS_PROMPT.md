# Work order: spike-drop motif discovery, family overlays, and an
# "icicle" dendrogram — figures + a reusable data store for a NeurIPS
# workshop submission

You are working autonomously in the CNN repo. **The operator has stepped away
and will not answer questions while this runs.** Every open question below
either has a stated default or is explicitly left to your judgement — when
you make a judgement call, make it, keep going, and record what you decided
and why in the summary document (§9). Never block waiting for input. A task
you cannot finish is written up as blocked, with what you tried and what
would unblock it — that is a valid outcome; silently skipping it is not.

Read `CLAUDE.md` at the repo root first if you have not already internalised
it — the rules there (no Panel/HoloViews/Bokeh/matplotlib below `UI/`, plain
SQL, bulk arrays never enter the database, `DATA/`/`Plots/` are gitignored
working directories not committed artifacts) apply to everything below and
are not repeated in full here.

---

## 0. Why this exists

The supervisor is drafting a NeurIPS 2026 workshop submission (see
`NeurIps 2026 submissions.docx` at the repo root — read it, it is short and
is the actual brief this figure work serves). The target is the **"Foundation
Models for Temporal Systems"** workshop. The paper's angle: mycelial
bio-electric recordings are an unexplored class of biosignal for temporal
foundation models — noisy, multimodal-adjacent, subject-variable, and built
from genuine spiking dynamics (the docx explicitly invokes Hodgkin-Huxley /
FitzHugh-Nagumo / Izhikevich framing: *"a spike is a rapid change with a
slower recovery back to a resting potential — perturbation from a trajectory
and gradual reset to the original trajectory"*). The paper needs evidence
that these signals have **structured, recurring, comparable temporal
morphology** — not just noise — and a **data card** (the docx spells out
what NeurIPS wants in one: provenance, composition, collection/annotation
process, preprocessing, missingness, known biases, recommended/discouraged
uses). The docx also singles out an existing overlay figure as the
**"wow factor"** — "*Icicles dataset - overlay*" — which is exactly the
family-overlay-plus-dendrogram shape this work order asks for. Keep that in
mind for the dendrogram figure in particular (§6): it is not a throwaway QC
plot, it is a candidate hero figure.

The supervisor already likes `Plots/motif_families/` and
`Plots/family_search/` (built by `Pipelines/motif_report/` — **read
`Pipelines/motif_report/README.md` and skim `motif_report.py`,
`family_search.py`, `seed_replicas.py` before writing anything new**; they
solve several of the sub-problems below already and the house style,
helper functions, and plotting conventions should be reused, not
reinvented, per `CLAUDE.md`'s "prefer importing an existing helper" rule).

What is new here, that those tools don't do: those find motifs by matrix-
profile self-similarity (families of *whole* spikes). This work order finds
one specific **sub-shape** — the sharp negative-going drop that follows the
rise of a spike, located by trend classification rather than by nearest-
neighbour search — collects every instance of it across two very different
recordings, and asks whether that sub-shape is itself a recurring, cluster-
able motif. That is a different, complementary claim for the paper: not
just "whole spikes repeat" but "the *rise-then-drop* dynamic itself has a
small vocabulary of shapes."

---

## 1. Hard constraints

1. **No new dependencies.** `numpy`, `scipy`, `pandas`, `matplotlib` are
   already used across this repo (`Working/Catalogue/dendrogram/` already
   imports all four) — use those and nothing else. If you find yourself
   wanting one, stop, don't install it, and say so in the summary.
2. **Nothing you write under `Working/` may import `matplotlib`, `Panel`,
   `HoloViews`, or `Bokeh`, directly or transitively.** This is enforced by
   an existing test and is why `Pipelines/motif_report/motif_report.py`
   keeps its "headless core" (profile/family logic) separate from its
   `MotifFamilyFigure` class (matplotlib, imported lazily). Follow that
   split: detection and clustering logic is a pure, headless, unit-testable
   module; figures are a separate module/script that imports matplotlib.
3. **`Working/` may not import from `Adapters/`.** `dsax.py`'s own docstring
   explains why (`Adapters.registry.discover_adapters()` auto-imports
   everything under `Adapters/`, so the dependency direction only goes one
   way). If you want segmentation arithmetic like
   `Adapters._sax_common.segment_plan`, either duplicate the few lines you
   need with a comment pointing at the original (as `dsax.py` did for
   `_letter`), or do the simpler direct computation described in §3.2 — you
   do not need `segment_plan`'s full round-trip precision here.
4. **Do not touch `Adapters/` or `UI/` at all, and do not register anything
   with the adapter registry.** This is an offline analysis pipeline for
   paper figures, not a UI feature — it should look like
   `Pipelines/motif_report/`, not like a new algorithm block. No
   `AdapterSpec`, no `register()`, nothing importable by
   `discover_adapters()`.
5. **Do not modify any existing file** (`dsax.py`, `motif_report.py`,
   `family_search.py`, `seed_replicas.py`, `distances.py`,
   `dendrogram_cluster.py`, or anything else). Import from them. If you
   think one of them should change, don't change it — note the exact diff
   you'd want under "Requested upstream changes" in the summary.
6. **No git state changes** — no commit, push, stash, reset, checkout,
   clean. Leave the working tree as you left it; `git status`/`git diff`
   for your own inspection is fine.
7. **`DATA/` and `Plots/` are gitignored working directories** (see
   `.gitignore`; `Plots/*` and `DATA/*` are ignored except their READMEs).
   Anything you write there is local-only and will not be committed —
   that's fine and expected, it's where `Plots/motif_families/` already
   lives. Code goes under `Pipelines/` and `Working/`, which **are**
   tracked, same as `Pipelines/motif_report/`.
8. **Everything that touches real recordings must be re-runnable and must
   not silently swallow a partial failure.** If a recording, a channel, or
   a stretch of it produces zero drop events, say so loudly in the run
   output and in the per-recording manifest (§4.4) — do not let an empty
   result look identical to "not yet run."

---

## 2. What you have to work with — read before designing anything

### 2.1 The two recordings

| | Mushroom_260720 | M2_aug_concat_fs1 |
|---|---|---|
| `recordings.id` | **385** | **1** (channel 0 of 16; ids 1–16 are CH00–CH15) |
| source file | `Mushroom_260720_0509_4hrs_CH14_fs1.mat` | `M2_aug_concat_fs1.mat` |
| `channel` (DB column) | 0 | 0 |
| `fs` | 1.0 Hz | 1.0 Hz |
| `n_samples` | 14,401 (~4.0 h) | 2,595,600 (~721 h) |

The `CH14` in the Mushroom filename is the *hardware* channel from the
original acquisition; the DB's `channel` column is 0 because this recording
was ingested as a single-channel file. Don't read that as "14 channels
exist" — there's one. This is also why the existing
`Plots/motif_families/.../..._CH14_fs1_CH00_...` filenames carry both
numbers.

### 2.2 The M2_aug span, and what's already annotated there

The operator's description ("a sequence of nice spikes ... about 336.8 h to
344.4 h ... I believe it is already a recorded annotation") matches an
existing `annotations` row exactly. Query it yourself to confirm current
state (`Working.database.schema.init_db()` → `annotations` joined to
`recordings`), but at write time:

| `annotations.id` | recording | span (hours) | verdict | note |
|---|---|---|---|---|
| 11266 | id=1 (CH00) | 336.0 – 346.0 | interesting | "amplitude modulation am increasing; frequency modulation fm decreasing; 16 cycles; 20-70 mV" |
| 11279 | id=1 (CH00) | 337.09 – 338.165 | interesting | "4x sharkfin sequence" |
| 11267 | id=1 (CH00) | 337.9 – 338.18 | interesting | "single cycle; type specimen" |

Use this as **ground truth to sanity-check your detector against**, not as
the literal crop window (the operator's 336.8–344.4 h is inside 11266's
wider 336–346 h span — default to the full 336–346 h annotation unless you
have reason to trust the narrower figure more; either is defensible, pick
one and say which). The arithmetic worth noting: 16 cycles over 10 h ≈ 37.5
min/cycle for the whole AM/FM-modulated envelope, but the "4x sharkfin"
sub-annotation is 4 cycles in ~64.5 min ≈ 16 min/cycle, and the "single
cycle, type specimen" annotation is ~17 min wide. **Individual spikes here
are on the order of 15–20 minutes**, not seconds — this should directly
inform your rolling-mean detrend window and dSAX segment length (§3.1–3.2):
too short a detrend window will treat the spike itself as drift and remove
it; too long a dSAX segment will average the rise-then-drop into mush.
20–70 mV is the envelope's peak-to-peak amplitude range — useful for
sanity-checking that your extracted events are landing on real excursions
and not noise.

For Mushroom_260720, there is no equivalent annotation to lean on (it's the
dataset `Plots/motif_families/` and `Plots/family_search/`'s
`mp_families_CH0_short`/`catalogue_M2aug` etc. were built against, but that
was whole-spike matrix-profile discovery, not drop detection) — you're
finding structure fresh here. Cross-check visually against
`Plots/motif_families/win1min_windowaligned/` — those are the same
recording's whole-spike families, and your drops should visibly correspond
to the falling edge of those families' events.

### 2.3 dSAX — the trend classifier you'll build on

`Working/Detection/sax/dsax_python/dsax.py` implements a data-adaptively
quantised trend alphabet — read its module docstring in full, it explains
the design better than a summary here would. Signature:

```python
def dsax(data, training_len, dim_ratio, alphabet_size=3,
         trend_estimator="ols_slope", threshold_mode="learned",
         endpoint_k=1, absolute_threshold=None, same_fraction=0.5,
         min_same_halfwidth=None, force_symmetric=True,
         normalize=True, return_details=False)
```

- `alphabet_size=3` gives DOWN/SAME/UP — the case this work order needs.
- `dsax_letters(symbols, alphabet_size=3)` turns the integer symbol array
  into a `"DSSUUUDDS..."`-style string. **This is what makes UP-region
  detection a regex, not a loop**: `re.finditer(r"U+", letters)` gives you
  every maximal run of UP segments directly, with its `.start()`/`.end()`
  in *segment* index space.
- `details["segment_starts"]`/`details["segment_ends"]` (sample indices,
  present when `return_details=True`) convert a segment index back to a
  sample index in your (detrended) input array — use these rather than
  re-deriving `sps` arithmetic yourself.
- `threshold_mode="learned"` (the default) fits the DOWN/SAME/UP cutlines
  from the data itself via the pSAX KDE + Lloyd-Max machinery — recommended
  default here, since the two recordings differ enormously in length and
  you don't want to hand-tune an absolute threshold for each. Use
  `training_len=len(data)` (fit on the whole segment you're analysing;
  there's no separate held-out concept here).
- Seed `np.random` before every call (dsax's learned mode consumes
  `kmeanspp`'s RNG) — see the dsax docstring's "Determinism" note. Do this
  once per detection run with a fixed seed, and record the seed in the
  manifest (§4.4), so a rerun reproduces the exact same event set.

`Working/Detection/sax/dsax_python/trend_estimators.py` documents the four
estimator choices; `"ols_slope"` (the default) is the sensible one here —
it's the least noise-sensitive of the four per
`DSAX_IMPLEMENTATION_PROMPT.md`'s test 13.

### 2.4 Shape distance and roughness — the tools `family_search.py` already built

`Working/distances.py` gives you `scale_invariant_distance` (resample both
spans to a common length, z-normalise, Euclidean — the shape-only distance,
robust to the two datasets having wildly different absolute drop durations)
and `native_length_distance` (the un-resampled control — large when two
spans are the same shape at different durations, which is itself a finding
worth reporting per `family_search.py`'s README). Both already divide-by-
`sqrt(n)` conventions are established in this repo (`motif_report`'s
`--max-distance-norm`, `family_search`'s cross-scale matrix) — follow them
so your numbers are comparable to the existing plots' numbers.

`Pipelines/motif_report/family_search.py` has three pieces worth reusing
directly rather than re-deriving:

```python
cross_scale_matrix(exemplars, metric=DISTANCE_SCALE_INVARIANT)  # pairwise D
cluster_order(D)                                                # avg-linkage leaf order + Z
plot_cross_scale(D, labels, lengths_min, ...)                   # dendrogram + heatmap figure
```

`Pipelines/motif_report/seed_replicas.py`'s `roughness(values)` (RMS first
difference of the z-normalised span) and `split_by_roughness(...)` are the
"distance-matching with roughness accounted for" the operator pointed you
at. Read `seed_replicas.py`'s module docstring — the finding that motivated
it (roughness varies 16x among matches at near-identical distance) is
exactly the kind of thing this paper wants to say about mycelial spikes
too, so it's worth citing/reproducing the same measurement on your drop
events if you have time.

---

## 3. Drop detection — the algorithm

This is the operator's own design; your job is to make it precise and
implement it, using their spec as the source of truth and the notes below
to resolve the parts left implicit. Where you disagree with a choice below,
implement your better idea instead and justify it in the summary — this
section is a strong recommendation, not a spec to follow blindly.

### 3.1 Detrend

Rolling-mean detrend the segment before running dSAX on it — dSAX's trend
alphabet should describe the *event's* rise and fall, not the recording's
slow baseline drift (the exact failure mode `family_search.py`'s
`linear_residual_fraction` guards against for matrix-profile discovery
applies here too, just to a symbolic classifier instead of a distance).

```python
from scipy.ndimage import uniform_filter1d
baseline = uniform_filter1d(x, size=window_samples, mode="nearest")
x_detrend = x - baseline
```

`window_samples` needs to be **long relative to noise, short relative to
one spike** (per §2.2, spikes here run 15–20 minutes). A window of a few
minutes is a reasonable starting point; validate by eye against
`Plots/motif_families/` (Mushroom) and the annotated span (M2_aug) — the
detrended trace should still show the spike's rise and fall clearly, not
flatten it. Make this a CLI parameter, don't hardcode it, and record
whatever default you land on with the reasoning in the summary.

### 3.2 dSAX segmentation

Pick a per-segment duration short enough to trace the rise distinctly from
the fall (seconds, not minutes — you need several UP segments across one
spike's rise, not one segment spanning the whole spike). Expose this as
`--segment-seconds`, convert to `dim_ratio` directly:

```python
n_segments = max(2, int(round(len(x_detrend) / (segment_seconds * fs))))
dim_ratio = (n_segments + 0.5) / len(x_detrend)   # matches dsax's own
                                                    # floor(dim_ratio*len) arithmetic;
                                                    # +0.5 avoids a boundary
                                                    # floor landing one short —
                                                    # same trick segment_plan()
                                                    # uses, done inline since
                                                    # Working/ can't import
                                                    # Adapters/._sax_common
```

You do not need `segment_plan`'s exact-round-trip guarantee here (nothing
downstream compares this to a persisted encoding-view artifact) — the
inline version above is sufficient; don't over-engineer it.

### 3.3 UP regions

```python
symbols, details = dsax(x_detrend, len(x_detrend), dim_ratio, alphabet_size=3,
                        threshold_mode="learned", return_details=True)
letters = dsax_letters(symbols, alphabet_size=3)
up_regions = [(m.start(), m.end()) for m in re.finditer(r"U+", letters)]
```

Each `(start, end)` is in **segment** index space; convert to sample space
via `details["segment_starts"][start]` and `details["segment_ends"][end-1]`.

Judgement call, left to you: whether a lone `S` between two `U` runs should
merge them into one region (a rise with a brief plateau) or count as two
separate UP regions. Either is defensible; the regex above treats them as
separate. If you change it, say so.

### 3.4 The drop point

> "the first instance after an upward region where dx/dy lies within a
> negative slope threshold ... only dx/dy events after the UP classification
> ... prevents a string of identifications on a large downward slope, we
> are only interested in the most vertical drop at the start of the drop"

Read literally: after each UP region ends, scan forward sample-by-sample
through the per-sample derivative until the first sample whose slope is at
or below a negative threshold. That sample is the drop's onset. Do **not**
keep scanning within the same falling run for a second, third, ... crossing
— one UP region produces at most one drop candidate.

**Recommended threshold, tying it to dSAX rather than inventing a second
free parameter**: dSAX's own learned DOWN cutline (`details["cutlines_raw"][0]`,
delta-space, "rise across one segment") converted to a per-sample slope by
dividing by the segment's `samples_per_symbol`. This makes "negative slope
threshold" the *same* data-adaptive quantity dSAX already learned for this
segment, rather than a second knob you'd have to separately justify and
retune per recording. Compute the per-sample derivative on the **detrended**
signal (so the drift-cancelling from §3.1 doesn't leak back in) with
`np.gradient` or `np.diff`.

If no qualifying sample is found within some bounded lookahead after a UP
region (recommend a few multiples of that region's own duration, not
unbounded — an UP region at the very end of a segment with nothing after it
should not hang the scan or silently extend past the data), drop that
candidate and log it — count logged-and-dropped candidates explicitly in
the manifest (§4.4) rather than letting them vanish silently.

### 3.5 The event window — collect enough to re-slice later, not just enough for today's plot

§5 requires that plots be adjustable **without rerunning detection**. That
means the stored snippet per event must be generous enough that a later,
different padding choice doesn't require reloading the channel — but it
also means you should **always store the absolute sample indices**
(`recording_id`, onset index, UP-region bounds) alongside the materialised
array, so that in the worst case (someone wants more context than was
saved) the original `.npy` can still be re-sliced exactly. Indices are the
real safety net; the materialised snippet is a convenience/durability copy
independent of `DATA/`'s availability.

Recommended default extraction window: from the UP-region start back by one
more UP-region-duration of pre-context, through to `k ×` the UP-region's
own duration after the onset (`k≈3` as a starting point — long enough to
show the recovery, per the Izhikevich-style "gradual reset to trajectory"
framing the paper wants). Make both the pre-context and post-context
multiples CLI parameters.

---

## 4. Storage — the actual deliverable, not a side effect

> "make sure all the data collected on these motifs is stored too, such
> that the plots can be adjusted without having to rerun any algorithms,
> and collect enough data to help satisfy the idea of a 'data card'"

Two consumers, two artefacts. Build both.

### 4.1 The event table (per-drop, tabular, drives replotting)

One row per collected drop, written to CSV (matches every other table in
this repo — `families_WIN1min_d0.775.csv`, `matches.csv`). Minimum columns:

```
event_id, recording_id, source_file, channel, fs,
up_region_start_idx, up_region_end_idx, up_region_start_h, up_region_end_h,
onset_idx, onset_h, onset_slope_raw,
snippet_start_idx, snippet_end_idx, snippet_path,
peak_to_peak_mV, pre_context_s, post_context_s,
detrend_window_s, segment_seconds, dsax_threshold_mode, dsax_trend_estimator,
random_seed, cluster_id (filled in after §6, -1 until then)
```

### 4.2 The snippet store (arrays, replayed into figures)

One `.npz` per event (or one packed `.npz`/`.parquet` per recording if you
prefer fewer files — either is fine, say which and why) holding the raw
(mV or volts — be explicit and consistent with `motif_report.py`'s
mV convention), detrended, and time-index arrays for that event's snippet,
keyed by `event_id` so the table and the arrays join trivially.

Location: `DATA/derived/drop_motifs/<recording_id>/` (gitignored, local,
consistent with `DATA/derived/encodings/` for dSAX's own persisted output —
**this is a different, bespoke detrend, not the same input dSAX's adapter
already encoded elsewhere; don't try to reuse
`DATA/derived/encodings/.../sax_dsax` artifacts, they're a different
channel/params and going through them would be more work than just calling
`dsax()` directly on your own detrended array**).

### 4.3 Figures must read from storage, not from a live detection run

The plotting script (§5, §6) should take the event table + snippet store as
its input, not the recording directly. This is what makes "adjust the plot
without rerunning the algorithm" literally true — a run flag like
`--replot-from <event_table.csv>` that skips detection entirely and goes
straight to figures is the cleanest way to guarantee this; build it that
way rather than merely "in principle you could."

### 4.4 The manifest — the data-card raw material

`DATA/derived/drop_motifs/<recording_id>/manifest.json` per detection run:
every parameter used (detrend window, segment seconds, dSAX mode/estimator,
random seed, pre/post context), counts (UP regions found, drops confirmed,
candidates dropped for no qualifying slope found and why), timing, and the
measured distributions worth quoting in a data card — event count, drop
duration distribution, peak-to-peak amplitude distribution, per-recording
breakdown. This is what §7 turns into prose; get the numbers right here so
that step is transcription, not re-analysis.

---

## 5. Family overlay figures — match the existing look, non-normalised only

> "compare them overlaid much like how the plots in plots/motif_families
> appear, but without the family mean, and only non-normalised motifs"

Reuse `Pipelines/motif_report/motif_report.py`'s building blocks rather
than re-implementing the look: `_apply_report_style`, `overlay_limits`,
`transform_snippet` (use `mode="raw"` or `"centred"` — **not** `"znorm"`;
the operator was explicit that these overlays are non-normalised, unlike
the shape-clustering step in §6 which needs z-normalisation internally to
even define "same shape" — keep that distinction visible in your own head
and in the figure: the clustering math z-normalises, the rendered overlay
never does**). One figure per cluster (post-§6), in the same
visual language as `Plots/motif_families/`'s family PNGs, so the supervisor
recognises the figure family at a glance — same colour conventions
(`SEED_COLOR`, `CYCLE_PALETTE`) if it reads sensibly for this shape too.

---

## 6. The dendrogram — the "wow factor" figure

> "construct a dendrogram and cluster them, such that the edges of the
> branches plot each unique spike, and the clusters plot an overlay of each
> spike in that cluster"

This is genuinely the hardest deliverable here — say so plainly if it
doesn't fully land, and fall back cleanly (below) rather than shipping
something broken. There are working dendrogram functions within the code base (perhaps in Experimentation/Catalogue experiments among others) that were used to cluster data from a Window Matrix input and then plot the results. The plotting and clustering was quite successful, albeit short of the requirements for this task, reuse the working functionality where you need. 

### 6.1 Clustering — recommended default

Two-stage, mirroring how `seed_replicas.py` already separates "is it the
same shape" from "is it a clean instance of that shape":

1. **Shape clustering.** Resample every drop snippet to a common length,
   z-normalise (exactly what `scale_invariant_distance` does internally —
   either call it pairwise to build a distance matrix and feed
   `scipy.cluster.hierarchy.linkage` with `method="average"` on the
   condensed form (mirrors `cluster_order()` in `family_search.py`), or
   build the resampled+z-normalised vectors directly and use
   `method="ward"` the way `Working/Catalogue/dendrogram/dendrogram_cluster.py`
   does for window-matrix features — either is defensible; ward on the
   vectors is simpler to reason about and avoids a second O(n²) pairwise
   step if you're already resampling everyone to one length, so it's the
   lighter-weight default, but say which you chose and why.
2. **Roughness as a QC axis, not a clustering dimension.** Within each
   cluster, compute each member's `roughness(...)` ratio against the
   cluster's own mean waveform (not a single hand-picked seed, since there
   isn't one here) using `seed_replicas.roughness`, and use it exactly as
   `split_by_roughness` does — to flag/exclude noisy members from the
   family-mean overlay (§5), and to report the excluded fraction. This
   keeps the two axes (what shape is it / how clean an instance is it)
   separate and interpretable, which is the finding `seed_replicas.py`
   already demonstrated is real on this kind of data.

This is a recommendation, not a mandate — "clustering methodology is open"
per the brief. If you fold roughness directly into a composite distance
instead, that's a legitimate alternative; just state the composite formula
explicitly (e.g. weights) so it's reproducible, and note that this is a
free design choice you made rather than a repo convention.

### 6.2 Rendering waveforms at leaves and overlays at internal nodes

`scipy.cluster.hierarchy.dendrogram(Z, no_plot=True)` returns `icoord`/
`dcoord` (the x/y coordinates of every branch segment) and `leaves` (the
left-to-right leaf order) — this is what you need to place inset axes at
the right x-positions. Approach:

1. Draw the dendrogram skeleton normally (`dendrogram(Z, ax=ax, ...)`, not
   `no_plot`) so the branch structure is there as a backdrop.
2. For each leaf (x-position from `icoord`'s leaf ends, in the same order
   as `leaves`), place a small inset axes (`ax.inset_axes(...)` or manually
   computed `fig.add_axes` in figure coordinates translated from the data
   coordinates) showing that one drop's raw waveform — small, no ticks, a
   thumbnail, not a full plot.
3. At internal merge nodes — either every merge, or (more legible, and
   recommended if the full tree gets crowded) only at the cut height that
   produced your §6.1 clusters — place a larger inset showing the overlay
   of every leaf beneath that node, in the same non-normalised style as §5.

If this proves too fiddly to render legibly at the actual event count you
end up with (a dendrogram with hundreds of leaves each needing a readable
thumbnail is a real risk — say up front how many events you actually have
before committing to this), the acceptable fallback is: a standard
dendrogram (branches + cut line only, like `plot_cross_scale`'s left panel)
placed **beside** a grid of per-cluster overlay panels in cluster order
(reusing §5's figures), with the dendrogram's leaf order and the grid's
cluster order visibly matched (annotate cluster IDs on both). This still
tells the same story — "here is the tree, here is what each branch looks
like as a shape" — with far less rendering risk. Pick whichever you can
actually ship looking clean; note which you chose and why in the summary.
Do not ship a figure with unreadable overlapping thumbnails and call it
done — that is the "silently blank pane" failure mode this repo has hit
before, just in matplotlib instead of HoloViews: technically present,
useless to the reader.

### 6.3 Cross-dataset comparison

Run detection separately per recording (Mushroom_260720 and M2_aug's
annotated span — detrend/segment parameters may reasonably differ between
a 4-hour and a 721-hour recording; don't force them identical if the data
argues otherwise, but do record whatever you chose per recording). Then
build **one combined distance matrix and dendrogram over the pooled event
set from both recordings**, colour-coded by source recording (leaf colour
or a small marker), so the figure itself is evidence for the paper's
"where do they diverge, where are they similar" framing — a cluster mixing
both recordings' events is a same-shape-across-datasets finding; a cluster
that's pure one recording is a divergence finding. Report the mix
explicitly (e.g. per-cluster composition table) alongside the figure, not
just visually — reviewers will want the number.

---

## 7. Data-card notes — turn the manifest into prose

Write `Pipelines/drop_motifs/DATA_CARD_NOTES.md`, structured against the
fields the docx names (re-read the "Dataset Card" / "In practice" section
of `NeurIps 2026 submissions.docx` — it gives near-verbatim field names):
modalities, collection context, sampling rate/duration, annotation process,
preprocessing/filtering steps applied here specifically (detrend window,
dSAX params), counts (events found per recording, rejected candidates and
why), known biases/limitations (state plainly: dSAX's documented offset
sensitivity per `DSAX_IMPLEMENTATION_PROMPT.md` §7, the fact that the
negative-slope threshold is learned per-recording so isn't identical across
the two datasets, anything your own §3–§6 judgement calls introduce as a
limitation), and recommended/discouraged uses. This is meant to be
lift-and-shift material for the actual paper section, not just an internal
log — write it in that register (full sentences, no unexplained internal
jargon), but keep every number traceable to the manifest (§4.4) rather than
eyeballed off a figure.

---

## 8. Code layout

```
Working/Detection/drop_motifs/
    __init__.py
    detect.py          # detrend, dSAX call, UP-region walk, drop-onset
                        # scan, event-window extraction. Pure numpy/scipy.
                        # Zero matplotlib/Panel/HoloViews/Bokeh imports —
                        # this is the headless core (§1.2).
    cluster.py          # pairwise distance / linkage / roughness QC.
                        # Also headless.
tests/
    test_drop_motifs_detect.py    # engineered synthetic signals: a clean
                                   # ramp-up-then-sharp-drop, a ramp with no
                                   # drop, back-to-back UP regions, a flat
                                   # signal (zero events, no exception) —
                                   # assert exact onset sample on the
                                   # engineered cases, mirroring
                                   # tests/test_dsax_engineered.py's style.
    test_drop_motifs_store.py     # round-trip: write event table + snippet
                                   # store, reload, assert identical arrays
                                   # and that --replot-from (§4.3) needs no
                                   # recording access at all.
Pipelines/drop_motifs/
    __init__.py
    run_drop_report.py  # CLI entry point, argparse in motif_report.py's
                         # style (grouped argument groups, sensible
                         # defaults, --export-all / --replot-from).
    figures.py           # §5 and §6 plotting. matplotlib imported here,
                         # lazily, Agg backend when headless — same pattern
                         # as motif_report.py.
    README.md            # same register as Pipelines/motif_report/README.md:
                          # what each knob does and why, not just its type.
    DATA_CARD_NOTES.md   # §7.
```

Write the engineered tests first, watch them fail, then implement — this
repo's ticket workflow requires that discipline for merged work
(`CLAUDE.md` "Working a ticket"); this isn't a formal ticket but the
practice is worth keeping since it's exactly how `dsax.py`'s own test suite
caught the offset-sensitivity and estimator-robustness findings that ended
up in its `IMPLEMENTATION_NOTES.md`. Don't skip straight to real-data
plotting without the engineered cases passing first.

---

## 9. Final summary — the document the operator reads first

Write `SPIKE_DROP_MOTIFS_SUMMARY.md` into ClaudeSkills/work-orders:

1. **What now works** — one paragraph.
2. **DECISIONS** — every judgement call from §3–§6 (detrend window, segment
   seconds, region-merging, lookahead bound, pre/post context multiples,
   clustering method, roughness handling, dendrogram rendering choice,
   annotation-span choice from §2.2), each with: what you chose, the
   alternative(s), why, and how to reverse it. This is the most important
   section — err toward over-including rather than omitting a decision as
   too small.
3. **Numbers** — events found per recording, rejected-candidate counts and
   reasons, cluster count and sizes, per-cluster dataset composition
   (§6.3), roughness-excluded fraction. Pull these from the manifest
   (§4.4), don't re-derive them.
4. **Test results** — every test added, pass/fail, and confirmation the
   pre-existing suite (`pytest` from repo root) shows no regressions.
5. **Figures produced** — file paths under `Plots/drop_motifs/`, and for
   the dendrogram specifically, which rendering approach you used (§6.2's
   embedded-thumbnail version or the fallback) and why.
6. **Blocked / not done** — anything incomplete, what you tried, what would
   unblock it.
7. **Next** — the honest next step (likely: hand-picking the best cluster
   cut / figure crop for the actual paper, which is a human editorial call
   this work order deliberately doesn't make for you).

No praise, no restating the brief back. If something is half-finished, say
it is half-finished.
