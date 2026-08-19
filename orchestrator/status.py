"""Ticket status values, per ORCHESTRATOR_SPEC Appendix A.

`PENDING` → `READY` → `RUNNING` → `GATING` → `MERGING` → `MERGED`, with four
terminal alternatives. Kept in their own module so the pure scheduler can be
imported without dragging in the state store.
"""

PENDING = "PENDING"
READY = "READY"
RUNNING = "RUNNING"
GATING = "GATING"
MERGING = "MERGING"
MERGED = "MERGED"

FAILED = "FAILED"                    # quarantined
BLOCKED_UPSTREAM = "BLOCKED_UPSTREAM"  # a blocker was quarantined
OVERLAP = "OVERLAP"                  # held by the overlap check
HELD = "HELD"                        # human-gate, never dispatched
#: The environment could not run this ticket — a usage cap, a rate limit, an
#: API error. Nothing about the *work* was judged, which is the whole point of
#: separating it from FAILED: a quarantine says "this ticket is wrong" and
#: holds every dependent, and saying that about a plan usage cap is how
#: run-20260818-2244 turned four environment failures into a dead night.
#: Deferred tickets cost nothing against the circuit breaker, hold no
#: dependents, and are the one status `--resume` re-dispatches.
DEFERRED = "DEFERRED"

#: A subprocess is alive, or was when the orchestrator last wrote state.
IN_FLIGHT = (RUNNING, GATING, MERGING)

#: The ticket is done, one way or another, and will not be dispatched again
#: *by this run*. `DEFERRED` belongs here for two reasons: the run loop would
#: otherwise re-dispatch it straight back into the closed door that deferred it,
#: and it would race the thread still tearing the ticket's worktree down.
#: Terminal for the night; `Runner._requeue_deferred` makes it pending again at
#: the top of the next pass, which is what `--resume` is for.
TERMINAL = (MERGED, FAILED, BLOCKED_UPSTREAM, OVERLAP, HELD, DEFERRED)

#: The only status that releases dependents. Nothing weaker will do: a ticket
#: has landed only once it merged *and* the suite was green after the merge.
LANDED = MERGED

ALL = (
    PENDING, READY, RUNNING, GATING, MERGING, MERGED,
    FAILED, BLOCKED_UPSTREAM, OVERLAP, HELD, DEFERRED,
)
