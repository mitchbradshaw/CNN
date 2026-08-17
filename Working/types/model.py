"""
model.py
=========
`Model` — a trained classifier, serialised **by path reference only**: the
weights themselves live wherever the training step put them (joblib,
pickle, a framework's own format); this type just carries and round-trips
that reference, so the step cache can treat "which model" as a typed value
without knowing how to read the model itself.

Serialises to `.json` — a one-field manifest, not the model.
"""

import json
import os
from dataclasses import dataclass

_FILENAME = "model.json"


@dataclass(frozen=True)
class Model:
    """A reference to a trained classifier's serialised file.

    Attributes
    ----------
    path : str
        Path to the actual model file, written by whatever trained it.
    """
    path: str

    def to_path(self, dir_path):
        """Write this reference to `dir_path` (created if missing) and
        return the path to the written manifest."""
        os.makedirs(dir_path, exist_ok=True)
        manifest_path = os.path.join(dir_path, _FILENAME)
        with open(manifest_path, "w") as f:
            json.dump({"path": self.path}, f, sort_keys=True)
        return manifest_path

    @classmethod
    def from_path(cls, dir_path):
        """Read a `Model` reference back from `dir_path`."""
        manifest_path = os.path.join(dir_path, _FILENAME)
        with open(manifest_path) as f:
            payload = json.load(f)
        return cls(path=payload["path"])
