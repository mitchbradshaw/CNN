"""FastAPI bridge for prototype A. Thin: every route is a few lines over
``server/{corpus,chain,runs,serialize}.py``. Errors are **loud**: an
unhandled exception returns a 500 whose body carries the traceback and is
logged to ``runtime/<stamp>/server.log``; the page shows it in a red card.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import traceback

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from Working.database.runs import list_runs, list_templates, load_template, save_template, load_recipe

from . import chain as chain_mod
from . import corpus
from .runs import RunManager
from .runtime import HELD_OUT_FILE, PROTO_DIR, Runtime

log = logging.getLogger("proto")


class Step(BaseModel):
    stage: str
    algorithm: str
    params: dict = Field(default_factory=dict)
    side_inputs: dict = Field(default_factory=dict)


class ChainBody(BaseModel):
    recording_id: int | None = None
    span: list[int] | None = None
    steps: list[Step]
    position: int | None = None


class RunBody(BaseModel):
    recording_id: int
    span: list[int] | None = None
    steps: list[Step]
    px: int = 1200


class TemplateBody(BaseModel):
    name: str
    steps: list[Step]


def _steps(body) -> list[dict]:
    return [s.model_dump() for s in body.steps]


def create_app(rt: Runtime) -> FastAPI:
    app = FastAPI(title="Underground Brains — UI prototype A bridge", docs_url="/api/docs", openapi_url="/api/openapi.json")
    manager = RunManager(rt.db_path)
    app.state.rt = rt
    app.state.manager = manager
    app.state.started = time.time()

    def conn():
        return corpus.connect(rt.db_path)

    def rec_or_423(recording_id: int) -> dict:
        c = conn()
        try:
            rec = corpus.recording_row(c, recording_id)
        finally:
            c.close()
        if rec is None:
            raise HTTPException(404, f"no recording id {recording_id}")
        if rec["held_out"]:
            raise HTTPException(423, f"{HELD_OUT_FILE} is held out (spec §0 D6 / Working.config.HELD_OUT_RECORDING_FILE); this prototype refuses it")
        return rec

    @app.on_event("startup")
    async def _startup():
        manager.attach_loop(asyncio.get_running_loop())
        # warm STUMPY's numba JIT off the request path (first matrix_profile call otherwise pays ~30 s)
        def _warm():
            try:
                import numpy as np, stumpy
                stumpy.stump(np.random.default_rng(0).standard_normal(256), 8)
                log.info("stumpy JIT warm")
            except Exception as e:  # pragma: no cover
                log.warning("stumpy warm-up skipped: %s", e)
        import threading
        threading.Thread(target=_warm, daemon=True, name="stumpy-warm").start()

    @app.exception_handler(Exception)
    async def _loud(request: Request, exc: Exception):
        tb = traceback.format_exc()
        log.error("unhandled %s on %s %s\n%s", type(exc).__name__, request.method, request.url.path, tb)
        return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}", "traceback": tb, "path": request.url.path})

    # ------------------------------------------------------------- meta ----
    @app.get("/api/health")
    def health():
        return {"ok": True, "uptime_s": time.time() - app.state.started, "jobs": len(manager.jobs)}

    @app.get("/api/runtime")
    def runtime_info():
        return rt.describe()

    @app.get("/api/boom")
    def boom(kind: str = "server"):
        """Deliberate failure endpoint for the loud-failure evidence."""
        raise RuntimeError("deliberate server-side failure (GET /api/boom)")

    # ---------------------------------------------------------- explore ----
    @app.get("/api/recordings")
    def get_recordings():
        c = conn()
        try:
            return corpus.recordings(c)
        finally:
            c.close()

    @app.get("/api/corpus/{source_file}/coverage")
    def get_coverage(source_file: str, bins: int = 57, verdicts: str | None = None):
        if source_file == HELD_OUT_FILE:
            raise HTTPException(423, f"{HELD_OUT_FILE} is held out; the corpus map refuses it")
        c = conn()
        try:
            vs = tuple(v for v in verdicts.split(",") if v) if verdicts else None
            return corpus.coverage(c, source_file, bins=max(4, min(400, bins)), verdicts=vs)
        except KeyError:
            raise HTTPException(404, f"unknown recording {source_file}")
        finally:
            c.close()

    @app.get("/api/channels/{recording_id}")
    def get_channel(recording_id: int):
        rec = rec_or_423(recording_id)
        c = conn()
        try:
            rec["summary"] = corpus.channel_summary(c, recording_id)
            rec["ribbons"] = corpus.ribbons(c, recording_id, rec["fs"], rec["n_samples"])
            rec["y_range"] = corpus.y_range(rec)
            return rec
        finally:
            c.close()

    @app.get("/api/channels/{recording_id}/window")
    def get_window(recording_id: int, t0: float = 0.0, t1: float | None = None, px: int = 1200):
        rec = rec_or_423(recording_id)
        if t1 is None:
            t1 = rec["duration_s"]
        c = conn()
        try:
            out = corpus.window(c, rec, t0, t1, max(16, min(8000, px)))
        finally:
            c.close()
        resp = JSONResponse(out)
        resp.headers["Server-Timing"] = f"decimate;dur={out['decimate_ms']:.2f}"
        return resp

    @app.get("/api/channels/{recording_id}/spans")
    def get_spans(recording_id: int, t0: float = 0.0, t1: float | None = None):
        rec = rec_or_423(recording_id)
        if t1 is None:
            t1 = rec["duration_s"]
        c = conn()
        try:
            return corpus.spans(c, recording_id, t0, t1, rec["fs"])
        finally:
            c.close()

    # ---------------------------------------------------------- analyse ----
    @app.get("/api/adapters")
    def get_adapters():
        return chain_mod.catalog()

    @app.post("/api/chain/validate")
    def post_validate(body: ChainBody):
        steps = _steps(body)
        out = chain_mod.validate(steps)
        if body.recording_id is not None and out["ok"] and steps:
            rec = rec_or_423(body.recording_id)
            span = tuple(body.span) if body.span else None
            try:
                recipe = chain_mod.build_recipe(body.recording_id, span, steps)
            except ValueError as e:
                out["recipe_error"] = str(e)
                return out
            n = (span[1] - span[0]) if span else rec["n_samples"]
            out["estimate"] = chain_mod.estimate(recipe, n, rec["fs"])
            out["hashes"] = chain_mod.hashes(recipe)
            c = conn()
            try:
                out["cache"] = chain_mod.cache_status(recipe, c)
            finally:
                c.close()
            out["over_ceiling"] = [i for i, s in enumerate(recipe["steps"])
                                   if (lambda spec: spec.max_span_samples is not None and n > spec.max_span_samples)(chain_mod.get_adapter(f"{s['stage']}.{s['algorithm']}"))]
        return out

    @app.post("/api/chain/compatible")
    def post_compatible(body: ChainBody):
        pos = body.position if body.position is not None else len(body.steps)
        return chain_mod.compatible_at(_steps(body), pos)

    @app.post("/api/chain/params")
    def post_params(body: Step):
        """Validated (defaults filled, coerced, range-checked) params for one step."""
        try:
            return {"params": chain_mod.validated_params(body.model_dump())}
        except (ValueError, KeyError) as e:
            raise HTTPException(422, str(e))

    @app.get("/api/templates")
    def get_templates():
        c = conn()
        try:
            builtin = [
                {"id": "builtin:mp_threshold", "name": "mp_threshold · Baseline → Matrix profile → Threshold", "builtin": True,
                 "steps": [{"stage": "preprocessing", "algorithm": "detrend", "params": {"mode": "rolling_mean", "window_s": 600.0}},
                           {"stage": "detection", "algorithm": "matrix_profile", "params": {"window_min": 1.0, "backend": "stump"}},
                           {"stage": "detection", "algorithm": "threshold", "params": {"threshold": 8.0}}]},
                {"id": "builtin:dsax", "name": "dsax_encoding · Baseline → Symbolic encoding (dSAX)", "builtin": True,
                 "steps": [{"stage": "preprocessing", "algorithm": "detrend", "params": {"mode": "rolling_mean", "window_s": 600.0}},
                           {"stage": "detection", "algorithm": "sax_dsax", "params": {"seconds_per_symbol": 20.0, "alphabet_size": 3}}]},
                {"id": "builtin:windows_model", "name": "windows_model · Sliding windows → Cluster → Classifier", "builtin": True,
                 "steps": [{"stage": "preprocessing", "algorithm": "window_matrix", "params": {"window_min": 1.0, "slow_entropy": False}},
                           {"stage": "catalogue", "algorithm": "cluster", "params": {"k": 3}},
                           {"stage": "catalogue", "algorithm": "classifier", "params": {"n_estimators": 50},
                            "side_inputs": {"windows": {"source_kind": "earlier_step", "step_index": 0}}}]},
                {"id": "builtin:gramian", "name": "gramian · Baseline → Gramian GASF image", "builtin": True,
                 "steps": [{"stage": "preprocessing", "algorithm": "detrend", "params": {"mode": "rolling_mean", "window_s": 600.0}},
                           {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}}]},
            ]
            saved = [{"id": row["id"], "name": row["name"], "builtin": False, "steps": json.loads(row["steps_json"])}
                     for row in list_templates(c)]
            return builtin + saved
        finally:
            c.close()

    @app.post("/api/templates")
    def post_template(body: TemplateBody):
        c = conn()
        try:
            tid = save_template(c, body.name, _steps(body))
            return {"id": tid, "name": body.name, "note": "written to the throwaway database copy"}
        finally:
            c.close()

    # -------------------------------------------------------------- runs ----
    @app.post("/api/runs")
    def post_run(body: RunBody):
        rec = rec_or_423(body.recording_id)
        span = tuple(body.span) if body.span else None
        steps = _steps(body)
        v = chain_mod.validate(steps)
        if not v["ok"]:
            raise HTTPException(422, {"message": "chain is invalid", "junctions": v["junctions"]})
        try:
            recipe = chain_mod.build_recipe(body.recording_id, span, steps)
        except ValueError as e:
            raise HTTPException(422, str(e))
        job = manager.start(recipe, rec, px=body.px)
        return job.snapshot()

    @app.get("/api/runs")
    def get_runs(recording_id: int | None = None, limit: int = 30):
        c = conn()
        try:
            rows = list_runs(c, recording_id=recording_id)[:limit]
            out = []
            for row in rows:
                d = dict(row)
                try:
                    recipe = load_recipe(c, d["config_id"])
                    d["steps"] = [f"{s['stage']}.{s['algorithm']}" for s in recipe["steps"]]
                    d["recipe"] = recipe
                except Exception:
                    d["steps"] = []; d["recipe"] = None
                d["step_timings"] = json.loads(d["step_timings_json"]) if d.get("step_timings_json") else None
                d["n_detections"] = c.execute("SELECT COUNT(*) FROM detections WHERE run_id = ?", (d["id"],)).fetchone()[0]
                out.append(d)
            live = [j.snapshot() for j in manager.jobs.values()]
            return {"db_runs": out, "jobs": live}
        finally:
            c.close()

    def job_or_404(job_id: int):
        job = manager.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id} (jobs live in server memory for this server's lifetime)")
        return job

    @app.get("/api/runs/{job_id}")
    def get_run(job_id: int):
        return job_or_404(job_id).snapshot()

    @app.post("/api/runs/{job_id}/cancel")
    def post_cancel(job_id: int):
        job = job_or_404(job_id)
        return {"accepted": manager.cancel(job), "status": job.status,
                "note": "cancel is cooperative: the core checks it once before each step, never mid-step"}

    @app.get("/api/runs/{job_id}/steps/{index}")
    def get_step_payload(job_id: int, index: int, px: int | None = None):
        job = job_or_404(job_id)
        if index not in job.payloads:
            raise HTTPException(404, f"step {index} of job {job_id} has no payload yet (status {job.steps[index]['status'] if index < len(job.steps) else '?'})")
        return job.payloads[index]

    @app.get("/api/runs/{job_id}/log")
    def get_run_log(job_id: int):
        job = job_or_404(job_id)
        return {"job_id": job_id, "lines": job.log_lines, "error": job.error}

    @app.get("/api/runs/{job_id}/events")
    async def get_events(job_id: int, request: Request):
        job = job_or_404(job_id)
        q = manager.subscribe(job)

        async def gen():
            try:
                yield f"event: hello\ndata: {json.dumps(job.snapshot())}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: {e['event']}\ndata: {json.dumps(e)}\n\n"
                    if e["event"] == "run_end":
                        break
            finally:
                manager.unsubscribe(job, q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/runs/{job_id}/export")
    def get_export(job_id: int):
        """Could-have: export the run as a simple self-contained JSON report (recipe, timings, summaries, payloads)."""
        job = job_or_404(job_id)
        path = os.path.join(rt.exports_dir, f"run-{job_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"snapshot": job.snapshot(), "payloads": job.payloads}, f)
        return {"path": path, "bytes": os.path.getsize(path)}

    # ------------------------------------------------------- static client --
    dist = os.path.join(PROTO_DIR, "client", "dist")
    if os.path.isdir(dist):
        app.mount("/assets", StaticFiles(directory=os.path.join(dist, "assets")), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            candidate = os.path.join(dist, full_path)
            if full_path and os.path.isfile(candidate):
                return FileResponse(candidate)
            return FileResponse(os.path.join(dist, "index.html"))
    else:
        @app.get("/")
        def no_client():
            return JSONResponse({"note": "client/dist not built; run `npm run build` in client/ or use `npm run dev` with the proxy",
                                 "api": "/api/docs"})

    return app
