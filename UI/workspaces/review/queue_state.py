"""
queue_state.py
==============
The headless half of the Review candidate queue (ticket 20).

`ReviewQueue` holds the filtered candidate list, the current index into it, and
the verdict history — and what advancing and undoing mean — without any UI
library. Ticket 21 renders what this holds; keeping the state object free of
any UI import is what lets every criterion here be asserted headlessly.

The queue builds on two ticket-19 pieces rather than reimplementing them:
`Working.database.queries.queue_candidates` provides the ordered, filterable
candidate list, and `Working.database.adjudications` owns the single
adjudication write path. This module only decides *which* candidate is current
and what a verdict does to the queue.

The Review invariant (PIPELINE_PRD.md, "The central invariant of the Review
workspace"): adjudicating a candidate writes an `adjudications` row and never
an `annotations` row. Undo reverses the last adjudication write, so a
mis-keyed verdict is not permanent.
"""

from Working.database import adjudications as _adjudications
from Working.database import queries as _queries

# The filter keyword names `ReviewQueue` accepts, mirrored onto
# `queue_candidates`. Anything else is a typo and should say so.
_FILTER_KEYS = (
    "run_id",
    "run_group_id",
    "method",
    "score_min",
    "score_max",
    "channel",
    "adjudication_status",
)


class ReviewQueue:
    """A filtered queue of detection candidates, positioned at one candidate.

    Parameters mirror `queue_candidates`'s filters and compose the same way.
    The default `adjudication_status="unadjudicated"` is the review flow: the
    queue presents only candidates still waiting for a verdict.

    `candidates` is an ordered snapshot taken when the queue is built (or when
    `set_filters` reloads it). `current` is the candidate at `index`, or
    `None` at the end of the queue. `history` records each verdict entered,
    newest last, so `undo` can step back through them.
    """

    def __init__(self, conn, *, run_id=None, run_group_id=None, method=None,
                 score_min=None, score_max=None, channel=None,
                 adjudication_status="unadjudicated"):
        self._conn = conn
        self._filters = {
            "run_id": run_id,
            "run_group_id": run_group_id,
            "method": method,
            "score_min": score_min,
            "score_max": score_max,
            "channel": channel,
            "adjudication_status": adjudication_status,
        }
        self._candidates = []
        self._index = None
        self._history = []
        self._load()

    def _load(self):
        """(Re)build the candidate snapshot from the current filters."""
        self._candidates = list(_queries.queue_candidates(
            self._conn, limit=-1, offset=0, **self._filters))
        self._index = 0 if self._candidates else None

    @property
    def candidates(self):
        """The filtered candidate rows, ordered as loaded."""
        return list(self._candidates)

    @property
    def index(self):
        """Position of `current` in `candidates`, or `None` at the end."""
        return self._index

    @property
    def current(self):
        """The candidate row under review, or `None` at the end."""
        if self._index is None or self._index >= len(self._candidates):
            return None
        return self._candidates[self._index]

    @property
    def history(self):
        """Verdicts entered so far, newest last. Each entry records the
        adjudicated detection, its verdict, the index it was entered at, and
        enough to reverse the write on undo."""
        return list(self._history)

    def set_filters(self, **filters):
        """Replace the given filters and reload the queue.

        Changing filters redefines the candidate list, so the position and the
        verdict history are reset — an index into a different list is
        meaningless, and undo would restore a position that no longer refers
        to the same candidate.
        """
        unknown = set(filters) - set(_FILTER_KEYS)
        if unknown:
            raise ValueError(
                "unknown filter key(s): {}; expected one of {}".format(
                    ", ".join(sorted(unknown)), ", ".join(_FILTER_KEYS)))
        self._filters.update(filters)
        self._history = []
        self._load()

    def advance(self):
        """Move to the next unadjudicated candidate in the filtered list.

        Candidates that have since been adjudicated — by this queue or by any
        other writer — are skipped, so the queue always lands on the next
        candidate still waiting for a verdict. Returns the new current, or
        `None` once every candidate has been adjudicated (or the queue is
        empty), at which point `index` is `None`.
        """
        if self._index is None:
            return None
        for i in range(self._index + 1, len(self._candidates)):
            if self._is_unadjudicated(self._candidates[i]):
                self._index = i
                return self._candidates[i]
        self._index = None
        return None

    def adjudicate_current(self, verdict, note=None):
        """Write a verdict against the current candidate and auto-advance.

        Records the verdict in `history`, then moves to the next
        unadjudicated candidate under the current filter (PRD story 27:
        score with a keystroke and advance automatically).

        Returns the adjudication row id. Raises `RuntimeError` when there is
        no current candidate to adjudicate.
        """
        det = self.current
        if det is None:
            raise RuntimeError("no current candidate to adjudicate")
        previous = _adjudications.get_adjudication(self._conn, det["id"])
        previous_snapshot = None
        if previous is not None:
            previous_snapshot = {
                "verdict": previous["verdict"],
                "note": previous["note"],
            }
        adj_id = _adjudications.insert_adjudication(
            self._conn, det["id"], verdict, note=note)
        self._history.append({
            "index": self._index,
            "detection_id": det["id"],
            "verdict": verdict,
            "adjudication_id": adj_id,
            "previous": previous_snapshot,
        })
        self.advance()
        return adj_id

    def undo(self):
        """Restore the previous index and reverse the last adjudication write.

        If the verdict created a new adjudication row, the row is removed; if
        it updated an existing one, the previous verdict and note are
        restored. The current index returns to the candidate the verdict was
        entered at.

        Returns `True` if a verdict was undone, `False` if there is nothing
        to undo.
        """
        if not self._history:
            return False
        entry = self._history.pop()
        self._reverse_adjudication(entry)
        self._index = entry["index"]
        return True

    # ── internals ──────────────────────────────────────────────────────────

    def _is_unadjudicated(self, detection):
        return _adjudications.get_adjudication(
            self._conn, detection["id"]) is None

    def _reverse_adjudication(self, entry):
        """Reverse one history entry's adjudication write in place."""
        detection_id = entry["detection_id"]
        previous = entry["previous"]
        if previous is None:
            # The row did not exist before the verdict: remove it. Tag links
            # go first so the delete cannot trip the foreign key.
            self._conn.execute(
                "DELETE FROM adjudication_tags WHERE adjudication_id = ?",
                (entry["adjudication_id"],),
            )
            self._conn.execute(
                "DELETE FROM adjudications WHERE detection_id = ?",
                (detection_id,),
            )
        else:
            self._conn.execute(
                "UPDATE adjudications SET verdict = ?, note = ? "
                "WHERE detection_id = ?",
                (previous["verdict"], previous["note"], detection_id),
            )
        self._conn.commit()
