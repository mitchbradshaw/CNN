"""
encoding.py
============
`Encoding` — an image or symbolic representation per window (Gramian
images, SAX words). `kind` names which, so a downstream block can tell
whether it received pixels or symbols without inspecting dtypes.

Serialises to a compressed `.npz` — see `docs/PIPELINE_PRD.md` "Type
system": arrays serialise to compressed numpy archives.
"""

import os
from dataclasses import dataclass

import numpy as np

_FILENAME = "encoding.npz"


@dataclass(frozen=True, eq=False)
class Encoding:
    """An image or symbolic representation, one entry per window.

    Attributes
    ----------
    values : np.ndarray
        Image stack (e.g. `(n_windows, H, W)`) or symbolic array (e.g.
        `(n_windows,)` of fixed-width unicode strings).
    kind : str
        `"image"` or `"symbolic"`.
    """
    values: np.ndarray
    kind: str

    def __eq__(self, other):
        if not isinstance(other, Encoding):
            return NotImplemented
        return self.kind == other.kind and np.array_equal(self.values, other.values)

    def to_path(self, dir_path):
        """Write this encoding to `dir_path` (created if missing) and
        return the path to the written archive."""
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, _FILENAME)
        np.savez_compressed(path, values=self.values, kind=str(self.kind))
        return path

    @classmethod
    def from_path(cls, dir_path):
        """Read an `Encoding` back from `dir_path`."""
        path = os.path.join(dir_path, _FILENAME)
        with np.load(path, allow_pickle=False) as data:
            return cls(values=data["values"], kind=str(data["kind"]))
