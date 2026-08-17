"""
signal.py
==========
`Signal` — a time series plus its sample rate, the root type every chain
starts from. Frozen so a step can safely hand its input to the next step
without either mutating the other's view of it.

Serialises to a single compressed `.npz` — see `docs/PIPELINE_PRD.md`
"Type system": arrays serialise to compressed numpy archives.
"""

import os
from dataclasses import dataclass

import numpy as np

_FILENAME = "signal.npz"


@dataclass(frozen=True, eq=False)
class Signal:
    """A time series and its sample rate.

    Attributes
    ----------
    x : np.ndarray
        The series, one value per timepoint.
    fs : float
        Sample rate in Hz.
    """
    x: np.ndarray
    fs: float

    def __eq__(self, other):
        if not isinstance(other, Signal):
            return NotImplemented
        return self.fs == other.fs and np.array_equal(self.x, other.x)

    def to_path(self, dir_path):
        """Write this signal to `dir_path` (created if missing) and return
        the path to the written archive."""
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, _FILENAME)
        np.savez_compressed(path, x=self.x, fs=np.float64(self.fs))
        return path

    @classmethod
    def from_path(cls, dir_path):
        """Read a `Signal` back from `dir_path`."""
        path = os.path.join(dir_path, _FILENAME)
        with np.load(path, allow_pickle=False) as data:
            return cls(x=data["x"], fs=float(data["fs"]))
