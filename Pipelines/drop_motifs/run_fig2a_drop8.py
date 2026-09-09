"""
run_fig2a_drop8.py
===================
The drop_motifs8 run over the five Fig2A channels, instead of over the
sixteen operator-chosen catalogue spans.

    python Pipelines/drop_motifs/run_fig2a_drop8.py
    python Pipelines/drop_motifs/run_fig2a_drop8.py --channels 0 3
    python Pipelines/drop_motifs/run_fig2a_drop8.py --no-figures

Detection, merge, grouping and every figure are `run_drop8_report`'s,
imported rather than copied: this file only changes WHICH signal goes in
and WHERE the output lands. If the eight run's behaviour changes, this
changes with it.

What is different about this input
----------------------------------
THERE IS NO CATALOGUE ROW. `spans5.SPANS5` maps an operator catalogue ID
to a recording, a span and a human's prose. Fig2A has none of that: no
`annotated_n` to check against, no `expect` morphology to disagree with,
no annotation id. Those fields are carried as None, and the report prints
them blank rather than as a passed check. **Nothing here is validated
against a human count.** Every span in the eight run has at least the
operator's note; these five have nothing.

SYNTHETIC CATALOGUE IDS. The figure set and the store key are built from
`id{catalogue_id:03d}`, so the channels need integer ids that cannot
collide with the real catalogue's 1-385. They get `900 + channel`, so
CH0 -> id900 ... CH4 -> id904. The id is a filename, not a claim that
these are catalogue entries.

IT IS 10 Hz, NOT 1 Hz. Every recording the eight run was built and
validated on is 1 Hz. This is the first that is not, which makes it the
first input where `passes8`'s seconds-vs-samples dedup fix actually does
something rather than coinciding. The detector derives its own scale from
the signal, so no parameter is retuned here - but no count in this run has
ever been checked by a human, at this sample rate or any other.

WHOLE CHANNEL, NO SPAN. `span=None` reads the channel entire (1200 s,
12001 samples), so `span_offset` is 0 and the report says "whole
recording" where the eight run names an hour range.

Writes `Plots/drop_motifs8_fig2a/` and touches neither `Plots/drop_motifs8/`
nor the catalogue store.
"""

import argparse
import json
import os
import sys
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Pipelines.drop_motifs import passes7
from Pipelines.drop_motifs.run_drop8_report import open_db, run_span
from Working.Detection.drop_motifs import motifs5

DEFAULT_DB = os.path.join("DATA", "db", "annotations.sqlite")
DEFAULT_PLOT_DIR = os.path.join("Plots", "drop_motifs8_fig2a")

SOURCE_FILE = "Fig2A_dt0p1.csv"
CATALOGUE_ID_BASE = 900
STORE_KIND = "drop_motifs8_fig2a"


def build_spans(conn, source_file=SOURCE_FILE):
    """`{catalogue_id: spec}` for every channel of `source_file`.

    Shaped exactly like `spans5.SPANS5` so `run_span` needs no changes.
    The check fields are None on purpose - see the module docstring.
    """
    rows = conn.execute(
        "SELECT id, channel FROM recordings WHERE source_file = ? "
        "ORDER BY channel", (source_file,)).fetchall()
    if not rows:
        raise SystemExit(
            f"no recordings for {source_file!r}. Materialise it first with "
            "Pipelines/materialize_channels.")
    spans = {}
    for row in rows:
        channel = int(row["channel"])
        spans[CATALOGUE_ID_BASE + channel] = dict(
            annotation=None,
            recording=int(row["id"]),
            span=None,
            annotated_n=None,
            expect=None,
            channel=channel,
            note=f"{source_file} CH{channel} - whole channel, no catalogue "
                 "entry and no human count.")
    return spans


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", nargs="*", type=int, default=None,
                        help="channel numbers, not catalogue ids (default: all)")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--plot-dir", default=DEFAULT_PLOT_DIR)
    parser.add_argument("--source-file", default=SOURCE_FILE)
    parser.add_argument("--max-passes", type=int, default=3)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-fine", action="store_true")
    parser.add_argument("--no-sensitive", action="store_true")
    parser.add_argument("--no-inverted", action="store_true")
    parser.add_argument("--no-micro", action="store_true")
    args = parser.parse_args(argv)

    conn = open_db(args.db)
    spans = build_spans(conn, args.source_file)

    if args.channels is None:
        wanted = sorted(spans)
    else:
        wanted = [CATALOGUE_ID_BASE + c for c in args.channels]
        unknown = [c for c, w in zip(args.channels, wanted) if w not in spans]
        if unknown:
            raise SystemExit(f"unknown channels: {unknown}")

    out_dir = _Path(args.plot_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries, store_rows, store_arrays, span_signal = [], [], {}, {}
    for catalogue_id in wanted:
        spec = spans[catalogue_id]
        print(f"[CH{spec['channel']} = id{catalogue_id}] {args.source_file}",
              flush=True)
        summary, rows, arrays, x = run_span(conn, catalogue_id, spec, args)
        summary["channel"] = spec["channel"]
        summary["source_file"] = args.source_file

        kept = summary["per_pass_kept"]
        print(f"      n={summary['n_motifs']:<4d} pure={summary['n_pure']:<4d} "
              f"base={kept.get('base', 0):<3d} fine={kept.get('fine', 0):<3d} "
              f"sens={kept.get('sens', 0):<3d} micro={kept.get('micro', 0):<4d} "
              f"inv={kept.get('inv', 0):<3d}  "
              f"bands={summary['scale_band_labels']}", flush=True)

        store_rows.extend(rows)
        store_arrays.update(arrays)
        span_signal[catalogue_id] = x
        summaries.append(summary)

    store_dir = out_dir / "motifs"
    motifs5.write_store(str(store_dir), store_rows, store_arrays,
                        manifest_extra={
                            "kind": STORE_KIND,
                            "detector": "detect5 + passes8 (recovery-edge "
                                        "dedup, size split)",
                            "source_file": args.source_file,
                            "spans_run": list(wanted),
                            "catalogue_id_base": CATALOGUE_ID_BASE,
                            "passes": list(passes7.PASS_ORDER),
                            "key_format": "id{cat:03d}_r{rec}_{pass}_{onset}",
                            "validated_against_human": False,
                        })
    print(f"\nmotif library -> {store_dir}  ({len(store_rows)} motifs, "
          f"{sum(int(r['is_pure']) for r in store_rows)} pure)")

    if not args.no_figures:
        from Pipelines.drop_motifs.figuresets8 import draw_all
        index = draw_all(store_dir, out_dir, summaries, wanted, span_signal)
        for summary in summaries:
            entry = index.get(str(summary["catalogue_id"]))
            if entry:
                summary["figure_set"] = entry
        if index.get("ALL"):
            summaries.append({"catalogue_id": "ALL", "pooled": index["ALL"]})

    (out_dir / "run_summary.json").write_text(
        json.dumps(summaries, indent=2, default=float), encoding="utf-8")

    from Pipelines.drop_motifs.report7 import write_report
    print(f"\nreport  -> {write_report(summaries, out_dir)}")
    print(f"figures -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
