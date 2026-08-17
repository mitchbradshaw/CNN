"""
scores.py
==========
`Scores` — a time-aligned profile, one value per timepoint. This is the
type a single generic "threshold to obtain a SpanSet" block operates on,
which is exactly why it must be time-aligned: `from_signal` asserts its
length against the `Signal` it was derived from, so a feature table
(one row per window, no timepoint alignment — see `WindowSet`) can never
be silently substituted for it.
"""

import os
from dataclasses import dataclass

import numpy as np

_FILENAME = "scores.npz"


@dataclass(frozen=True, eq=False)
class Scores:
    """A time-aligned profile, one value per timepoint.

    Attributes
    ----------
    values : np.ndarray
        One value per timepoint.
    fs : float
        Sample rate in Hz.
    """
    values: np.ndarray
    fs: float

    @property
    def n_timepoints(self):
        return len(self.values)

    def __eq__(self, other):
        if not isinstance(other, Scores):
            return NotImplemented
        return self.fs == other.fs and np.array_equal(self.values, other.values)

    @classmethod
    def from_signal(cls, signal, values):
        """Build a `Scores` from `values`, asserting its length matches
        `signal` — the alignment a generic thresholding block depends on."""
        values = np.asarray(values)
        if len(values) != len(signal.x):
            raise ValueError(
                f"Scores must have one value per timepoint: got {len(values)} "
                f"value(s) for a signal of length {len(signal.x)}."
            )
        return cls(values=values, fs=signal.fs)

    def to_path(self, dir_path):
        """Write these scores to `dir_path` (created if missing) and
        return the path to the written archive."""
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, _FILENAME)
        np.savez_compressed(path, values=self.values, fs=np.float64(self.fs))
        return path

    @classmethod
    def from_path(cls, dir_path):
        """Read `Scores` back from `dir_path`."""
        path = os.path.join(dir_path, _FILENAME)
        with np.load(path, allow_pickle=False) as data:
            return cls(values=data["values"], fs=float(data["fs"]))
