"""Gate 3 — scope check. Soft by design.

Matching is deliberately lenient about shape, because the backlog's `files:`
lists are written the way a human writes them: sometimes a full repo path
(`tests/test_types.py`), sometimes a bare filename (`signal.py`), sometimes a
directory (`Working/types/`). A strict matcher would report a deviation on
every ticket and the table would stop being read by the second morning.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ScopeVerdict:
    status: str                       # pass | warn
    deviations: tuple[str, ...] = ()
    untouched: tuple[str, ...] = ()
    declared: tuple[str, ...] = ()

    def render(self) -> str:
        lines = ["declared: " + (", ".join(self.declared) or "(none)")]
        if self.deviations:
            lines.append("touched but not declared: " + ", ".join(self.deviations))
        if self.untouched:
            lines.append("declared but not touched: " + ", ".join(self.untouched))
        if not self.deviations:
            lines.append("no out-of-scope files")
        return "\n".join(lines) + "\n"


def _covers(declared: str, touched: str) -> bool:
    declared = declared.replace("\\", "/").strip()
    touched = touched.replace("\\", "/").strip()
    if not declared:
        return False
    if declared.endswith("/"):
        return touched.startswith(declared)
    if declared == touched or touched.endswith("/" + declared):
        return True
    # A bare filename in the front-matter matches by basename.
    return "/" not in declared and PurePosixPath(touched).name == declared


def check_scope(*, touched, declared) -> ScopeVerdict:
    touched = [t for t in touched if t]
    declared = tuple(declared)

    deviations = tuple(t for t in touched if not any(_covers(d, t) for d in declared))
    untouched = tuple(d for d in declared if not any(_covers(d, t) for t in touched))

    return ScopeVerdict(
        status="warn" if deviations else "pass",
        deviations=deviations,
        untouched=untouched,
        declared=declared,
    )
