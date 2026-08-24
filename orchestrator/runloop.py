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

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import status as st
from .agent import (
    build_prompt, classify_exit, parse_reset_delay_seconds, run_agent,
)
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
from .merge import append_followups, append_run_postmortem, merge_ticket
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
        self._requeue_deferred()

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

    def _requeue_deferred(self) -> None:
        """A new pass over the backlog re-queues what the environment refused.

        DEFERRED is terminal for the night that set it and pending for the next
        one, which is what makes `--resume` worth running after a usage window
        reopens. Quarantined tickets are deliberately left alone: those carry a
        verdict on the work, and re-running them unchanged just spends the
        budget again on the same wrong answer.

        Only at the top of `run()`. A ticket deferred mid-run stays deferred for
        the rest of it, or the loop would re-dispatch it into the same closed
        door until the deadline.
        """
        with self._state_lock:
            requeued = [key for key, record in self.state.tickets.items()
                        if record.status == st.DEFERRED]
            for key in requeued:
                record = self.state.tickets[key]
                record.status = st.PENDING
                record.exit_class = None
                record.infrastructure_attempts = 0
            if requeued:
                self._commit_state()
        if requeued:
            self._note("re-queued deferred from a previous pass: "
                       + ", ".join(f"T{int(k):02d}" for k in sorted(requeued, key=int)))

    def _dispatch_wave(self) -> list[int]:
        with self._state_lock:
            states = self.state.statuses(self.backlog.ids)
        decision = schedule(self.backlog, states, self.config.ceilings)

        started = []
        for ticket_id in decision.dispatch:
            if started and self.config.agent.launch_stagger_seconds:
                # The worktrees are isolated; the CLI's `~/.claude.json` is not.
                # Three agents launched in the same second raced on it in
                # run-20260817-2050, two read it mid-write, and both looped on a
                # parse error until their budget ran out. Spacing the launches is
                # the cheapest fix that does not involve moving that file.
                time.sleep(self.config.agent.launch_stagger_seconds)
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
            # Only after the worktree is gone: git refuses to delete a branch
            # that a live worktree still has checked out.
            if self.state.record(ticket.id).status == st.DEFERRED:
                self._clear_empty_branch(ticket, worktree)

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
        """Returns True when the agent produced work worth gating.

        Two counters, deliberately separate. `attempts` counts attempts at the
        *work* and is what the stall retry spends. `infrastructure_attempts`
        counts times the environment refused to run at all — a usage cap, a
        rate limit, a corrupted CLI config — and spends nothing, because none
        of those is a fact about the ticket.

        ORCHESTRATOR_SPEC.md:183 has always said so ("does not count against
        the ticket"), and until now that policy existed only for provisioning.
        The agent path quarantined on the first infrastructure failure, which
        charged it to the circuit breaker at full weight and put every
        dependent into BLOCKED_UPSTREAM. run-20260818-2244 lost four tickets
        and the entire night to exactly that, to a message that said in plain
        English when it would be able to work again.
        """
        tail = ""
        attempt = 0
        infrastructure_attempts = 0

        def commits_so_far() -> int:
            return len(self.git.commits_between(self.state.integration_branch,
                                                worktree.branch))

        while True:
            attempt += 1
            with self._state_lock:
                self.state.record(ticket.id).attempts = attempt
                self._commit_state()

            # Transcripts are numbered by launch, not by attempt, so an
            # infrastructure retry never overwrites the evidence of the one
            # before it.
            launch = attempt + infrastructure_attempts
            result = run_agent(
                list(self.config.agent.cli),
                cwd=worktree.path,
                prompt=build_prompt(ticket, self.config, previous_transcript_tail=tail),
                model=self.config.model_id(ticket.model),
                env=self.config.agent_env(ticket.model),
                budget_minutes=ticket.budget_minutes or self.config.budget_minutes(ticket.size),
                extra_args=self.config.agent.extra_args,
                transcript_path=self.run_dir.artifact(ticket.id, f"transcript-{launch}.log"),
                stall_minutes=self.config.agent.stall_minutes,
                commit_count=commits_so_far,
                output_format=self.config.agent.output_format,
                max_budget_usd=self.config.agent.max_budget_usd,
            )
            self._record_usage(ticket.id, result.usage)
            commits = commits_so_far()
            verdict = classify_exit(result, commits_made=commits, config=self.config)

            if verdict == "ok":
                return True

            if verdict == "infrastructure":
                # An environment failure is not an attempt at the work, so the
                # attempt it just consumed is given back.
                attempt -= 1
                infrastructure_attempts += 1
                with self._state_lock:
                    record = self.state.record(ticket.id)
                    record.attempts = attempt
                    record.infrastructure_attempts = infrastructure_attempts
                    self._commit_state()

                if infrastructure_attempts > self.config.retries.infrastructure:
                    self._defer(ticket, "the environment did not recover within "
                                        f"{self.config.retries.infrastructure} retries",
                                worktree=worktree)
                    return False

                wait = self._infrastructure_pause(ticket, result, infrastructure_attempts)
                if not self._wait_out(wait):
                    self._defer(ticket, "past the wall-clock stop while waiting for "
                                        "the usage window to reopen", worktree=worktree)
                    return False
                continue

            # Stall. One retry from a clean worktree with the transcript tail.
            bound = (f"silent for {self.config.agent.stall_minutes}m"
                     if result.stalled_without_commit else "budget exhausted")
            self._note(f"T{ticket.id:02d} stalled (attempt {attempt}, {bound}, "
                       f"{commits} commit(s))")
            if attempt > self.config.retries.stall:
                self._quarantine(ticket, "stalled and did not recover", exit_class="stall")
                return False
            tail = result.transcript[-4000:]

            fresh = self._reprovision_for_retry(ticket, worktree, commits=commits)
            if fresh is None:
                self._quarantine(ticket, "could not reprovision for the stall retry",
                                 exit_class="infrastructure")
                return False
            worktree = fresh

    def _reprovision_for_retry(self, ticket, worktree, *, commits: int):
        """Replace a stalled worktree with a fresh one, so the retry's prompt is true.

        `RETRY_PREFIX` tells the retrying agent "you are starting again from a
        clean worktree, so do not assume any of its work exists". It was handed
        the same half-edited tree the previous attempt stalled in — being lied
        to about the one thing it cannot cheaply check.

        Teardown-and-reprovision, **not** `git reset --hard` plus `git clean -fd`.
        `clean` is a recursive delete aimed at a tree that contains a junction to
        317 MB of shared recording data. It is safe today only because `DATA/*`
        is in `.gitignore` and `clean` without `-x` honours that — a one-line
        dependency, in a repo that has already had one near-miss where a
        recursive walk followed exactly that junction and would have deleted its
        target (see `teardown`'s reparse-point check, and the test that covers
        it). `teardown()` is the code that already knows to unlink junctions
        before anything recursive runs, so this reuses it rather than opening a
        second path to the same cliff.

        Safe only because a stall means zero commits by construction:
        `classify_exit` grades a timeout that *did* produce commits as `ok` and
        sends it to the gates, precisely so the run loop never discards work.
        Asserted rather than assumed — if that ever stops holding, this refuses
        instead of deleting.
        """
        if commits:
            self._note(f"T{ticket.id:02d} not reprovisioning: {commits} commit(s) "
                       f"on the branch would be discarded")
            return worktree

        try:
            teardown(self.git, worktree)
            # `provision` uses `git worktree add -b`, which refuses an existing
            # branch. Deleting is safe here for the same reason the reprovision
            # is: the branch carries nothing.
            self.git.delete_branch(worktree.branch)
            fresh = provision(
                self.git, ticket_id=ticket.id,
                worktrees_root=self.config.paths.worktrees,
                integration_branch=self.state.integration_branch,
                branch_prefix=self.config.ticket_branch_prefix,
                fixture_db=self.config.paths.fixture_db,
                fixture_db_dest=self.config.paths.fixture_db_dest,
                recordings=self.config.paths.recordings,
            )
        except Exception as exc:                     # noqa: BLE001
            self._note(f"T{ticket.id:02d} reprovision failed: {exc!r}")
            return None

        # Path and branch are derived from the ticket id, so the new worktree is
        # value-identical to the old one. `_pipeline` holds its own reference and
        # tears down by path; that reference stays correct precisely because of
        # this. Do not make `provision` allocate unique paths without also
        # threading the new worktree back out to `_pipeline`.
        self._note(f"T{ticket.id:02d} reprovisioned a clean worktree for the retry")
        return fresh

    def _infrastructure_pause(self, ticket, result, attempts: int) -> float:
        """How long to wait, and pause the whole fleet for it.

        Preference order: what the transcript said, then the exponential
        backoff. `You're out of extra usage · resets 3:30am` names its own
        answer, and guessing at it is how a fifteen-minute ceiling came to sit
        in front of a cap that clears in hours.

        The pause is fleet-wide because the cap is: three agents each backing
        off independently is three agents discovering the same closed door.
        """
        stated = parse_reset_delay_seconds(f"{result.transcript}\n{result.raw}")
        if stated is not None:
            wait = min(stated + self.config.rate_limit.usage_reset_grace_seconds,
                       self.config.rate_limit.max_usage_wait_seconds)
            self._note(f"T{ticket.id:02d} usage exhausted — the transcript says the "
                       f"window reopens in {stated / 60:.0f}m; pausing all dispatch "
                       f"for {wait / 60:.0f}m")
        else:
            wait = min(self.config.retries.infrastructure_backoff_seconds * attempts,
                       self.config.rate_limit.max_backoff_seconds)
            self._note(f"T{ticket.id:02d} infrastructure failure "
                       f"({attempts}/{self.config.retries.infrastructure}) — "
                       f"backing off {wait:.0f}s")

        self._register_rate_limit_signature(ticket)
        with self._state_lock:
            self._paused_until = max(self._paused_until, time.monotonic() + wait)
        return wait

    def _wait_out(self, seconds: float) -> bool:
        """Sleep in slices. False if the run's night ended while we waited.

        Sliced rather than one long sleep so that a deadline reached mid-wait
        is noticed then, rather than hours later.
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._past_deadline():
                return False
            if self.state.circuit_breaker.tripped:
                return False
            time.sleep(min(self.poll_seconds, max(0.0, deadline - time.monotonic())))
        return not self._past_deadline()

    def _record_usage(self, ticket_id: int, usage) -> None:
        """Accumulate what a ticket cost, across its agent, reviews and fixes.

        `None` stays `None`: an unmeasured ticket must not read as a free one.
        """
        if usage is None:
            return
        with self._state_lock:
            record = self.state.record(ticket_id)
            record.tokens = (record.tokens or 0) + usage.total_tokens
            record.cost_usd = round((record.cost_usd or 0.0) + usage.cost_usd, 6)
            self._commit_state()

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
                                include_private=self.config.overlap.include_private,
                                ignore_paths=self.config.overlap.ignore_paths)
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
                               env=self.config.agent_env("review"),
                               budget_minutes=self.config.review.timeout_minutes,
                               extra_args=self.config.agent.extra_args,
                               output_format=self.config.agent.output_format,
                               max_budget_usd=self.config.agent.max_budget_usd)
            # A review is two parallel sub-agents plus an orchestrating session,
            # and on a two-round ticket it runs twice. Left uncosted, the most
            # expensive half of a ticket would be invisible in the column that
            # exists to price it.
            self._record_usage(ticket.id, result.usage)
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
                            env=self.config.agent_env("fix"),
                            output_format=self.config.agent.output_format,
                            max_budget_usd=self.config.agent.max_budget_usd,
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

    def _defer(self, ticket: Ticket, reason: str, *, worktree=None) -> None:
        """The environment could not run this. Nothing about the work was judged.

        Everything a quarantine does, this deliberately does not: no circuit
        breaker weight, because a usage cap is not evidence that the base is
        broken; no `BLOCKED_UPSTREAM` for dependents, because there is no
        verdict for them to be downstream of. The ticket simply did not run,
        and `--resume` will pick it up.

        The empty branch it leaves behind is cleaned up by `_pipeline`, after
        the worktree comes down — see `_clear_empty_branch`.
        """
        self._note(f"T{ticket.id:02d} DEFERRED — {reason}")
        with self._state_lock:
            record = self.state.record(ticket.id)
            record.status = st.DEFERRED
            record.exit_class = "infrastructure"
            self._commit_state()

    def _clear_empty_branch(self, ticket: Ticket, worktree) -> None:
        """Delete a deferred ticket's branch when it carries no commits.

        `provision` uses `git worktree add -b`, which fails outright against a
        branch that already exists, so a nothing-branch left behind would kill
        this ticket's next dispatch before it started — the defect that took out
        the first three dispatches of run 2. A branch carrying commits is
        evidence and is never deleted, however the run ended.

        Called after teardown: git will not delete a branch a live worktree is
        still checked out on.
        """
        try:
            if self.git.commits_between(self.state.integration_branch, worktree.branch):
                return
            self.git.delete_branch(worktree.branch)
        except Exception as exc:                     # noqa: BLE001
            self._note(f"T{ticket.id:02d} could not clear its empty branch: {exc!r}")

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
        try:
            append_run_postmortem(self.git, state=self.state, backlog=self.backlog,
                                  filename=self.config.review.followups_file)
        except Exception as exc:                     # noqa: BLE001
            # A post-mortem that cannot be written must not be the reason a
            # night's merges are lost.
            self._note(f"post-mortem stub not written: {exc!r}")


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


def stale_ticket_branches(backlog, existing_branches, *, prefix: str) -> tuple[str, ...]:
    """Ticket branches left over from an earlier run, for tickets this run would dispatch.

    `Git.worktree_add` reuses an existing branch instead of cutting a new one —
    which is right on a resume and wrong on a fresh run. Left unchecked, a
    quarantined ticket's next attempt is provisioned onto the previous
    attempt's commits, cut from the previous run's base, and the red-proof gate
    grades last night's test commit as this run's first.

    Tickets that will not be provisioned are not stale: a `done` ticket's branch
    is the one most likely to still exist, since it is the one that merged.
    """
    existing = set(existing_branches)
    return tuple(sorted(
        f"{prefix}T{t.id:02d}" for t in backlog
        if not t.done and not t.human_gate and f"{prefix}T{t.id:02d}" in existing
    ))


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

    _refuse_a_baseline_that_skipped_the_data_it_junctioned(result, config)

    unattributed = [n for n in result.failed if n.startswith(UNATTRIBUTED_PREFIX)]
    if unattributed:
        raise BaselineError(
            "refusing to start: the baseline suite failed in a way that names no "
            "node ids — a collection error, an internal pytest error, or a timeout. "
            "Recording that as the baseline would hand every ticket a gate it cannot "
            f"pass.\n{unattributed[0]}\n\n{result.output[-4000:]}"
        )
    return result.failed


#: `544 passed, 88 skipped in 420.41s` — pytest's own summary line.
_SUITE_TALLY = re.compile(r"(\d+) passed(?:,\s*(\d+) skipped)?")

#: Above this fraction of the suite, skipping is not "a few tests opted out",
#: it is a coverage collapse. Measured: a worktree with the junction skips 0 of
#: 632; one without skips 88, which is 13.9%.
MAX_BASELINE_SKIP_FRACTION = 0.05


def _refuse_a_baseline_that_skipped_the_data_it_junctioned(result, config) -> None:
    """Stop a run whose baseline measured a fraction of the suite.

    `paths.recordings` exists so that the 88 real-data tests actually execute.
    If they skipped anyway, the junction is configured but its target is empty
    or wrong — the run-20260817-1157 failure, where all 16 fixture rows pointed
    at absent `.npy` files and every worktree ran effectively nothing.

    That used to be caught by accident: `UI/app.py` built the application at
    import, so the missing file raised at collection. Removing that was right,
    and it removed the accidental alarm with it. Converting the guards from
    `return` to `pytest.skip` is what makes the condition visible again; this is
    what reads it.

    Not applied when `recordings` is empty — in that configuration the guarded
    tests are supposed to skip, and refusing would make it unstartable.
    """
    if not config.paths.recordings:
        return

    match = _SUITE_TALLY.search(result.output or "")
    if match is None:
        return                       # no tally to read; other checks still apply

    passed = int(match.group(1))
    skipped = int(match.group(2) or 0)
    total = passed + skipped
    if not total or skipped / total <= MAX_BASELINE_SKIP_FRACTION:
        return

    raise BaselineError(
        f"refusing to start: the baseline skipped {skipped} of {total} tests "
        f"({skipped / total:.0%}) while paths.recordings is configured. Those "
        f"tests skip only when the real channel data is unreachable, so the "
        f"junction is present but its target is empty or wrong — every ticket "
        f"tonight would be gated against a suite that measured a fraction of "
        f"itself. Check {', '.join(str(p) for p in config.paths.recordings)}, "
        f"then rebuild the fixture with `python -m orchestrator.make_fixture`."
    )
