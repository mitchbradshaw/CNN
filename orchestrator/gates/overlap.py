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


def _top_level_names(source: str, *, include_private: bool) -> set[str]:
    """Top-level function and class names. Unparseable source yields none.

    Private names are included by default — a deliberate choice, not an
    oversight. Two agents both adding `_resample_and_znorm` are still two
    implementations of one idea; being module-private makes the duplication
    harder to notice, not less real, and standards rule 6.4 calls duplicated
    logic across modules a blocker at the merge boundary either way. Set
    `overlap.include_private = false` in config.toml to narrow it.

    Dunder names are always excluded: `__getattr__` and friends are module
    machinery, not shared vocabulary, and would collide constantly.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    names = set()
    for node in tree.body:
        if not isinstance(node, TOP_LEVEL_DEFS):
            continue
        if node.name.startswith("__") and node.name.endswith("__"):
            continue
        if not include_private and node.name.startswith("_"):
            continue
        names.add(node.name)
    return names


def _file_at(git: Git, ref: str, path: str) -> str:
    try:
        return git.run("show", f"{ref}:{path}")
    except GitError:
        return ""   # the file did not exist at that ref


def added_symbols(git: Git, base: str, branch: str, *,
                  include_private: bool = True,
                  ignore_paths: tuple[str, ...] = ()) -> set[str]:
    """Top-level names the branch adds, relative to the merge base.

    `ignore_paths` drops whole prefixes out of the comparison. It exists for
    test files, which are leaves: nothing imports them, so their top-level names
    are file-local rather than shared vocabulary, and this repo's convention
    puts an identical `_run_all()` at the foot of 41 of its 42 test files. In
    run-20260818-0554 that convention read as a collision — T35 merged first and
    took the name, and T13 was held for writing the same boilerplate in a
    different file. The gate exists to catch two implementations of one idea,
    not two copies of one footer.
    """
    merge_base = git.merge_base(base, branch)
    added: set[str] = set()

    for path in git.files_changed(base, branch):
        if not path.endswith(".py"):
            continue
        if any(path.startswith(prefix) for prefix in ignore_paths):
            continue
        before = _top_level_names(_file_at(git, merge_base, path),
                                  include_private=include_private)
        after = _top_level_names(_file_at(git, branch, path),
                                 include_private=include_private)
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
