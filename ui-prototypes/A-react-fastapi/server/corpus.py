"""Explore queries: recordings, coverage heatmap, spans in view, channel summaries.

Reads the **database copy** only; ``.npy`` channel files are memory-mapped
read-only from ``DATA/`` (through the worktree junction).
"""
from __future__ import annotations

import functools
import os
import sqlite3
import time

import numpy as np

from Working.database import queries as q
from Working.database import runs as r

from .decimate import envelope
from .runtime import HELD_OUT_FILE

M2_STYLE_NAMES = ["CH1_A1", "CH2_A1", "CH3_A2", "CH4_A2", "CH5_B1", "CH6_B1", "CH7_B2", "CH8_B2",
                  "CH9_C1", "CH10_C1", "CH11_C2", "CH12_C2", "CH13_D1", "CH14_D1", "CH15_D2", "CH16_D2"]

VERDICTS = ("seed", "interesting", "not_interesting", "artifact", "unsure")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def channel_name(source_file: str, channel: int, n_channels: int) -> str:
    if source_file.startswith(("M2_aug", "M4_aug")) and n_channels == 16 and channel < 16:
        return M2_STYLE_NAMES[channel]
    return f"CH{channel + 1}"


@functools.lru_cache(maxsize=32)
def _mmap(npy_path: str, mtime_ns: int):
    return np.load(npy_path, mmap_mode="r")


def load_channel(npy_path: str):
    st = os.stat(npy_path)
    return _mmap(npy_path, st.st_mtime_ns)


def recordings(conn) -> list[dict]:
    rows = [dict(x) for x in q.list_recordings(conn)]
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        by_file.setdefault(row["source_file"], []).append(row)
    out = []
    for sf, chans in by_file.items():
        chans.sort(key=lambda c: c["channel"])
        fs = float(chans[0]["fs"]); n = int(chans[0]["n_samples"])
        out.append({
            "source_file": sf, "fs": fs, "n_samples": n, "duration_h": n / fs / 3600.0,
            "n_channels": len(chans), "held_out": sf == HELD_OUT_FILE,
            "channels": [{"id": c["id"], "channel": c["channel"],
                          "name": channel_name(sf, c["channel"], len(chans)),
                          "npy_exists": os.path.isfile(c["npy_path"])} for c in chans],
        })
    order = {"M2_aug_concat_fs1.mat": 0, "M2_aug_concat_fs2.mat": 1, "M2_concat_fs1.mat": 2}
    out.sort(key=lambda d: (order.get(d["source_file"], 9), d["source_file"]))
    return out


def recording_row(conn, recording_id: int) -> dict | None:
    row = q.get_recording_by_id(conn, recording_id)
    if row is None:
        return None
    d = dict(row)
    n_ch = conn.execute("SELECT COUNT(*) FROM recordings WHERE source_file = ?", (d["source_file"],)).fetchone()[0]
    d["name"] = channel_name(d["source_file"], d["channel"], n_ch)
    d["held_out"] = d["source_file"] == HELD_OUT_FILE
    d["duration_s"] = d["n_samples"] / d["fs"]
    return d


def _overlap_flags(a_start, a_end, b_start, b_end):
    """For each interval in A, True if it overlaps any interval in B (B sorted by start)."""
    if len(b_start) == 0 or len(a_start) == 0:
        return np.zeros(len(a_start), dtype=bool)
    order = np.argsort(b_start)
    bs = b_start[order]; be = b_end[order]
    # cumulative max of ends lets us test "any earlier-or-equal-start interval reaches past a_start"
    be_cummax = np.maximum.accumulate(be)
    idx = np.searchsorted(bs, a_end, side="left")   # b intervals starting before a_end
    flags = np.zeros(len(a_start), dtype=bool)
    has = idx > 0
    flags[has] = be_cummax[idx[has] - 1] > a_start[has]
    return flags


def coverage(conn, source_file: str, bins: int = 57, verdicts: tuple | None = None) -> dict:
    """channels × bins counts of annotation spans, detection spans, both and
    'disagree' (annotations with no overlapping detection + detections with
    no overlapping annotation), plus per-channel summaries."""
    t0 = time.perf_counter()
    recs = [dict(x) for x in q.list_recordings(conn, source_file)]
    if not recs:
        raise KeyError(source_file)
    n = int(recs[0]["n_samples"]); fs = float(recs[0]["fs"])
    edges = np.linspace(0, n, bins + 1)
    rows = []
    verdict_counts = {v: 0 for v in VERDICTS}
    for rec in recs:
        rid = rec["id"]
        ann = conn.execute("SELECT start_idx, end_idx, verdict FROM annotations WHERE recording_id = ? AND deleted_at IS NULL",
                           (rid,)).fetchall()
        det = conn.execute("SELECT d.start_idx, d.end_idx FROM detections d JOIN runs r ON r.id = d.run_id WHERE r.recording_id = ?",
                           (rid,)).fetchall()
        for a in ann:
            if a["verdict"] in verdict_counts:
                verdict_counts[a["verdict"]] += 1
        if verdicts:
            ann = [a for a in ann if a["verdict"] in verdicts]
        a_s = np.array([a["start_idx"] for a in ann], dtype=np.int64); a_e = np.array([a["end_idx"] for a in ann], dtype=np.int64)
        d_s = np.array([d["start_idx"] for d in det], dtype=np.int64); d_e = np.array([d["end_idx"] for d in det], dtype=np.int64)
        a_mid = (a_s + a_e) / 2 if len(a_s) else a_s
        d_mid = (d_s + d_e) / 2 if len(d_s) else d_s
        ah = np.histogram(a_mid, bins=edges)[0] if len(a_s) else np.zeros(bins, int)
        dh = np.histogram(d_mid, bins=edges)[0] if len(d_s) else np.zeros(bins, int)
        a_flag = _overlap_flags(a_s, a_e, d_s, d_e)
        d_flag = _overlap_flags(d_s, d_e, a_s, a_e)
        dis_mid = np.concatenate([a_mid[~a_flag], d_mid[~d_flag]]) if (len(a_s) or len(d_s)) else np.array([])
        xh = np.histogram(dis_mid, bins=edges)[0] if len(dis_mid) else np.zeros(bins, int)
        reviewed = q.reviewed_fraction(conn, rid)
        try:
            reviewed_pct = float(reviewed) * (100.0 if float(reviewed) <= 1.0 else 1.0)
        except Exception:
            reviewed_pct = None
        rows.append({
            "id": rid, "channel": rec["channel"], "name": channel_name(source_file, rec["channel"], len(recs)),
            "annotations": ah.tolist(), "detections": dh.tolist(), "both": (ah + dh).tolist(), "disagree": xh.tolist(),
            "counts": {"annotations": int(len(a_s)), "detections": int(len(d_s)), "disagree": int((~a_flag).sum() + (~d_flag).sum()),
                       "reviewed_pct": reviewed_pct},
        })
    n_runs = conn.execute("SELECT COUNT(DISTINCT r.id) FROM runs r JOIN detections d ON d.run_id = r.id JOIN recordings x ON x.id = r.recording_id WHERE x.source_file = ?", (source_file,)).fetchone()[0]
    return {"source_file": source_file, "fs": fs, "n_samples": n, "duration_h": n / fs / 3600.0,
            "bins": bins, "bin_h": n / fs / 3600.0 / bins, "bin_edges_h": (edges / fs / 3600.0).tolist(),
            "rows": rows, "verdict_counts": verdict_counts, "n_detection_runs": int(n_runs),
            "held_out": source_file == HELD_OUT_FILE, "compute_ms": (time.perf_counter() - t0) * 1e3}


def _finite(v):
    """JSON has no inf/NaN; detection scores in the real DB include inf."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def spans(conn, recording_id: int, t0_s: float, t1_s: float, fs: float, cap: int = 5000) -> dict:
    s0 = int(np.floor(t0_s * fs)); s1 = int(np.ceil(t1_s * fs))
    ann = conn.execute(
        "SELECT id, start_idx, end_idx, verdict, tag, note, source FROM annotations WHERE recording_id = ? AND deleted_at IS NULL "
        "AND end_idx > ? AND start_idx < ? ORDER BY start_idx LIMIT ?", (recording_id, s0, s1, cap + 1)).fetchall()
    det = conn.execute(
        "SELECT d.id, d.start_idx, d.end_idx, d.score, d.run_id FROM detections d JOIN runs r ON r.id = d.run_id "
        "WHERE r.recording_id = ? AND d.end_idx > ? AND d.start_idx < ? ORDER BY d.start_idx LIMIT ?", (recording_id, s0, s1, cap + 1)).fetchall()
    return {
        "recording_id": recording_id, "t0_s": t0_s, "t1_s": t1_s,
        "annotations": [{"id": a["id"], "start_s": a["start_idx"] / fs, "end_s": a["end_idx"] / fs, "verdict": a["verdict"],
                         "tag": a["tag"], "note": a["note"], "source": a["source"]} for a in ann[:cap]],
        "detections": [{"id": d["id"], "start_s": d["start_idx"] / fs, "end_s": d["end_idx"] / fs,
                        "score": _finite(d["score"]), "run_id": d["run_id"]} for d in det[:cap]],
        "annotations_capped": len(ann) > cap, "detections_capped": len(det) > cap,
    }


def ribbons(conn, recording_id: int, fs: float, n: int, buckets: int = 300) -> dict:
    """Overview ribbons for Explore › Signal: per-bucket dominant annotation
    verdict (coverage) and detection count (density)."""
    edges = np.linspace(0, n, buckets + 1)
    ann = conn.execute("SELECT start_idx, end_idx, verdict FROM annotations WHERE recording_id = ? AND deleted_at IS NULL", (recording_id,)).fetchall()
    det = conn.execute("SELECT d.start_idx FROM detections d JOIN runs r ON r.id = d.run_id WHERE r.recording_id = ?", (recording_id,)).fetchall()
    cov = [None] * buckets
    counts = {v: np.zeros(buckets, int) for v in VERDICTS}
    for a in ann:
        b0 = int(np.searchsorted(edges, a["start_idx"], side="right") - 1)
        b1 = int(np.searchsorted(edges, max(a["start_idx"], a["end_idx"] - 1), side="right") - 1)
        v = a["verdict"] if a["verdict"] in counts else "unsure"
        counts[v][max(0, b0):min(buckets, b1 + 1)] += 1
    prio = ["artifact", "seed", "interesting", "unsure", "not_interesting"]
    for b in range(buckets):
        best = None
        for v in prio:
            if counts[v][b] > 0:
                best = v; break
        cov[b] = best
    dh = np.histogram([d["start_idx"] for d in det], bins=edges)[0] if det else np.zeros(buckets, int)
    return {"buckets": buckets, "bucket_s": n / fs / buckets, "coverage": cov, "detection_density": dh.tolist()}


def channel_summary(conn, recording_id: int) -> dict:
    a = conn.execute("SELECT COUNT(*) FROM annotations WHERE recording_id = ? AND deleted_at IS NULL", (recording_id,)).fetchone()[0]
    d = conn.execute("SELECT COUNT(*) FROM detections d JOIN runs r ON r.id = d.run_id WHERE r.recording_id = ?", (recording_id,)).fetchone()[0]
    runs = conn.execute("SELECT COUNT(DISTINCT r.id) FROM runs r JOIN detections d ON d.run_id = r.id WHERE r.recording_id = ?", (recording_id,)).fetchone()[0]
    return {"annotations": int(a), "detections": int(d), "detection_runs": int(runs)}


def window(conn, rec: dict, t0_s: float, t1_s: float, px: int) -> dict:
    x = load_channel(rec["npy_path"])
    fs = float(rec["fs"])
    i0 = int(max(0, np.floor(t0_s * fs))); i1 = int(min(len(x), np.ceil(t1_s * fs)))
    tt = time.perf_counter()
    env = envelope(x, fs, i0, i1, px)
    ms = (time.perf_counter() - tt) * 1e3
    return {"recording_id": rec["id"], "fs": fs, "n_samples": int(len(x)), "t0_s": i0 / fs, "t1_s": i1 / fs,
            "envelope": env, "decimate_ms": ms}


@functools.lru_cache(maxsize=64)
def _yrange(npy_path: str, mtime_ns: int):
    x = _mmap(npy_path, mtime_ns)
    return float(np.nanmin(x)), float(np.nanmax(x))


def y_range(rec: dict) -> list:
    st = os.stat(rec["npy_path"])
    lo, hi = _yrange(rec["npy_path"], st.st_mtime_ns)
    return [lo, hi]
