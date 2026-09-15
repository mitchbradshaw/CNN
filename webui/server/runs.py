"""Run manager: bridges the synchronous, blocking ``execute_recipe`` to the
browser.

* One worker thread per run. ``execute_recipe`` is called **unchanged** with
  ``on_progress`` / ``on_step_result`` / ``should_cancel`` callbacks.
* Progress crosses thread → event loop via ``loop.call_soon_threadsafe`` onto
  per-subscriber ``asyncio.Queue``s, streamed to the page as Server-Sent
  Events (``GET /api/runs/{job}/events``). Every event is also appended to
  the job's history so a late subscriber (a page reloaded mid-run) replays
  it and catches up.
* Cancel is a ``threading.Event`` read by ``should_cancel``; the core polls
  it **once, before each step** (cooperative, never mid-step).
* A client disconnect does **not** cancel: the run finishes and its
  snapshot (``GET /api/runs/{job}``) survives the reload.
* ``force=True`` is always passed so the step loop actually runs; a step
  whose prefix is in the cache is restored with ``step_timings[i] == 0.0``
  (the core's own signal for a hit) — that is what the "cached · 0 s" badge
  reports after a suffix re-run.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import threading
import time
import traceback
from typing import Any

from Working.execution import RecipeCancelled, RecipeExecutionError, execute_recipe
from Working.database.schema import init_db

from . import chain as chain_mod
from .serialize import _clean, to_payload
from Working.execution import _recipe_prefix_hash
import json
import os
import re

log = logging.getLogger("proto.runs")


class Job:
    _ids = itertools.count(1)

    def __init__(self, recipe: dict, recording: dict, px: int):
        self.id = next(Job._ids)
        self.recipe = recipe
        self.recording = recording
        self.px = px
        self.status = "queued"          # queued | running | completed | failed | cancelled
        self.n_steps = len(recipe["steps"])
        self.current_step: int | None = None
        self.steps: list[dict] = [
            {"index": i, "stage": s["stage"], "algorithm": s["algorithm"], "status": "pending",
             "started_at": None, "elapsed_s": None, "cached_predicted": False, "cached": None,
             "kind": None, "summary": None, "has_payload": False}
            for i, s in enumerate(recipe["steps"])
        ]
        self.payloads: dict[int, dict] = {}
        self.error: dict | None = None
        self.step_timings: dict | None = None
        self.detections_written: int | None = None
        self.config_hash: str | None = None
        self.db_run_id: int | None = None
        self.started_at = time.time()
        self.finished_at: float | None = None
        self.events: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self.cancel_event = threading.Event()
        self._windowset = None          # last WindowSet seen, for Grouping strips
        self.log_lines: list[str] = []

    def snapshot(self) -> dict:
        return {
            "job_id": self.id, "status": self.status, "n_steps": self.n_steps,
            "current_step": self.current_step, "steps": self.steps, "error": self.error,
            "step_timings": self.step_timings, "detections_written": self.detections_written,
            "config_hash": self.config_hash, "db_run_id": self.db_run_id,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "recipe": self.recipe, "recording_id": self.recording["id"],
            "elapsed_s": (self.finished_at or time.time()) - self.started_at,
        }


class RunManager:
    def __init__(self, db_path: str, meta_dir: str | None = None):
        self.db_path = db_path
        self.meta_dir = meta_dir
        self.jobs: dict[int, Job] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ plumbing --
    def attach_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    def _publish(self, job: Job, event: dict):
        event = dict(event, job_id=job.id, ts=time.time())
        job.events.append(event)
        for q in list(job.subscribers):
            q.put_nowait(event)

    def _emit(self, job: Job, event: dict):
        if self.loop is None:
            self._publish(job, event)
        else:
            self.loop.call_soon_threadsafe(self._publish, job, event)

    def subscribe(self, job: Job) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for e in job.events:          # replay for late subscribers (reload mid-run)
            q.put_nowait(e)
        job.subscribers.append(q)
        return q

    def unsubscribe(self, job: Job, q: asyncio.Queue):
        if q in job.subscribers:
            job.subscribers.remove(q)

    # ---------------------------------------------------------------- start --
    def start(self, recipe: dict, recording: dict, px: int = 1200) -> Job:
        job = Job(recipe, recording, px)
        # the recipe's short hash is known before the run, so a FAILED run still
        # carries it (frame chain-1f: "adapter … · recipe a7f39c · traceback in log")
        job.config_hash = chain_mod.hashes(recipe)["config_hash"]
        with self._lock:
            self.jobs[job.id] = job
        conn = init_db(self.db_path)
        try:
            for row in chain_mod.cache_status(recipe, conn):
                job.steps[row["index"]]["cached_predicted"] = row["cached"]
        finally:
            conn.close()
        t = threading.Thread(target=self._run, args=(job,), name=f"run-{job.id}", daemon=True)
        job.status = "running"
        t.start()
        return job

    def cancel(self, job: Job) -> bool:
        if job.status != "running":
            return False
        job.cancel_event.set()
        self._emit(job, {"event": "cancel_requested", "step": job.current_step})
        return True

    def _latest_db_run_id(self, job: Job) -> int | None:
        """The core writes the runs row before raising; find it by the recipe's config hash."""
        try:
            conn = init_db(self.db_path)
            try:
                row = conn.execute("SELECT r.id FROM runs r JOIN configs c ON c.id = r.config_id WHERE c.config_hash = ? "
                                   "ORDER BY r.id DESC LIMIT 1", (job.config_hash,)).fetchone()
                return int(row[0]) if row else None
            finally:
                conn.close()
        except Exception:
            return None

    # ------------------------------------------------------------- worker --
    def _run(self, job: Job):
        span = job.recipe.get("span")
        span_start = int(span[0]) if span else 0
        fs = float(job.recording["fs"])
        n_span = (int(span[1]) - int(span[0])) if span else int(job.recording["n_samples"])
        step_wall: dict[int, float] = {}

        def on_progress(i, n, stage, algorithm):
            job.current_step = i
            step_wall[i] = time.perf_counter()
            job.steps[i]["status"] = "running"
            job.steps[i]["started_at"] = time.time()
            for j in range(i + 1, n):
                job.steps[j]["status"] = "pending"
            self._emit(job, {"event": "step_start", "step": i, "n_steps": n, "stage": stage, "algorithm": algorithm,
                             "cached_predicted": job.steps[i]["cached_predicted"]})

        def on_step_result(i, result):
            wall = time.perf_counter() - step_wall.get(i, time.perf_counter())
            kind = result.output_kind
            ctx = {"fs": fs, "span_start": span_start, "px": job.px, "n_samples": n_span,
                   "windowset": job._windowset, "params": job.recipe["steps"][i].get("params") or {}}
            # The core's step cache restores the typed value only; AdapterResult.meta (SAX cutlines,
            # MP window m, the model card) is lost on a hit. The bridge keeps a JSON sidecar per
            # prefix hash at first compute and reads it back on a hit (critique r1 P1).
            meta = result.meta or {}
            meta_from_sidecar = False
            if self.meta_dir:
                try:
                    side = os.path.join(self.meta_dir, _recipe_prefix_hash(job.recipe, i), f"{i}.json")
                    if meta:
                        os.makedirs(os.path.dirname(side), exist_ok=True)
                        with open(side, "w", encoding="utf-8") as f:
                            json.dump(_clean(meta), f)
                    elif os.path.isfile(side):
                        with open(side, encoding="utf-8") as f:
                            meta = json.load(f)
                        meta_from_sidecar = True
                except Exception:
                    log.exception("meta sidecar failed for step %d", i)
            try:
                if kind == "windowset":
                    job._windowset = result.value
                payload = to_payload(kind, result.value, meta, ctx)
                if meta_from_sidecar:
                    payload["meta_from_sidecar"] = True
                job.payloads[i] = payload
                job.steps[i]["has_payload"] = True
                job.steps[i]["summary"] = payload.get("summary")
            except Exception as e:      # serialisation must never hide a step that ran
                tb = traceback.format_exc()
                job.log_lines.append(tb)
                log.exception("payload serialisation failed for step %d", i)
                job.payloads[i] = {"type": kind, "error": f"{type(e).__name__}: {e}", "traceback": tb, "summary": "render payload failed"}
                job.steps[i]["has_payload"] = True
                job.steps[i]["summary"] = "render payload failed"
            job.steps[i]["kind"] = kind
            job.steps[i]["status"] = "done"
            job.steps[i]["elapsed_s"] = wall
            self._emit(job, {"event": "step_done", "step": i, "kind": kind, "elapsed_s": wall,
                             "cached_predicted": job.steps[i]["cached_predicted"],
                             "summary": job.steps[i]["summary"]})

        def should_cancel():
            return job.cancel_event.is_set()

        t0 = time.perf_counter()
        try:
            out = execute_recipe(job.recipe, db_path=self.db_path, force=True,
                                 on_progress=on_progress, should_cancel=should_cancel,
                                 on_step_result=on_step_result)
            job.step_timings = {int(k): float(v) for k, v in (out.get("step_timings") or {}).items()}
            for i, s in enumerate(job.steps):
                if i in job.step_timings:
                    s["cached"] = job.step_timings[i] == 0.0
                    s["core_elapsed_s"] = job.step_timings[i]
            job.detections_written = out.get("detections_written")
            job.config_hash = out.get("config_hash")
            job.db_run_id = out.get("run_id")
            job.status = "completed"
            job.finished_at = time.time()
            self._emit(job, {"event": "run_end", "status": "completed", "step_timings": job.step_timings,
                             "detections_written": job.detections_written, "config_hash": job.config_hash,
                             "db_run_id": job.db_run_id, "elapsed_s": time.perf_counter() - t0})
        except RecipeCancelled as e:
            i = job.current_step
            job.db_run_id = self._latest_db_run_id(job)
            if i is not None and job.steps[i]["status"] != "done":
                job.steps[i]["status"] = "cancelled"
            for s in job.steps:
                if s["status"] == "pending":
                    s["status"] = "cancelled"
            job.status = "cancelled"
            job.finished_at = time.time()
            first_cancelled = next((s["index"] for s in job.steps if s["status"] == "cancelled"), i)
            i = first_cancelled   # critique r2: name the stage that was stopped, not the last one that finished
            job.error = {"step": i, "message": str(e), "type": "RecipeCancelled"}
            self._emit(job, {"event": "run_end", "status": "cancelled", "step": i, "message": str(e),
                             "db_run_id": job.db_run_id, "elapsed_s": time.perf_counter() - t0})
        except RecipeExecutionError as e:
            i = job.current_step
            m = re.search(r"run_id=(\d+)", str(e))
            job.db_run_id = int(m.group(1)) if m else self._latest_db_run_id(job)
            cause = e.__cause__
            tb = "".join(traceback.format_exception(cause)) if cause else traceback.format_exc()
            job.log_lines.append(tb)
            if i is not None:
                job.steps[i]["status"] = "failed"
                job.steps[i]["elapsed_s"] = time.perf_counter() - step_wall.get(i, t0)
            for s in job.steps:
                if s["status"] == "pending":
                    s["status"] = "blocked"
            job.status = "failed"
            job.finished_at = time.time()
            job.error = {"step": i, "message": f"{type(cause).__name__}: {cause}" if cause else str(e),
                         "type": type(cause).__name__ if cause else "RecipeExecutionError",
                         "traceback": tb, "adapter": (job.recipe["steps"][i]["stage"] + "." + job.recipe["steps"][i]["algorithm"]) if i is not None else None}
            log.error("run %s failed at step %s: %s", job.id, i, job.error["message"])
            self._emit(job, {"event": "run_end", "status": "failed", "step": i, "error": job.error,
                             "db_run_id": job.db_run_id, "elapsed_s": time.perf_counter() - t0})
        except Exception as e:          # pre-run validation errors etc.
            tb = traceback.format_exc()
            job.log_lines.append(tb)
            job.status = "failed"
            job.finished_at = time.time()
            job.error = {"step": job.current_step, "message": f"{type(e).__name__}: {e}", "type": type(e).__name__, "traceback": tb}
            log.exception("run %s failed before/outside the step loop", job.id)
            self._emit(job, {"event": "run_end", "status": "failed", "step": job.current_step, "error": job.error,
                             "elapsed_s": time.perf_counter() - t0})
