"""
test_drop_motifs_motifs5.py
============================
The motif library (`Working.Detection.drop_motifs.motifs5`).

This store exists so the extracted windows survive the process that found
them - the operator's stated use is a motif library for the UI, and the
clustering and rose figures already read from it rather than from a live
detection result. So the properties worth pinning are the ones a library
is judged on:

  - it round-trips. What is written is what is read, bit for bit on the
    arrays and type-for-type on the index.
  - it is keyed uniquely ACROSS spans. Two of the sixteen spans are
    sub-spans of two others (ID 20 inside ID 1, ID 21 inside ID 3), so a
    key built from recording and onset alone collides between them and
    silently drops one of each pair from the pooled figures.
  - it carries the grade. `is_pure` must be on the row, because every
    downstream figure excludes impure windows and recomputing that from
    the arrays would let the figure and the library disagree.
  - it is readable without the detector. A consumer holding only the
    directory must be able to load it, which is what makes it a library
    rather than a cache.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np
import pytest

from Working.Detection.drop_motifs import motifs5
from Working.Detection.drop_motifs.autoparams import derive_params
from Working.Detection.drop_motifs.detect5 import (
    Detect5Params,
    detect_drops5,
    window_purity,
)

FS = 1.0


def sharkfin_span(n_cycles=5, rise_s=300, fall_s=60, flat_s=40, lead_s=200,
                  amplitude=10.0, seed=11):
    cycle = np.concatenate([
        np.linspace(0.0, amplitude, rise_s, endpoint=False),
        np.linspace(amplitude, 0.0, fall_s, endpoint=False),
        np.zeros(flat_s),
    ])
    x = np.concatenate([np.zeros(lead_s)] + [cycle] * n_cycles)
    return x + np.random.default_rng(seed).normal(0.0, 0.02, len(x))


def detected(x, **kw):
    params = Detect5Params(**derive_params(360.0, FS, len(x), **kw))
    result = detect_drops5(x, FS, params)
    return result, window_purity(x, FS, result)


def written(tmp_path, x, result, purity, **kw):
    rows, arrays = motifs5.rows_and_arrays(
        result, x, purity, catalogue_id=kw.pop("catalogue_id", 21),
        recording_id=kw.pop("recording_id", 1), fs=FS,
        source_file="CH0.npy", channel=0, **kw)
    return rows, arrays


def test_store_round_trips_arrays_bit_for_bit_and_indices_as_ints(tmp_path):
    x = sharkfin_span()
    result, purity = detected(x)
    rows, arrays = written(tmp_path, x, result, purity)
    assert rows, "the fixture produced no events to store"

    motifs5.write_store(str(tmp_path), rows, arrays)
    back, snippets, manifest = motifs5.load_store(str(tmp_path))

    assert len(back) == len(rows)
    assert manifest["kind"] == motifs5.STORE_KIND
    assert manifest["n_motifs"] == len(rows)

    for original, reloaded in zip(rows, back):
        assert reloaded["event_id"] == original["event_id"]
        # Indices must come back as ints. A float read back here becomes a
        # float array subscript later and numpy's complaint arrives a long
        # way from the cause.
        for key in ("onset_idx", "trough_idx", "snippet_start_idx",
                    "snippet_end_idx", "catalogue_id", "purity", "is_pure"):
            assert isinstance(reloaded[key], int), f"{key} came back as " \
                                                   f"{type(reloaded[key])}"
            assert reloaded[key] == original[key]

        stored = snippets[original["event_id"]]
        np.testing.assert_array_equal(
            stored["raw_mv"], arrays[f"{original['event_id']}__raw_mv"])
        np.testing.assert_array_equal(
            stored["detrended_mv"],
            arrays[f"{original['event_id']}__detrended_mv"])


def test_every_row_has_its_arrays_and_every_array_has_its_row(tmp_path):
    """The bijection. A row with no window is a citation to nothing; an
    array with no row is invisible to every consumer."""
    x = sharkfin_span()
    result, purity = detected(x)
    rows, arrays = written(tmp_path, x, result, purity)
    motifs5.write_store(str(tmp_path), rows, arrays)

    back, snippets, _ = motifs5.load_store(str(tmp_path))
    assert {r["event_id"] for r in back} == set(snippets)
    for key, fields in snippets.items():
        assert {"raw_mv", "detrended_mv", "t_s"} <= set(fields)
        assert len({len(v) for v in fields.values()}) == 1, (
            f"{key}'s arrays disagree on length")


def test_ids_do_not_collide_between_a_span_and_its_own_sub_span(tmp_path):
    """ID 20 lies inside ID 1 and ID 21 inside ID 3, on the same recording.

    A key built from recording and onset alone is IDENTICAL for the same
    physical event seen from both spans, so writing them into one store
    would silently drop one of each pair - and the pooled dendrogram would
    then be missing motifs without anything reporting it.
    """
    x = sharkfin_span()
    result, purity = detected(x)

    outer, outer_arrays = written(tmp_path, x, result, purity,
                                  catalogue_id=1, recording_id=1)
    inner, inner_arrays = written(tmp_path, x, result, purity,
                                  catalogue_id=20, recording_id=1)

    assert not ({r["event_id"] for r in outer}
                & {r["event_id"] for r in inner}), (
        "the same onset on one recording produced the same key from two "
        "different spans")

    rows = outer + inner
    arrays = {**outer_arrays, **inner_arrays}
    motifs5.write_store(str(tmp_path), rows, arrays)
    back, snippets, manifest = motifs5.load_store(str(tmp_path))
    assert len(back) == len(rows), "a motif was lost to a key collision"
    assert len(snippets) == len(rows)
    assert manifest["spans"] == [1, 20]


def test_purity_is_carried_on_the_row_and_filters_the_load(tmp_path):
    """Every downstream figure excludes impure windows by this flag, so it
    has to be stored rather than recomputed - a figure and a library that
    each decide purity for themselves can disagree."""
    x = sharkfin_span()
    result, purity = detected(x)
    rows, arrays = written(tmp_path, x, result, purity)

    # Force one impure row so the filter has something to remove.
    rows[0]["purity"] = 3
    rows[0]["is_pure"] = 0
    motifs5.write_store(str(tmp_path), rows, arrays)

    everything, _, manifest = motifs5.load_store(str(tmp_path))
    pure_only, _, _ = motifs5.load_store(str(tmp_path), pure_only=True)

    assert len(everything) == len(rows)
    assert len(pure_only) == len(rows) - 1
    assert all(r["is_pure"] for r in pure_only)
    assert manifest["n_impure"] == 1
    assert manifest["n_pure"] == len(rows) - 1


def test_an_empty_run_still_writes_a_readable_store(tmp_path):
    """An empty result must not look like a result that was never
    computed - the same requirement the three-stage store carries."""
    motifs5.write_store(str(tmp_path), [], {})
    events, snippets, manifest = motifs5.load_store(str(tmp_path))
    assert events == []
    assert snippets == {}
    assert manifest["empty"] is True
    assert manifest["n_motifs"] == 0


def test_the_store_needs_no_plotting_library(tmp_path):
    """CLAUDE.md rule 1: this lives under `Working/`."""
    forbidden = {"panel", "holoviews", "bokeh", "matplotlib"}
    names = {getattr(v, "__name__", "").split(".")[0]
             for v in vars(motifs5).values()}
    assert not (forbidden & names)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
