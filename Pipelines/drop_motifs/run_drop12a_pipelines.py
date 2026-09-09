"""
run_drop12a_pipelines.py
=========================
Task 3. The `_01_pipeline.png` figures for the corpora that need no new
detection: the fifteen oyster spans and three Reishi sequences.

    python Pipelines/drop_motifs/run_drop12a_pipelines.py
    python Pipelines/drop_motifs/run_drop12a_pipelines.py --only oyster
    python Pipelines/drop_motifs/run_drop12a_pipelines.py --only reishi

The Lion's mane third of Task 3 is not here, because it needs Task 1's
detections and Task 1 is blocked on the scale probe's verdict. See
`PROVENANCE.md`.

Reads `Plots/drop_motifs10/motifs/` and `Plots/drop_motifs11/sequences.csv`
and writes only under `Plots/drop_motifs12a/pipelines/`. Nothing earlier is
modified and the database is not opened for writing.

Redrawn, not re-detected
------------------------
The work order is explicit that the oyster figures come "from the detections
already in the store, redrawn, not re-detected". Steps 0-3b of the figure
have to be recomputed - the store carries measurements, not staging, so
there is no other way to draw a dSAX strip - but STEP 4 shades the SHIPPED
STORE ROWS, via `casestudy9.plot_pipeline(store_rows=...)`. Without that the
panel shades a fresh detection which may disagree with the store it is
supposed to be illustrating, and the disagreement would be invisible.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path as _Path

import numpy as np

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import (corpora10, lionsmane12,  # noqa: E402
                                   passes9, pipelines12, sequences11,
                                   spans5, store11, tree10)
from Working.Detection.drop_motifs import motifs5  # noqa: E402

OUT = _Path("Plots") / "drop_motifs12a" / "pipelines"
STORE = os.path.join("Plots", "drop_motifs10", "motifs")
SEQUENCES = os.path.join("Plots", "drop_motifs11", "sequences.csv")
DB = os.path.join("DATA", "db", "annotations.sqlite")


def open_db(path=DB):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def family_map(rows, snippets):
    """`{event_id: family}` from the POOLED tree over the whole store.

    The same map `run_drop10_casestudies` builds, so a pipeline plot's fill
    colours mean what they mean on `Plots/drop_motifs10/ALL_dendrogram.png`
    - which is what the STEP 4 title claims they mean. Built once and shared
    by every figure; over 3511 motifs it costs about two seconds.
    """
    tree = tree10.build(rows, snippets)
    if tree is None:
        return {}
    return {r["event_id"]: int(label)
            for r, label in zip(tree["rows"], tree["coarse"])}


def do_oyster(conn, rows, out_dir, family_of, log=print):
    """One pipeline plot per catalogue span, from the store's own rows."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for catalogue_id, spec in corpora10.catalogue_spans(
            corpora10.OYSTER_SPAN_IDS):
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?",
                           (spec["recording"],)).fetchone()
        if rec is None:
            log(f"  ! no recording {spec['recording']} for id{catalogue_id}")
            continue
        fs = float(rec["fs"])
        channel = np.asarray(np.load(rec["npy_path"], mmap_mode="r"),
                             dtype=float)
        # Absolute bounds against the WHOLE channel, so the replay and the
        # store share one frame. See `pipelines12.replay_for`.
        span_x, offset = spans5.load_span(rec, spec["span"])
        start, stop = int(offset), int(offset + len(span_x))

        kept = pipelines12.rows_in(rows, start, stop,
                                   corpus=corpora10.CORPUS_OYSTER,
                                   catalogue_id=catalogue_id)
        if not kept:
            log(f"  ! id{catalogue_id:03d} holds no store rows")
            continue

        stem = f"id{catalogue_id:03d}"
        started = time.time()
        replay = pipelines12.replay_for(
            channel, fs, start, stop, catalogue_id=catalogue_id,
            recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=int(rec["channel"]), span_key=stem,
            span_label=f"catalogue ID {catalogue_id}")
        path, info = pipelines12.draw(
            replay, channel, out_dir / f"{stem}_01_pipeline.png",
            title=f"drop_motifs12a — oyster, catalogue ID {catalogue_id} "
                  f"({spec.get('expect')}) — {len(kept)} events from "
                  f"Plots/drop_motifs10/motifs/",
            store_rows=kept, family_of=family_of)
        index[stem] = {
            "path": path, "catalogue_id": catalogue_id, "fs": fs,
            "recording_id": int(rec["id"]), "channel": int(rec["channel"]),
            "window_start_idx": start, "window_stop_idx": stop,
            "n_store_rows": len(kept),
            "annotated_n": spec.get("annotated_n"),
            "expected_morphology": spec.get("expect"),
            "seconds": round(time.time() - started, 1),
            "selected_by": "sample range (never window_index)",
            **{k: v for k, v in info.items() if k != "letters"},
        }
        log(f"  -> {path}  ({len(kept)} events, "
            f"{index[stem]['seconds']}s)")
    return index


def do_reishi(conn, rows, sequences, out_dir, family_of, n=3, log=print):
    """Three Reishi sequences, seeded, preferring what drop_motifs11 drew."""
    max_window_s = pipelines12.MAX_WINDOW_MULTIPLE * passes9.DEFAULT_WINDOW_S
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    chosen = pipelines12.choose_sequences(sequences, "reishi", n=n)
    log(f"  chosen (seed {pipelines12.SEED}): "
        + ", ".join(s["sequence_key"] for s in chosen))

    for sequence in chosen:
        channel_no = int(sequence["channel"])
        rec = conn.execute(
            "SELECT * FROM recordings WHERE source_file = ? AND channel = ?",
            (corpora10.FIG2A_SOURCE, channel_no)).fetchone()
        if rec is None:
            log(f"  ! no recording for CH{channel_no}")
            continue
        fs = float(rec["fs"])
        channel = np.asarray(np.load(rec["npy_path"], mmap_mode="r"),
                             dtype=float)
        start, stop = pipelines12.window_for(sequence, fs,
                                             n_samples=len(channel),
                                             max_window_s=max_window_s)
        catalogue_id = int(sequence["catalogue_id"])
        kept = pipelines12.rows_in(rows, start, stop,
                                   corpus=corpora10.CORPUS_REISHI_10HZ,
                                   catalogue_id=catalogue_id)
        if not kept:
            log(f"  ! {sequence['sequence_key']} holds no store rows")
            continue

        stem = pipelines12.sequence_stem(sequence)
        started = time.time()
        replay = pipelines12.replay_for(
            channel, fs, start, stop, catalogue_id=catalogue_id,
            recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=channel_no, span_key=f"id{catalogue_id:03d}",
            span_label=f"{corpora10.FIG2A_SOURCE} CH{channel_no}")
        path, info = pipelines12.draw(
            replay, channel, out_dir / f"{stem}_01_pipeline.png",
            title=f"drop_motifs12a — reishi, sequence {stem} "
                  f"({sequence['n']} events in the run) — {len(kept)} events "
                  "from Plots/drop_motifs10/motifs/",
            store_rows=kept, family_of=family_of)
        entry = pipelines12.manifest_entry(sequence, start, stop, fs, kept)
        entry.update(path=path, seconds=round(time.time() - started, 1),
                     **{k: v for k, v in info.items() if k != "letters"})
        index[stem] = entry
        log(f"  -> {path}  ({len(kept)} events, {entry['seconds']}s)")
    return index


def do_lionsmane(rows, out_dir, family_of, store_dir, n=3,
                 detection_window_s=None, log=print):
    """Three Lion's mane sequences, from the store this run detected.

    The Reishi and Oyster sequences come out of `drop_motifs11`'s
    `sequences.csv`, which was written against a store that has no Lion's
    mane in it. So the qualifying runs are found here, by the same
    `sequences11` rules and thresholds, against this run's own store - which
    is what "drawn the same way from the sequences found in Task 1" asks
    for. No sequence is preferred, because none of them appears in any
    earlier figure yet.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    loaded, _snippets, _manifest = store11.load(store_dir)
    mine = [r for r in loaded if r.get("species") == lionsmane12.SPECIES]
    if not mine:
        log(f"  ! {store_dir} holds no {lionsmane12.SPECIES} rows")
        return index
    runs, run_summary = sequences11.extract(mine)
    log(f"  {len(runs)} qualifying sequences from {len(mine)} events")
    chosen = pipelines12.choose_sequences(runs, lionsmane12.SPECIES, n=n)
    if not chosen:
        log("  ! no qualifying sequence to draw")
        return index
    log(f"  chosen (seed {pipelines12.SEED}): "
        + ", ".join(s["sequence_key"] for s in chosen))

    max_window_s = (pipelines12.MAX_WINDOW_MULTIPLE * detection_window_s
                    if detection_window_s else None)
    onsets_by_key = {r["sequence_key"]: [m["onset_s"] for m in r["rows"]]
                     for r in runs}
    for sequence in chosen:
        channel_no = int(sequence["channel"])
        channel = lionsmane12.load_channel(channel_no)
        start, stop = pipelines12.window_for(
            sequence, lionsmane12.FS, n_samples=len(channel),
            max_window_s=max_window_s,
            onsets_s=onsets_by_key.get(sequence["sequence_key"]))
        catalogue_id = int(sequence["catalogue_id"])
        kept = pipelines12.rows_in(rows, start, stop,
                                   corpus=lionsmane12.CORPUS,
                                   catalogue_id=catalogue_id)
        if not kept:
            log(f"  ! {sequence['sequence_key']} holds no store rows")
            continue

        stem = pipelines12.sequence_stem(sequence)
        started = time.time()
        try:
            replay = pipelines12.replay_for(
                channel, lionsmane12.FS, start, stop,
                catalogue_id=catalogue_id,
                recording_id=lionsmane12.RECORDING_ID,
                source_file=lionsmane12.SOURCE_FILE, channel=channel_no,
                span_key=f"id{catalogue_id:03d}",
                span_label=f"{lionsmane12.STEM} CH{channel_no}")
        except Exception as exc:                              # noqa: BLE001
            # One sequence whose replay cannot derive a scale must not cost
            # the other two their figures. The refusal is reported, not
            # swallowed - the same rule `passes9` applies per window.
            log(f"  ! {stem}: replay failed, {exc!r}")
            index[stem] = {"sequence_key": stem, "drawn": False,
                           "error": repr(exc),
                           "window_start_idx": int(start),
                           "window_stop_idx": int(stop)}
            continue
        path, info = pipelines12.draw(
            replay, channel, out_dir / f"{stem}_01_pipeline.png",
            title=f"drop_motifs12a — Lion's mane, sequence {stem} "
                  f"({sequence['n']} events in the run) — {len(kept)} events "
                  f"from {store_dir}",
            store_rows=kept, family_of=family_of)
        entry = pipelines12.manifest_entry(sequence, start, stop,
                                           lionsmane12.FS, kept)
        entry.update(path=path, seconds=round(time.time() - started, 1),
                     **{k: v for k, v in info.items() if k != "letters"})
        index[stem] = entry
        log(f"  -> {path}  ({len(kept)} events, {entry['seconds']}s)")
    index["_sequences"] = run_summary
    return index


def _lionsmane_window_s(path=os.path.join("Plots", "drop_motifs12a",
                                          "detect_summary.json")):
    """The window the Lion's mane detection actually used, per region.

    Read from the detection's own summary rather than restated, so a figure
    can never be framed against a window the store was not built with.
    """
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        summary = json.load(handle)
    windows = [float(v["window_s"]) for v in summary.values()
               if isinstance(v, dict) and v.get("window_s")]
    return max(windows) if windows else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=STORE)
    parser.add_argument("--sequences", default=SEQUENCES)
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--db", default=DB)
    parser.add_argument("--only", nargs="*",
                        default=["oyster", "reishi", "lionsmane"])
    parser.add_argument("--lionsmane-store",
                        default=os.path.join("Plots", "drop_motifs12a",
                                             "motifs"))
    parser.add_argument("--n-sequences", type=int, default=3)
    args = parser.parse_args(argv)

    out = _Path(args.out_dir)
    conn = open_db(args.db)
    rows, snippets, _manifest = motifs5.load_store(args.store)
    print(f"store {args.store}: {len(rows)} rows")
    family_of = family_map(rows, snippets)
    print(f"pooled families: {len(set(family_of.values()))} at the coarse cut")

    index = {"store": args.store, "seed": pipelines12.SEED,
             "preferred": list(pipelines12.PREFERRED),
             "rows_from_store": True,
             "n_coarse_families": len(set(family_of.values()))}
    if "oyster" in args.only:
        print("\n=== oyster: the 15 catalogue spans ===")
        index["oyster"] = do_oyster(conn, rows, out / "oyster", family_of)
    if "reishi" in args.only:
        print("\n=== reishi: 3 sequences ===")
        sequences = pipelines12.read_sequences(args.sequences)
        index["reishi"] = do_reishi(conn, rows, sequences, out / "reishi",
                                    family_of, n=args.n_sequences)

    if "lionsmane" in args.only:
        print("\n=== Lion's mane: 3 sequences ===")
        store = args.lionsmane_store
        if not os.path.exists(os.path.join(store, "motifs.csv")):
            partial = store + "_PARTIAL"
            store = partial if os.path.exists(
                os.path.join(partial, "motifs.csv")) else store
        if not os.path.exists(os.path.join(store, "motifs.csv")):
            print(f"  ! {store} does not exist — Lion's mane not detected yet")
            index["lionsmane"] = {}
        else:
            lm_rows, lm_snippets, _m = motifs5.load_store(store)
            lm_families = family_map(lm_rows, lm_snippets)
            index["lionsmane"] = do_lionsmane(
                lm_rows, out / "lionsmane", lm_families, store,
                n=args.n_sequences,
                detection_window_s=_lionsmane_window_s())
            index["lionsmane_store"] = store

    out.mkdir(parents=True, exist_ok=True)
    path = out / "pipelines_index.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=1, default=str)
    print(f"\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
