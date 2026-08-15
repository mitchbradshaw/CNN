"""Command-line entry point: `--plan`, `--run`, `--resume`, `--status`.

    python -m orchestrator.run --plan
    python -m orchestrator.run --run
    python -m orchestrator.run --resume runs/run-20260815-2130
    python -m orchestrator.run --status runs/run-20260815-2130

`--plan` dispatches nothing. The first real run is a decision you make
deliberately after reading it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import status as st
from .backlog import load_backlog
from .config import load_config
from .gitops import Git
from .planner import render_plan, simulate
from .report import RunDirectory, render_report
from .runloop import Runner, capture_baseline
from .state import RunState, load_state, reconcile, save_state

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.toml"


def _utf8_stdout() -> None:
    """The plan and report contain em dashes; a cp1252 console mangles them."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.run",
        description="Deterministic autonomous ticket runner. See docs/ORCHESTRATOR_SPEC.md.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true",
                      help="print the wave-by-wave schedule and dispatch nothing")
    mode.add_argument("--run", action="store_true", help="start a new run")
    mode.add_argument("--resume", metavar="RUN_DIR",
                      help="reconcile an existing run against git and continue it")
    mode.add_argument("--status", metavar="RUN_DIR",
                      help="print REPORT.md for an existing run without changing anything")

    parser.add_argument("--config", default=str(DEFAULT_CONFIG), type=Path)
    parser.add_argument("--repo", default=str(REPO_ROOT), type=Path)
    parser.add_argument("--label", default="run", help="run directory prefix")
    parser.add_argument("--ceiling", type=int, help="override the global concurrency ceiling")
    parser.add_argument("--opus-ceiling", type=int, help="override the Opus sub-ceiling")
    parser.add_argument("--skip-baseline", action="store_true",
                        help="assume the baseline suite is green rather than measuring it")
    return parser.parse_args(argv)


def _apply_ceiling_overrides(config, args):
    """Fold `--ceiling` / `--opus-ceiling` into the config itself.

    The run loop reads `config.ceilings`, so an override that only reached the
    planner would print one schedule and execute a different one.
    """
    from dataclasses import replace

    ceilings = config.ceilings
    if args.ceiling is not None:
        ceilings = replace(ceilings, concurrent=args.ceiling)
    if args.opus_ceiling is not None:
        ceilings = replace(ceilings, opus=args.opus_ceiling)
    return config if ceilings == config.ceilings else replace(config, ceilings=ceilings)


def main(argv=None) -> int:
    _utf8_stdout()
    args = _parse_args(argv)

    config = _apply_ceiling_overrides(load_config(args.config, repo_root=args.repo), args)
    backlog = load_backlog(config.paths.tickets)

    if args.plan:
        return _do_plan(config, backlog, args)
    if args.status:
        return _do_status(config, backlog, args)
    if args.resume:
        return _do_resume(config, backlog, args)
    return _do_run(config, backlog, args)


def _do_plan(config, backlog, args) -> int:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    branch = f"{config.branch_prefix}{timestamp}"
    plan = simulate(backlog, config, ceilings=config.ceilings, branch=branch)
    print(render_plan(plan))
    return 0


def _do_status(config, backlog, args) -> int:
    run_dir = RunDirectory(Path(args.status))
    state = load_state(run_dir.state_path)
    print(render_report(state, backlog))
    return 0


def _do_run(config, backlog, args) -> int:
    git = Git(config.paths.repo_root)

    if not git.is_clean():
        print("refusing to start: the working tree is dirty. `git worktree add` "
              "materialises only committed files, so anything untracked is invisible "
              "inside every agent's worktree.", file=sys.stderr)
        return 2

    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    branch = f"{config.branch_prefix}{timestamp}"
    base_sha = git.rev_parse(config.base_branch)
    git.create_branch(branch, config.base_branch)
    git.checkout(branch)

    run_dir = RunDirectory.create(config.paths.runs, label=args.label, timestamp=timestamp)
    started = datetime.now()
    deadline = config.wall_clock_stop_at(started)

    state = RunState(
        run_id=f"{args.label}-{timestamp}",
        integration_branch=branch,
        base_sha=base_sha,
        config_hash=config.config_hash,
        started_at=started.isoformat(timespec="seconds"),
        wall_clock_stop=deadline.isoformat(timespec="seconds"),
    )
    save_state(state, run_dir.state_path)

    plan = simulate(backlog, config, ceilings=config.ceilings, branch=branch)
    plan_text = render_plan(plan)
    run_dir.plan_path.write_text(plan_text, encoding="utf-8")
    print(plan_text)

    baseline = () if args.skip_baseline else capture_baseline(git, config)
    if baseline:
        print(f"baseline: {len(baseline)} test(s) already failing before any ticket ran:")
        for node in baseline:
            print(f"  {node}")
    run_dir.path.joinpath("baseline.txt").write_text("\n".join(baseline) + "\n",
                                                     encoding="utf-8")

    runner = Runner(config=config, backlog=backlog, git=git, state=state,
                    run_dir=run_dir, baseline_failed=baseline, deadline=deadline)
    runner.run()
    return 0 if not state.circuit_breaker.tripped else 1


def _do_resume(config, backlog, args) -> int:
    run_dir = RunDirectory(Path(args.resume))
    state = load_state(run_dir.state_path)
    git = Git(config.paths.repo_root)

    if state.config_hash != config.config_hash:
        print(f"warning: config.toml has changed since this run started "
              f"({state.config_hash} -> {config.config_hash})", file=sys.stderr)

    git.checkout(state.integration_branch)
    for note in reconcile(state, git):
        print(note)
    save_state(state, run_dir.state_path)

    baseline_path = run_dir.path / "baseline.txt"
    baseline = tuple(
        line for line in baseline_path.read_text(encoding="utf-8").splitlines() if line
    ) if baseline_path.exists() else ()

    deadline = config.wall_clock_stop_at(datetime.now())
    runner = Runner(config=config, backlog=backlog, git=git, state=state,
                    run_dir=run_dir, baseline_failed=baseline, deadline=deadline)
    runner.run()
    return 0 if not state.circuit_breaker.tripped else 1


if __name__ == "__main__":
    raise SystemExit(main())
