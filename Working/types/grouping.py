"""
grouping.py
============
`Grouping` — a cluster or class assignment over a window set, one integer
label per window.

Serialises to a compressed `.npz` — see `docs/PIPELINE_PRD.md` "Type
system": arrays serialise to compressed numpy archives.
"""

import os
from dataclasses import dataclass

import numpy as np

_FILENAME = "grouping.npz"


@dataclass(frozen=True, eq=False)
class Grouping:
    """A cluster or class assignment over a window set.

    Attributes
    ----------
    labels : np.ndarray
        Integer cluster/class id per window, in window order.
    """
    labels: np.ndarray

    def __eq__(self, other):
        if not isinstance(other, Grouping):
            return NotImplemented
        return np.array_equal(self.labels, other.labels)

    def to_path(self, dir_path):
        """Write this grouping to `dir_path` (created if missing) and
        return the path to the written archive."""
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, _FILENAME)
        np.savez_compressed(path, labels=np.asarray(self.labels, dtype=np.int64))
        return path

    @classmethod
    def from_path(cls, dir_path):
        """Read a `Grouping` back from `dir_path`."""
        path = os.path.join(dir_path, _FILENAME)
        with np.load(path, allow_pickle=False) as data:
            return cls(labels=data["labels"])
