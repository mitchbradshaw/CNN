"""
run_drop10_detect.py
=====================
Task 2: detect over all four corpora with ONE parameterisation, and write
the pooled store plus the per-corpus sub-stores.

    python Pipelines/drop_motifs/run_drop10_detect.py
    python Pipelines/drop_motifs/run_drop10_detect.py --corpora oyster sp385
    python Pipelines/drop_motifs/run_drop10_detect.py --floor-rule global_0.1mV

Writes `Plots/drop_motifs10/` and touches no earlier plot directory and no
earlier store. Nothing here reaches `DATA/db/annotations.sqlite`.

Two stores come out of one detection run - the derived per-corpus floor
and the global 0.1 mV floor - so the measurement decision in `floor10` is
comparable rather than baked in. The floor is the only thing that differs
between them; the detections are identical.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import corpora10, detect10, floor10  # noqa: E402

DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
OUT_DIR = os.path.join("Plots", "drop_motifs10")


def open_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def run_corpus(conn, corpus, floor_rule, log=print):
    if corpus == corpora10.CORPUS_OYSTER:
        return detect10.run_catalogue(
            conn, corpora10.OYSTER_SPAN_IDS, corpus=corpus,
            species=corpora10.SPECIES_OYSTER, floor_rule=floor_rule, log=log)
    if corpus == corpora10.CORPUS_385:
        return detect10.run_catalogue(
            conn, corpora10.SP385_SPAN_IDS, corpus=corpus,
            species=corpora10.SPECIES_385, floor_rule=floor_rule, log=log)
    if corpus == corpora10.CORPUS_REISHI_10HZ:
        return detect10.run_fig2a(conn, decimate=False,
                                  floor_rule=floor_rule, log=log)
    if corpus == corpora10.CORPUS_REISHI_1HZ:
        return detect10.run_fig2a(conn, decimate=True,
                                  floor_rule=floor_rule, log=log)
    raise SystemExit(f"unknown corpus {corpus!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=OUT_DIR)
    parser.add_argument("--corpora", nargs="*", default=list(corpora10.CORPORA))
    parser.add_argument("--floor-rule", default=None,
                        choices=[floor10.RULE_DERIVED, floor10.RULE_GLOBAL],
                        help="run ONE floor rule instead of both")
    args = parser.parse_args(argv)

    rules = ([args.floor_rule] if args.floor_rule
             else [floor10.RULE_DERIVED, floor10.RULE_GLOBAL])
    conn = open_db(args.db)
    out = _Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    index = {"floor_rules": {}, "parameterisation": {
        "max_passes": detect10.MAX_PASSES, "window_s": detect10.WINDOW_S,
        "overlap": detect10.OVERLAP, "passes": detect10.PASSES,
        "floor_sigmas": floor10.FLOOR_SIGMAS}}

    for rule in rules:
        tag = "" if rule == floor10.RULE_DERIVED else "_globalfloor"
        print(f"\n=== floor rule: {rule} ===", flush=True)
        pooled_rows, pooled_arrays, all_summaries = [], {}, []

        for corpus in args.corpora:
            print(f"[{corpus}]", flush=True)
            started = time.time()
            rows, arrays, summaries = run_corpus(conn, corpus, rule)
            rows, arrays = detect10.rekey_for_corpus(rows, arrays, corpus)

            sub = out / "by_corpus" / corpus / f"motifs{tag}"
            detect10.write(sub, rows, arrays,
                           extra={"corpus": corpus,
                                  "species": corpora10.species_of(corpus),
                                  "framing": corpora10.framing_of(corpus),
                                  "floor_rule": rule})
            print(f"  -> {sub}  ({len(rows)} motifs, "
                  f"{round(time.time() - started, 1)}s)", flush=True)

            pooled_rows.extend(rows)
            pooled_arrays.update(arrays)
            all_summaries.extend(summaries)

        pooled = out / f"motifs{tag}"
        detect10.write(pooled, pooled_rows, pooled_arrays,
                       extra={"corpora": list(args.corpora),
                              "floor_rule": rule, "pooled": True})
        print(f"\npooled -> {pooled}  ({len(pooled_rows)} motifs)", flush=True)

        by_corpus = {}
        for row in pooled_rows:
            by_corpus[row["corpus"]] = by_corpus.get(row["corpus"], 0) + 1
        index["floor_rules"][rule] = {
            "store": str(pooled), "n_motifs": len(pooled_rows),
            "by_corpus": by_corpus, "spans": all_summaries}

    with open(out / "detect_summary.json", "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=1, default=str)
    print(f"\n-> {out / 'detect_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
