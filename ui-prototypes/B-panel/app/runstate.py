"""Chain state derivation shared by the chain page and the block page — a Python port of A's
``client/src/analyse/rowState.ts`` + ``captions.ts`` + the few lines of ``server/app.py post_validate``
that compute ``over_ceiling`` (replicated here because B calls the service layer, not the bridge).

UI-library free on purpose: nothing here imports Panel or Bokeh."""
from __future__ import annotations

import json
import os
import time

from server import chain as chain_mod
from server import corpus
from server.runtime import HELD_OUT_FILE

EXAMPLE_SOURCE = {"recording_id": 4, "channel_name": "CH4_A2", "source_file": "M2_aug_concat_fs1.mat", "fs": 1.0,
                  "start_idx": 995040, "end_idx": 1002240, "label": "example span"}

_CATALOG = None


def catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {c["name"]: c for c in chain_mod.catalog()}
    return _CATALOG


def step_name(step: dict) -> str:
    return f"{step['stage']}.{step['algorithm']}"


def page_name(step: dict) -> str:
    c = catalog().get(step_name(step))
    return c["page_name"] if c else step_name(step)


def source_of(ctx) -> tuple[dict, bool]:
    """(source, is_example)."""
    if ctx.source:
        return ctx.source, False
    return dict(EXAMPLE_SOURCE), True


def validate_full(ctx, steps: list[dict]) -> dict:
    """``chain.validate`` + (when valid) recipe, estimate, hashes, cache status and over-ceiling — the
    same shape A's ``POST /api/chain/validate`` returns."""
    src, _ = source_of(ctx)
    out = chain_mod.validate(steps)
    out["over_ceiling"] = []
    conn = corpus.connect(ctx.db_path)
    try:
        rec = corpus.recording_row(conn, src["recording_id"])
        out["recording"] = rec
        if rec is None or rec["held_out"]:
            out["held_out"] = bool(rec and rec["held_out"])
            out["ok_to_run"] = False
            return out
        if not (out["ok"] and steps):
            out["ok_to_run"] = False
            return out
        span = (int(src["start_idx"]), int(src["end_idx"]))
        if span[1] - span[0] <= 0:          # FIX (critique r1 P1): an empty span is not a source
            out["recipe_error"] = f"the source span is empty ({max(0, span[1] - span[0])} samples) · send a span of at least 30 s from Explore"
            out["ok_to_run"] = False
            return out
        try:
            recipe = chain_mod.build_recipe(src["recording_id"], span, steps)
        except ValueError as e:
            out["recipe_error"] = str(e)
            out["ok_to_run"] = False
            return out
        n = span[1] - span[0]
        out["recipe"] = recipe
        out["n_samples"] = n
        out["estimate"] = chain_mod.estimate(recipe, n, rec["fs"])
        out["hashes"] = chain_mod.hashes(recipe)
        out["cache"] = chain_mod.cache_status(recipe, conn)
        # replicated from A's server/app.py post_validate / post_run
        for i, s in enumerate(recipe["steps"]):
            spec = chain_mod.get_adapter(f"{s['stage']}.{s['algorithm']}")
            if spec.max_span_samples is not None and n > spec.max_span_samples:
                out["over_ceiling"].append({"index": i, "name": spec.name, "max_span_samples": spec.max_span_samples})
        out["ok_to_run"] = not out["over_ceiling"]
        return out
    finally:
        conn.close()


def job_for_source(job, src: dict):
    """A job's results are only shown against the source it ran on (recording + sample span)."""
    if job is None or src is None:
        return None
    r = job.recipe
    if r.get("recording_id") != src["recording_id"]:
        return None
    sp = r.get("span")
    if sp and (int(sp[0]) != int(src["start_idx"]) or int(sp[1]) != int(src["end_idx"])):
        return None
    return job


def _same(a: dict | None, b: dict | None) -> bool:
    return bool(a and b and a["stage"] == b["stage"] and a["algorithm"] == b["algorithm"])


def derive_rows(steps: list[dict], job, stale_from: int | None, v: dict) -> list[dict]:
    """One RowInfo per step: status ∈ new | cached | computed | stale | running | waiting | failed | blocked | cancelled | invalid | error."""
    live = job is not None and job.status in ("running", "queued")
    rows = []
    for i, step in enumerate(steps):
        jstep = job.steps[i] if job is not None and i < len(job.steps) else None
        matches = job is not None and i < len(job.recipe["steps"]) and _same(job.recipe["steps"][i], step)
        payload = job.payloads.get(i) if (matches and job is not None) else None
        has = payload is not None
        junction = (v.get("junctions") or [None] * (i + 1))[i] if i < len(v.get("junctions") or []) else None
        invalid = junction["reason"] if junction and not junction["ok"] else None
        core_t = (job.step_timings or {}).get(i) if (job is not None and matches) else None
        timing = core_t if core_t is not None else (jstep or {}).get("elapsed_s") if matches else None
        cache_row = (v.get("cache") or [])[i] if i < len(v.get("cache") or []) else None
        base = dict(index=i, payload=payload, has_result=has, timing=timing, timing_is_core=core_t is not None,
                    cached_predicted=bool((jstep or {}).get("cached_predicted")) or bool(cache_row and cache_row["cached"]),
                    invalid_reason=invalid, over_ceiling=any(o["index"] == i for o in v.get("over_ceiling") or []),
                    started_at=(jstep or {}).get("started_at"))
        # FIX (critique r1 P1): "cached" means the core's prefix cache was hit — jstep["cached"] is true or the core's
        # own step timing is exactly 0.0. Anything else that finished was computed and says so.
        done_st = "cached" if (bool((jstep or {}).get("cached")) or core_t == 0.0) else "computed"
        err_payload = has and bool(payload.get("error"))
        if err_payload and not (live and jstep and jstep["status"] == "running"):
            rows.append(dict(base, status="error")); continue
        if live and jstep and matches:
            s = jstep["status"]
            rows.append(dict(base, status={"running": "running", "pending": "waiting", "done": done_st, "failed": "failed",
                                           "blocked": "blocked", "cancelled": "cancelled"}.get(s, "new"))); continue
        if invalid:
            rows.append(dict(base, status="invalid")); continue
        if stale_from is not None and i >= stale_from:
            if has:
                rows.append(dict(base, status="stale")); continue
            if job is not None and job.status == "failed" and (job.error or {}).get("step") == i and matches:
                rows.append(dict(base, status="failed")); continue
            rows.append(dict(base, status="new")); continue
        if job is not None and matches and jstep:
            st = job.status
            if st == "completed":
                rows.append(dict(base, status=done_st if (has or jstep["status"] == "done") else "new")); continue
            if st == "failed":
                rows.append(dict(base, status={"done": done_st, "failed": "failed", "blocked": "blocked"}.get(jstep["status"], "new"))); continue
            if st == "cancelled":
                rows.append(dict(base, status={"done": done_st, "cancelled": "cancelled"}.get(jstep["status"], "new"))); continue
        if cache_row and cache_row["cached"]:
            # critique r1: a step-cache hit with no job attached (reload, another span's run) has no result in this view
            rows.append(dict(base, status="cached", cache_only=not has)); continue
        rows.append(dict(base, status="new"))
    return rows


def fmt_timing(t) -> str:
    if t is None:
        return ""
    if t == 0:
        return "0 s"
    if t < 0.05:
        return "<0.1 s"
    return f"{t:.1f} s"


def terminal_wording(kind: str | None, label: str | None) -> tuple[str, str]:
    if not kind:
        return "no stages — the terminal type is the source", "grey"
    if kind == "spanset":
        return f"terminal {label} → detection template", "green"
    if kind == "model":
        return f"terminal {label} → training template", "green"
    return f"terminal {label} — add a stage to reach a template type", "grey"


def _num(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else f"{float(v):.3g}"
    return str(v)


def param_caption(step: dict) -> str:
    p = step.get("params") or {}
    n = step_name(step)
    if n == "preprocessing.detrend":
        return "linear trend subtracted" if p.get("mode") == "linear" else \
            f"{_num(p.get('window_s', 600))} s {'rolling z-score' if p.get('mode') == 'rolling_z' else 'rolling mean'} subtracted"
    if n == "detection.matrix_profile":
        return f"m = {_num(p.get('window_min', 10))} min · z-normalised · {p.get('backend', 'auto')}"
    if n == "detection.threshold":
        return f"spans where score > {_num(p.get('threshold', 0))}"
    if n in ("detection.sax_dsax", "detection.sax_csax", "detection.sax_psax"):
        return f"{_num(p.get('seconds_per_symbol', 20))} s per symbol → {n.split('_')[-1]} letters · alphabet {_num(p.get('alphabet_size', 3))}"
    if n == "preprocessing.window_matrix":
        return f"{_num(p.get('window_min', 10))} min windows · step {_num(p.get('step_frac', 1))} ×"
    if n == "catalogue.cluster":
        return f"{p.get('linkage', 'ward')} linkage · cut into k = {_num(p.get('k', 3))}"
    if n == "catalogue.classifier":
        return f"{_num(p.get('n_estimators', 300))} trees · {round(float(p.get('holdout_frac', 0.25)) * 100)} % held out"
    items = list(p.items())[:3]
    if items:
        return " · ".join(f"{k} {_num(v)}" for k, v in items)
    c = catalog().get(n)
    return (c["description"].split(".")[0] if c and c["description"] else "defaults")


BUILTIN_TEMPLATES = [   # copied from A's server/app.py get_templates
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
    {"id": "builtin:gramian", "name": "gramian · Baseline → Gramian GASF image (needs a span ≤ 5000 samples)", "builtin": True,
     "steps": [{"stage": "preprocessing", "algorithm": "detrend", "params": {"mode": "rolling_mean", "window_s": 600.0}},
               {"stage": "catalogue", "algorithm": "gramian_gasf", "params": {}}]},
]


def templates(ctx) -> list[dict]:
    from Working.database.runs import list_templates
    conn = corpus.connect(ctx.db_path)
    try:
        saved = [{"id": row["id"], "name": row["name"], "builtin": False, "steps": json.loads(row["steps_json"])}
                 for row in list_templates(conn)]
    finally:
        conn.close()
    return BUILTIN_TEMPLATES + saved


def history(ctx, recording_id: int | None, limit: int = 12) -> list[dict]:
    from Working.database.runs import list_runs, load_recipe
    conn = corpus.connect(ctx.db_path)
    try:
        held = {r["id"] for r in conn.execute("SELECT id FROM recordings WHERE source_file = ?", (HELD_OUT_FILE,))}
        rows = [r for r in list_runs(conn, recording_id=recording_id) if r["recording_id"] not in held][:limit]
        out = []
        for row in rows:
            d = dict(row)
            if d.get("status") == "failed" and str(d.get("error_text") or "").startswith("Cancelled"):
                d["status"] = "cancelled"      # the core stores a cancel as failed + "Cancelled before step N" (critique r1 P2)
            try:
                recipe = load_recipe(conn, d["config_id"])
                d["steps"] = [f"{s['stage']}.{s['algorithm']}" for s in recipe["steps"]]
                d["recipe"] = recipe
            except Exception:
                d["steps"], d["recipe"] = [], None
            d["n_detections"] = conn.execute("SELECT COUNT(*) FROM detections WHERE run_id = ?", (d["id"],)).fetchone()[0]
            out.append(d)
        return out
    finally:
        conn.close()


def export_job(ctx, job) -> str:
    path = os.path.join(ctx.rt.exports_dir, f"run-{job.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"snapshot": job.snapshot(), "payloads": job.payloads, "exported_at": time.time()}, f, default=str)
    return path
