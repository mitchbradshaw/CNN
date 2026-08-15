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

#: A subprocess is alive, or was when the orchestrator last wrote state.
IN_FLIGHT = (RUNNING, GATING, MERGING)

#: The ticket is done, one way or another, and will not be dispatched again.
TERMINAL = (MERGED, FAILED, BLOCKED_UPSTREAM, OVERLAP, HELD)

#: The only status that releases dependents. Nothing weaker will do: a ticket
#: has landed only once it merged *and* the suite was green after the merge.
LANDED = MERGED

ALL = (
    PENDING, READY, RUNNING, GATING, MERGING, MERGED,
    FAILED, BLOCKED_UPSTREAM, OVERLAP, HELD,
)
