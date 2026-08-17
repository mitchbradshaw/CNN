"""The run loop: reconcile, schedule, dispatch, gate, merge, report.

The only stateful, concurrent part of the runner. Everything it decides is
delegated: scheduling to the pure `schedule()`, each gate to its own module,
merging to `merge_ticket`. What lives here is sequencing and the two policies
that need a view across all tickets at once — the circuit breaker and fleet-wide
rate-limit backoff.

Concurrency model: one thread per in-flight ticket, a single merge lock, and a
single state lock. `state.json` is rewritten atomically after every transition,
so killing the orchestrator and restarting it resumes rather than restarts.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import status as st
from .agent import build_prompt, classify_exit, run_agent
from .backlog import Backlog, Ticket
from .breaker import BreakerState, note_flaky, note_merged, note_quarantine
from .config import Config
from .gates.overlap import added_symbols, check_overlap
from .gates.red_proof import check_red_proof
from .gates.review import (
    build_review_prompt, check_review, grade_findings, load_rule_severities,
    parse_findings, write_review_json,
)
from .gates.scope import check_scope
from .gates.suite import UNATTRIBUTED_PREFIX, check_suite, run_suite
from .gitops import Git
from .merge import append_followups, merge_ticket
from .report import RunDirectory, render_report
from .scheduler import schedule
from .state import RunState, save_state
from .worktree import ProvisionError, provision, teardown


@dataclass
class Runner:
    config: Config
    backlog: Backlog
    git: Git
    state: RunState
    run_dir: RunDirectory
    baseline_failed: tuple[str, ...] = ()
    deadline: datetime | None = None
    poll_seconds: float = 2.0

    _state_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _merge_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _threads: dict[int, threading.Thread] = field(default_factory=dict, repr=False)
    _rate_limit_hits: list[float] = field(default_factory=list, repr=False)
    _paused_until: float = 0.0
    _backoff_seconds: float = 0.0
    #: Majors and minors, held until the ticket's merge actually lands.
    _pending_followups: dict = field(default_factory=dict, repr=False)
    log: list[str] = field(default_factory=list)

    # ------------------------------------------------------------ bookkeeping

    def _note(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        self.log.append(line)
        print(line, flush=True)

    def _commit_state(self) -> None:
        """Called with the state lock held."""
        save_state(self.state, self.run_dir.state_path)

    def _transition(self, ticket_id: int, status: str, **fields) -> None:
        with self._state_lock:
            record = self.state.record(ticket_id)
            record.status = status
            for key, value in fields.items():
                setattr(record, key, value)
            self._commit_state()

    # -------------------------------------------------------- the outer loop

    def run(self) -> None:
        self._note(f"run {self.state.run_id} on {self.state.integration_branch}")
        self._mark_human_gates()

        while True:
            if self.state.circuit_breaker.tripped:
                self._note("circuit breaker tripped — starting nothing further")
                break

            self._reap_finished()

            if self._past_deadline():
                if not self._threads:
                    self._note("past the wall-clock stop and nothing in flight — done")
                    break
                time.sleep(self.poll_seconds)
                continue

            if time.monotonic() < self._paused_until:
                time.sleep(self.poll_seconds)
                continue

            dispatched = self._dispatch_wave()

            if not dispatched and not self._threads:
                self._note("nothing dispatchable and nothing in flight — done")
                break

            time.sleep(self.poll_seconds)

        self._join_all()
        self._write_report()

    def _past_deadline(self) -> bool:
        return self.deadline is not None and datetime.now() >= self.deadline

    def _mark_human_gates(self) -> None:
        with self._state_lock:
            for ticket in self.backlog:
                if ticket.human_gate:
                    self.state.record(ticket.id).status = st.HELD
            self._commit_state()

    def _dispatch_wave(self) -> list[int]:
        with self._state_lock:
            states = self.state.statuses(self.backlog.ids)
        decision = schedule(self.backlog, states, self.config.ceilings)

        started = []
        for ticket_id in decision.dispatch:
            self._transition(ticket_id, st.RUNNING,
                             started_at=datetime.now().isoformat(timespec="seconds"))
            thread = threading.Thread(target=self._guarded_pipeline,
                                      args=(self.backlog[ticket_id],),
                                      name=f"T{ticket_id:02d}", daemon=True)
            self._threads[ticket_id] = thread
            thread.start()
            started.append(ticket_id)
            self._note(f"T{ticket_id:02d} dispatched ({self.backlog[ticket_id].model})")
        return started

    def _reap_finished(self) -> None:
        for ticket_id in [i for i, t in self._threads.items() if not t.is_alive()]:
            self._threads.pop(ticket_id).join()

    def _join_all(self) -> None:
        for ticket_id, thread in list(self._threads.items()):
            thread.join()
            self._threads.pop(ticket_id, None)

    # --------------------------------------------------------- per-ticket run

    def _guarded_pipeline(self, ticket: Ticket) -> None:
        try:
            self._pipeline(ticket)
        except Exception as exc:                     # noqa: BLE001 — never kill the run
            self._note(f"T{ticket.id:02d} orchestrator error: {exc!r}")
            self._quarantine(ticket, f"orchestrator error: {exc!r}", exit_class="orchestrator")
        finally:
            self._transition(ticket.id, self.state.record(ticket.id).status,
                             ended_at=datetime.now().isoformat(timespec="seconds"))

    def _pipeline(self, ticket: Ticket) -> None:
        worktree = self._provision_with_retry(ticket)
        if worktree is None:
            return

        try:
            if not self._run_agent_with_retry(ticket, worktree):
                return
            if not self._gate(ticket, worktree):
                return
            self._merge(ticket, worktree)
        finally:
            try:
                teardown(self.git, worktree)
            except Exception as exc:                 # noqa: BLE001
                self._note(f"T{ticket.id:02d} worktree teardown failed: {exc!r}")

    # ------------------------------------------------------------ provisioning

    def _provision_with_retry(self, ticket: Ticket):
        """Infrastructure failures back off and do not count against the ticket."""
        for attempt in range(1, self.config.retries.infrastructure + 1):
            try:
                worktree = provision(
                    self.git, ticket_id=ticket.id,
                    worktrees_root=self.config.paths.worktrees,
                    integration_branch=self.state.integration_branch,
                    branch_prefix=self.config.ticket_branch_prefix,
                    fixture_db=self.config.paths.fixture_db,
                    fixture_db_dest=self.config.paths.fixture_db_dest,
                    recordings=self.config.paths.recordings,
                )
            except ProvisionError as exc:
                self._note(f"T{ticket.id:02d} provisioning failed "
                           f"({attempt}/{self.config.retries.infrastructure}): {exc}")
                time.sleep(self.config.retries.infrastructure_backoff_seconds * attempt)
                continue

            self._transition(ticket.id, st.RUNNING, branch=worktree.branch,
                             worktree=str(worktree.path))
            return worktree

        self._quarantine(ticket, "could not provision a worktree",
                         exit_class="infrastructure")
        return None

    # ------------------------------------------------------------------ agent

    def _run_agent_with_retry(self, ticket, worktree) -> bool:
        """Returns True when the agent produced work worth gating."""
        tail = ""
        for attempt in range(1, self.config.retries.stall + 2):
            with self._state_lock:
                self.state.record(ticket.id).attempts = attempt
                self._commit_state()

            result = run_agent(
                list(self.config.agent.cli),
                cwd=worktree.path,
                prompt=build_prompt(ticket, self.config, previous_transcript_tail=tail),
                model=self.config.model_id(ticket.model),
                budget_minutes=ticket.budget_minutes or self.config.budget_minutes(ticket.size),
                extra_args=self.config.agent.extra_args,
                transcript_path=self.run_dir.artifact(ticket.id, f"transcript-{attempt}.log"),
            )
            commits = len(self.git.commits_between(self.state.integration_branch,
                                                   worktree.branch))
            verdict = classify_exit(result, commits_made=commits, config=self.config)

            if verdict == "ok":
                return True

            if verdict == "infrastructure":
                self._register_rate_limit_signature(ticket)
                self._quarantine(ticket, "infrastructure failure during dispatch",
                                 exit_class="infrastructure")
                return False

            # Stall. One retry from a clean worktree with the transcript tail.
            self._note(f"T{ticket.id:02d} stalled (attempt {attempt})")
            if attempt > self.config.retries.stall:
                self._quarantine(ticket, "stalled and did not recover", exit_class="stall")
                return False
            tail = result.transcript[-4000:]

        return False

    def _register_rate_limit_signature(self, ticket: Ticket) -> None:
        """Rate limiting is handled fleet-wide, not per-agent."""
        now = time.monotonic()
        window = self.config.rate_limit.fast_exit_seconds * 5
        self._rate_limit_hits = [t for t in self._rate_limit_hits if now - t < window]
        self._rate_limit_hits.append(now)

        if len(self._rate_limit_hits) >= self.config.rate_limit.concurrent_signature:
            self._backoff_seconds = min(
                self.config.rate_limit.max_backoff_seconds,
                max(self.config.rate_limit.initial_backoff_seconds,
                    self._backoff_seconds * 2),
            )
            self._paused_until = now + self._backoff_seconds
            self._rate_limit_hits.clear()
            self._note(f"rate-limit signature on {self.config.rate_limit.concurrent_signature}+ "
                       f"agents — pausing all dispatch for {self._backoff_seconds:.0f}s")

    # ------------------------------------------------------------------ gates

    def _gate(self, ticket: Ticket, worktree) -> bool:
        self._transition(ticket.id, st.GATING)
        base = self.state.integration_branch
        branch = worktree.branch
        gates: dict[str, str] = {}

        # 1 — red proof
        red = check_red_proof(self.git, worktree.path, base=base, branch=branch,
                              command=self.config.suite.command,
                              timeout_minutes=self.config.suite.timeout_minutes)
        self.run_dir.write(ticket.id, "red-proof.txt", f"{red.detail}\n\n{red.output}")
        gates["red_proof"] = red.status
        self._set_gates(ticket.id, gates)
        if red.status != "pass":
            self._quarantine(ticket, f"red proof: {red.detail}", exit_class="red-proof")
            return False

        # 2 — suite, with the flake amendment
        suite = check_suite(worktree.path, self.config.suite.command,
                            baseline_failed=self.baseline_failed,
                            timeout_minutes=self.config.suite.timeout_minutes)
        self.run_dir.write(ticket.id, "suite.txt", suite.output + suite.rerun_output)
        gates["suite"] = suite.status
        self._set_gates(ticket.id, gates, flaky_tests=list(suite.flaky))
        if suite.status == "fail":
            self._quarantine(ticket, f"suite regressions: {', '.join(suite.regressions)}",
                             exit_class="red-at-exit")
            return False
        if suite.status == "flaky":
            self._note(f"T{ticket.id:02d} FLAKY: {', '.join(suite.flaky)}")
            self._count_flaky()

        # 3 — scope, a soft gate
        touched = self.git.files_changed(base, branch)
        scope = check_scope(touched=touched, declared=ticket.files)
        self.run_dir.write(ticket.id, "scope.txt", scope.render())
        gates["scope"] = scope.status
        self._set_gates(ticket.id, gates, scope_deviations=list(scope.deviations))

        self.run_dir.write(ticket.id, "diff.patch", self.git.diff(base, branch))

        # 4 — two-axis review
        if not self._review(ticket, worktree, gates, scope.deviations):
            return False

        # 5 — overlap
        symbols = added_symbols(self.git, base, branch,
                                include_private=self.config.overlap.include_private)
        with self._state_lock:
            owners = dict(self.state.symbols)
        overlap = check_overlap(ticket_id=ticket.id, symbols=symbols, owners=owners)
        self.run_dir.write(ticket.id, "overlap.txt", overlap.render())
        gates["overlap"] = overlap.status
        self._set_gates(ticket.id, gates, overlap_symbols=sorted(overlap.collisions))
        if overlap.status == "hold":
            self._note(f"T{ticket.id:02d} OVERLAP — held, never auto-resolved")
            self._transition(ticket.id, st.OVERLAP)
            return False

        with self._state_lock:
            for symbol in symbols:
                self.state.symbols.setdefault(symbol, ticket.id)
            self._commit_state()
        return True

    def _review(self, ticket, worktree, gates, scope_deviations) -> bool:
        severities = load_rule_severities(self.config.paths.coding_standards)
        merge_base = self.git.merge_base(self.state.integration_branch, worktree.branch)

        for round_number in range(1, self.config.review.max_rounds + 1):
            prompt = build_review_prompt(
                skill=self.config.review.skill,
                merge_base=merge_base,
                ticket_path=ticket.path,
                standards_path=self.config.paths.coding_standards,
                scope_deviations=scope_deviations,
            )
            result = run_agent(list(self.config.agent.cli), cwd=worktree.path, prompt=prompt,
                               model=self.config.model_id("review"),
                               budget_minutes=self.config.review.timeout_minutes,
                               extra_args=self.config.agent.extra_args)
            self.run_dir.write(ticket.id, f"review-{round_number}.md", result.transcript)

            findings = grade_findings(parse_findings(result.transcript), severities,
                                      default=self.config.review.default_severity)
            verdict = check_review(findings,
                                   blocking_severities=self.config.review.blocking_severities)
            write_review_json(findings, self.run_dir.artifact(ticket.id, "review.json"),
                              round_number=round_number)

            gates["review"] = verdict.status
            self._set_gates(ticket.id, gates, review_rounds=round_number,
                            review_blockers=dict(verdict.blockers))

            if verdict.status == "pass":
                self._pending_followups[ticket.id] = list(verdict.followups)
                return True

            if round_number >= self.config.review.max_rounds:
                break

            # One auto-fix round: a fresh agent gets the diff plus the findings.
            self._note(f"T{ticket.id:02d} review blockers — one auto-fix round")
            fix_prompt = _fix_prompt(ticket, verdict.findings)
            fix = run_agent(list(self.config.agent.cli), cwd=worktree.path, prompt=fix_prompt,
                            model=self.config.model_id("fix"),
                            budget_minutes=ticket.budget_minutes,
                            extra_args=self.config.agent.extra_args)
            self.run_dir.write(ticket.id, "review-fix.log", fix.transcript)

        self._quarantine(ticket, "review blockers survived the auto-fix round",
                         exit_class="review-rejected")
        return False

    # ------------------------------------------------------------------ merge

    def _merge(self, ticket: Ticket, worktree) -> None:
        self._transition(ticket.id, st.MERGING)

        with self._merge_lock:
            with self._state_lock:
                self.state.merge_lock_holder = str(ticket.id)
                self._commit_state()
            try:
                result = merge_ticket(
                    self.git, ticket_id=ticket.id, branch=worktree.branch,
                    integration=self.state.integration_branch, title=ticket.title,
                    suite_command=self.config.suite.command,
                    baseline_failed=self.baseline_failed,
                    timeout_minutes=self.config.suite.timeout_minutes,
                )
                self.run_dir.write(ticket.id, "post-merge.txt", result.suite_output)

                if result.status == "merged":
                    append_followups(self.git, ticket_id=ticket.id,
                                     filename=self.config.review.followups_file,
                                     findings=self._pending_followups.pop(ticket.id, []))
            finally:
                with self._state_lock:
                    self.state.merge_lock_holder = None
                    self._commit_state()

        if result.status == "merged":
            with self._state_lock:
                record = self.state.record(ticket.id)
                record.status = st.MERGED
                record.merge_sha = result.merge_sha
                record.gates["post_merge_suite"] = "pass"
                # The flake streak clears only if this ticket's suite was
                # genuinely clean. A ticket that merged because its re-run went
                # green is evidence of an unreliable suite, not against one.
                self._note_merged(suite_was_clean=record.gates.get("suite") == "pass")
                self._commit_state()
            self._note(f"T{ticket.id:02d} MERGED {result.merge_sha[:7]}")
            return

        detail = (f"post-merge red, reverted: {', '.join(result.regressions)}"
                  if result.status == "reverted" else f"merge conflict: {result.detail}")
        self._quarantine(ticket, detail, exit_class=result.status)

    # ------------------------------------------------- quarantine and breaker

    def _set_gates(self, ticket_id: int, gates: dict[str, str], **fields) -> None:
        with self._state_lock:
            record = self.state.record(ticket_id)
            record.gates.update(gates)
            for key, value in fields.items():
                setattr(record, key, value)
            self._commit_state()

    def _quarantine(self, ticket: Ticket, reason: str, *, exit_class: str) -> None:
        """Branch preserved, not merged, dependents held, run continues."""
        self._note(f"T{ticket.id:02d} QUARANTINED — {reason}")
        with self._state_lock:
            record = self.state.record(ticket.id)
            record.status = st.FAILED
            record.exit_class = exit_class
            for dependent in self.backlog.dependents(ticket.id):
                blocked = self.state.record(dependent)
                if blocked.status in (st.PENDING, st.READY):
                    blocked.status = st.BLOCKED_UPSTREAM
            self._note_breaker(note_quarantine)
            self._commit_state()

    def _count_flaky(self) -> None:
        """A FLAKY mark counts toward the breaker at half weight."""
        with self._state_lock:
            self._note_breaker(note_flaky)
            self._commit_state()

    def _note_merged(self, *, suite_was_clean: bool) -> None:
        """Called with the state lock held."""
        breaker = self.state.circuit_breaker
        working = BreakerState(
            consecutive_quarantines=breaker.consecutive_quarantines,
            consecutive_flakes=breaker.consecutive_flakes,
            tripped=breaker.tripped, reason=breaker.reason,
        )
        note_merged(working, suite_was_clean=suite_was_clean)
        breaker.consecutive_quarantines = working.consecutive_quarantines
        breaker.consecutive_flakes = working.consecutive_flakes

    def _note_breaker(self, event) -> None:
        """Apply one breaker event. Called with the state lock held.

        The policy itself lives in `orchestrator/breaker.py` so it can be
        tested without git, subprocesses or a clock.
        """
        breaker = self.state.circuit_breaker
        working = BreakerState(
            consecutive_quarantines=breaker.consecutive_quarantines,
            consecutive_flakes=breaker.consecutive_flakes,
            tripped=breaker.tripped,
            reason=breaker.reason,
        )
        dispatched = [r for r in self.state.tickets.values()
                      if r.status not in (st.PENDING, st.READY, st.HELD,
                                          st.BLOCKED_UPSTREAM)]
        quarantined = [r for r in dispatched if r.status == st.FAILED]

        event(working, self.config.circuit_breaker,
              dispatched=len(dispatched), quarantined=len(quarantined))

        was_tripped = breaker.tripped
        breaker.consecutive_quarantines = working.consecutive_quarantines
        breaker.consecutive_flakes = working.consecutive_flakes
        breaker.tripped = working.tripped
        breaker.reason = working.reason

        if working.tripped and not was_tripped:
            self._note(f"CIRCUIT BREAKER: {working.reason} — halting the run")

    # ----------------------------------------------------------------- report

    def _write_report(self) -> None:
        self.run_dir.report_path.write_text(render_report(self.state, self.backlog),
                                            encoding="utf-8")
        self._note(f"report written to {self.run_dir.report_path}")


def _fix_prompt(ticket: Ticket, findings) -> str:
    lines = "\n".join(
        f"- [{f.severity}] [{f.axis}] "
        f"{('rule ' + f.rule) if f.rule else 'no rule cited'}: {f.summary}"
        for f in findings if f.severity == "blocker"
    )
    return (
        f"The two-axis review of your work on {ticket.label} returned blockers.\n"
        f"Fix them in this worktree and commit. Change nothing else.\n\n"
        f"Blocking findings:\n{lines}\n\n"
        f"Your ticket is {ticket.path.as_posix()}; the standards are in "
        f"docs/CODING_STANDARDS.md. Do not ask questions — this session is unattended.\n"
    )


class BaselineError(Exception):
    """The baseline could not be measured where the agents actually live."""


# Ticket 0 is not a ticket. The baseline worktree borrows the provisioning path
# and is torn down, branch and all, before the first agent is dispatched.
BASELINE_TICKET_ID = 0
BASELINE_BRANCH_PREFIX = "baseline/"


def capture_baseline(git: Git, config: Config, *, integration_branch: str) -> tuple[str, ...]:
    """The failing set at run start. The suite is not green by construction.

    Measured inside a throwaway **provisioned worktree**, never in the main repo.
    The main repo has `DATA/derived/`; a worktree has only what `provision()`
    junctions in. A baseline taken in one and compared against the other is not
    a weak comparison, it is an inverted one — it is what let ten real-data
    collection errors read as a greenfield ticket's regressions and blocked 36
    tickets behind it.

    Using the same `provision()` path the agents get also makes provisioning
    verification automatic: a worktree that cannot be built, or that cannot
    collect its own suite, now stops the run at startup rather than 20 minutes
    per ticket into it.
    """
    try:
        worktree = provision(
            git, ticket_id=BASELINE_TICKET_ID,
            worktrees_root=config.paths.worktrees,
            integration_branch=integration_branch,
            branch_prefix=BASELINE_BRANCH_PREFIX,
            fixture_db=config.paths.fixture_db,
            fixture_db_dest=config.paths.fixture_db_dest,
            recordings=config.paths.recordings,
        )
    except ProvisionError as exc:
        raise BaselineError(
            f"refusing to start: the baseline worktree could not be provisioned, so "
            f"no agent's worktree can be either — {exc}"
        ) from exc

    try:
        result = run_suite(worktree.path, config.suite.command,
                           timeout_minutes=config.suite.timeout_minutes)
    finally:
        try:
            teardown(git, worktree)
        finally:
            if git.branch_exists(worktree.branch):
                git.delete_branch(worktree.branch)

    if result.collection_interrupted:
        # The failure mode this misses if left to the check below: pytest names
        # the unimportable files on ordinary `ERROR <file>` lines, so the failing
        # set is attributable and looks like a merely-red baseline. It is not —
        # collection aborted, so no test ran. Recorded as the baseline, it makes
        # every later suite gate a comparison of one empty run against another,
        # and the whole night's tickets merge on a gate that measured nothing.
        raise BaselineError(
            "refusing to start: the baseline suite aborted during collection, so no "
            "test executed. The named files below could not be imported in a "
            "provisioned worktree — fix the worktree fixture (missing recording data "
            "is the usual cause; see orchestrator/make_fixture.py) before running.\n"
            f"{', '.join(result.failed[:12])}\n\n{result.output[-4000:]}"
        )

    unattributed = [n for n in result.failed if n.startswith(UNATTRIBUTED_PREFIX)]
    if unattributed:
        raise BaselineError(
            "refusing to start: the baseline suite failed in a way that names no "
            "node ids — a collection error, an internal pytest error, or a timeout. "
            "Recording that as the baseline would hand every ticket a gate it cannot "
            f"pass.\n{unattributed[0]}\n\n{result.output[-4000:]}"
        )
    return result.failed
