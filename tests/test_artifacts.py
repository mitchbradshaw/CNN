"""
test_artifacts.py
===================
Tests for Working/artifacts.py: filename generation matching the brief's
own example, uniqueness (via the hash8 suffix), the length cap, and
illegal-character stripping.

Run from the project root:
    python tests/test_artifacts.py
"""

import inspect
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "Working")) \
        and os.path.dirname(PROJECT_ROOT) != PROJECT_ROOT:
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Working.artifacts import (
    MAX_FILENAME_LENGTH,
    build_artifact_filename,
    build_artifact_path,
    paramslug,
)


def test_matches_brief_example():
    fn = build_artifact_filename(
        "M2_aug_concat_fs1.mat", 3, "preprocessing", "preprocessing.lowpass",
        {"cutoff_hz": 0.05, "order": 4}, "a1b2c3d4", "png",
    )
    assert fn == "M2aug_CH03_prep_lowpass_fc0p05_ord4_a1b2c3d4.png"


def test_recording_slug_strips_concat_fs_suffix():
    fn = build_artifact_filename(
        "M2_concat_fs1.mat", 0, "detection", "detection.rupture", {}, "deadbeef", "png",
    )
    assert fn.startswith("M2_CH00_det_rupture")


def test_channel_zero_padded():
    fn = build_artifact_filename(
        "M2_concat_fs1.mat", 7, "detection", "detection.rupture", {}, "deadbeef", "png",
    )
    assert "_CH07_" in fn


def test_no_illegal_characters_in_param_slug():
    fn = build_artifact_filename(
        "M2_concat_fs1.mat", 0, "preprocessing", "preprocessing.bandpass",
        {"low_hz": -0.5, "high_hz": 0.1}, "deadbeef", "png",
    )
    forbidden = set(".,/\\ ")
    # everything up to the extension's final dot
    body = fn.rsplit(".", 1)[0]
    assert not (forbidden & set(body))


def test_uniqueness_guaranteed_by_hash_even_with_identical_paramslug():
    # Two different hashes -> two different filenames, even with identical
    # human-readable parts (paramslug is a lossy abbreviation; hash8 isn't).
    common = ("M2_concat_fs1.mat", 0, "catalogue", "catalogue.gramian_gasf", {})
    fn1 = build_artifact_filename(*common, "aaaaaaaa", "png")
    fn2 = build_artifact_filename(*common, "bbbbbbbb", "png")
    assert fn1 != fn2


def test_length_cap_respected_and_hash_preserved():
    long_params = {
        "some_extremely_long_parameter_name_that_goes_on_and_on": "a" * 200,
    }
    fn = build_artifact_filename(
        "M2_concat_fs1.mat", 0, "catalogue", "catalogue.gramian_gasf",
        long_params, "deadbeef", "png",
    )
    assert len(fn) <= MAX_FILENAME_LENGTH
    assert fn.endswith("_deadbeef.png")


def test_paramslug_takes_first_three_params_only():
    params = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    slug = paramslug(params, max_params=3)
    assert slug.count("_") == 2  # 3 parts joined by 2 underscores


def test_paramslug_empty_params_is_default():
    assert paramslug({}) == "default"


def test_build_artifact_path_layout():
    path = build_artifact_path(
        "M2_aug_concat_fs1.mat", 3, "preprocessing", "preprocessing.lowpass",
        {"cutoff_hz": 0.05, "order": 4}, "a1b2c3d4", "png",
    )
    normalized = path.replace("\\", "/")
    assert normalized == "Plots/Preprocessing/lowpass/M2aug_CH03_prep_lowpass_fc0p05_ord4_a1b2c3d4.png"


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
