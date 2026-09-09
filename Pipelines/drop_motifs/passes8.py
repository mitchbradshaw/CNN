"""
passes8.py
===========
drop_motifs8. The detection passes are `passes7`'s; two things change
about what survives them and how the survivors are grouped.

1. A RISE IS ONLY WHAT THE DROPS LEFT OVER
------------------------------------------
`passes6.deduplicate` already knew that a rise peaking where a drop begins
is that drop's LEADING edge. It did not know about the other edge, and on
catalogue ID 10 that is the whole population. Measured on the 7.3 store:

    +1 base  onset 1362676  trough 1362707
    -1 inv   onset 1362708  trough 1362773     <- starts AT the trough

Every one of ID 10's thirty surviving inverted detections, and all four of
ID 22's, begins within a sample or two of a kept drop's trough. They are
the recovery edge of an excursion the drop pass already recorded, which is
why the figures alternated drop, rise, drop, rise down the train. Not one
of them had its peak inside a drop's window, so the containment rule that
was tried and rejected in drop_motifs6 would not have caught them either.

Rule 3 is the mirror of rule 2 and is stated the same way: an opposite
direction detection whose ONSET coincides with a kept event's TROUGH is
that event's trailing edge.

An isolated rise - ID 385's opposite-direction population, which the
supervisor asked for - touches neither end of any drop and is untouched.

While here: the tolerance was a duration in SECONDS compared against a
difference in SAMPLE INDICES. Every recording in this catalogue is 1 Hz so
the two coincided and nothing was wrong, but the confusion would scale the
tolerance by fs on the first recording that is not.

2. THE LARGEST DROPS GET A FAMILY OF THEIR OWN
----------------------------------------------
`scale_bands` splits on fall duration, so size cannot separate. On ID 10
that put its two large spikes - 7.30 mV and 5.38 mV against a median of
2.41 - in two different bands, each lumped with the small train: the
7.30 with thirty-one others in the 4-7 s band, the 5.38 with five in the
16-31 s band.

`size_split` lifts the motifs an octave or more above the span's median
depth into a band of their own, across duration bands. It fires only when
at least two qualify, because a lone giant is already drawn and
de-emphasised by the outlier screen and a family of one shows no family.
"""

import numpy as np

from Pipelines.drop_motifs import passes7
from Pipelines.drop_motifs import passes6
from Pipelines.drop_motifs.passes6 import DEDUP_ONSET_FRAC, scale_bands
from Pipelines.drop_motifs.passes7 import (PASS_BASE, PASS_FINE, PASS_INV,  # noqa: F401
                                           PASS_LABELS, PASS_MICRO,
                                           PASS_ORDER, PASS_SENS, motif_key)

# ---------------------------------------------------------------------------
# 1. dedup
# ---------------------------------------------------------------------------


# One copy of this rule, in `passes6`, since drop_motifs10 fixed the
# seconds/samples defect there too. Two copies that disagreed is how the
# defect survived four runs.
_fs_of = passes6._fs_of


def deduplicate(candidates, *, onset_frac=DEDUP_ONSET_FRAC):
    """Drop later-pass detections of an event an earlier pass already has.

    `candidates` is `[(pass_key, sign, onset_idx, trough_idx,
    fall_duration_s, start_idx, end_idx, payload), ...]` in priority order
    - base first, inverted last - and the kept subset comes back in order.

    THREE rules now.

      1. same direction: onsets within a fraction of the event's own
         length are the same event found twice.
      2. opposite direction, LEADING edge: the rise peaks where the drop
         begins. One excursion, not two.
      3. opposite direction, TRAILING edge: the rise begins where the drop
         bottoms out. Also one excursion - and on ID 10 this is every
         single inverted detection.

    Rules 2 and 3 together say a rise is kept only when it touches neither
    end of any drop already kept, which is what "whatever is left over
    after the drops" means.
    """
    kept = []
    for entry in candidates:
        _, sign, onset, trough, fall_s, _, _, payload = entry
        onset, trough, sign = float(onset), float(trough), int(sign)
        fs = _fs_of(payload)
        duplicate = False

        for kept_entry in kept:
            (_, kept_sign, kept_onset, kept_trough,
             kept_fall, _, _, _) = kept_entry
            # Seconds -> samples, so the tolerance means the same thing
            # whatever the recording is sampled at.
            tolerance = onset_frac * max(float(fall_s), float(kept_fall)) * fs

            if int(kept_sign) == sign:
                if abs(onset - float(kept_onset)) <= tolerance:
                    duplicate = True
                    break
            elif (abs(trough - float(kept_onset)) <= tolerance
                  or abs(onset - float(kept_trough)) <= tolerance):
                duplicate = True
                break

        if not duplicate:
            kept.append(entry)
    return kept


# ---------------------------------------------------------------------------
# 2. the size split
# ---------------------------------------------------------------------------

# How far above the span's MEDIAN depth a motif must sit to count as one
# of the large ones. An octave: the same idiom the duration bands use, and
# on ID 10 it separates 7.30 and 5.38 from a median of 2.41 while leaving
# the 3.71 that follows them where it is.
#
# Median rather than minimum, because ID 10's shallowest drop is 0.07 mV
# and anchoring on it would call two thirds of the span large.
LARGE_DEPTH_RATIO = 2.0

# Fewer than this and the split does not happen. A single outlier is
# already drawn and de-emphasised by `style6.outlier_mask`; giving it a
# panel spends a row and a hue to show one trace.
MIN_LARGE_MEMBERS = 2


def size_split(depths_mv, bands, labels, *, ratio=LARGE_DEPTH_RATIO,
               min_members=MIN_LARGE_MEMBERS):
    """Lift the largest drops into a band of their own.

    Returns `(bands, labels)` with at most one band appended. Duration
    labels for the other bands are left as they were: they describe the
    octave the band covers, which does not change because two of its
    members moved.
    """
    depths = np.abs(np.asarray(depths_mv, dtype=float).ravel())
    bands = np.asarray(bands, dtype=int).ravel().copy()
    labels = list(labels)
    if depths.size == 0 or depths.size != bands.size:
        return bands, labels

    finite = depths[np.isfinite(depths) & (depths > 0)]
    if finite.size < min_members + 1:
        return bands, labels

    threshold = float(np.median(finite)) * float(ratio)
    large = np.isfinite(depths) & (depths >= threshold)
    if int(large.sum()) < min_members:
        return bands, labels
    # Everything being "large" means the median was dragged up by the very
    # motifs being selected; there is no separation to draw.
    if int(large.sum()) >= depths.size - 1:
        return bands, labels

    index = len(labels)
    bands[large] = index
    labels.append(f"{depths[large].min():.3g}-{depths[large].max():.3g} mV"
                  f" (largest)")
    return bands, labels


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def detect_multiscale(x, fs, **kwargs):
    """`passes7.detect_multiscale`, re-dedupled and re-banded.

    The passes themselves are untouched, so every per-pass count the
    drop_motifs7 report validated still reproduces; what changes is which
    detections survive the merge and how the survivors are grouped.
    """
    rows, arrays, info = passes7.detect_multiscale(x, fs, **kwargs)
    rows, arrays, info = _reduce_recoveries(rows, arrays, info, float(fs))

    bands, labels = scale_bands([r["fall_duration_s"] for r in rows])
    bands, labels = size_split(
        [abs(float(r["drop_depth_mv"])) for r in rows], bands, labels)
    for row, band in zip(rows, bands):
        row["scale_band"] = int(band)
    info["scale_band_labels"] = labels
    info["n_scale_bands"] = len(labels)
    info["per_pass_kept"] = {
        key: sum(1 for r in rows if r["pass_key"] == key) for key in PASS_ORDER
    }
    return rows, arrays, info


def _reduce_recoveries(rows, arrays, info, fs):
    """Re-run the merge with rule 3 over `passes7`'s output.

    `passes7.detect_multiscale` has already deduplicated under the two-rule
    version, so this is a second, stricter pass over what it kept rather
    than a re-detection. Drops keep their priority: they are presented
    first, in pass order, exactly as the first merge saw them.
    """
    order = {key: i for i, key in enumerate(PASS_ORDER)}
    ranked = sorted(
        rows, key=lambda r: (0 if int(r.get("signal_sign", 1)) > 0 else 1,
                             order.get(r.get("pass_key"), 99),
                             int(r["onset_idx"])))
    candidates = [(r.get("pass_key"), int(r.get("signal_sign", 1)),
                   r["onset_idx"], r["trough_idx"], r["fall_duration_s"],
                   r["snippet_start_idx"], r["snippet_end_idx"],
                   {"fs": fs, "row": r})
                  for r in ranked]

    kept_rows = [entry[7]["row"] for entry in deduplicate(candidates)]
    keep_ids = {r["event_id"] for r in kept_rows}
    dropped = len(rows) - len(kept_rows)

    kept_arrays = {key: value for key, value in arrays.items()
                   if key.split("__")[0] in keep_ids}
    info = dict(info)
    info["n_recovery_edges_dropped"] = int(dropped)
    info["n_after_dedup"] = len(kept_rows)
    # Back in time order, which is what every figure and the store expect.
    kept_rows.sort(key=lambda r: int(r["onset_idx"]))
    return kept_rows, kept_arrays, info
