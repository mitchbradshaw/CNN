"""The **one server-side dispatch seam** over the seven interchange types.

``to_payload(kind, value, meta, ctx)`` turns a ``Working.types`` value (plus
the ``AdapterResult.meta`` that only exists at run time) into a compact,
JSON-safe payload keyed on ``payload["type"]``. The client has the matching
single seam ``renderByType`` in ``client/src/analyse/Renderer.tsx``.

Transport rules (DECISIONS.md §3): bulk arrays never cross. A Signal or
Scores ships as a peak-preserving polyline sized to the viewport; a SpanSet
ships absolute seconds (capped); an Encoding ships a symbol strip or a
block-averaged uint8 image; a WindowSet ships its geometry and a capped,
rounded feature matrix; a Grouping ships labels + sizes (+ a time strip when
the WindowSet it was computed over is at hand); a Model ships a metadata
card, never the joblib.

Index conventions differ per type and are handled here, once:
* Signal / Scores: sample i of the value is absolute sample ``span_start + i``.
* SpanSet: producers emit **span-relative** indices (execution.py inserts
  them unshifted into ``detections``); we add ``span_start``.
* WindowSet.starts are already **channel-absolute**.
* Grouping has no time; it borrows the WindowSet's starts.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import numpy as np

from .decimate import envelope

SPAN_CAP = 5000
FEATURE_CELL_CAP = 200_000
IMAGE_SIDE = 256
SYMBOL_CAP = 20_000

_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _letter(i: int) -> str:
    i = int(i)
    if i < 26:
        return _LETTERS[i]
    return _LETTERS[i // 26 - 1] + _LETTERS[i % 26]


def _clean(v: Any) -> Any:
    """Recursively make a meta value JSON-safe (numpy scalars/arrays, NaN)."""
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if np.isnan(f) or np.isinf(f) else f
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, float):
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
    if isinstance(v, np.ndarray):
        if v.size > 4096:
            return {"_array": True, "shape": list(v.shape), "dtype": str(v.dtype), "omitted": True}
        return [_clean(a) for a in v.ravel().tolist()] if v.ndim == 1 else _clean(v.tolist())
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


def _finite_range(a: np.ndarray) -> list | None:
    a = np.asarray(a, dtype=float)
    f = a[np.isfinite(a)]
    if f.size == 0:
        return None
    return [float(f.min()), float(f.max())]


# ---------------------------------------------------------------- per type --

def _signal(value, meta, ctx):
    fs = float(value.fs)
    n = int(len(value.x))
    ss = int(ctx.get("span_start", 0))
    env = envelope(value.x, fs, 0, n, ctx.get("px", 1200))
    # envelope() reports t from index 0; shift to absolute seconds.
    env["t"] = [tt + ss / fs for tt in env["t"]]
    yr = _finite_range(value.x)
    return {
        "type": "signal", "fs": fs, "n": n, "t0_s": ss / fs, "t1_s": (ss + n) / fs,
        "y_range": yr, "envelope": env,
        "summary": f"{n:,} samples · {'%.3f' % yr[0] if yr else '–'} … {'%.3f' % yr[1] if yr else '–'} mV",
    }


def _scores(value, meta, ctx):
    fs = float(value.fs)
    vals = np.asarray(value.values, dtype=float)
    n = int(len(vals))
    ss = int(ctx.get("span_start", 0))
    env = envelope(vals, fs, 0, n, ctx.get("px", 1200))
    env["t"] = [tt + ss / fs for tt in env["t"]]
    nan_tail = int(np.isnan(vals[::-1]).cumprod().sum()) if n else 0
    finite = vals[np.isfinite(vals)]
    # top-k lowest (motif-like) and highest (discord-like) locations
    top = {"low": [], "high": []}
    if finite.size:
        order = np.argsort(np.where(np.isfinite(vals), vals, np.inf))
        top["low"] = [{"t_s": (ss + int(i)) / fs, "v": float(vals[i])} for i in order[:3]]
        order_hi = np.argsort(np.where(np.isfinite(vals), -vals, np.inf))
        top["high"] = [{"t_s": (ss + int(i)) / fs, "v": float(vals[i])} for i in order_hi[:1]]
    hist = None
    if finite.size:
        counts, edges = np.histogram(finite, bins=40)
        hist = {"counts": counts.tolist(), "edges": edges.tolist()}
    m = meta.get("m") if meta else None
    return {
        "type": "scores", "fs": fs, "n": n, "t0_s": ss / fs, "t1_s": (ss + n) / fs,
        "nan_tail": nan_tail, "value_range": _finite_range(vals), "envelope": env,
        "top": top, "histogram": hist, "m": _clean(m),
        "summary": f"{n:,} values · one per {1 / fs:g} s" + (f" · m = {int(m)} samples" if m else ""),
    }


def _spanset(value, meta, ctx):
    fs = float(ctx.get("fs", (meta or {}).get("fs", 1.0)))
    ss = int(ctx.get("span_start", 0))
    starts = np.asarray(value.starts, dtype=np.int64)
    ends = np.asarray(value.ends, dtype=np.int64)
    n = int(len(starts))
    capped = n > SPAN_CAP
    sl = slice(0, SPAN_CAP)
    scores = list(value.scores)[sl] if value.scores is not None else None
    labels = list(value.labels)[sl] if value.labels is not None else None
    dur = (ends - starts) / fs if n else np.array([])
    return {
        "type": "spanset", "fs": fs, "n": n, "capped": capped,
        "start_s": ((starts[sl] + ss) / fs).tolist(), "end_s": ((ends[sl] + ss) / fs).tolist(),
        "labels": labels, "scores": _clean(scores),
        "summary": (f"{n} span{'s' if n != 1 else ''}" + (f" · mean {dur.mean():.1f} s" if n else " · nothing above threshold")),
    }


def _windowset(value, meta, ctx):
    fs = float(value.fs)
    starts = np.asarray(value.starts, dtype=np.int64)
    n = int(len(starts))
    out = {
        "type": "windowset", "fs": fs, "n_windows": n, "length": int(value.length),
        "length_s": int(value.length) / fs, "starts_s": (starts[:SPAN_CAP] / fs).tolist(),
        "capped": n > SPAN_CAP, "features": None,
    }
    if value.features is not None:
        df = value.features
        cols = [str(c) for c in df.columns]
        feat = {"n_columns": len(cols), "columns": cols, "matrix": None}
        if n * len(cols) <= FEATURE_CELL_CAP:
            mat = df.to_numpy(dtype=float)
            mat = np.where(np.isfinite(mat), np.round(mat, 4), np.nan)
            feat["matrix"] = [[None if np.isnan(c) else float(c) for c in row] for row in mat]
            colmin = np.nanmin(mat, axis=0) if n else np.array([])
            colmax = np.nanmax(mat, axis=0) if n else np.array([])
            feat["col_range"] = [[None if np.isnan(a) else float(a), None if np.isnan(b) else float(b)] for a, b in zip(colmin, colmax)]
        out["features"] = feat
    out["summary"] = f"{n} windows · {out['length_s']:g} s each" + (f" · {out['features']['n_columns']} features" if out["features"] else "")
    return out


def _encoding(value, meta, ctx):
    meta = meta or {}
    vals = np.asarray(value.values)
    fs = float(ctx.get("fs", 1.0))
    ss = int(ctx.get("span_start", 0))
    if value.kind == "symbolic":
        details = meta.get("details", {}) or {}
        syms = vals.astype(int).ravel()
        n = int(len(syms))
        sps = details.get("samples_per_symbol") or ctx.get("samples_per_symbol")
        if not sps and n:
            sps = max(1, int(round(ctx.get("n_samples", n) / n)))
        alphabet = details.get("alphabet_size")
        if alphabet is None:
            alphabet = int(syms.max()) + 1 if n else 0
        letters = "".join(_letter(s) for s in syms[:SYMBOL_CAP])
        return {
            "type": "encoding", "kind": "symbolic", "n_symbols": n, "alphabet_size": int(alphabet),
            "symbols": syms[:SYMBOL_CAP].tolist(), "letters": letters, "capped": n > SYMBOL_CAP,
            "samples_per_symbol": int(sps) if sps else None,
            "seconds_per_symbol": (int(sps) / fs) if sps else None,
            "t0_s": ss / fs, "fs": fs,
            "cutlines": _clean(details.get("cutlines")), "cutline_domain": details.get("cutline_domain"),
            "representatives": _clean(details.get("representatives")),
            "paa": _clean(np.asarray(details["paa"])[:SYMBOL_CAP]) if details.get("paa") is not None else None,
            "n_trimmed": _clean(details.get("n_trimmed")),
            "summary": f"{n} symbols · alphabet {int(alphabet)} · {(int(sps) / fs) if sps else 0:g} s per symbol",
        }
    # image kinds
    if vals.ndim == 1:
        return {"type": "encoding", "kind": "image", "ndim": 1, "shape": list(vals.shape),
                "series": _clean(vals), "bin_freqs": _clean(meta.get("bin_freqs")),
                "summary": f"{vals.shape[0]} log-frequency bins"}
    if vals.ndim in (2, 3):
        h, w = vals.shape[0], vals.shape[1]
        fh = max(1, int(np.ceil(h / IMAGE_SIDE))); fw = max(1, int(np.ceil(w / IMAGE_SIDE)))
        hh, ww = h // fh * fh, w // fw * fw
        img = vals[:hh, :ww]
        if vals.ndim == 2:
            img = img.reshape(hh // fh, fh, ww // fw, fw).mean(axis=(1, 3))
            rng = _finite_range(img) or [0.0, 1.0]
            u8 = np.clip((img - rng[0]) / ((rng[1] - rng[0]) or 1.0) * 255, 0, 255).astype(np.uint8)
            chans = 1
        else:
            img = img.reshape(hh // fh, fh, ww // fw, fw, vals.shape[2]).mean(axis=(1, 3))
            rng = _finite_range(img) or [0.0, 1.0]
            u8 = np.clip((img - rng[0]) / ((rng[1] - rng[0]) or 1.0) * 255, 0, 255).astype(np.uint8)
            chans = int(vals.shape[2])
        return {"type": "encoding", "kind": "image", "ndim": int(vals.ndim), "shape": list(vals.shape),
                "display_shape": [int(u8.shape[0]), int(u8.shape[1])], "channels": chans,
                "value_range": rng, "pixels_b64": base64.b64encode(np.ascontiguousarray(u8).tobytes()).decode("ascii"),
                "summary": f"{h}×{w}" + (f"×{vals.shape[2]}" if vals.ndim == 3 else "") + f" image · shown at {u8.shape[0]}×{u8.shape[1]}"}
    return {"type": "encoding", "kind": value.kind, "shape": list(vals.shape), "summary": f"{value.kind} {vals.shape}"}


def _grouping(value, meta, ctx):
    meta = meta or {}
    labels = np.asarray(value.labels).astype(int).ravel()
    n = int(len(labels))
    ids, counts = np.unique(labels, return_counts=True) if n else (np.array([]), np.array([]))
    clusters = [{"id": int(i), "count": int(c)} for i, c in zip(ids, counts)]
    out = {"type": "grouping", "n": n, "k": int(len(ids)), "label_base": int(ids.min()) if n else 1,
           "linkage": meta.get("linkage"), "clusters": clusters, "labels": labels[:SPAN_CAP].tolist(),
           "capped": n > SPAN_CAP, "strip": None}
    ws = ctx.get("windowset")
    if ws is not None and len(ws.starts) == n:
        out["strip"] = {"starts_s": (np.asarray(ws.starts) / float(ws.fs))[:SPAN_CAP].tolist(),
                        "length_s": int(ws.length) / float(ws.fs)}
    out["summary"] = f"{len(ids)} clusters · sizes " + ", ".join(str(int(c)) for c in counts)
    return out


def _model(value, meta, ctx):
    meta = meta or {}
    path = str(value.path)
    exists = os.path.isfile(path)
    keep = ("n_windows", "n_classes", "class_counts", "feature_names", "n_features_in",
            "n_features_kept", "n_train", "n_holdout", "holdout_accuracy", "params")
    card = {k: _clean(meta[k]) for k in keep if k in meta}
    acc = card.get("holdout_accuracy")
    return {"type": "model", "path": path, "exists": exists,
            "size_bytes": os.path.getsize(path) if exists else None, "card": card,
            "summary": (f"holdout accuracy {acc:.2f}" if isinstance(acc, (int, float)) else "model") +
                       (f" · {card['n_classes']} classes" if "n_classes" in card else "") +
                       (f" · {card['n_windows']} windows" if "n_windows" in card else "")}


_DISPATCH = {
    "signal": _signal, "scores": _scores, "spanset": _spanset, "windowset": _windowset,
    "encoding": _encoding, "grouping": _grouping, "model": _model,
}
TYPE_KINDS = tuple(sorted(_DISPATCH))


def to_payload(kind: str, value, meta: dict | None = None, ctx: dict | None = None) -> dict:
    """Serialise one typed value. ``ctx`` carries fs, span_start (samples), px,
    n_samples and optionally the WindowSet a Grouping was computed over."""
    fn = _DISPATCH.get(str(kind).lower())
    if fn is None:
        raise ValueError(f"unknown interchange type {kind!r}; known: {TYPE_KINDS}")
    return fn(value, meta or {}, ctx or {})
