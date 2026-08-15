"""Parse the ticket backlog's YAML front-matter and derive the scheduling graph.

The runner is indifferent to what a ticket says; it consumes only front-matter.
That front-matter is a deliberately small YAML subset — scalars and flow-style
lists — so this parses it directly rather than taking a dependency on PyYAML.
Anything outside that subset is an error, not a silent skip: a ticket whose
`blocked_by` failed to parse would dispatch too early and no one would notice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
SCALAR_LIST_FIELDS = ("blocked_by", "mutex", "files", "flags")
REQUIRED_FIELDS = ("id", "model", "size")


class BacklogError(Exception):
    """The backlog is malformed or its graph is invalid."""


@dataclass(frozen=True)
class Ticket:
    id: int
    title: str
    model: str
    size: str
    path: Path
    blocked_by: tuple[int, ...] = ()
    mutex: tuple[int, ...] = ()
    files: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    level: int = 0
    declared_unblocks: int = 0
    budget_minutes: int = 60

    @property
    def human_gate(self) -> bool:
        return "human-gate" in self.flags

    @property
    def solo(self) -> bool:
        return "solo" in self.flags

    @property
    def human_verify(self) -> bool:
        return "human-verify" in self.flags

    @property
    def label(self) -> str:
        return f"T{self.id:02d}"


def _parse_scalar(raw: str):
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in inner.split(",")]
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def parse_front_matter(text: str, source: Path) -> dict:
    """Return the front-matter mapping, or raise if it is absent or malformed."""
    match = FRONT_MATTER.match(text)
    if not match:
        raise BacklogError(f"{source}: no YAML front-matter block")

    data: dict = {}
    for lineno, line in enumerate(match.group(1).splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise BacklogError(f"{source}:{lineno}: not a `key: value` line: {line!r}")
        key, _, value = line.partition(":")
        data[key.strip()] = _parse_scalar(value)
    return data


def _as_tuple(value, *, field_name: str, source: Path, of_int: bool) -> tuple:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise BacklogError(f"{source}: `{field_name}` must be a list, got {value!r}")
    for item in value:
        if of_int and not isinstance(item, int):
            raise BacklogError(f"{source}: `{field_name}` must hold ids, got {item!r}")
    return tuple(value)


def ticket_from_file(path: Path) -> Ticket:
    data = parse_front_matter(path.read_text(encoding="utf-8"), path)

    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise BacklogError(f"{path}: missing front-matter field(s) {missing}")
    if not isinstance(data["id"], int):
        raise BacklogError(f"{path}: `id` must be an integer, got {data['id']!r}")

    return Ticket(
        id=data["id"],
        title=str(data.get("title", "")),
        model=str(data["model"]),
        size=str(data["size"]).upper(),
        path=path,
        blocked_by=_as_tuple(data.get("blocked_by", []), field_name="blocked_by",
                             source=path, of_int=True),
        mutex=_as_tuple(data.get("mutex", []), field_name="mutex",
                        source=path, of_int=True),
        files=tuple(str(f) for f in _as_tuple(data.get("files", []), field_name="files",
                                              source=path, of_int=False)),
        flags=tuple(str(f) for f in _as_tuple(data.get("flags", []), field_name="flags",
                                              source=path, of_int=False)),
        level=int(data.get("level", 0) or 0),
        declared_unblocks=int(data.get("unblocks", 0) or 0),
        budget_minutes=int(data.get("budget_minutes", 60) or 60),
    )


@dataclass
class Backlog:
    tickets: dict[int, Ticket] = field(default_factory=dict)
    _levels: dict[int, int] = field(default_factory=dict, repr=False)
    _dependents: dict[int, set[int]] = field(default_factory=dict, repr=False)
    _critical_path: dict[int, int] = field(default_factory=dict, repr=False)
    _mutex: dict[int, set[int]] = field(default_factory=dict, repr=False)

    def __getitem__(self, ticket_id: int) -> Ticket:
        return self.tickets[ticket_id]

    def __contains__(self, ticket_id: object) -> bool:
        return ticket_id in self.tickets

    def __iter__(self):
        return iter(self.ordered)

    def __len__(self) -> int:
        return len(self.tickets)

    @property
    def ids(self) -> list[int]:
        return sorted(self.tickets)

    @property
    def ordered(self) -> list[Ticket]:
        return [self.tickets[i] for i in self.ids]

    def level(self, ticket_id: int) -> int:
        """Earliest wave the ticket can start in, ignoring ceilings and mutexes."""
        return self._levels[ticket_id]

    def dependents(self, ticket_id: int) -> set[int]:
        """Every ticket transitively blocked by this one."""
        return self._dependents[ticket_id]

    def critical_path(self, ticket_id: int) -> int:
        """Longest remaining chain starting here, counting this ticket."""
        return self._critical_path[ticket_id]

    def mutex_partners(self, ticket_id: int) -> set[int]:
        """Mutex is simultaneity-only and symmetric, however it was declared."""
        return self._mutex[ticket_id]


def _validate(tickets: dict[int, Ticket]) -> None:
    for ticket in tickets.values():
        for blocker in ticket.blocked_by:
            if blocker == ticket.id:
                raise BacklogError(f"T{ticket.id:02d} blocks on itself (self-reference)")
            if blocker not in tickets:
                raise BacklogError(
                    f"T{ticket.id:02d}: `blocked_by` names unknown ticket {blocker}"
                )
        for partner in ticket.mutex:
            if partner == ticket.id:
                raise BacklogError(f"T{ticket.id:02d} declares a mutex with itself (self-reference)")
            if partner not in tickets:
                raise BacklogError(
                    f"T{ticket.id:02d}: `mutex` names unknown ticket {partner}"
                )


def _toposort(tickets: dict[int, Ticket]) -> list[int]:
    """Kahn's algorithm. Raises on a cycle, naming the tickets still in it."""
    indegree = {i: len(set(t.blocked_by)) for i, t in tickets.items()}
    successors: dict[int, list[int]] = {i: [] for i in tickets}
    for ticket in tickets.values():
        for blocker in set(ticket.blocked_by):
            successors[blocker].append(ticket.id)

    ready = sorted(i for i, d in indegree.items() if d == 0)
    order: list[int] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for nxt in sorted(successors[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort()

    if len(order) != len(tickets):
        stuck = sorted(set(tickets) - set(order))
        raise BacklogError(f"blocking graph has a cycle among tickets {stuck}")
    return order


def _derive(backlog: Backlog) -> None:
    tickets = backlog.tickets
    order = _toposort(tickets)

    for ticket_id in order:
        blockers = tickets[ticket_id].blocked_by
        backlog._levels[ticket_id] = (
            0 if not blockers else 1 + max(backlog._levels[b] for b in blockers)
        )

    # Transitive dependents and critical path both fold backwards over the order.
    for ticket_id in reversed(order):
        dependents: set[int] = set()
        longest = 0
        for other in tickets.values():
            if ticket_id in other.blocked_by:
                dependents.add(other.id)
                dependents |= backlog._dependents[other.id]
                longest = max(longest, backlog._critical_path[other.id])
        backlog._dependents[ticket_id] = dependents
        backlog._critical_path[ticket_id] = longest + 1

    for ticket_id in tickets:
        backlog._mutex[ticket_id] = set()
    for ticket in tickets.values():
        for partner in ticket.mutex:
            backlog._mutex[ticket.id].add(partner)
            backlog._mutex[partner].add(ticket.id)


def load_backlog(tickets_dir: Path | str) -> Backlog:
    """Load every `T*.md` in `tickets_dir`."""
    tickets_dir = Path(tickets_dir)
    paths = sorted(tickets_dir.glob("T*.md"))
    if not paths:
        raise BacklogError(f"{tickets_dir}: no ticket files matching T*.md")

    tickets: dict[int, Ticket] = {}
    for path in paths:
        ticket = ticket_from_file(path)
        if ticket.id in tickets:
            raise BacklogError(
                f"duplicate ticket id {ticket.id}: {tickets[ticket.id].path} and {path}"
            )
        tickets[ticket.id] = ticket

    _validate(tickets)
    backlog = Backlog(tickets=tickets)
    _derive(backlog)
    return backlog
