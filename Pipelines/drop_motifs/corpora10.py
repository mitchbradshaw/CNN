"""
corpora10.py
=============
The four labelled corpora drop_motifs10 detects over, and the one thing
that separates them that is NOT biology.

The confound, stated before anything is measured
------------------------------------------------
    corpus        species   recordings        fs      framing   fall range
    oyster        oyster    1, 2, 4, 6, 7, 16 1 Hz    span      4 - 236 s
    sp385         [385]     Mushroom_260720   1 Hz    span      3 - 47 s
    reishi_10hz   reishi    900-904 (466-470) 10 Hz   sliding   0.3 - 3.7 s
    reishi_1hz    reishi    the same, decimated 1 Hz  sliding   0.3 - 3.7 s

SPECIES IS PERFECTLY CONFOUNDED WITH SAMPLING RATE between reishi and the
other two, and nothing in a dendrogram would show it. A feature vector is
200 points resampled from the event's OWN samples, so a reishi event built
from 7 samples is 96% interpolation while an oyster event built from 150
samples is a decimation. A tree that separates reishi from oyster may be
separating 10 Hz from 1 Hz.

Two things follow and both are built in here rather than discussed later.

  OYSTER AGAINST sp385 IS THE CLEAN CONTRAST. Both 1 Hz, both single-span
  framing. Any family mixing them mixes species at matched rate, and that
  pair carries the cross-species claim.

  reishi_1hz IS THE RATE CONTROL. The same physical events, decimated
  properly, run through the same sliding chain with the window length in
  SECONDS unchanged. If families still mix reishi with the others after
  the rate is matched, the three-species claim is real; if the mixing only
  appears at 10 Hz, it was the resample.

Decimation
----------
`decimate_to` low-pass filters and then downsamples. Taking every tenth
sample would alias every drop shorter than 2 s straight into the band the
detector reads, which would make the control worse than useless - it would
manufacture exactly the short, sharp events whose absence it is meant to
test for. `scipy.signal.decimate` with an order-8 Chebyshev I zero-phase
filter is used, zero-phase so no event moves in time and the decimated
onsets stay comparable to the 10 Hz ones sample for sample.

The species of ID 385
---------------------
`SPECIES_385` is the label used throughout. The brief carries it as
`[SPECIES-385]`, unresolved: `Mushroom_260720` names the experiment, not
the organism, and nothing in `recordings`, in the catalogue spreadsheet or
in `spans5.SPANS5`'s note records a species for it. It is treated here as
a THIRD species distinct from oyster and reishi, which is what every
downstream contingency table and decoding assumes, and that assumption is
recorded in `PROVENANCE.md` as the one that would invalidate the
three-species reading if it turned out to be wrong.

No plotting library.
"""

import numpy as np
from scipy.signal import decimate

from Pipelines.drop_motifs import spans5

SPECIES_OYSTER = "oyster"
SPECIES_385 = "sp385"
SPECIES_REISHI = "reishi"

CORPUS_OYSTER = "oyster"
CORPUS_385 = "sp385"
CORPUS_REISHI_10HZ = "reishi_10hz"
CORPUS_REISHI_1HZ = "reishi_1hz"

CORPORA = (CORPUS_OYSTER, CORPUS_385, CORPUS_REISHI_10HZ, CORPUS_REISHI_1HZ)

FRAMING_SPAN = "span"
FRAMING_SLIDING = "sliding"

# The pair that carries the cross-species claim: matched rate, matched
# framing, different species.
MATCHED_RATE_CLEAN_PAIR = (CORPUS_OYSTER, CORPUS_385)

# Matched rate across all three species. reishi enters at 1 Hz, so the
# only thing still unmatched is the framing.
MATCHED_RATE_SUBSET = (CORPUS_OYSTER, CORPUS_385, CORPUS_REISHI_1HZ)

# Fig2A: catalogue id 900+channel, recording ids 466-470. The catalogue
# ids are what the drop_motifs9 store is keyed by and are kept so the two
# stores can be compared row for row.
FIG2A_SOURCE = "Fig2A_dt0p1.csv"
FIG2A_CATALOGUE_BASE = 900

# The fifteen operator-chosen catalogue spans are oyster; ID 385 is not.
OYSTER_SPAN_IDS = tuple(cid for cid in spans5.SPANS5 if cid != 385)
SP385_SPAN_IDS = (385,)

DECIMATION_FACTOR = 10          # 10 Hz -> 1 Hz


def species_of(corpus):
    """The species label for a corpus label."""
    return {
        CORPUS_OYSTER: SPECIES_OYSTER,
        CORPUS_385: SPECIES_385,
        CORPUS_REISHI_10HZ: SPECIES_REISHI,
        CORPUS_REISHI_1HZ: SPECIES_REISHI,
    }[corpus]


def framing_of(corpus):
    return (FRAMING_SPAN if corpus in (CORPUS_OYSTER, CORPUS_385)
            else FRAMING_SLIDING)


def decimate_to(x, fs, target_fs=1.0, factor=None):
    """`(y, target_fs)` - anti-alias filtered, then downsampled.

    NOT `x[::factor]`. At 10 Hz a 0.3 s fall is three samples; decimating
    by taking every tenth sample folds every one of those into the 1 Hz
    band as a single-sample step, which the detector would read as the
    sharpest drop in the recording. The control has to be a control.

    `zero_phase=True` so the filter introduces no group delay and a
    decimated onset lands at `onset_10hz / factor`, which is what lets
    `RATE_COMPARISON` draw the same physical events on two axes.
    """
    x = np.asarray(x, dtype=float).ravel()
    factor = int(factor if factor is not None else round(float(fs) / float(target_fs)))
    if factor <= 1:
        return x, float(fs)
    y = decimate(x, factor, ftype="iir", zero_phase=True)
    return np.asarray(y, dtype=float), float(fs) / factor


def fig2a_recordings(conn, source_file=FIG2A_SOURCE):
    """`[(catalogue_id, recording_row), ...]` in channel order."""
    rows = conn.execute(
        "SELECT * FROM recordings WHERE source_file = ? ORDER BY channel",
        (source_file,)).fetchall()
    if not rows:
        raise SystemExit(f"no recordings for {source_file!r}")
    return [(FIG2A_CATALOGUE_BASE + int(r["channel"]), r) for r in rows]


def catalogue_spans(ids=None):
    """`[(catalogue_id, spec), ...]` from `spans5.SPANS5`, in id order."""
    wanted = set(spans5.SPANS5) if ids is None else set(ids)
    return [(cid, spans5.SPANS5[cid]) for cid in sorted(wanted)]


def label_row(row, *, corpus, species, framing, fs):
    """Stamp the four corpus columns and the confound control's variable.

    `n_samples_in_fall` is the primary variable of the whole confound
    control and nothing in Task 5b works without it, so it is computed
    from the row's own indices here rather than trusted to arrive.
    """
    row = dict(row)
    row["corpus"] = corpus
    row["species"] = species
    row["framing"] = framing
    row["fs"] = float(fs)
    row["n_samples_in_fall"] = int(max(1, int(row["trough_idx"])
                                       - int(row["onset_idx"])))
    return row
