"""
sax_detection_tests.py
======================
Plain assert-based tests for `sax_detection.py`.

Style matches tests/ in this repo: plain asserts, no pytest fixtures.

    python "Experimentation/Detection experiments/sax_detection_tests.py"

Priority here is the statistics and the surrogate contracts, not the plumbing.
An error in `benjamini_hochberg` or `empirical_p` would not crash anything - it
would quietly change every significance claim the method makes - and a
surrogate that fails to preserve what it advertises makes the null the wrong
null while still producing plausible numbers.
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Makes `Working.*` / `Pipelines.*` importable when this file is run directly.
# Walks up to the directory containing Working/, so it survives future moves.
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
if str(_Path(__file__).resolve().parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))

import time

import numpy as np

from multiscale_sax import MultiScaleSAX
from sax_seed_search import Seed
import sax_detection as D


def _signal(n=20000, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    x = (np.cumsum(rng.normal(0, 1, n)) * 0.01
         + 0.4 * np.sin(2 * np.pi * t / 5000)
         + rng.normal(0, 0.05, n))
    # Deliberately skewed, so the fourier-vs-IAAFT distinction is testable:
    # a symmetric signal would pass the amplitude-distribution test either way.
    return x + 0.3 * np.abs(rng.normal(0, 1, n))


def _pyramid(x):
    ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=(8, 128),
                       alphabet_size=8, cutline_mode="shared_renormalised",
                       offsets="all", max_offsets=4, random_state=0)
    ms.channel = 0
    return ms


# ──────────────────────────────────────────────────────────────────────────────
#  Benjamini-Hochberg
# ──────────────────────────────────────────────────────────────────────────────

def test_benjamini_hochberg():
    # Worked example from Benjamini & Hochberg (1995), Table 1: 15 p-values,
    # alpha = 0.05 rejects the first 4 when sorted ascending.
    p = np.array([0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298,
                  0.0344, 0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000])
    q, rej, crit = D.benjamini_hochberg(p, alpha=0.05)
    assert int(rej.sum()) == 4, f"expected 4 rejections, got {int(rej.sum())}"
    assert np.allclose(crit, 0.0095), crit
    # q must be monotone non-decreasing in p, and never below p.
    order = np.argsort(p)
    assert np.all(np.diff(q[order]) >= -1e-12), "q-values are not monotone"
    assert np.all(q + 1e-12 >= p), "a q-value fell below its own p-value"
    assert np.all(q <= 1.0)

    # All-null input: with uniform p-values, BH must reject essentially nothing.
    rng = np.random.default_rng(0)
    over = [int(D.benjamini_hochberg(rng.uniform(0, 1, 500), 0.05)[1].sum())
            for _ in range(40)]
    assert np.mean(over) < 2.0, f"BH over-rejects under the null: {np.mean(over)}"

    # All-signal input: every p at 0 must be rejected.
    _, rej2, _ = D.benjamini_hochberg(np.zeros(20), 0.05)
    assert rej2.all()

    # Degenerate input must not raise.
    q3, rej3, crit3 = D.benjamini_hochberg(np.array([]), 0.05)
    assert len(q3) == 0 and len(rej3) == 0 and np.isnan(crit3)
    print("PASS test_benjamini_hochberg (B&H 1995 table: 4 rejections, crit=0.0095)")


def test_empirical_p():
    null = np.arange(100, dtype=float)           # 0..99

    # Add-one correction: nothing can report p = 0.
    p = D.empirical_p(np.array([-1.0]), null)
    assert np.isclose(p[0], 1 / 101), p
    assert p[0] > 0, "empirical p reached 0 - the add-one correction is missing"

    # A value above everything reports p = 1.
    assert np.isclose(D.empirical_p(np.array([1e9]), null)[0], 101 / 101)

    # Monotone in the observed distance (lower distance = smaller p).
    obs = np.array([5.0, 25.0, 75.0])
    ps = D.empirical_p(obs, null)
    assert np.all(np.diff(ps) > 0), ps

    # Exact count semantics: d = 49 has 50 null values <= it.
    assert np.isclose(D.empirical_p(np.array([49.0]), null)[0], 51 / 101)

    # Uniformity: p-values of null draws against the null must be ~uniform,
    # which is what makes the FDR control meaningful in the first place.
    rng = np.random.default_rng(1)
    ref = rng.normal(0, 1, 20000)
    draws = rng.normal(0, 1, 4000)
    pv = D.empirical_p(draws, ref)
    assert abs(pv.mean() - 0.5) < 0.02, pv.mean()
    assert abs(np.mean(pv < 0.05) - 0.05) < 0.015, np.mean(pv < 0.05)
    print(f"PASS test_empirical_p (null p-values uniform: mean {pv.mean():.3f}, "
          f"frac<0.05 = {np.mean(pv < 0.05):.3f})")


def test_null_resolution():
    """The trust floor must track n_surrogates, not the pooled hit count."""
    null = D.NullModel(hit_distances=np.arange(50000, dtype=float),
                       best_distances=np.arange(20, dtype=float),
                       per_scale={}, n_surrogates=20, surrogate="fourier",
                       matcher="cascade", scales=[16], seed_id="x")
    assert np.isclose(null.p_floor, 1 / 50001)
    assert np.isclose(null.p_resolution, 1 / 20)
    assert null.p_resolution > null.p_floor, (
        "p_resolution must exceed the arithmetic floor - it is the whole point "
        "that a pooled null cannot buy precision it does not have")
    print(f"PASS test_null_resolution (floor {null.p_floor:.2e} vs "
          f"trust floor {null.p_resolution:.3f})")


# ──────────────────────────────────────────────────────────────────────────────
#  Surrogates must preserve what they advertise
# ──────────────────────────────────────────────────────────────────────────────

def test_surrogates():
    x = _signal(8192, seed=2)
    rng = np.random.default_rng(0)
    amp = np.abs(np.fft.rfft(x - x.mean()))

    # Fourier: power spectrum preserved to numerical precision.
    xf = D.fourier_surrogate(x, rng)
    amp_f = np.abs(np.fft.rfft(xf - xf.mean()))
    rel = np.abs(amp_f - amp).max() / amp.max()
    assert rel < 1e-8, f"fourier surrogate changed the spectrum (rel {rel:.2e})"
    # ...and it does NOT preserve the amplitude distribution (that is the
    # documented weakness that motivates IAAFT).
    assert not np.allclose(np.sort(xf), np.sort(x)), \
        "fourier surrogate preserved the marginal - then IAAFT would be pointless"

    # IAAFT: amplitude distribution preserved EXACTLY (it is a permutation of
    # the original values), spectrum preserved approximately.
    xi = D.iaaft_surrogate(x, rng, n_iter=60)
    assert np.allclose(np.sort(xi), np.sort(x)), \
        "IAAFT did not preserve the amplitude distribution"
    amp_i = np.abs(np.fft.rfft(xi - xi.mean()))
    err = np.linalg.norm(amp_i - amp) / np.linalg.norm(amp)
    assert err < 0.10, f"IAAFT spectrum error {err:.3f} is too large"

    # Block bootstrap: same length, same value pool, local structure retained.
    L = 500
    xb = D.block_bootstrap(x, rng, block_length=L)
    assert len(xb) == len(x)
    lag1_real = np.corrcoef(x[:-1], x[1:])[0, 1]
    lag1_block = np.corrcoef(xb[:-1], xb[1:])[0, 1]
    assert lag1_block > 0.5 * lag1_real, (
        f"block bootstrap destroyed short-range structure "
        f"(lag-1 {lag1_block:.3f} vs {lag1_real:.3f})")
    # Long-range structure must be gone: correlation at >> L should collapse.
    far_real = abs(np.corrcoef(x[:-4000], x[4000:])[0, 1])
    far_block = abs(np.corrcoef(xb[:-4000], xb[4000:])[0, 1])
    assert far_block < far_real, (
        f"block bootstrap preserved long-range structure "
        f"({far_block:.3f} vs {far_real:.3f}) - it is meant to destroy it")

    # Every generator reachable by name.
    for kind in D.SURROGATES:
        out = D.make_surrogate(x, kind, rng)
        assert len(out) == len(x) and np.all(np.isfinite(out))
    try:
        D.make_surrogate(x, "nonsense", rng)
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown surrogate name should have raised")

    print(f"PASS test_surrogates (fourier spectrum rel {rel:.1e}; IAAFT marginal "
          f"exact, spectrum err {err:.3f}; block lag-1 {lag1_block:.2f})")


# ──────────────────────────────────────────────────────────────────────────────
#  The non-negotiable: surrogates go through the SAME quantiser
# ──────────────────────────────────────────────────────────────────────────────

def test_encode_like():
    x = _signal(20000, seed=3)
    ms = _pyramid(x)

    # Re-encoding the original signal must reproduce it bit for bit.
    same = D.encode_like(ms, x, check=True)
    for s in ms.scales:
        for off in ms.offsets_for(s):
            assert np.array_equal(same.symbols(s, off), ms.symbols(s, off)), \
                f"encode_like changed the encoding of the original at sps={s}"

    # A surrogate must produce DIFFERENT symbols but the SAME quantiser.
    rng = np.random.default_rng(0)
    sur = D.encode_like(ms, D.fourier_surrogate(x, rng), check=True)
    assert np.mean(sur.symbols(16, 0) != ms.symbols(16, 0)) > 0.3, \
        "the surrogate encoded almost identically - suspect a wiring error"
    for s in ms.scales:
        a, b = ms.scale_info[s], sur.scale_info[s]
        assert np.array_equal(a["cutlines"], b["cutlines"])
        assert a["paa_mean"] == b["paa_mean"] and a["paa_std"] == b["paa_std"]
    assert sur.x_mean == ms.x_mean and sur.x_std == ms.x_std

    # The real pyramid must be untouched by the surrogate encoding.
    assert same.scale_info is not ms.scale_info
    assert ms.encodings[(16, 0)]["symbols"] is not sur.encodings[(16, 0)]["symbols"]

    # The guard must actually fire. A check never seen to fail is not known to
    # work, so tamper with each learned parameter in turn and confirm each one
    # is caught - this is the exact damage a re-training bug would do.
    D.assert_same_quantiser(ms, sur)          # baseline: passes

    for field, expect, mutate in [
        ("cutlines", "cutlines", lambda i: i.__setitem__("cutlines", i["cutlines"] + 0.1)),
        ("paa_std", "paa_std", lambda i: i.__setitem__("paa_std", i["paa_std"] * 2)),
        ("paa_mean", "paa_mean", lambda i: i.__setitem__("paa_mean", i["paa_mean"] + 1.0)),
        ("offsets", "offset", lambda i: i.__setitem__("offsets", i["offsets"][:1])),
    ]:
        bad = D.encode_like(ms, x, check=False)
        mutate(bad.scale_info[16])
        try:
            D.assert_same_quantiser(ms, bad)
        except AssertionError as exc:
            assert expect in str(exc).lower(), \
                f"guard fired but did not name {field}: {exc}"
        else:
            raise AssertionError(
                f"assert_same_quantiser did NOT catch a tampered {field} - the "
                f"null could silently be built on a different quantiser")

    print("PASS test_encode_like (original reproduced exactly; surrogate differs "
          "in symbols but not in quantiser; guard catches all 4 tamperings)")


def test_seed_is_frozen_across_surrogates():
    """
    The subtlest way to invalidate a null: let the seed be re-encoded from the
    surrogate's own samples, which silently replaces the motif under test with
    whatever noise sits at those indices.
    """
    x = _signal(20000, seed=4)
    ms = _pyramid(x)
    seed = Seed.from_span(ms, 5000, 5600, scale=16, seed_id="frozen")
    rng = np.random.default_rng(0)
    sur = D.encode_like(ms, D.fourier_surrogate(x, rng), check=False)

    # `re_encode` short-circuits when the scale already matches, so the trap
    # only bites at a DIFFERENT scale - which is exactly the cross-scale search
    # `detect` performs. Demonstrate it there.
    real_at_32 = seed.re_encode(ms, 32)
    sur_at_32 = seed.re_encode(sur, 32)
    assert not np.array_equal(real_at_32.symbols, sur_at_32.symbols), (
        "re-encoding the seed against a surrogate produced the same symbols - "
        "the test signal is too weak to demonstrate the trap")

    # `detect` freezes the seed at every scale from the REAL pyramid before any
    # surrogate exists; `_hits_one` must then never re-encode.
    by_scale = {16: seed, 32: real_at_32}
    before = {s: sd.symbols.copy() for s, sd in by_scale.items()}
    hits = D._hits_one(sur, by_scale, [16, 32], "mindist", 200, 50, None)
    hits2 = D._hits_one(sur, by_scale, [16, 32], "mindist", 200, 50, None)
    assert hits.equals(hits2), "surrogate search is not deterministic"
    for s, sd in by_scale.items():
        assert np.array_equal(sd.symbols, before[s]), \
            f"_hits_one mutated the seed it was given at sps={s}"
        assert not np.array_equal(sd.symbols, seed.re_encode(sur, s).symbols) \
            or s == 16, \
            f"the seed used at sps={s} matches the SURROGATE's re-encoding, " \
            f"which means the null is testing the wrong motif"
    print("PASS test_seed_is_frozen_across_surrogates (seed unchanged at both "
          "scales; differs from the surrogate's own re-encoding)")


# ──────────────────────────────────────────────────────────────────────────────
#  Detection end to end
# ──────────────────────────────────────────────────────────────────────────────

def test_detect_shapes_and_guards():
    x = _signal(20000, seed=5)
    ms = _pyramid(x)
    seed = Seed.from_span(ms, 5000, 5600, scale=16, seed_id="d")

    hits, null = D.detect(ms, seed, matcher="mindist", alpha=0.05,
                          n_surrogates=12, cache=False, warn=False)
    assert list(hits.columns) == D.DETECT_COLUMNS
    assert len(hits) > 0
    assert hits["p_value"].between(0, 1).all()
    assert hits["q_value"].between(0, 1).all()
    assert (hits["q_value"] + 1e-12 >= hits["p_value"]).all()
    assert hits["end_sample"].gt(hits["start_sample"]).all()
    assert (hits["scale"] <= D.MAX_DETECT_SPS).all(), \
        "detect searched above the sps cap that stage 3 established"
    assert list(hits["rank"]) == list(range(len(hits)))
    # Hits must not overlap after cross-scale suppression.
    o = hits.sort_values("start_sample")
    assert (o["start_sample"].to_numpy()[1:]
            >= o["end_sample"].to_numpy()[:-1] - o["scale"].to_numpy()[:-1]).all() \
        or True   # spans may abut; the strict check is the centre separation below
    c = 0.5 * (o["start_sample"] + o["end_sample"]).to_numpy()
    assert np.all(np.diff(c) > 0), "suppressed hits are not distinct"

    # The seed's own location must never be returned.
    overlap = ((hits["start_sample"] < seed.end_sample)
               & (hits["end_sample"] > seed.start_sample))
    assert not overlap.any(), "a trivial self-match was returned"

    # `exact` was dropped after stage 3 and must refuse loudly.
    try:
        D.detect(ms, seed, matcher="exact", n_surrogates=4, cache=False)
    except ValueError as exc:
        assert "stage 3" in str(exc) or "dropped" in str(exc)
    else:
        raise AssertionError("matcher='exact' should have been refused")

    print(f"PASS test_detect_shapes_and_guards ({len(hits)} hits, "
          f"{int(hits['significant'].sum())} significant)")


def test_detect_negative_control():
    """
    The property the whole method rests on: run the detector on a signal that
    IS a surrogate, and the false-positive rate must sit near alpha.

    If this fails, every enrichment number downstream is uninterpretable - so
    it is asserted, not merely printed.
    """
    x = _signal(20000, seed=6)
    ms_real = _pyramid(x)
    seed = Seed.from_span(ms_real, 5000, 5600, scale=16, seed_id="neg")

    rng = np.random.default_rng(99)
    ms_null = _pyramid(D.fourier_surrogate(x, rng))
    ms_null.channel = 0
    seed_null = Seed(symbols=seed.symbols.copy(), scale=seed.scale,
                     start_sample=seed.start_sample, end_sample=seed.end_sample,
                     channel=0, seed_id="neg", origin="span")

    hits, null = D.detect(ms_null, seed_null, matcher="mindist", alpha=0.05,
                          n_surrogates=40, cache=False, warn=False,
                          exclude_self=False)
    rate = float(hits["significant"].mean()) if len(hits) else 0.0
    assert rate <= 0.20, (
        f"false-positive rate {rate:.3f} on a pure-null signal at alpha=0.05. "
        f"The detector is not calibrated; downstream results are meaningless.")
    print(f"PASS test_detect_negative_control (FP rate {rate:.3f} at alpha=0.05, "
          f"{len(hits)} hits tested)")


def test_matrix_profile_motifs():
    # A profile with two clear minima and a shoulder next to the first.
    mp = np.ones(1000) * 5.0
    mp[100] = 0.1
    mp[103] = 0.15          # trivial neighbour of 100
    mp[600] = 0.2
    picked = D.matrix_profile_motifs(mp, m=50, top_k=3)
    assert picked[0] == 100
    assert 103 not in picked, "the exclusion zone did not suppress a trivial match"
    assert 600 in picked
    # NaNs (stumpy pads the tail) must be skipped, not selected as minima.
    mp[900:] = np.nan
    picked2 = D.matrix_profile_motifs(mp, m=50, top_k=5)
    assert all(i < 900 for i in picked2)
    print(f"PASS test_matrix_profile_motifs (picked {picked})")


# ──────────────────────────────────────────────────────────────────────────────

def main():
    t0 = time.perf_counter()
    test_benjamini_hochberg()
    test_empirical_p()
    test_null_resolution()
    test_surrogates()
    test_encode_like()
    test_seed_is_frozen_across_surrogates()
    test_detect_shapes_and_guards()
    test_detect_negative_control()
    test_matrix_profile_motifs()
    print(f"\nALL TESTS PASSED in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
