"""
test_wm_backfill.py
=====================
Tests for Pipelines/import_wm_artifacts/import_wm_artifacts.py (the pre-v1
MATRICES/*.csv backfill, WINDOW_MATRIX_UI_PROMPT.md §5).

Run from the project root:
    python tests/test_wm_backfill.py
"""

import inspect
import os
import shutil
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import numpy as np

from Working.database.schema import init_db
from Working.database import queries as q
from Working.database import window_matrix_store as store
from Pipelines.import_wm_artifacts import import_wm_artifacts as backfill


class _Fixture:
    """A temp DB + a fake channel .npy + a `recordings` row, and a
    `MATRICES/`-shaped temp directory to backfill from — never the real
    `MATRICES/` tree."""

    def __init__(self, n_samples=1200, fs=1.0, channel=2, source_stem="fake_wm_src"):
        self.tmpdir = tempfile.mkdtemp(prefix="wm_backfill_test_")
        self.db_path = os.path.join(self.tmpdir, "test.sqlite")
        self.matrices_dir = os.path.join(self.tmpdir, "MATRICES")
        os.makedirs(self.matrices_dir, exist_ok=True)
        self.results_dir = os.path.join(self.tmpdir, "wm_results")
        # `apply_plan`'s `legacy_dir` default is relative to the process CWD
        # (the real repo's MATRICES/_legacy/), NOT this fixture's temp dir —
        # every `apply_plan` call in this file must pass this explicitly, or
        # a test would move a file into the real repo tree.
        self.legacy_dir = os.path.join(self.matrices_dir, "_legacy")
        self.npy_path = os.path.join(self.tmpdir, "CH2.npy")
        self.channel = channel
        self.source_stem = source_stem
        np.save(self.npy_path, np.random.default_rng(0).standard_normal(n_samples))
        self.conn = init_db(self.db_path)
        self.recording_id = q.insert_recording(
            self.conn, f"{source_stem}.mat", channel, fs, n_samples, 0, self.npy_path,
        )

    def write_csv(self, name, df):
        path = os.path.join(self.matrices_dir, name)
        df.to_csv(path)
        return path

    def close(self):
        self.conn.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _self_describing_csv_name(fx, window_min=10, step_pct=100):
    return f"{fx.source_stem}_CH{fx.channel}_WIN{window_min}min_STEP{step_pct}pct.csv"


def _make_matching_frame(m, step, n_samples, n_cols=3, seed=0):
    """A DataFrame with a UNIFORM start_idx grid consistent with
    `store.window_samples`/`store.step_samples` at (window_min, step_frac) —
    `plan_file` refuses anything whose observed spacing disagrees with what
    the filename implies."""
    import pandas as pd
    stop = n_samples - m + 1
    start_idx = np.arange(0, max(stop, 0), step, dtype=np.int64)
    rng = np.random.default_rng(seed)
    data = {f"col{i}": rng.standard_normal(len(start_idx)) for i in range(n_cols)}
    df = pd.DataFrame(data, index=start_idx)
    df.index.name = "start_idx"
    return df


def test_self_describing_file_is_ready_and_round_trips_to_the_same_values():
    fx = _Fixture()
    try:
        m = store.window_samples(10, fx.conn.execute(
            "SELECT fs FROM recordings WHERE id=?", (fx.recording_id,)).fetchone()[0])
        step = store.step_samples(m, 1.0)
        df = _make_matching_frame(m, step, 1200)
        name = _self_describing_csv_name(fx)
        fx.write_csv(name, df)

        plan = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        assert plan["action"] == "import", plan["reason"]
        assert plan["recording"]["id"] == fx.recording_id
        assert plan["n_windows"] == len(df)

        result = backfill.apply_plan(fx.conn, plan, results_dir=fx.results_dir, legacy_dir=fx.legacy_dir)
        assert result["status"] == "imported"
        loaded = store.load_wm(result["artifact_path"], mmap=False)
        # Round-trips to the SAME values, in the SAME column order.
        expected = df[[c for c in df.columns]].to_numpy(dtype=np.float32)
        np.testing.assert_allclose(np.asarray(loaded["values"]), expected)
        assert list(loaded["columns"]) == list(df.columns)
        assert bool(loaded["backfilled"]) is True

        # Original moved to _legacy/, not deleted, not left in place.
        assert not os.path.isfile(os.path.join(fx.matrices_dir, name))
        assert os.path.isfile(os.path.join(fx.matrices_dir, "_legacy", name))
    finally:
        fx.close()


def test_backfilled_computed_mask_is_inferred_from_isfinite():
    fx = _Fixture()
    try:
        fs = 1.0
        m = store.window_samples(10, fs)
        step = store.step_samples(m, 1.0)
        df = _make_matching_frame(m, step, 1200)
        df.iloc[0, 0] = np.nan  # a genuinely-missing-looking cell
        name = _self_describing_csv_name(fx)
        fx.write_csv(name, df)

        plan = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        result = backfill.apply_plan(fx.conn, plan, results_dir=fx.results_dir, legacy_dir=fx.legacy_dir)
        loaded = store.load_wm(result["artifact_path"], mmap=False)
        computed = np.asarray(loaded["computed"], dtype=bool)
        assert computed[0, 0] == False
        assert computed[0, 1] == True
    finally:
        fx.close()


def test_second_apply_is_a_no_op():
    fx = _Fixture()
    try:
        fs = 1.0
        m = store.window_samples(10, fs)
        step = store.step_samples(m, 1.0)
        df = _make_matching_frame(m, step, 1200)
        name = _self_describing_csv_name(fx)
        fx.write_csv(name, df)

        plan1 = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        r1 = backfill.apply_plan(fx.conn, plan1, results_dir=fx.results_dir, legacy_dir=fx.legacy_dir)
        assert r1["status"] == "imported"

        # The original was MOVED to _legacy/ by the first apply — a second
        # backfill run scans the (now empty of that file) MATRICES/ dir, so
        # simulate "re-running against the same file" the way the actual
        # idempotency guarantee is meant (find_wm already resolves it):
        # re-planning + re-applying the artifact's own (recording, window_min,
        # step_frac, span) must report already-imported, not write again.
        existing = store.find_wm(fx.conn, fx.recording_id, 10.0, span=plan1["span"])
        assert existing is not None
        assert existing["artifact_path"] == r1["artifact_path"]

        plan2 = dict(plan1)  # same identity, as if re-discovered
        r2 = backfill.apply_plan(fx.conn, plan2, results_dir=fx.results_dir, legacy_dir=fx.legacy_dir)
        assert r2["status"] == "already-imported"
        assert r2["artifact_path"] == r1["artifact_path"]
    finally:
        fx.close()


def test_unidentifiable_files_are_reported_and_left_in_place():
    fx = _Fixture()
    try:
        for name in ("features.csv", "features - Copy.csv", "features_graph.csv"):
            fx.write_csv(name, _make_matching_frame(600, 600, 1200))
            plan = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
            assert plan["action"] == "skip", name
            assert plan["reason"], name
            assert os.path.isfile(os.path.join(fx.matrices_dir, name))
    finally:
        fx.close()


def test_subsample_files_are_skipped():
    fx = _Fixture()
    try:
        name = "0.01_percent_M2_concat_fs1_consecutive.csv"
        fx.write_csv(name, _make_matching_frame(600, 600, 1200))
        plan = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        assert plan["action"] == "skip"
        assert "subsample" in plan["reason"]
    finally:
        fx.close()


def test_channel_missing_from_filename_requires_assume():
    fx = _Fixture()
    try:
        name = f"{fx.source_stem}_10min_999wins_consecutive.csv"
        fx.write_csv(name, _make_matching_frame(600, 600, 1200))

        plan_no_assume = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        assert plan_no_assume["action"] == "skip"
        assert "CHANNEL" in plan_no_assume["reason"]

        plan_assumed = backfill.plan_file(
            fx.conn, os.path.join(fx.matrices_dir, name), assume_channel=fx.channel,
        )
        assert plan_assumed["action"] == "import"
    finally:
        fx.close()


def test_inconsistent_step_spacing_is_a_hard_failure_not_a_guess():
    fx = _Fixture()
    try:
        import pandas as pd
        # Non-uniform start_idx spacing: the filename says WIN10min/STEP100pct
        # but the actual grid doesn't match that geometry.
        df = pd.DataFrame({"col0": [1.0, 2.0, 3.0]}, index=[0, 600, 1300])
        df.index.name = "start_idx"
        name = _self_describing_csv_name(fx)
        fx.write_csv(name, df)

        plan = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        assert plan["action"] == "skip"
        assert "disagree" in plan["reason"] or "not uniform" in plan["reason"]
    finally:
        fx.close()


def test_excluded_columns_are_dropped_on_import():
    fx = _Fixture()
    try:
        import pandas as pd
        fs = 1.0
        m = store.window_samples(10, fs)
        step = store.step_samples(m, 1.0)
        df = _make_matching_frame(m, step, 1200)
        df["cnn_1_minus_p_notinteresting"] = 0.5  # §2.1 exclusion
        df["category"] = "interesting"             # §2.1 exclusion (non-numeric metadata)
        name = _self_describing_csv_name(fx)
        fx.write_csv(name, df)

        plan = backfill.plan_file(fx.conn, os.path.join(fx.matrices_dir, name))
        assert plan["action"] == "import"
        assert "cnn_1_minus_p_notinteresting" in plan["dropped_columns"]
        assert "category" in plan["dropped_columns"] or "category" in plan["dropped_non_numeric"]
        assert "cnn_1_minus_p_notinteresting" not in plan["columns"]
        assert "category" not in plan["columns"]
    finally:
        fx.close()


# ── runner ───────────────────────────────────────────────────────────────────

def _run_all():
    fns = [obj for name, obj in sorted(globals().items())
           if name.startswith("test_") and inspect.isfunction(obj)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e!r}")
            failed.append(fn.__name__)
    print(f"\n{passed}/{len(fns)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
