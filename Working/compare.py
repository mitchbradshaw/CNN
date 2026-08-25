"""
compare.py
==========
Headless two-run set-overlap computation (ticket 33).

"Does the banded chain find things the direct chain misses" is answered here:
given two completed runs, compute the intersection of their detection span
sets and each run's exclusive remainder. The same mechanism is what ticket 44
consumes for the surrogate control — a real run compared against its surrogate
pair is still just two completed runs, so one implementation serves both
research questions (PRD "Chain shape").

The overlap notion is deliberately imported, not reimplemented:
`Working.database.similarity.interval_iou` is the single interval-overlap
definition in the codebase, and `compare_run_sets` records its name
(`overlap_criterion`) alongside the result so the criterion is explicit rather
than an unnamed threshold buried in a loop.

No UI imports. Plain SQL through `Working.database.runs`.
"""

from dataclasses import dataclass
from typing import Tuple

from Working.config import SIMILARITY_IOU_THRESHOLD
from Working.database import runs as _runs
from Working.database.similarity import interval_iou

#: The one supported span-overlap criterion. Kept as a named constant so a
#: result can state how it was computed, and a caller can ask for it by name.
OVERLAP_CRITERION = "interval_iou"


@dataclass(frozen=True)
class MatchedPair:
    """One pair of detections (one from each run) that count as the same span."""

    a_detection_id: int
    b_detection_id: int
    iou: float


@dataclass(frozen=True)
class RunSetComparison:
    """The set-overlap result for two completed runs.

    `intersection` is one matched pair per overlap; `a_only` and `b_only` are
    the unmatched detection rows, i.e. each run's exclusive remainder. The
    rows are `sqlite3.Row` objects straight from `Working.database.runs`.
    """

    run_a_id: int
    run_b_id: int
    overlap_criterion: str
    iou_threshold: float
    intersection: Tuple[MatchedPair, ...]
    a_only: tuple
    b_only: tuple

    @property
    def counts(self):
        """Counts for the comparison.

        `a_total`/`b_total` are the total detection counts; `intersection` is
        the number of matched pairs; `a_only`/`b_only` are the sizes of the
        exclusive remainders.
        """
        return {
            "a_total": len(self.intersection) + len(self.a_only),
            "b_total": len(self.intersection) + len(self.b_only),
            "intersection": len(self.intersection),
            "a_only": len(self.a_only),
            "b_only": len(self.b_only),
        }


def _require_completed_run(conn, run_id):
    run = _runs.get_run(conn, run_id)
    if run is None:
        raise ValueError(f"No run with id={run_id}")
    if run["status"] != "completed":
        raise ValueError(
            f"Run {run_id} has status {run['status']!r}; only completed runs "
            "have a final span set to compare"
        )
    return run


def _greedy_interval_iou_match(a_rows, b_rows, iou_threshold):
    """Pair each A span with its best not-yet-paired B overlap.

    Both lists are already ordered by `start_idx` (`Working.database.runs.
    list_detections`), so this is deterministic. Each B is used at most once;
    an A with no B overlap above the threshold becomes an exclusive remainder.
    """
    used_b = set()
    matched_a = set()
    pairs = []

    for a in a_rows:
        best = None  # (iou, b_index, b_row)
        for index, b in enumerate(b_rows):
            if index in used_b:
                continue
            iou = interval_iou(a["start_idx"], a["end_idx"], b["start_idx"], b["end_idx"])
            if iou >= iou_threshold and (best is None or iou > best[0]):
                best = (iou, index, b)

        if best is not None:
            iou, index, b = best
            used_b.add(index)
            matched_a.add(a["id"])
            pairs.append(MatchedPair(a["id"], b["id"], iou))

    a_only = tuple(row for row in a_rows if row["id"] not in matched_a)
    b_only = tuple(row for index, row in enumerate(b_rows) if index not in used_b)
    return pairs, a_only, b_only


def compare_run_sets(conn, run_a_id, run_b_id, *,
                     overlap_criterion=OVERLAP_CRITERION,
                     iou_threshold=SIMILARITY_IOU_THRESHOLD):
    """Compare the detection span sets of two completed runs.

    Parameters
    ----------
    conn : sqlite3.Connection
    run_a_id, run_b_id : int
        The two runs to compare. Both must have `status == 'completed'`.
    overlap_criterion : str
        The named span-overlap criterion. Only `"interval_iou"` is supported.
    iou_threshold : float
        Minimum interval IoU for two spans to count as the same finding.

    Returns
    -------
    RunSetComparison
    """
    if overlap_criterion != OVERLAP_CRITERION:
        raise ValueError(
            f"overlap_criterion must be {OVERLAP_CRITERION!r}, got {overlap_criterion!r}"
        )
    _require_completed_run(conn, run_a_id)
    _require_completed_run(conn, run_b_id)

    a_rows = _runs.list_detections(conn, run_a_id)
    b_rows = _runs.list_detections(conn, run_b_id)
    pairs, a_only, b_only = _greedy_interval_iou_match(a_rows, b_rows, iou_threshold)

    return RunSetComparison(
        run_a_id=run_a_id,
        run_b_id=run_b_id,
        overlap_criterion=overlap_criterion,
        iou_threshold=iou_threshold,
        intersection=tuple(pairs),
        a_only=a_only,
        b_only=b_only,
    )
