"""
Working.types
==============
The seven interchange types that gate which pipeline blocks may connect —
see `docs/PIPELINE_PRD.md` "Type system". No eighth type is added; a
method that fits none of these seven is out of scope.

Each is a frozen dataclass with a `to_path(dir_path)` / `from_path(dir_path)`
pair so the step cache and the cluster round trip get a serialiser for
free, without needing to know per-type file formats.
"""

from Working.types.encoding import Encoding
from Working.types.grouping import Grouping
from Working.types.model import Model
from Working.types.scores import Scores
from Working.types.signal import Signal
from Working.types.spanset import SpanSet
from Working.types.windowset import WindowSet

__all__ = [
    "Encoding",
    "Grouping",
    "Model",
    "Scores",
    "Signal",
    "SpanSet",
    "WindowSet",
]
