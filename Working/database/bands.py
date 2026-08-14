"""
bands.py
=========
Derived, read-time-only classifications for annotations — never stored as
tags or columns. The facts are `event_count` and `(end_idx - start_idx) / fs`;
these bands are just views over those facts, computed fresh on every read so
changing a threshold never requires a backfill.

Thresholds live in `Working.config`, not here — see that module for the
actual band tables and the reasoning behind their boundaries.

`_band()` uses an INCLUSIVE upper bound (`value <= bound`). An earlier
version used a strict `<`, which combined with duration bounds of
(60, 600) meant every one of the 11,234 imported 10-minute (600s) windows —
sitting exactly ON the 600s edge — fell through to "long" instead of
"medium": `600 < 600` is `False`. Switching to `<=` alone doesn't fix that
class of bug in general (600 would still land exactly on whichever edge is
placed at 600) — the real fix is `Working.config.DURATION_BANDS_S` puts no
edge at 600s at all. `<=` is used consistently here (for both duration and
spike-train bands) so the comparison semantics are uniform and predictable.
"""

from Working.config import DURATION_BANDS_S, SPIKE_TRAIN_BANDS

__all__ = ["spike_train_band", "duration_band", "SPIKE_TRAIN_BANDS", "DURATION_BANDS_S"]


def _band(value, thresholds):
    if value is None:
        return None
    for bound, label in thresholds:
        if bound is None or value <= bound:
            return label
    return thresholds[-1][1]


def spike_train_band(event_count):
    """short (<5) / medium (5-10) / long (10+) / None if event_count is None."""
    return _band(event_count, SPIKE_TRAIN_BANDS)


def duration_band(start_idx, end_idx, fs):
    """short (<=1min) / medium (1-15min) / long (15-60min) / very_long (1-6h)
    / extreme (6h+), computed from (end_idx - start_idx) / fs seconds."""
    duration_s = (end_idx - start_idx) / fs
    return _band(duration_s, DURATION_BANDS_S)
