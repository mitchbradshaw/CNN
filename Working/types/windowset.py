"""
windowset.py
=============
`WindowSet` — fixed-length segments over a signal, optionally carrying an
attached per-window feature matrix (e.g. Catch22, entropy). One row per
window, and deliberately **no timepoint alignment** — unlike `Scores`, a
window count has no obligation to match the source signal's length, so
`WindowSet` carries no assertion against a `Signal`.

Serialises to a compressed `.npz` for the window geometry and, when
present, a `.parquet` for the attached feature table — see
`docs/PIPELINE_PRD.md` "Type system": arrays serialise to compressed numpy
archives, feature tables to parquet.
"""

import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

_GEOMETRY_FILENAME = "windowset.npz"
_FEATURES_FILENAME = "features.parquet"


@dataclass(frozen=True, eq=False)
class WindowSet:
    """Fixed-length windows over a signal, with an optional attached
    per-window feature table.

    Attributes
    ----------
    starts : np.ndarray
        Sample index of each window's start, one per window.
    length : int
        Window length in samples, fixed across the set.
    fs : float
        Sample rate in Hz.
    features : pd.DataFrame | None
        One row per window, in `starts` order, or None if no feature
        matrix is attached.
    """
    starts: np.ndarray
    length: int
    fs: float
    features: Optional[pd.DataFrame] = None

    def __post_init__(self):
        if self.features is not None and len(self.features) != len(self.starts):
            raise ValueError(
                f"features has {len(self.features)} row(s) but there are "
                f"{len(self.starts)} window(s) — WindowSet carries one feature "
                "row per window."
            )

    @property
    def n_windows(self):
        return len(self.starts)

    def __eq__(self, other):
        if not isinstance(other, WindowSet):
            return NotImplemented
        if self.length != other.length or self.fs != other.fs:
            return False
        if not np.array_equal(self.starts, other.starts):
            return False
        if (self.features is None) != (other.features is None):
            return False
        if self.features is None:
            return True
        a = self.features.reset_index(drop=True)
        b = other.features.reset_index(drop=True)
        return a.equals(b)

    def to_path(self, dir_path):
        """Write this window set to `dir_path` (created if missing) and
        return the path to the geometry archive."""
        os.makedirs(dir_path, exist_ok=True)
        geometry_path = os.path.join(dir_path, _GEOMETRY_FILENAME)
        np.savez_compressed(
            geometry_path,
            starts=np.asarray(self.starts, dtype=np.int64),
            length=np.int64(self.length),
            fs=np.float64(self.fs),
        )
        if self.features is not None:
            features_path = os.path.join(dir_path, _FEATURES_FILENAME)
            self.features.to_parquet(features_path, index=False)
        return geometry_path

    @classmethod
    def from_path(cls, dir_path):
        """Read a `WindowSet` back from `dir_path`."""
        geometry_path = os.path.join(dir_path, _GEOMETRY_FILENAME)
        with np.load(geometry_path, allow_pickle=False) as data:
            starts = data["starts"]
            length = int(data["length"])
            fs = float(data["fs"])

        features_path = os.path.join(dir_path, _FEATURES_FILENAME)
        features = pd.read_parquet(features_path) if os.path.isfile(features_path) else None

        return cls(starts=starts, length=length, fs=fs, features=features)
