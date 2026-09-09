"""
nulls1.py
==========
The null models and the population statistics the NeurIPS figures quote.
Compute only - every figure lives in `nullfigs1.py`, so this module can be
imported by a test without drawing anything.

The claim this exists to support is one sentence:

    Within 20 minutes of five-channel recording, absolute event amplitude
    is a property of the electrode, while relative event shape is not -
    and the events are not what this detector finds in noise with the same
    spectrum.

Three separable pieces of evidence, three sections below.

1. SURROGATES
-------------
Two generators, nulling two different claims:

  AAFT phase randomisation  keeps the power spectrum AND the marginal
                            amplitude distribution, destroys phase
                            structure and waveform asymmetry. Nulls
                            "these events are just excursions in coloured
                            noise". Plain phase randomisation is NOT used:
                            these channels are strongly non-Gaussian and a
                            Gaussianising surrogate would null the
                            marginal rather than the phase, which is the
                            wrong null.

  block shuffle             keeps every local waveform intact, destroys
                            the order they arrive in. Nulls "these
                            families are an artefact of sequence". Run at
                            two block lengths that bracket the claim: 50 s
                            (the analysis window - sequence between
                            windows is destroyed, everything inside one
                            window survives) and 5 s (sequence between
                            events destroyed, individual waveforms
                            survive).

The primitives are `Adapters.preprocessing_surrogate`'s - the PRD's
signal-to-signal surrogate block, already written and already seeded - not
a second implementation. AAFT is the rank-mapping wrapper around its phase
step.

THE WRAP-AROUND. An FFT surrogate is circular: the join at the channel
boundary is a step discontinuity the detector will happily call a drop. A
block shuffle has the same problem at every block join, but those are
interior and are part of what the null is testing. This module handles the
boundary by DISCARDING, not tapering: the first and last `EDGE_TRIM_S`
seconds of every surrogate are excluded from the counts, and the same
seconds of the real channel are excluded from the observed counts.
Tapering would change the spectrum the surrogate exists to preserve;
discarding costs 100 s of 1200 and keeps the comparison exactly like for
like. Every observed number in `NULL_surrogate.json` is therefore computed
on the trimmed store and differs slightly from the untrimmed numbers in
`refine_report.json`.

2. THE CHAIN IS NOT REIMPLEMENTED
---------------------------------
`run_chain` calls `passes9.detect_sliding` and `refine9.refine_store` with
the arguments the shipped run used, read out of `run_summary.json` rather
than retyped. A surrogate that went through a slightly different detector
is not a null of this detector.

3. WHAT COUNTS AS A FAMILY, UNDER A NULL
----------------------------------------
Comparing "k = 4 against k = 4" is not a test - k is imposed, so both
sides have four families by construction. Two statistics avoid that:

  families at fixed height   the ABSOLUTE Ward merge height at which the
                             real tree was cut to give k = 4, applied
                             unchanged to each surrogate tree, counting
                             families with >= MIN_FAMILY_MEMBERS. A real
                             repertoire should give FEWER, LARGER families
                             than a surrogate. If the surrogates give
                             fewer, that falsifies the limited-repertoire
                             claim and is a result, not a bug.

  within-family dispersion   mean Euclidean distance from a member to its
                             own family's centroid in the 200-dimensional
                             z-normalised feature space, at k = 4 on both
                             sides. Distance-to-centroid rather than
                             sum-of-squares because the surrogate stores
                             hold different numbers of events and a sum
                             would compare n rather than tightness.

Ward heights are not n-free (the merge cost carries a size factor), so the
fixed-height comparison is only fair when the two trees hold comparable
numbers of leaves. Every statistic here records its own n alongside it so
the figure can say whether they did.
"""

import json
import os
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import pdist
from scipy.stats import linregress, spearmanr

from Adapters.preprocessing_surrogate import _block_shuffle, _phase_randomise
from Pipelines.drop_motifs import passes9, refine9
from Working.Detection.drop_motifs import cluster as dc
from Working.Detection.drop_motifs import motifs5

REPO_ROOT = Path(__file__).resolve().parents[2]

PLOT_DIR = REPO_ROOT / "Plots" / "drop_motifs9_fig2a"
REFINED_STORE = PLOT_DIR / "refined_v2" / "motifs"
RAW_STORE = PLOT_DIR / "motifs"
RUN_SUMMARY = PLOT_DIR / "run_summary.json"
OUT_DIR = PLOT_DIR / "nulls_v1"
SURROGATE_RUNS = OUT_DIR / "surrogate_runs"

# Channels. The catalogue ids are 900-904; the `recordings` rows they
# point at are 466-470. Both numbers appear in the store and they are not
# the same field.
DB_PATH = REPO_ROOT / "DATA" / "db" / "annotations.sqlite"
SOURCE_FILE = "Fig2A_dt0p1.csv"
CATALOGUE_ID_BASE = 900
CHANNEL_NAMES = ("CH0", "CH1", "CH2", "CH3", "CH4")

# Seconds discarded from each end of every channel and every surrogate
# before anything is counted. See the wrap-around note above.
EDGE_TRIM_S = 50.0

# The floor `refine9` applied to the shipped store, restated through the
# module that owns it so a surrogate run cannot use a different one.
MIN_DEPTH_MV = refine9.MIN_DROP_DEPTH_MV

# The coarse cut the shipped figures use, and the fine one.
COARSE_K = 4
FINE_K = 10

# A "family" at the fixed-height test needs this many members. A tree of
# noise produces a long tail of two- and three-member twigs; counting them
# would make the surrogate look like it had a rich repertoire when what it
# has is fragmentation.
MIN_FAMILY_MEMBERS = 5

GENERATORS = ("aaft", "block50", "block5")
GENERATOR_LABELS = {
    "aaft": "AAFT phase randomisation",
    "block50": "block shuffle, 50 s blocks",
    "block5": "block shuffle, 5 s blocks",
}
BLOCK_SECONDS = {"block50": 50.0, "block5": 5.0}

SEED_BASE = 20260902


def seed_for(generator, channel, realisation):
    """`20260902 + 1000*generator_index + 10*channel + realisation`.

    Reproduced verbatim from the specification so any null in the JSON can
    be regenerated from its three coordinates alone.

    THIS FORMULA COLLIDES, AND THE COLLISION IS DOCUMENTED RATHER THAN
    SILENTLY PATCHED. `10*channel + realisation` is not injective once
    `realisation >= 10`: CH0 realisation 10 and CH1 realisation 0 both map
    to +10. Over the 5 x 100 grid there are 140 distinct seed values for
    500 channel-realisations, so each seed is reused by up to five of
    them. `seed_collisions` quantifies it; what matters is which
    collisions are harmful:

      WITHIN A CHANNEL - none. For fixed `channel`, the seed is strictly
      increasing in `realisation`, so a channel's 100 realisations are 100
      genuinely different surrogates. This is the property the per-channel
      nulls in panel A depend on, and it holds.

      WITHIN A REALISATION - none. For fixed `realisation`, the five
      channels differ by 10, so no realisation draws the same randomness
      twice. This is the property the pooled tree depends on, and it
      holds.

      ACROSS CHANNELS - yes. CH0 realisation 10 and CH1 realisation 0 draw
      the same random numbers. They are applied to DIFFERENT source
      signals, so the two surrogates are different signals; but their
      randomness is shared, so the pooled realisations are not perfectly
      independent of one another and the effective N behind a pooled p is
      somewhat below the nominal one.

    The formula is kept because it is the one the specification fixed and
    the one every recorded seed was drawn from; a future run should use
    `100 * channel + realisation` instead, which is injective for
    realisation < 100.
    """
    return int(SEED_BASE
               + 1000 * GENERATORS.index(generator)
               + 10 * int(channel)
               + int(realisation))


def seed_collisions(n_realisations, n_channels=5):
    """How badly `seed_for` collides over a grid of this size.

    Computed rather than asserted so the README quotes a measured number.
    """
    report = {"n_realisations": int(n_realisations),
              "n_channels": int(n_channels)}
    for generator in GENERATORS[:1]:
        pairs = [(c, r) for c in range(n_channels)
                 for r in range(n_realisations)]
        seeds = [seed_for(generator, c, r) for c, r in pairs]
        report["n_channel_realisations_per_generator"] = len(pairs)
        report["n_distinct_seeds_per_generator"] = len(set(seeds))
        report["max_reuse_of_one_seed"] = max(
            seeds.count(s) for s in set(seeds)) if seeds else 0
    report["unique_within_each_channel"] = all(
        len({seed_for(g, c, r) for r in range(n_realisations)})
        == n_realisations
        for g in GENERATORS for c in range(n_channels))
    report["unique_within_each_realisation"] = all(
        len({seed_for(g, c, r) for c in range(n_channels)}) == n_channels
        for g in GENERATORS for r in range(n_realisations))
    report["reading"] = (
        "%d channel-realisations per generator draw from only %d distinct "
        "seeds, so a seed is reused by up to %d of them - always on "
        "DIFFERENT channels, hence on different source signals. Seeds are "
        "unique within each channel (%s) and within each realisation (%s), "
        "which is what the per-channel and pooled nulls respectively "
        "require. The cost is that pooled realisations share randomness "
        "across channels, so the effective N behind a pooled p is below "
        "the nominal one. Use 100*channel + realisation next time."
        % (report["n_channel_realisations_per_generator"],
           report["n_distinct_seeds_per_generator"],
           report["max_reuse_of_one_seed"],
           report["unique_within_each_channel"],
           report["unique_within_each_realisation"]))
    return report


# ---------------------------------------------------------------------------
# the detector's arguments, read rather than retyped
# ---------------------------------------------------------------------------

def detect_kwargs(summary_path=RUN_SUMMARY):
    """The exact `detect_sliding` arguments the shipped run used.

    `window_s` and `overlap` are recorded per channel in
    `run_summary.json` and are asserted identical across the five.
    `fine` / `sensitive` / `micro` are not recorded as flags, but
    `per_pass_kept` records a nonzero count for `base`, `fine`, `sens` and
    `micro` on every channel, which is only possible if all three were on.
    `max_passes` is recorded nowhere; it is `run_drop9_report.py`'s
    default of 3 and nothing in the summary indicates an override, so it
    is taken from there and written into the output JSON so the assumption
    is visible rather than buried.
    """
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    channels = summary["channels"]
    window_s = {float(c["window_s"]) for c in channels}
    overlap = {float(c["overlap"]) for c in channels}
    if len(window_s) != 1 or len(overlap) != 1:
        raise ValueError(
            "channels disagree about the sliding window "
            f"(window_s={window_s}, overlap={overlap}) - a surrogate "
            "cannot be a null of two different detectors")

    passes_fired = {key for c in channels
                    for key, n in c["per_pass_kept"].items() if n}
    return {
        "window_s": window_s.pop(),
        "overlap": overlap.pop(),
        "max_passes": 3,
        "fine": "fine" in passes_fired,
        "sensitive": "sens" in passes_fired,
        "micro": "micro" in passes_fired,
        "_max_passes_source": ("run_drop9_report.py default; not recorded "
                               "in run_summary.json"),
        "_passes_fired_in_shipped_run": sorted(passes_fired),
    }


def channel_table(db_path=DB_PATH, source_file=SOURCE_FILE):
    """`[{catalogue_id, recording_id, channel, fs, npy_path}, ...]`."""
    import sqlite3
    from urllib.request import pathname2url
    # Opened READ-ONLY, and enforced by sqlite rather than by the fact
    # that the only statement below is a SELECT. This module is the one
    # that generates surrogates, and the standing rule for that work is
    # that nothing surrogate-derived may reach annotations.sqlite - a
    # guarantee worth having the database refuse rather than having a
    # reviewer take on trust.
    conn = sqlite3.connect(
        "file:%s?mode=ro" % pathname2url(str(db_path)), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, channel, fs, npy_path FROM recordings "
            "WHERE source_file = ? ORDER BY channel",
            (source_file,)).fetchall()
    finally:
        conn.close()
    if not rows:
        raise SystemExit(f"no recordings for {source_file!r} in {db_path}")
    return [{"catalogue_id": CATALOGUE_ID_BASE + int(r["channel"]),
             "recording_id": int(r["id"]),
             "channel": int(r["channel"]),
             "fs": float(r["fs"]),
             "npy_path": str(REPO_ROOT / r["npy_path"])} for r in rows]


def load_channel(entry):
    return np.asarray(np.load(entry["npy_path"], mmap_mode="r"), dtype=float)


# ---------------------------------------------------------------------------
# 1. the surrogates
# ---------------------------------------------------------------------------

def aaft_surrogate(x, rng):
    """Amplitude-adjusted Fourier transform surrogate (Theiler 1992).

    Three steps, and the middle one is the adapter's:

      1. rank-map `x` onto Gaussian deviates, so the phase step operates
         on something whose spectrum is meaningful under a Gaussian
         assumption rather than on a heavily skewed marginal;
      2. `_phase_randomise` that Gaussian version - the PRD's own
         surrogate block, not a second copy of it;
      3. rank-map the result back onto `x`'s own sorted values.

    Step 3 is what makes this AAFT rather than plain phase randomisation,
    and it is the step that matters here: these channels are strongly
    non-Gaussian (long one-sided excursions), and a surrogate that
    Gaussianised them would be nulling the marginal distribution instead
    of the phase structure. The output is a permutation of the input's
    exact sample values.

    The cost, stated because it is real: step 3 distorts the spectrum
    slightly, so AAFT preserves the periodogram approximately rather than
    exactly. IAAFT iterates to fix that; it is not used here because the
    statistic under test is a detection count, which is far more sensitive
    to the marginal than to a few percent of spectral leakage.
    """
    x = np.asarray(x, dtype=float).ravel()
    ranks = np.argsort(np.argsort(x))
    gaussian = np.sort(rng.standard_normal(len(x)))[ranks]
    randomised = _phase_randomise(gaussian, rng)
    return np.sort(x)[np.argsort(np.argsort(randomised))]


def block_shuffle_surrogate(x, rng, block_s, fs):
    """Contiguous blocks of `block_s` seconds, reordered.

    Straight through to `Adapters.preprocessing_surrogate._block_shuffle`
    - the trailing partial block stays in place so the length is exactly
    preserved, which the sliding window depends on.
    """
    return _block_shuffle(np.asarray(x, dtype=float).ravel(), rng,
                          float(block_s), float(fs))


def make_surrogate(x, fs, generator, seed):
    """One surrogate of one channel. A fresh `Generator` per call, so the
    seed alone determines the output."""
    rng = np.random.default_rng(int(seed))
    if generator == "aaft":
        return aaft_surrogate(x, rng)
    if generator in BLOCK_SECONDS:
        return block_shuffle_surrogate(x, rng, BLOCK_SECONDS[generator], fs)
    raise ValueError(f"unknown generator {generator!r}; expected one of "
                     f"{GENERATORS}")


# ---------------------------------------------------------------------------
# 2. the chain, unchanged
# ---------------------------------------------------------------------------

def run_chain(x, entry, kwargs, *, min_depth_mv=MIN_DEPTH_MV):
    """`detect_sliding` then `refine_store`, exactly as the shipped run.

    Returns `(before_floor, after_floor, snippets, info)` with `snippets`
    in the NESTED `{event_id: {field: array}}` form - the form
    `motifs5.load_store` returns and the form `gradients.event_gradients`
    indexes. `detect_sliding` hands back the flat `{event_id}__{field}`
    form, and `refine_store` returns whichever form it was given, so the
    conversion has to happen once, here, rather than at every call site.

    Both counts are wanted: the floor removes half the raw store on the
    real data, and a surrogate whose events are all sub-floor is a
    different finding from one that finds nothing at all.
    """
    fs = entry["fs"]
    detect = {k: v for k, v in kwargs.items() if not k.startswith("_")}
    rows, arrays, info = passes9.detect_sliding(
        x, fs,
        catalogue_id=entry["catalogue_id"],
        recording_id=entry["recording_id"],
        source_file=os.path.basename(entry["npy_path"]),
        channel=entry["channel"],
        span_label=f"{SOURCE_FILE} CH{entry['channel']}",
        span_key="id%03d" % entry["catalogue_id"],
        **detect)

    # Refine with the gate OFF, then gate by hand, so the pre-floor and
    # post-floor populations come out of one refinement rather than two.
    nested = {}
    for key, values in arrays.items():
        event_id, _, name = key.partition("__")
        nested.setdefault(event_id, {})[name] = values

    refined, snippets, report = refine9.refine_store(
        rows, nested, min_depth_mv=min_depth_mv,
        refine=True, dedup=True, gate=False)
    after, n_below = refine9.depth_gate(refined, min_depth_mv)
    report["n_below_noise_floor"] = int(n_below)
    report["n_out"] = len(after)
    return refined, after, snippets, {**info, "refine": report}


def trim_edges(rows, fs, n_samples, trim_s=EDGE_TRIM_S):
    """Keep only events whose ONSET is at least `trim_s` from either end.

    Applied identically to the real store and to every surrogate. The
    onset rather than the snippet is the criterion because the onset is
    where the event is; a snippet reaching into the trimmed region is
    still an event that happened in the interior.
    """
    lo = int(round(float(trim_s) * float(fs)))
    hi = int(n_samples) - lo
    return [r for r in rows if lo <= int(r["onset_idx"]) < hi]


# ---------------------------------------------------------------------------
# 3. the statistics
# ---------------------------------------------------------------------------

def quartiles(values):
    values = np.asarray([v for v in values if v is not None
                         and np.isfinite(v)], dtype=float)
    if not values.size:
        return {"n": 0, "q1": None, "median": None, "q3": None}
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    return {"n": int(values.size), "q1": float(q1),
            "median": float(med), "q3": float(q3)}


def gradient_table(rows, snippets):
    """`clusterfigs9._gradient_table`, imported lazily.

    Lazy because that module pulls matplotlib in at import time; this
    module must stay importable by a test that draws nothing.
    """
    from Pipelines.drop_motifs.clusterfigs9 import _gradient_table
    return _gradient_table(rows, snippets)


EMPTY_ANGLE_STATS = {
    "n": 0, "spearman_rho_depth_vs_angle": None, "spearman_p": None,
    "duration_vs_depth_exponent": None, "duration_vs_depth_r2": None,
    "median_depth_mv": None, "median_angle_deg": None,
}


def angle_stats(rows, snippets):
    """Spearman rho(depth, angle) and the control exponent b, over the
    same population the shipped rose uses - short falls and
    non-descending events excluded by `_gradient_table`, not by a second
    rule written here."""
    if len(rows) < 8:
        return dict(EMPTY_ANGLE_STATS)
    built, _ = gradient_table(rows, snippets)
    if built is None or len(built["depths"]) < 8:
        return dict(EMPTY_ANGLE_STATS)

    depths = np.asarray(built["depths"], dtype=float)
    angles = np.degrees(np.asarray(built["angles"], dtype=float))
    durations = np.asarray(built["durations"], dtype=float)
    rho = spearmanr(depths, angles)

    ok = (depths > 0) & (durations > 0)
    if int(ok.sum()) >= 3 and len(np.unique(depths[ok])) >= 3:
        fit = linregress(np.log10(depths[ok]), np.log10(durations[ok]))
        b, r2 = float(fit.slope), float(fit.rvalue ** 2)
    else:
        b, r2 = None, None

    return {"n": int(len(depths)),
            "spearman_rho_depth_vs_angle": float(rho.statistic),
            "spearman_p": float(rho.pvalue),
            "duration_vs_depth_exponent": b,
            "duration_vs_depth_r2": r2,
            "median_depth_mv": float(np.median(depths)),
            "median_angle_deg": float(np.median(angles))}


# The two ways a motif can be turned into a shape vector, and the reason
# both are computed rather than one being chosen:
#
#   "fall"     onset..trough only. This is what `clusterfigs7._waveform_of`
#              slices and therefore what the SHIPPED `ALL_dendrogram.png`,
#              `ALL_families.png` and every quoted family count are built
#              from. Any null of the shipped analysis has to use it.
#
#   "snippet"  the whole re-cut snippet: refine9's 1.2 falls of approach,
#              the fall, and 1.8 falls of recovery. Strictly more shape
#              information - a z-normalised monotone fall is close to a
#              straight line whatever its curvature, so "fall" throws away
#              most of what distinguishes one drop morphology from
#              another, which is a plausible explanation for the shipped
#              tree's cophenetic r of 0.681.
#
# The null grid runs both. If the two disagree about whether the real
# store has a repertoire, that is a fact about the representation and
# belongs in the paper, not a number to choose between.
FEATURE_MODES = ("fall", "snippet")


def waveform_of(row, snippets, mode="fall", field="detrended_mv"):
    """One event's shape vector in its native units.

    `mode="fall"` reproduces `clusterfigs7._waveform_of` with
    `orient_rises_as_drops=False` (drop_motifs8 onward, and what
    drop_motifs9 ran). It is restated here rather than imported because
    that module pulls matplotlib in at import time and this one must stay
    drawing-free.

    THE CLIPPING MATTERS AND IS NOT COSMETIC. `onset_idx` and
    `snippet_start_idx` are absolute sample indices; the stored array is
    supposed to span exactly `snippet_end_idx - snippet_start_idx`
    samples, and in this store it sometimes does not (30 of the 1058
    refined rows, 208 of the 1736 raw ones). Where the array is shorter
    than the indices claim, the clip lands the onset on the last stored
    sample and the "fall" comes back one sample long - which
    `feature_matrix` turns into an all-zero 200-vector. `build_features`
    counts those and removes them rather than letting them cluster
    together as a spurious family of identical points.
    """
    fields = snippets.get(row["event_id"])
    if not fields:
        return None
    values = np.asarray(fields.get(field), dtype=float).ravel()
    if values.size < 2 or not np.all(np.isfinite(values)):
        return None
    if mode == "snippet":
        return values
    if mode != "fall":
        raise ValueError(f"unknown feature mode {mode!r}; expected one of "
                         f"{FEATURE_MODES}")
    start = int(row["snippet_start_idx"])
    onset = int(np.clip(int(row["onset_idx"]) - start, 0, values.size - 1))
    trough = int(np.clip(int(row["trough_idx"]) - start, onset + 1,
                         values.size))
    fall = values[onset:trough]
    return fall if fall.size >= 2 else values[onset:onset + 2]


def build_features(rows, snippets, mode="fall"):
    """The 200-point z-normalised feature matrix, and the rows it covers.

    `dc.feature_matrix` is the shipped call - the only place in this
    pipeline where normalisation happens - so the surrogate trees and the
    shipped tree are built from one representation.

    Returns `(features, keep, dropped)`. A row is dropped when its
    snippet is missing, non-finite, or degenerates to a constant: a
    constant vector z-normalises to all zeros, and any number of those sit
    on top of each other at the origin of feature space and read as a
    perfectly tight family that is really a store defect. Dropping them
    is applied identically to the real store and to every surrogate, and
    the count is reported on both sides.
    """
    waveforms, keep = [], []
    dropped = {"missing": 0, "degenerate": 0}
    for row in rows:
        wave = waveform_of(row, snippets, mode=mode)
        if wave is None or wave.size < 2:
            dropped["missing"] += 1
            continue
        if float(np.std(wave)) == 0.0:
            dropped["degenerate"] += 1
            continue
        waveforms.append(wave)
        keep.append(row)
    if len(keep) < 6:
        return None, keep, dropped
    features = dc.feature_matrix(waveforms)
    return features, keep, dropped


def within_family_dispersion(features, labels):
    """Mean distance from a member to its own family's centroid.

    In the z-normalised feature space, pooled over all members, so it
    reads as "how far a typical event is from the shape it is supposed to
    be an instance of". Not sum-of-squares: the surrogate stores hold
    different numbers of events and a sum would compare n rather than
    tightness.
    """
    features = np.asarray(features, dtype=float)
    labels = np.asarray(labels)
    distances, per_family = [], {}
    for label in sorted(set(labels.tolist())):
        members = features[labels == label]
        if not len(members):
            continue
        d = np.linalg.norm(members - members.mean(axis=0), axis=1)
        distances.append(d)
        per_family[int(label)] = {"n": int(len(members)),
                                  "mean_distance": float(d.mean())}
    if not distances:
        return None, per_family
    return float(np.concatenate(distances).mean()), per_family


def cut_height_for_k(Z, k):
    """The absolute Ward merge height half way between the merge that
    produces `k` clusters and the one that produces `k-1`.

    The same rule `clusterfigs7._cut_height` uses, restated here because
    that module imports matplotlib and this one must not.
    """
    heights = np.sort(np.asarray(Z, dtype=float)[:, 2])
    if k >= len(heights) + 1:
        return 0.0
    upper = heights[-(k - 1)]
    lower = heights[-k] if k <= len(heights) else 0.0
    return float((upper + lower) / 2.0)


def family_stats(features, *, cut_height=None, coarse_k=COARSE_K,
                 min_members=MIN_FAMILY_MEMBERS, keep_linkage=False):
    """Ward tree over `features`, plus every family statistic the nulls
    compare.

    `cut_height=None` computes and reports this tree's own k=4 height -
    that is how the real store's height is obtained in the first place.
    Passing the real store's height is how a surrogate is measured against
    it.
    """
    features = np.asarray(features, dtype=float)
    condensed = pdist(features, metric="euclidean")
    Z = linkage(condensed, method="ward")
    coph, _ = cophenet(Z, condensed)

    own_cut = cut_height_for_k(Z, int(coarse_k))
    height = float(own_cut if cut_height is None else cut_height)
    at_height = fcluster(Z, height, criterion="distance")
    sizes = np.bincount(at_height)[1:]

    labels_k = fcluster(Z, int(coarse_k), criterion="maxclust")
    dispersion, per_family = within_family_dispersion(features, labels_k)

    out = {
        "n": int(len(features)),
        "cophenetic": float(coph),
        "own_cut_height_k4": float(own_cut),
        "applied_cut_height": height,
        "n_families_at_height": int(len(sizes)),
        "n_families_at_height_min_members": int((sizes >= min_members).sum()),
        "min_family_members": int(min_members),
        "largest_family_at_height": int(sizes.max()) if sizes.size else 0,
        "within_family_dispersion": dispersion,
        "max_merge_height": float(np.sort(Z[:, 2])[-1]),
    }
    if keep_linkage:
        out["linkage"] = Z
        out["labels_k"] = labels_k
        out["per_family_dispersion"] = per_family
    return out


def pooled_cluster_stats(rows, snippets, *, cut_height, mode="fall",
                         **kwargs):
    """Family statistics for one pooled population - the real store, or
    one surrogate realisation across all five channels."""
    features, keep, dropped = build_features(rows, snippets, mode=mode)
    if features is None:
        return {"n": len(keep), "mode": mode, "dropped": dropped,
                "cophenetic": None,
                "own_cut_height_k4": None, "applied_cut_height": cut_height,
                "n_families_at_height": 0,
                "n_families_at_height_min_members": 0,
                "min_family_members": MIN_FAMILY_MEMBERS,
                "largest_family_at_height": 0,
                "within_family_dispersion": None, "max_merge_height": None}
    stats = family_stats(features, cut_height=cut_height, **kwargs)
    stats["mode"] = mode
    stats["dropped"] = dropped
    return stats


def cluster_stats_both_modes(rows, snippets, *, cut_heights):
    """`{mode: family_stats}` for both representations at once.

    Clustering is a small fraction of a realisation's cost (detection
    dominates), so both trees are built in the same worker call rather
    than the grid being run twice.
    """
    return {mode: pooled_cluster_stats(rows, snippets, mode=mode,
                                       cut_height=(cut_heights or {}).get(mode))
            for mode in FEATURE_MODES}


def realisation_stats(before, after, snippets, entry, *, n_samples,
                      trim_s=EDGE_TRIM_S):
    """Every number one channel of one realisation contributes, on the
    trimmed interior.

    The signal arrays are not returned. `_rows` carries the trimmed rows
    so the caller can pool five channels into one tree; the caller drops
    it before writing the summary row.
    """
    fs = entry["fs"]
    before_t = trim_edges(before, fs, n_samples, trim_s)
    after_t = trim_edges(after, fs, n_samples, trim_s)

    per_pass = {}
    for row in after_t:
        key = str(row.get("pass_key", "?"))
        per_pass[key] = per_pass.get(key, 0) + 1

    out = {
        "channel": int(entry["channel"]),
        "n_before_floor": len(before_t),
        "n_after_floor": len(after_t),
        "per_pass": per_pass,
        "depth_mv": quartiles(abs(float(r["drop_depth_mv"])) for r in after_t),
        "fall_duration_s": quartiles(float(r["fall_duration_s"])
                                     for r in after_t),
    }
    out.update({"angle_" + k: v
                for k, v in angle_stats(after_t, snippets).items()})
    out["_rows"] = after_t
    return out


def rank_p(observed, null_values, *, greater=True):
    """One-sided rank p with the observed value included in the reference
    set: `(1 + #{null >= observed}) / (1 + N)`.

    `greater=True` asks "is the observed value unusually LARGE"; False
    asks the other tail. No distributional assumption, and the +1 makes
    the smallest attainable p `1/(1+N)` rather than 0 - which is why N
    below 20 is not worth computing (1/21 = 0.048).
    """
    null_values = np.asarray([v for v in null_values
                              if v is not None and np.isfinite(v)],
                             dtype=float)
    base = {"n_null": int(null_values.size),
            "direction": "greater" if greater else "less",
            "observed": (None if observed is None
                         or not np.isfinite(observed) else float(observed))}
    if not null_values.size or base["observed"] is None:
        return {**base, "p": None, "null_median": None,
                "null_q1": None, "null_q3": None,
                "null_min": None, "null_max": None}
    if greater:
        n_hit = int((null_values >= float(observed)).sum())
    else:
        n_hit = int((null_values <= float(observed)).sum())
    q1, med, q3 = np.percentile(null_values, [25, 50, 75])
    return {**base,
            "p": float((1 + n_hit) / (1 + null_values.size)),
            "null_median": float(med), "null_q1": float(q1),
            "null_q3": float(q3), "null_min": float(null_values.min()),
            "null_max": float(null_values.max())}


def channel_entry(per_channel, channel):
    """One channel's entry from a per-channel dict, whatever the key form.

    `observed["per_channel"]` is built in memory keyed by INT channel, and
    `json.dump` turns every one of those keys into a string on the way to
    disk. The grid computes its p-values in memory (int keys) and the
    figure reads them back from the file (string keys), so exactly one of
    the two would work and the other would raise `KeyError: 0` - after
    the fifty-minute grid had finished. This accessor is the fix, and it
    also accepts "CH0" so a future rekeying does not break either caller.
    """
    for key in (int(channel), str(int(channel)), "CH%d" % int(channel)):
        if key in per_channel:
            return per_channel[key]
    raise KeyError("no entry for channel %r in %r"
                   % (channel, sorted(per_channel)))


def load_refined_store(store=REFINED_STORE):
    return motifs5.load_store(str(store))


def jsonable(obj):
    """numpy scalars and arrays out, plain Python in - so `json.dump` on a
    results dict cannot fail three hours into a run."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()
                if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return value if np.isfinite(value) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj
