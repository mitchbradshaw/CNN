"""
test_t09_detection_entropy.py
===============================
Ticket 09 — `detection.entropy` must not remain in the adapter registry.

The adapter returns a single scalar for the whole span, which is neither an
`Encoding`, a `Scores`, nor a `WindowSet`. Per the PRD type-system rule, a
method that fits none of the seven interchange types is out of scope rather
than a reason to add an eighth, so the resolution is to remove the adapter
from the chain system and keep the underlying `Working/` entropy functions
as plain analysis functions.
"""

from Adapters.registry import discover_adapters, get_adapter


def test_detection_entropy_is_not_registered():
    names = [spec.name for spec in discover_adapters()]
    assert "detection.entropy" not in names


def test_detection_entropy_is_not_retrievable():
    discover_adapters()
    try:
        get_adapter("detection.entropy")
    except KeyError:
        return
    raise AssertionError(
        "detection.entropy should have been removed from the adapter registry"
    )
