"""
import_10min_labels.py
========================
Import the ~11,000 manually-sorted 10-minute windows (from
`Working/Catalogue/labelling/interest_select.py`) into the annotation
database as `annotations` + matching `reviewed_spans`.

Source of truth
----------------
The three label-index files:

    DATA/derived/windows/10min_fs1.0/labels/10min_interesting_fs_1.00.json
    DATA/derived/windows/10min_fs1.0/labels/10min_notinteresting_fs_1.00.json
    DATA/derived/windows/10min_fs1.0/labels/10min_flag_fs_1.00.json

Each holds `{"starts": [...]}` — window start indices in **concatenated
global** coordinates. These indices were generated against
`M2_aug_concat_fs1.mat` (41,529,600 samples, fs=1) — *not*
`M2_concat_fs1.mat`, which is a different, shorter recording. This was
confirmed against `interest_select.py`'s own docstring usage example and
against `10min_session_fs_1.00.json`'s total candidate-window count, which
only matches a 41,529,600-sample source vector.

Verdict mapping
----------------
    interesting     -> 'interesting'
    notinteresting   -> 'not_interesting'
    flag             -> 'artifact'   (marked "too structured/straight" at the
                                       time — a suspected equipment fault, a
                                       distinct class, not a form of "not
                                       interesting")

Reviewed spans
---------------
Every imported window was individually judged, so each also gets a
`reviewed_spans` row — but only for that window's span. The signal *between*
sampled windows was never examined; absence of a label there means "not
examined", not "not interesting".

Boundary-straddling windows
-----------------------------
A window whose local span crosses a channel boundary
(`local + window_length > L`) splices two unrelated channels together and
may have looked structured purely because of the splice. Those are written
to `quarantined_boundary_straddle.json` next to the source labels instead of
being imported as annotations.

Idempotent: re-running skips any (recording_id, start_idx, end_idx, source)
already present.

Usage
-----
    python Pipelines/import_labels/import_10min_labels.py
    python Pipelines/import_labels/import_10min_labels.py --dry-run
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import argparse
import json
import os

from Working.Preprocessing.manage_data.load_data import window_root
from Working.database.schema import init_db
from Working.database.queries import (
    SOURCE_IMPORTED_10MIN,
    annotation_exists,
    global_to_local,
    insert_annotation,
    insert_reviewed_span,
    list_recordings,
    reviewed_span_exists,
    window_straddles_boundary,
)

SOURCE_RECORDING = "M2_aug_concat_fs1.mat"

LABEL_FILES = {
    "interesting": "interesting",
    "notinteresting": "not_interesting",
    "flag": "artifact",
}


def _label_dir():
    return os.path.join(window_root(10, 1.0), "labels")


def _load_label_files():
    """Return {json_label: {"starts": [...], "win_samp": int, "window_min": ..., "fs": ...}}."""
    label_dir = _label_dir()
    loaded = {}
    for json_label in LABEL_FILES:
        path = os.path.join(label_dir, f"10min_{json_label}_fs_1.00.json")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Expected label file not found: {path}")
        with open(path) as f:
            loaded[json_label] = json.load(f)
    return loaded


def _channel_length(conn):
    """L for SOURCE_RECORDING, read from the recordings table (requires
    Pipelines/materialize_channels/materialize_channels.py to have run)."""
    rows = list_recordings(conn, source_file=SOURCE_RECORDING)
    if not rows:
        raise RuntimeError(
            f"No recordings found for '{SOURCE_RECORDING}'. Run "
            "Pipelines/materialize_channels/materialize_channels.py first."
        )
    lengths = {r["n_samples"] for r in rows}
    if len(lengths) != 1:
        raise RuntimeError(
            f"Channels of '{SOURCE_RECORDING}' have inconsistent n_samples: {lengths}"
        )
    return next(iter(lengths)), {r["channel"]: r["id"] for r in rows}


def import_10min_labels(dry_run=False, db_path=None):
    conn = init_db(db_path)
    loaded = _load_label_files()

    # ── Cross-check metadata the three files agree on ────────────────────
    win_samps = {d["win_samp"] for d in loaded.values()}
    window_mins = {d["window_min"] for d in loaded.values()}
    fss = {d["fs"] for d in loaded.values()}
    if len(win_samps) != 1 or len(window_mins) != 1 or len(fss) != 1:
        raise RuntimeError(
            f"Label files disagree on window metadata: win_samp={win_samps} "
            f"window_min={window_mins} fs={fss}"
        )
    window_length = win_samps.pop()
    window_min = window_mins.pop()
    fs = fss.pop()
    scale_viewed = f"{window_min:g}min"
    print(f"window_length={window_length} samples  window_min={window_min}  fs={fs}")

    L, recording_by_channel = _channel_length(conn)
    n_channels = len(recording_by_channel)
    total_samples = L * n_channels
    print(f"{SOURCE_RECORDING}: L={L}  n_channels={n_channels}  total={total_samples}")

    quarantined = []
    counts = {"imported": 0, "already_present": 0, "quarantined": 0, "out_of_bounds": 0}

    for json_label, verdict in LABEL_FILES.items():
        starts = loaded[json_label]["starts"]
        for start in starts:
            if start < 0 or start + window_length > total_samples:
                counts["out_of_bounds"] += 1
                print(f"  [OOB] {json_label} start={start} — outside [0, {total_samples})")
                continue

            channel, local = global_to_local(start, L)
            if window_straddles_boundary(local, window_length, L):
                counts["quarantined"] += 1
                quarantined.append({
                    "global_start": start, "channel": channel, "local_start": local,
                    "verdict": verdict, "json_label": json_label,
                })
                continue

            recording_id = recording_by_channel[channel]
            end_local = local + window_length

            if annotation_exists(conn, recording_id, local, end_local, SOURCE_IMPORTED_10MIN):
                counts["already_present"] += 1
                continue

            counts["imported"] += 1
            if dry_run:
                continue

            insert_annotation(
                conn, recording_id, local, end_local, verdict,
                source=SOURCE_IMPORTED_10MIN, scale_viewed=scale_viewed,
                commit=False,
            )
            if not reviewed_span_exists(conn, recording_id, local, end_local, SOURCE_IMPORTED_10MIN):
                insert_reviewed_span(
                    conn, recording_id, local, end_local,
                    source=SOURCE_IMPORTED_10MIN, scale_viewed=scale_viewed,
                    commit=False,
                )
            if counts["imported"] % 500 == 0:
                conn.commit()

    if not dry_run:
        conn.commit()

    if quarantined and not dry_run:
        q_path = os.path.join(_label_dir(), "quarantined_boundary_straddle.json")
        with open(q_path, "w") as f:
            json.dump(quarantined, f, indent=2)
        print(f"Wrote {len(quarantined)} quarantined boundary-straddling windows -> {q_path}")

    print(
        f"\nDone{' (dry run)' if dry_run else ''}. "
        f"imported={counts['imported']}  already_present={counts['already_present']}  "
        f"quarantined={counts['quarantined']}  out_of_bounds={counts['out_of_bounds']}"
    )
    conn.close()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="Report what would be imported without writing to the database.")
    args = parser.parse_args()
    import_10min_labels(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
