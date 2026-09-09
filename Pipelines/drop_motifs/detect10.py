"""
detect10.py
============
One parameterisation, four corpora. Task 2.

The claim the whole run rests on is that no parameter was retuned per
corpus, so this module is the place that would have to break it and does
not. Everything that differs between corpora is either DERIVED from the
signal - the detrend window and the slope threshold, as they already were
- or is a property of the recording rather than a choice: its sampling
rate, and whether the operator handed us a span or a whole channel.

    corpus        framing   passes                      window
    oyster        span      base, fine, sens, micro     the span, whole
    sp385         span      base, fine, sens, micro     the recording, whole
    reishi_10hz   sliding   base, fine, sens, micro     50 s, 50% overlap
    reishi_1hz    sliding   base, fine, sens, micro     50 s, 50% overlap

Four DROP passes everywhere. drop_motifs8 ran a fifth, inverted pass on
the catalogue and drop_motifs9 did not run one on Fig2A; running it on two
corpora and not on the other two would be a per-corpus parameterisation,
so it runs on none. That is a deliberate difference from drop_motifs8 and
it is attributed as such in `REBASELINE.md` - it is not a defect fix and
it must not be counted as one.

The window length is in SECONDS, not samples, so `reishi_1hz` gets the
same 50 s of signal per window that `reishi_10hz` does. That is the whole
point of the rate control: everything about the framing is held fixed and
only the number of samples describing each event changes.

The depth floor is applied LAST and TWICE - once per the derived rule and
once at the global 0.1 mV - producing two stores from one detection run.
See `floor10`.
"""

import os
import time

import numpy as np

from Pipelines.drop_motifs import (corpora10, floor10, passes7, passes8,
                                   passes9, spans5)
from Working.Detection.drop_motifs import motifs5

# Held identical across every corpus. Repeated here rather than defaulted
# so that a diff of this file is a diff of the parameterisation.
MAX_PASSES = 3
WINDOW_S = passes9.DEFAULT_WINDOW_S          # 50.0
OVERLAP = passes9.DEFAULT_OVERLAP            # 0.5
PASSES = dict(fine=True, sensitive=True, micro=True, inverted=False)

STORE_KIND = "drop_motifs10"


def _finish(rows, x, fs, *, corpus, species, framing, floor_rule,
            floor_mv=None):
    """Label, floor, and report - the tail every corpus shares.

    `floor_mv` overrides the derivation. It exists for exactly one case
    and is documented at its caller: a decimated channel's own second
    difference no longer measures broadband noise, because the anti-alias
    filter removed the broadband noise. See `run_fig2a`.
    """
    labelled = [corpora10.label_row(r, corpus=corpus, species=species,
                                    framing=framing, fs=fs) for r in rows]
    if floor_mv is None:
        floor_mv, rule = floor10.floor_for(x, rule=floor_rule)
    else:
        floor_mv, rule = float(floor_mv), floor_rule
    kept, rejected = floor10.apply_floor(labelled, floor_mv, rule=rule)
    return kept, {
        "n_before_floor": len(labelled),
        "n_after_floor": len(kept),
        "n_below_floor": len(rejected),
        "depth_floor_mv": floor_mv,
        "floor_rule": rule,
        "amplitude_sigma_mv": floor10.amplitude_sigma_mv(x),
    }


def run_span(x, fs, *, catalogue_id, recording_id, source_file, channel,
             span_offset, span_label, span_key, corpus, species,
             floor_rule=floor10.RULE_DERIVED):
    """One catalogue span or whole recording, passed whole to the detector.

    As drop_motifs8 ran them, minus the inverted pass. No sliding window:
    the span IS the window, and the scale each pass derives is the scale of
    the whole span - which is the framing the fifteen operator-chosen spans
    were selected under and the framing every validated count reproduces.
    """
    started = time.time()
    # `passes8`, not `passes7`, and for the same reason drop_motifs8 used
    # it: the recovery-edge rule and the size split. With `inverted=False`
    # rule 3 has no opposite-direction detections to act on, so what it
    # actually contributes here is a second same-direction merge under the
    # fs-scaled tolerance and the largest-drops band. Using the chain
    # drop_motifs8 used is also what makes the re-baseline control able to
    # reproduce drop_motifs8 at all - `passes7` alone gave id385 70 events
    # against drop_motifs8's 54.
    rows, arrays, info = passes8.detect_multiscale(
        x, fs,
        catalogue_id=catalogue_id, recording_id=recording_id,
        source_file=source_file, channel=channel, span_offset=span_offset,
        span_label=span_label, span_key=span_key,
        max_passes=MAX_PASSES, **PASSES)

    kept, floor_info = _finish(rows, x, fs, corpus=corpus, species=species,
                               framing=corpora10.FRAMING_SPAN,
                               floor_rule=floor_rule)
    keep_ids = {r["event_id"] for r in kept}
    arrays = {k: v for k, v in arrays.items()
              if k.split("__")[0] in keep_ids}

    summary = dict(
        catalogue_id=catalogue_id, recording_id=recording_id, corpus=corpus,
        species=species, framing=corpora10.FRAMING_SPAN, fs=float(fs),
        channel=int(channel), source_file=source_file,
        n_samples=int(len(x)), span_offset=int(span_offset),
        n_before_dedup=info.get("n_before_dedup"),
        n_duplicates_dropped=info.get("n_duplicates_dropped"),
        per_pass_kept={k: sum(1 for r in kept if r["pass_key"] == k)
                       for k in passes7.PASS_ORDER},
        pass_detail={k: v.get("n_events") for k, v in info["passes"].items()},
        n_motifs=len(kept),
        seconds=round(time.time() - started, 1),
        **floor_info)
    return kept, arrays, summary


def run_sliding(x, fs, *, catalogue_id, recording_id, source_file, channel,
                span_label, span_key, corpus, species,
                window_s=WINDOW_S, overlap=OVERLAP,
                floor_rule=floor10.RULE_DERIVED, floor_mv=None,
                progress=None):
    """One channel, 50 s windows at 50% overlap.

    `window_s` is SECONDS on purpose - see the module docstring. At 10 Hz
    that is 500 samples and at 1 Hz it is 50, and the same 50 s of signal
    is framed either way.
    """
    started = time.time()
    rows, arrays, info = passes9.detect_sliding(
        x, fs,
        catalogue_id=catalogue_id, recording_id=recording_id,
        source_file=source_file, channel=channel,
        window_s=window_s, overlap=overlap,
        span_label=span_label, span_key=span_key,
        max_passes=MAX_PASSES, fine=PASSES["fine"],
        sensitive=PASSES["sensitive"], micro=PASSES["micro"],
        progress=progress)

    kept, floor_info = _finish(rows, x, fs, corpus=corpus, species=species,
                               framing=corpora10.FRAMING_SLIDING,
                               floor_rule=floor_rule, floor_mv=floor_mv)
    keep_ids = {r["event_id"] for r in kept}
    arrays = {k: v for k, v in arrays.items()
              if k.split("__")[0] in keep_ids}

    summary = dict(
        catalogue_id=catalogue_id, recording_id=recording_id, corpus=corpus,
        species=species, framing=corpora10.FRAMING_SLIDING, fs=float(fs),
        channel=int(channel), source_file=source_file,
        n_samples=int(len(x)), span_offset=0,
        n_motifs=len(kept),
        seconds=round(time.time() - started, 1),
        **{k: v for k, v in info.items() if k != "per_window"},
        **floor_info)
    summary["n_windows_detail"] = len(info["per_window"])
    return kept, arrays, summary


# ---------------------------------------------------------------------------
# the four corpora
# ---------------------------------------------------------------------------

def run_catalogue(conn, span_ids, *, corpus, species,
                  floor_rule=floor10.RULE_DERIVED, log=print):
    """The catalogue spans of one corpus."""
    all_rows, all_arrays, summaries = [], {}, []
    for catalogue_id, spec in corpora10.catalogue_spans(span_ids):
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?",
                           (spec["recording"],)).fetchone()
        if rec is None:
            raise SystemExit(f"no recording {spec['recording']}")
        x, offset = spans5.load_span(rec, spec["span"])
        rows, arrays, summary = run_span(
            x, float(rec["fs"]),
            catalogue_id=catalogue_id, recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=int(rec["channel"]), span_offset=offset,
            span_label=f"catalogue ID {catalogue_id}",
            span_key=f"id{catalogue_id:03d}",
            corpus=corpus, species=species, floor_rule=floor_rule)
        summary["annotated_n"] = spec.get("annotated_n")
        summary["expected_morphology"] = spec.get("expect")
        summary["note"] = spec.get("note")
        all_rows.extend(rows)
        all_arrays.update(arrays)
        summaries.append(summary)
        log(f"  id{catalogue_id:<4} {summary['n_motifs']:>4} motifs "
            f"({summary['n_below_floor']} below a "
            f"{summary['depth_floor_mv']:.4f} mV floor)  "
            f"{summary['seconds']}s")
    return all_rows, all_arrays, summaries


def run_fig2a(conn, *, decimate=False, floor_rule=floor10.RULE_DERIVED,
              log=print):
    """The five Fig2A channels, at 10 Hz or decimated to 1 Hz."""
    corpus = (corpora10.CORPUS_REISHI_1HZ if decimate
              else corpora10.CORPUS_REISHI_10HZ)
    all_rows, all_arrays, summaries = [], {}, []

    for catalogue_id, rec in corpora10.fig2a_recordings(conn):
        x = np.asarray(np.load(rec["npy_path"], mmap_mode="r"), dtype=float)
        fs = float(rec["fs"])
        floor_mv = None
        if decimate:
            # THE FLOOR IS INHERITED FROM THE NATIVE RATE, and it has to
            # be. `floor10.amplitude_sigma_mv` is a second-difference MAD,
            # which measures per-sample broadband noise - and the
            # anti-alias filter that makes an honest decimation possible
            # removes exactly that. Measured on CH1: sigma goes 0.0066 mV
            # at 10 Hz to 0.1012 mV at 1 Hz, a factor of 15, while the
            # channel's peak-to-peak barely moves (3.010 -> 2.826 mV). The
            # 1 Hz "noise" estimate is the signal's own curvature, not
            # noise, and a floor built on it would delete the corpus.
            #
            # The physical argument is the same one: how deep a real drop
            # is does not change when you resample it, so the instrument's
            # noise floor in millivolts is a property of the recording and
            # not of the rate it is read at. Using the native floor is
            # also what makes reishi_10hz and reishi_1hz comparable - a
            # rate control whose two arms applied different floors would
            # be measuring the floor, not the rate.
            floor_mv, _ = floor10.floor_for(x, rule=floor_rule)
            x, fs = corpora10.decimate_to(x, fs, target_fs=1.0,
                                          factor=corpora10.DECIMATION_FACTOR)
        rows, arrays, summary = run_sliding(
            x, fs,
            catalogue_id=catalogue_id, recording_id=int(rec["id"]),
            source_file=os.path.basename(rec["npy_path"]),
            channel=int(rec["channel"]),
            span_label=f"{corpora10.FIG2A_SOURCE} CH{int(rec['channel'])}",
            span_key=f"id{catalogue_id:03d}",
            corpus=corpus, species=corpora10.SPECIES_REISHI,
            floor_rule=floor_rule, floor_mv=floor_mv)
        summary["decimated"] = bool(decimate)
        summary["floor_inherited_from_native_rate"] = bool(decimate)
        all_rows.extend(rows)
        all_arrays.update(arrays)
        summaries.append(summary)
        log(f"  CH{int(rec['channel'])} {summary['n_motifs']:>4} motifs "
            f"from {summary['n_before_dedup']} raw "
            f"({summary['n_below_floor']} below a "
            f"{summary['depth_floor_mv']:.4f} mV floor)  "
            f"{summary['seconds']}s")
    return all_rows, all_arrays, summaries


def rekey_for_corpus(rows, arrays, corpus):
    """Make event ids unique across corpora.

    `reishi_10hz` and `reishi_1hz` are the same five recordings detected
    twice, so `id900_r466_base_3562` names an event in both. Without a
    corpus tag the pooled store would silently lose one of every colliding
    pair to a dict update - the same class of defect as the window-index
    collision that produced the all-zero feature vectors, so it is
    prevented here rather than discovered later.
    """
    # ONE underscore. `motifs5` keys arrays `{event_id}__{field}` and
    # splits on the double underscore, so a `__1hz` suffix would split the
    # key in the wrong place and every 1 Hz array would be orphaned from
    # its row - which is exactly what it did, silently, until the tree
    # reported 256 rows with no array.
    suffix = {corpora10.CORPUS_REISHI_1HZ: "_1hz"}.get(corpus, "")
    if not suffix:
        return list(rows), dict(arrays)
    out_rows, out_arrays = [], {}
    for row in rows:
        row = dict(row)
        old = row["event_id"]
        new = f"{old}{suffix}"
        row["event_id"] = new
        row["snippet_key"] = new
        out_rows.append(row)
        for field in ("raw_mv", "detrended_mv", "t_s"):
            key = f"{old}__{field}"
            if key in arrays:
                out_arrays[f"{new}__{field}"] = arrays[key]
    return out_rows, out_arrays


def write(out_dir, rows, arrays, extra=None):
    """Write one store, with the parameterisation in its manifest."""
    manifest = {
        "kind": STORE_KIND,
        "detector": "detect5 + passes7 (span) / passes9 (sliding), "
                    "drops only, four passes",
        "one_parameterisation": True,
        "max_passes": MAX_PASSES,
        "window_s": WINDOW_S,
        "overlap": OVERLAP,
        "passes": PASSES,
        "floor_sigmas": floor10.FLOOR_SIGMAS,
        "key_format": "id{cat:03d}_r{rec}_{pass}_{onset}[_w{window}][_1hz]",
        "validated_against_human": True,
    }
    manifest.update(extra or {})
    motifs5.write_store(str(out_dir), rows, arrays, manifest_extra=manifest)
    return out_dir
