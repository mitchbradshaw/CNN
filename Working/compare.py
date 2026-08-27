"""
compare.py
==========
Headless comparisons for the Compare view (tickets 33, 68).

Two independent questions are answered here, deliberately kept in one module
so the Compare surface has a single place to talk to:

- `compare_run_sets` (ticket 33): detection-set overlap between two completed
  runs. "Does the banded chain find things the direct chain misses" is
  answered by computing the intersection of their detection span sets and
  each run's exclusive remainder. The same mechanism is what ticket 44
  consumes for the surrogate control — a real run compared against its
  surrogate pair is still just two completed runs.

- `diff_recipes` (ticket 68): per-step structural difference between two
  recipe dicts. "These two chains are identical except low_hz is 0.01 in one
  and 0.05 in the other" is answered by comparing the ordered step lists,
  reporting steps present in one and not the other, and parameters whose
  values differ. Pure and headless — two recipe dicts in, a tuple of
  `StepDiff` records out.

The overlap notion is deliberately imported, not reimplemented:
`Working.database.similarity.interval_iou` is the single interval-overlap
definition in the codebase, and `compare_run_sets` records its name
(`overlap_criterion`) alongside the result so the criterion is explicit rather
than an unnamed threshold buried in a loop.

No UI imports. The run-set comparison reads through `Working.database.runs`;
the recipe diff touches neither the database nor the UI.
"""

from dataclasses import dataclass
from typing import Any, Optional, Tuple

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


# ── recipe diff (ticket 68) ──────────────────────────────────────────────────


class _Missing:
    """Sentinel type so an absent parameter reads as `<missing>`, not None."""

    def __repr__(self):
        return "<missing>"


#: Marks the side of a `ParamChange` on which the parameter is absent.
#: Distinct from a value of None, which a parameter may legitimately take.
MISSING = _Missing()


@dataclass(frozen=True)
class ParamChange:
    """One parameter whose value differs between two otherwise-same steps.

    `a_value`/`b_value` are the values from recipe A/B respectively. A side
    on which the parameter is absent carries `MISSING` rather than None.
    """

    name: str
    a_value: Any
    b_value: Any


@dataclass(frozen=True)
class StepDiff:
    """The difference at one chain position between two recipes.

    `a_step`/`b_step` are the step dicts at `index` from recipe A/B; a step
    present in only one recipe has `None` on the other side. A step present
    in both with the same algorithm but different parameters carries those
    changes in `changed_params`. A step whose algorithm itself differs is
    reported with both step dicts present and an empty `changed_params`.
    """

    index: int
    a_step: Optional[dict]
    b_step: Optional[dict]
    changed_params: Tuple[ParamChange, ...] = ()


def _step_identity(step):
    """The (stage, algorithm) pair that identifies a step for matching."""
    return (step.get("stage"), step.get("algorithm"))


def _diff_params(a_params, b_params):
    """Return the `ParamChange`s between two step parameter dicts.

    A parameter present in one dict and absent in the other is reported with
    `MISSING` on the absent side, so an explicit None value is not conflated
    with an absence.
    """
    a_params = a_params or {}
    b_params = b_params or {}
    changes = []
    for name in sorted(set(a_params) | set(b_params)):
        a_value = a_params.get(name, MISSING)
        b_value = b_params.get(name, MISSING)
        if a_value != b_value:
            changes.append(ParamChange(name, a_value, b_value))
    return tuple(changes)


def diff_recipes(recipe_a, recipe_b):
    """Return the per-step difference between two recipes.

    Steps are compared by position: step i of recipe A against step i of
    recipe B. Positional comparison is deliberate — it keeps two identical
    algorithms that appear twice in one chain distinct, and it lets a chain
    of different length report its surplus steps as added/removed rather
    than guessing at a re-alignment. A step whose algorithm differs at the
    same position is reported with both step dicts present.

    Parameters
    ----------
    recipe_a, recipe_b : dict
        Recipe dicts with an ordered `steps` list, as produced by
        `Working.recipes.make_recipe`.

    Returns
    -------
    Tuple[StepDiff, ...]
        One `StepDiff` per chain position where the two recipes differ. Two
        identical recipes return the empty tuple.
    """
    steps_a = recipe_a.get("steps") or []
    steps_b = recipe_b.get("steps") or []
    diffs = []
    for index in range(max(len(steps_a), len(steps_b))):
        a_step = steps_a[index] if index < len(steps_a) else None
        b_step = steps_b[index] if index < len(steps_b) else None
        if a_step is None or b_step is None:
            diffs.append(StepDiff(index, a_step, b_step))
        elif _step_identity(a_step) != _step_identity(b_step):
            diffs.append(StepDiff(index, a_step, b_step))
        else:
            changed = _diff_params(a_step.get("params"), b_step.get("params"))
            if changed:
                diffs.append(StepDiff(index, a_step, b_step, changed))
    return tuple(diffs)
