"""Gate 5 — mechanical overlap check.

AST-parse the branch's changed Python files, extract the top-level function and
class names it *adds*, and intersect against everything already merged into the
integration branch and everything in flight.

On collision: merge the first branch, hold the second, mark it `OVERLAP`,
continue with the rest of the DAG. **Never auto-resolve.**

Mechanical, not an LLM judgement — an LLM sibling-comparison may run as an
advisory note in the morning report, but it is never a gate.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from ..gitops import Git, GitError

TOP_LEVEL_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class OverlapVerdict:
    status: str                            # pass | hold
    collisions: dict[str, int] = field(default_factory=dict)
    symbols: tuple[str, ...] = ()

    def render(self) -> str:
        if not self.collisions:
            return f"no overlap; added {len(self.symbols)} top-level symbol(s)\n"
        lines = ["symbol collisions (branch held, never auto-resolved):"]
        for symbol, owner in sorted(self.collisions.items()):
            lines.append(f"  {symbol} — already owned by T{owner:02d}")
        return "\n".join(lines) + "\n"


def _top_level_names(source: str) -> set[str]:
    """Public top-level function and class names. Unparseable source yields none."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {
        node.name for node in tree.body
        if isinstance(node, TOP_LEVEL_DEFS) and not node.name.startswith("_")
    }


def _file_at(git: Git, ref: str, path: str) -> str:
    try:
        return git.run("show", f"{ref}:{path}")
    except GitError:
        return ""   # the file did not exist at that ref


def added_symbols(git: Git, base: str, branch: str) -> set[str]:
    """Top-level names the branch adds, relative to the merge base."""
    merge_base = git.merge_base(base, branch)
    added: set[str] = set()

    for path in git.files_changed(base, branch):
        if not path.endswith(".py"):
            continue
        before = _top_level_names(_file_at(git, merge_base, path))
        after = _top_level_names(_file_at(git, branch, path))
        added |= after - before

    return added


def check_overlap(*, ticket_id: int, symbols, owners) -> OverlapVerdict:
    """Intersect this ticket's added symbols against the accumulated owner map."""
    symbols = set(symbols)
    collisions = {
        name: owners[name] for name in sorted(symbols)
        if name in owners and owners[name] != ticket_id
    }
    return OverlapVerdict(
        status="hold" if collisions else "pass",
        collisions=collisions,
        symbols=tuple(sorted(symbols)),
    )
