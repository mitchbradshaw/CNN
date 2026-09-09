"""
round2.py
==========
The shared floor under round 2: load the corrected store, build the two
representations every task in this round decodes or clusters, and hold the
one seed formula.

Nothing here draws. `round2figs1` does that, and this module is importable
from a headless test.

The two representations
-----------------------
The whole round turns on the difference between them, so they are built in
one place and named the same way everywhere:

  AMPLITUDE   three numbers per event - drop depth in mV, fall duration in
              seconds, and the tangent slope at the steepest sample. These
              carry the size of the excursion.

  SHAPE       the 200-point z-normalised feature vector `cluster.
              feature_matrix` builds, which is the space the shipped tree
              was built in. Each event's own duration and amplitude are
              divided out per vector before any distance is taken, so
              nothing about size survives into it. `nulls_v1` measured that
              directly: the correlation between a feature vector's norm and
              its event's drop depth is -0.015.

The claim under test in Task B is that the first recovers the electrode and
the second does not. Keeping them side by side in one function is what makes
that a decoding comparison rather than two separate analyses.

The seed formula
----------------
`SEED_BASE + 100 * channel + realisation`. Round one used `10 * channel`,
which is not injective once realisation >= 10 - CH0 realisation 10 and CH1
realisation 0 drew identical randomness, and 500 channel-realisations drew
from 140 distinct seeds. 100 is the smallest multiplier that separates the
channels for realisation counts up to 100, which is what this round uses.
"""

import os

import numpy as np

from Pipelines.drop_motifs.clusterfigs7 import _waveform_of
from Working.Detection.drop_motifs import cluster as dc

SEED_BASE = 20260903

STORE = os.path.join("Plots", "drop_motifs9_fig2a", "round2_v1", "motifs")
RAW_STORE = os.path.join("Plots", "drop_motifs9_fig2a", "round2_v1",
                         "motifs_raw")
OUT_DIR = os.path.join("Plots", "drop_motifs9_fig2a", "round2_v1")
NULLS_V1 = os.path.join("Plots", "drop_motifs9_fig2a", "nulls_v1")

CHANNELS = (0, 1, 2, 3, 4)

# The three amplitude features, in the order every table and figure in this
# round prints them.
AMPLITUDE_FEATURES = ("drop_depth_mv", "fall_duration_s", "max_slope_raw")
AMPLITUDE_LABELS = ("drop depth (mV)", "fall duration (s)",
                    "tangent slope (mV/s)")


def seed(channel, realisation=0, base=SEED_BASE):
    """The round-2 seed. Injective for realisation < 100."""
    return int(base) + 100 * int(channel) + int(realisation)


def load(store=STORE, drop_zero_variance=True):
    """`(rows, shape, amplitude, channel, info)` from a refined store.

    `shape` is (n, 200) z-normalised; `amplitude` is (n, 3) raw units;
    `channel` is (n,) int. Rows whose feature vector has no variance are
    dropped by default and counted, because a constant vector z-normalises
    to zeros and lands on top of every other one at distance zero. On the
    corrected store there should be none of them, and the count is reported
    rather than assumed - that assumption is exactly what round one's
    defect hid behind.
    """
    from Working.Detection.drop_motifs import motifs5

    rows, snippets, manifest = motifs5.load_store(store)
    waveforms, keep = [], []
    for row in rows:
        # Raises on a length mismatch. That is the point: see _waveform_of.
        wave = _waveform_of(row, snippets, orient_rises_as_drops=False)
        if wave is None:
            continue
        waveforms.append(wave)
        keep.append(row)

    features = dc.feature_matrix(waveforms)
    variance = features.std(axis=1)
    n_zero = int(np.sum(variance <= 0.0))
    if drop_zero_variance and n_zero:
        mask = variance > 0.0
        features = features[mask]
        keep = [r for r, ok in zip(keep, mask) if ok]
        waveforms = [w for w, ok in zip(waveforms, mask) if ok]

    amplitude = np.column_stack([
        [abs(float(r[name])) for r in keep] for name in AMPLITUDE_FEATURES])
    channel = np.asarray([int(r["channel"]) for r in keep], dtype=int)

    info = {
        "store": store,
        "n_rows_in_store": len(rows),
        "n_clustered": len(keep),
        "n_zero_variance_dropped": n_zero,
        "n_per_channel": {int(c): int(np.sum(channel == c))
                          for c in sorted(set(channel.tolist()))},
        "manifest_kind": manifest.get("kind"),
    }
    return keep, features, amplitude, channel, waveforms, info


def medoid_index(features, member_indices):
    """Index (into `features`) of the member closest to its family's others.

    A medoid rather than a centroid because Task B2 assigns events on one
    channel to a shape learned on another, and a centroid is an average of
    z-normalised vectors that is not itself a normalised waveform. The
    medoid is a real event, so "the shapes CH0 learned" is a set of traces
    a reader can be shown.
    """
    member_indices = np.asarray(member_indices, dtype=int)
    if member_indices.size == 1:
        return int(member_indices[0])
    block = features[member_indices]
    d = np.sqrt(((block[:, None, :] - block[None, :, :]) ** 2).sum(axis=2))
    return int(member_indices[int(np.argmin(d.sum(axis=1)))])


def family_table(rows, labels, features=None):
    """Per-family n, median depth, median fall, and channel composition."""
    labels = np.asarray(labels)
    out = []
    for family in sorted(set(labels.tolist())):
        members = np.flatnonzero(labels == family)
        depths = [abs(float(rows[i]["drop_depth_mv"])) for i in members]
        falls = [abs(float(rows[i]["fall_duration_s"])) for i in members]
        channels = [int(rows[i]["channel"]) for i in members]
        entry = {
            "family": int(family),
            "n": int(members.size),
            "median_depth_mv": float(np.median(depths)),
            "median_fall_s": float(np.median(falls)),
            "channels": {int(c): int(channels.count(c))
                         for c in sorted(set(channels))},
            "n_channels_held": len(set(channels)),
        }
        if features is not None:
            entry["medoid_index"] = medoid_index(features, members)
        out.append(entry)
    return out


def within_family_distance(features, labels):
    """Mean Euclidean distance from an event to its family's centroid.

    The same statistic `nulls_v1` compared against the surrogate grid, so
    the round-2 number and the round-1 null are on one scale.
    """
    features = np.asarray(features, dtype=float)
    labels = np.asarray(labels)
    total, n = 0.0, 0
    for family in set(labels.tolist()):
        block = features[labels == family]
        if block.size == 0:
            continue
        centroid = block.mean(axis=0)
        total += float(np.linalg.norm(block - centroid, axis=1).sum())
        n += block.shape[0]
    return total / max(n, 1)


def permutation_p(observed, null, *, greater=True):
    """The (1 + #as-extreme) / (1 + N) p-value, floored as round one did.

    Reported with its floor visible: with N draws the smallest attainable p
    is 1/(1+N), and a run that prints 0.0000 is printing its own resolution
    rather than a measurement.
    """
    null = np.asarray(null, dtype=float)
    if null.size == 0:
        return float("nan"), True
    hits = (null >= observed) if greater else (null <= observed)
    p = float((1 + int(np.sum(hits))) / (1 + null.size))
    return p, bool(p <= 1.0 / (1.0 + null.size))
