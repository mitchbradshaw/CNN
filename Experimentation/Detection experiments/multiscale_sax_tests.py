"""
multiscale_sax_tests.py
=======================
Plain assert-based tests for multiscale_sax.MultiScaleSAX.

Style matches tests/ in this repo: plain asserts, no pytest fixtures.
Run directly::

    python "Experimentation/Detection experiments/multiscale_sax_tests.py"
    python "Experimentation/Detection experiments/multiscale_sax_tests.py" --bench

`--bench` additionally times a full real channel; it is not part of the
correctness suite because it needs DATA/ on disk.

The two substantive tests are `test_variance` and `test_offsets`.  Both exist
to put a design decision under assertion rather than in a comment, so that if
someone later "simplifies" the renormalisation or the offset sweep away, the
suite fails and says why.
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

from multiscale_sax import MultiScaleSAX, expand_scales, resolve_offsets


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

def normalised_entropy(hist: np.ndarray) -> float:
    """
    Shannon entropy of a symbol histogram, divided by log2(alphabet).

    1.0 = every symbol equally used; 0.0 = one symbol carries everything.
    Used instead of a raw max/min bin ratio as the primary collapse statistic
    because it degrades smoothly and does not become inf the moment a single
    symbol goes unused.
    """
    h = np.asarray(hist, dtype=float)
    h = h[h > 0]
    if len(h) <= 1:
        return 0.0
    return float(-(h * np.log2(h)).sum() / np.log2(len(hist)))


def total_variation(p: np.ndarray, q: np.ndarray) -> float:
    """Total-variation distance between two normalised histograms, in [0, 1]."""
    return float(0.5 * np.abs(np.asarray(p) - np.asarray(q)).sum())


def _drifting_signal(n: int, seed: int = 0) -> np.ndarray:
    """
    A stand-in for a mycelium channel: slow drift dominates, small fast noise.

    Not a claim about the real biology — just a signal whose PAA distribution
    is non-Gaussian and drift-heavy, so the tests are not accidentally passing
    on white noise alone.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    drift = np.cumsum(rng.normal(0, 1, n)) * 0.01
    slow = 0.4 * np.sin(2 * np.pi * t / 20000) + 0.2 * np.sin(2 * np.pi * t / 3300)
    return drift + slow + rng.normal(0, 0.02, n)


# ──────────────────────────────────────────────────────────────────────────────
#  1. Scale ladder validation
# ──────────────────────────────────────────────────────────────────────────────

def test_scale_expansion():
    assert expand_scales((2, 4096)) == [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096]
    assert expand_scales((8, 8)) == [8]
    assert expand_scales([64, 4, 16]) == [4, 16, 64]
    assert expand_scales(32) == [32]

    # Non-dyadic scales must be rejected: they break exact coarse->fine nesting.
    for bad in ([3], [10], [2, 6], [1]):
        try:
            expand_scales(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expand_scales({bad}) should have raised")

    # A 2-tuple is a range, not a literal pair; a 3-tuple is meaningless.
    try:
        expand_scales((2, 4, 8))
    except ValueError:
        pass
    else:
        raise AssertionError("3-tuple scales should have raised")

    # Physical durations at fs = 1 Hz: sps=4096 is the ~68 min top of the range.
    ms = MultiScaleSAX(_drifting_signal(60000, 0), fs=1.0, method="psax",
                       scales=(2, 4096), alphabet_size=8,
                       cutline_mode="per_scale", offsets="zero", random_state=0)
    assert abs(ms.scale_info[4096]["minutes"] - 68.2667) < 1e-3
    assert abs(ms.scale_info[512]["seconds"] - 512.0) < 1e-9
    print("PASS test_scale_expansion "
          f"(sps=4096 -> {ms.scale_info[4096]['minutes']:.1f} min at fs=1 Hz)")


# ──────────────────────────────────────────────────────────────────────────────
#  2. Index mapping round-trips
# ──────────────────────────────────────────────────────────────────────────────

def test_index_mapping():
    """
    Round-trip symbol span -> samples -> symbol span for EVERY scale and EVERY
    computed offset.  This is the mapping every later stage depends on; an
    off-by-one here produces plausible-looking but wrong motif locations, which
    is exactly the class of bug that never announces itself.
    """
    x = _drifting_signal(40000, 1)
    ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=(2, 2048), alphabet_size=8,
                       cutline_mode="shared_renormalised", offsets="all",
                       max_offsets=8, random_state=0)

    n_checked = 0
    for s in ms.scales:
        for o in ms.offsets_for(s):
            n = ms.n_symbols(s, o)
            sym = ms.symbols(s, o)
            assert len(sym) == n

            # Each symbol covers exactly `s` samples, starting at the offset.
            a, b = ms.symbol_span_to_samples(s, o, 0, 0)
            assert (a, b) == (o, o + s), f"first symbol span wrong at s={s} o={o}"
            a, b = ms.symbol_span_to_samples(s, o, n - 1, n - 1)
            assert (a, b) == (o + (n - 1) * s, o + n * s)

            # Encoded region never runs past the signal, and nothing is padded.
            assert b <= len(x), f"encoding overruns the signal at s={s} o={o}"
            head, tail = ms.dropped(s, o)
            assert head == o
            assert head + tail + n * s == len(x), \
                f"dropped-sample accounting does not close at s={s} o={o}"
            assert 0 <= tail < s

            # Forward round-trip must be an exact identity for every span.
            probes = {(0, 0), (0, n - 1), (n - 1, n - 1)}
            step = max(1, n // 17)
            for i in range(0, n, step):
                for j in (i, min(i + 3, n - 1), min(i + step, n - 1)):
                    probes.add((i, j))
            for i, j in probes:
                start, end = ms.symbol_span_to_samples(s, o, i, j)
                assert end - start == (j - i + 1) * s
                assert ms.samples_to_symbol_span(s, o, start, end) == (i, j), \
                    f"round-trip failed at s={s} o={o} span=({i},{j})"
                n_checked += 1

            # Reverse direction rounds OUTWARD to a covering span (documented as
            # not an identity): a range starting one sample into symbol i must
            # still report i, and ending one sample into symbol j must report j.
            if n >= 3 and s >= 2:
                i, j = 1, min(3, n - 1)
                start, end = ms.symbol_span_to_samples(s, o, i, j)
                assert ms.samples_to_symbol_span(s, o, start + 1, end - 1) == (i, j)
                assert ms.samples_to_symbol_span(s, o, start - 1, end) == (i - 1, j)

            # Out-of-range spans raise instead of silently clipping.
            for bad in ((-1, 0), (0, n), (2, 1)):
                try:
                    ms.symbol_span_to_samples(s, o, *bad)
                except IndexError:
                    pass
                else:
                    raise AssertionError(f"span {bad} should have raised at s={s} o={o}")

    print(f"PASS test_index_mapping ({n_checked} round-trips across "
          f"{len(ms.encodings)} (scale, offset) encodings)")


# ──────────────────────────────────────────────────────────────────────────────
#  3. Constant signal
# ──────────────────────────────────────────────────────────────────────────────

def test_constant_signal():
    """A constant signal has no structure at any resolution -> one symbol."""
    x = np.full(8000, 3.7)
    for method in ("psax", "csax"):
        for mode in ("per_scale", "shared_renormalised"):
            ms = MultiScaleSAX(x, fs=1.0, method=method, scales=(2, 256),
                               alphabet_size=8, cutline_mode=mode,
                               offsets="zero", random_state=0)
            for s in ms.scales:
                uniq = np.unique(ms.symbols(s))
                assert len(uniq) == 1, \
                    f"constant signal gave {len(uniq)} symbols at s={s} " \
                    f"({method}/{mode}) — quantiser is inventing structure"
            # Degenerate spread must be handled by mean-centring, not by
            # dividing through a ~0 std.
            assert all(ms.scale_info[s]["paa_std"] < 1e-9 for s in ms.scales)
    print("PASS test_constant_signal (psax+csax x per_scale+shared_renormalised)")


# ──────────────────────────────────────────────────────────────────────────────
#  4. Linear ramp
# ──────────────────────────────────────────────────────────────────────────────

def test_linear_ramp():
    """
    A monotone ramp must give a monotone non-decreasing symbol sequence at every
    scale.  This is the test that catches a PAA reshape-order bug: grouping the
    wrong axis scrambles segment order and breaks monotonicity immediately.
    """
    x = np.arange(8000, dtype=float)
    for method in ("psax", "csax"):
        for mode in ("per_scale", "shared_renormalised"):
            ms = MultiScaleSAX(x, fs=1.0, method=method, scales=(2, 256),
                               alphabet_size=8, cutline_mode=mode,
                               offsets="zero", random_state=0)
            for s in ms.scales:
                sym = ms.symbols(s)
                assert np.all(np.diff(sym) >= 0), \
                    f"ramp gave a non-monotone encoding at s={s} ({method}/{mode})"
                assert sym[0] < sym[-1], f"ramp collapsed to one symbol at s={s}"

                # The realised alphabet must be recorded honestly and agree
                # with the cutlines actually stored.
                info = ms.scale_info[s]
                assert info["alphabet_size"] == len(info["cutlines"]) + 1
                assert len(info["representatives"]) == info["alphabet_size"]
                assert np.all(np.diff(info["cutlines"]) > 0)

    # cSAX discovers its alphabet rather than being told it, so under
    # per_scale the realised alphabet legitimately shrinks at coarse scales.
    # Asserted here so the caveat in the class docstring is not just prose.
    ms = MultiScaleSAX(x, fs=1.0, method="csax", scales=(2, 256), alphabet_size=8,
                       cutline_mode="per_scale", offsets="zero", random_state=0)
    realised = [ms.scale_info[s]["alphabet_size"] for s in ms.scales]
    assert min(realised) < 8, \
        "expected cSAX to realise a smaller alphabet at some coarse scale"
    print(f"PASS test_linear_ramp (cSAX realised alphabets per scale: {realised})")


# ──────────────────────────────────────────────────────────────────────────────
#  5. THE VARIANCE TEST
# ──────────────────────────────────────────────────────────────────────────────

def test_variance():
    """
    Why "shared_renormalised" exists, stated as assertions rather than a comment.

    PAA is an averaging operator, so for noise-like input the std of the PAA
    sequence falls as ~1/sqrt(samples_per_symbol).  Cutlines learned at a fine
    scale therefore sit far out in the tails of a coarse scale's distribution,
    and the coarse scales collapse into one or two symbols.

    Asserted here:
      (a) the 1/sqrt(sps) shrinkage is real (so the problem is not imaginary);
      (b) with renormalisation, every scale keeps a near-full alphabet AND
          essentially the same symbol histogram as the finest scale — which is
          precisely what makes symbols comparable across scales;
      (c) without renormalisation ("shared_raw"), the coarse scales collapse.

    On the "roughly uniform" criterion
    ----------------------------------
    A max/min bin ratio below 3 is NOT achievable here, and its absence is not
    a bug.  Lloyd-Max (pSAX) is MSE-optimal, not entropy-optimal: on Gaussian
    input its 8-level solution has bin probabilities of roughly
    [.03 .09 .15 .19 .20 .17 .12 .04], a max/min ratio near 6, by construction.
    The meaningful statement is that the histogram does not COLLAPSE and does
    not CHANGE with scale, so the thresholds below are set from measurement:
    renormalised runs land at ratio 5.0-7.5 and normalised entropy >= 0.93,
    while the naive shared-cutline runs reach ratio inf and entropy <= 0.32.
    """
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, 600000)          # white noise: the clean, analysable case
    scales = (2, 512)

    ENTROPY_FLOOR = 0.85        # measured >= 0.93 across seeds
    RATIO_LIMIT = 12.0          # measured <= 7.5 across seeds
    TV_LIMIT = 0.10             # measured <= 0.030 across seeds
    COLLAPSE_ENTROPY = 0.50     # naive coarse scale measured <= 0.32

    good = MultiScaleSAX(x, fs=1.0, method="psax", scales=scales, alphabet_size=8,
                         cutline_mode="shared_renormalised", offsets="zero",
                         random_state=11)
    naive = MultiScaleSAX(x, fs=1.0, method="psax", scales=scales, alphabet_size=8,
                          cutline_mode="shared_raw", offsets="zero",
                          random_state=11)

    # (a) The shrinkage that motivates the whole design.
    finest = good.scales[0]
    base_std = good.scale_info[finest]["paa_std"]
    for s in good.scales:
        expected = base_std * np.sqrt(finest / s)
        got = good.scale_info[s]["paa_std"]
        assert abs(got - expected) / expected < 0.15, \
            f"PAA std at s={s} is {got:.4f}, expected ~{expected:.4f} (1/sqrt(sps) law)"
    total_shrink = base_std / good.scale_info[good.scales[-1]]["paa_std"]

    # (b) Renormalised: alphabet stays in use, and the histogram is stable.
    ref_hist = good.symbol_histogram(finest)
    rows = []
    for s in good.scales:
        h = good.symbol_histogram(s)
        H = normalised_entropy(h)
        ratio = good.occupancy_ratio(s)
        tv = total_variation(h, ref_hist)
        rows.append((s, H, ratio, tv))
        assert H >= ENTROPY_FLOOR, \
            f"shared_renormalised entropy {H:.3f} < {ENTROPY_FLOOR} at s={s}"
        assert ratio < RATIO_LIMIT, \
            f"shared_renormalised max/min bin ratio {ratio:.2f} >= {RATIO_LIMIT} at s={s}"
        assert tv < TV_LIMIT, \
            f"shared_renormalised histogram drifted TV={tv:.3f} from the finest " \
            f"scale at s={s} — symbols are no longer comparable across scales"

    # (c) Naive shared cutlines: assert the collapse HAPPENS.  If this ever
    #     starts failing, the renormalisation has become unnecessary and this
    #     module's central design decision should be revisited.
    naive_rows = []
    for s in naive.scales:
        h = naive.symbol_histogram(s)
        naive_rows.append((s, normalised_entropy(h), naive.occupancy_ratio(s), h.max()))

    coarsest = naive.scales[-1]
    h_coarse = naive.symbol_histogram(coarsest)
    H_coarse = normalised_entropy(h_coarse)
    assert H_coarse < COLLAPSE_ENTROPY, \
        f"expected the naive shared-cutline encoding to collapse at s={coarsest}, " \
        f"but entropy is {H_coarse:.3f}"
    assert h_coarse.max() > 0.80, \
        f"expected one symbol to swallow >80% of the coarsest scale; got {h_coarse.max():.3f}"
    assert np.count_nonzero(h_coarse) <= 3, \
        f"expected <=3 symbols in use at the collapsed coarsest scale; " \
        f"got {np.count_nonzero(h_coarse)}"
    # Collapse must be progressive with scale, not a single-scale artefact.
    naive_entropies = [r[1] for r in naive_rows]
    assert naive_entropies[-1] < naive_entropies[0] - 0.5

    print("PASS test_variance")
    print(f"       PAA std shrinks {base_std:.4f} -> "
          f"{good.scale_info[good.scales[-1]]['paa_std']:.4f} "
          f"(x{total_shrink:.1f} over sps 2->512, 1/sqrt(sps) law holds)")
    print(f"       {'sps':>5} | {'renorm H':>8} {'ratio':>7} {'TV':>6} | "
          f"{'naive H':>8} {'ratio':>8} {'maxbin':>7}")
    for (s, H, ratio, tv), (_, nH, nratio, nmax) in zip(rows, naive_rows):
        print(f"       {s:>5} | {H:>8.3f} {ratio:>7.2f} {tv:>6.3f} | "
              f"{nH:>8.3f} {nratio:>8.2f} {nmax:>7.3f}")


# ──────────────────────────────────────────────────────────────────────────────
#  6. THE OFFSET TEST
# ──────────────────────────────────────────────────────────────────────────────

def test_offsets():
    """
    What the phase-offset sweep actually buys.

    The same 200-sample motif is written twice into the signal, the second time
    shifted by s/2 samples.  The two occurrences are byte-identical, so any
    difference in their encodings is purely an artefact of the PAA segmentation
    grid.

    Asserted:
      - at offsets="zero" the two encodings differ (the artefact is real);
      - at offsets="all" some offset encodes occurrence 2 exactly as occurrence
        1 was encoded at offset 0 (the sweep removes the artefact);
      - that offset is s/2, as the construction predicts.

    The reported Hamming profile quantifies the gain: symbols wrong out of 25.
    """
    S, L = 8, 200
    P1 = 4000                 # aligned to the offset-0 grid
    P2 = 12000 + S // 2       # deliberately half a segment out of phase

    rng = np.random.default_rng(7)
    t = np.arange(L)
    motif = (1.5 * np.sin(2 * np.pi * t / 50)
             + 0.9 * np.sin(2 * np.pi * t / 13)
             + 1.2 * (t >= 100))

    n = 20000
    x = 0.05 * rng.normal(0, 1, n) + 0.3 * np.sin(2 * np.pi * np.arange(n) / 9000)
    # Overwrite, not add: the two occurrences must be identical samples, or the
    # test would be measuring background noise instead of phase sensitivity.
    x[P1:P1 + L] = motif
    x[P2:P2 + L] = motif
    assert np.array_equal(x[P1:P1 + L], x[P2:P2 + L])

    ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=[S], alphabet_size=8,
                       cutline_mode="shared_renormalised", offsets="all",
                       random_state=0)
    assert ms.offsets_for(S) == list(range(S)), "expected the full sweep at s=8"

    sym0 = ms.symbols(S, 0)
    i1, j1 = ms.samples_to_symbol_span(S, 0, P1, P1 + L)
    ref = sym0[i1:j1 + 1]
    assert len(ref) == L // S == 25

    # offsets="zero": only the phase-0 grid is available, so occurrence 2 must
    # be read off the nearest aligned symbols.
    naive = sym0[P2 // S: P2 // S + len(ref)]
    naive_ham = int((naive != ref).sum())
    assert not np.array_equal(naive, ref), \
        "the shifted occurrence encoded identically at offset 0 — the motif is " \
        "too smooth for this test to mean anything"

    # offsets="all": sweep, comparing the exact covering span at each offset.
    profile, matches = [], []
    for o in ms.offsets_for(S):
        i, j = ms.samples_to_symbol_span(S, o, P2, P2 + L)
        sy = ms.symbols(S, o)[i:j + 1]
        if len(sy) == len(ref):
            ham = int((sy != ref).sum())
            if ham == 0:
                matches.append(o)
        else:
            # A span that needs an extra symbol is already misaligned; score it
            # on the overlap plus the length mismatch so the profile is comparable.
            m = min(len(sy), len(ref))
            ham = int((sy[:m] != ref[:m]).sum()) + abs(len(sy) - len(ref))
        profile.append((o, len(sy), ham))

    assert matches, "no offset reproduced the motif encoding — the sweep buys nothing"
    assert matches == [S // 2], \
        f"expected the aligned offset to be s/2={S // 2}; got {matches}"

    # Independent check via encode_segment: re-encoding the raw motif with the
    # learned cutlines must reproduce the reference symbols without retraining.
    assert np.array_equal(ms.encode_segment(x[P2:P2 + L], S), ref), \
        "encode_segment disagreed with the swept encoding"

    best_swept = min(h for _, _, h in profile)
    print("PASS test_offsets")
    print(f"       offsets='zero'  -> {naive_ham}/25 symbols wrong "
          f"({100 * naive_ham / 25:.0f}% of the motif encoding)")
    print(f"       offsets='all'   -> exact match at offset {matches[0]} "
          f"(0/25 wrong); best over sweep = {best_swept}/25")
    print(f"       {'offset':>7} {'span':>5} {'hamming':>8}")
    for o, ln, ham in profile:
        print(f"       {o:>7} {ln:>5} {ham:>8}")


# ──────────────────────────────────────────────────────────────────────────────
#  7. encode_segment (no retraining)
# ──────────────────────────────────────────────────────────────────────────────

def test_encode_segment():
    """
    A raw segment re-encoded with already-learned cutlines must reproduce the
    corresponding slice of the full encoding, exactly, in every cutline mode.

    This is what stage 3 relies on to re-encode a seed at a different scale, so
    "close enough" is not good enough — it must be bit-identical.
    """
    x = _drifting_signal(30000, 3)
    for mode in ("per_scale", "shared_renormalised", "shared_raw"):
        ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=(2, 512),
                           alphabet_size=8, cutline_mode=mode,
                           offsets="zero", random_state=0)
        for s in ms.scales:
            full = ms.symbols(s, 0)
            a, b = 10 * s, 10 * s + 40 * s          # aligned to the offset-0 grid
            assert np.array_equal(ms.encode_segment(x[a:b], s), full[a // s: b // s]), \
                f"encode_segment disagreed with the full encoding at s={s} ({mode})"

        # A seed can be re-encoded at a scale other than the one it came from.
        seed = x[5000:5000 + 4096]
        for s in ms.scales:
            assert len(ms.encode_segment(seed, s)) == 4096 // s

        # Too-short segments raise rather than padding.
        try:
            ms.encode_segment(x[:3], 512)
        except ValueError:
            pass
        else:
            raise AssertionError("a sub-symbol segment should have raised")

        # Untrained scales raise rather than silently retraining.
        try:
            ms.encode_segment(x[:4096], 8192)
        except KeyError:
            pass
        else:
            raise AssertionError("an untrained scale should have raised")

    print("PASS test_encode_segment (all 3 cutline modes, exact agreement)")


# ──────────────────────────────────────────────────────────────────────────────
#  8. Numerosity reduction keeps the mapping exact
# ──────────────────────────────────────────────────────────────────────────────

def test_numerosity_reduction():
    x = _drifting_signal(30000, 5)
    ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=[16, 64], alphabet_size=8,
                       cutline_mode="shared_renormalised", offsets="zero",
                       numerosity_reduction=True, random_state=0)

    for s in [16, 64]:
        e = ms.encodings[(s, 0)]
        sym, nr, lens, starts = (e["symbols"], e["nr_symbols"],
                                 e["nr_run_lengths"], e["nr_run_starts"])

        assert len(nr) == len(lens) == len(starts)
        assert len(nr) <= len(sym)
        assert lens.sum() == len(sym), "run lengths must account for every symbol"
        assert np.all(np.diff(nr) != 0), "adjacent runs must differ — not collapsed"
        assert np.array_equal(np.repeat(nr, lens), sym), \
            "expanding the runs must reconstruct the full sequence exactly"

        # The mapping in (4) still works after collapsing.
        for r in range(len(nr)):
            i, j = ms.nr_run_to_symbol_span(s, 0, r)
            assert i == starts[r] and j - i + 1 == lens[r]
            assert np.all(sym[i:j + 1] == nr[r])
            a, b = ms.nr_run_to_samples(s, 0, r)
            assert (a, b) == ms.symbol_span_to_samples(s, 0, i, j)
            assert b - a == lens[r] * s

    # Off by default, and asking for runs without enabling it raises.
    off = MultiScaleSAX(x, fs=1.0, method="psax", scales=[64], alphabet_size=8,
                        cutline_mode="shared_renormalised", offsets="zero",
                        random_state=0)
    assert "nr_symbols" not in off.encodings[(64, 0)]
    try:
        off.nr_run_to_symbol_span(64, 0, 0)
    except KeyError:
        pass
    else:
        raise AssertionError("nr accessors should raise when NR is disabled")

    e = ms.encodings[(64, 0)]
    print(f"PASS test_numerosity_reduction "
          f"({e['n_symbols']} symbols -> {len(e['nr_symbols'])} runs at sps=64)")


# ──────────────────────────────────────────────────────────────────────────────
#  9. Offset resolution and boundary accounting
# ──────────────────────────────────────────────────────────────────────────────

def test_offset_resolution_and_boundaries():
    # "all" is capped and evenly spaced, not truncated to the first N.
    assert resolve_offsets(8, "all", 16).tolist() == list(range(8))
    assert resolve_offsets(4096, "all", 16).tolist() == list(range(0, 4096, 256))
    assert resolve_offsets(4096, "zero", 16).tolist() == [0]
    assert resolve_offsets(64, [0, 7, 3], 16).tolist() == [0, 3, 7]
    try:
        resolve_offsets(8, [0, 9], 16)
    except ValueError:
        pass
    else:
        raise AssertionError("an out-of-range explicit offset should have raised")

    # A deliberately non-divisible length, so trimming is actually exercised.
    n = 40000 + 37
    x = _drifting_signal(n, 9)
    ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=(2, 4096), alphabet_size=8,
                       cutline_mode="shared_renormalised", offsets="all",
                       max_offsets=16, random_state=0)

    for s in ms.scales:
        recorded = ms.offsets_for(s)
        assert recorded == resolve_offsets(s, "all", 16).tolist(), \
            f"the computed offsets were not recorded faithfully at s={s}"
        assert len(recorded) == min(s, 16)
        for o in recorded:
            head, tail = ms.dropped(s, o)
            # Nothing is padded: every sample is either used or explicitly dropped.
            assert head + ms.n_symbols(s, o) * s + tail == n
            assert 0 <= tail < s

    # Cutlines are learned once per scale and shared across that scale's
    # offsets — re-learning per offset would make the offsets incomparable.
    info = ms.scale_info[256]
    assert info["n_train_points"] <= ms.max_train_points
    assert len(info["cutlines"]) == info["alphabet_size"] - 1

    # Scales longer than the signal are rejected rather than silently dropped.
    try:
        MultiScaleSAX(x[:500], fs=1.0, scales=[1024], cutline_mode="per_scale",
                      offsets="zero", random_state=0)
    except ValueError:
        pass
    else:
        raise AssertionError("an over-long scale should have raised")

    print(f"PASS test_offset_resolution_and_boundaries "
          f"(n={n}, {len(ms.encodings)} encodings, all sample budgets close)")


# ──────────────────────────────────────────────────────────────────────────────
#  10. Cross-scale comparability under shared_renormalised
# ──────────────────────────────────────────────────────────────────────────────

def test_cross_scale_units():
    """
    Under "shared_renormalised" every scale must apply the SAME cutlines in
    renormalised units, while `cutlines_raw` maps them back into that scale's
    own PAA units.  Stage 3's MINDIST needs both, and needs them consistent.
    """
    x = _drifting_signal(60000, 13)
    ms = MultiScaleSAX(x, fs=1.0, method="psax", scales=(2, 1024), alphabet_size=8,
                       cutline_mode="shared_renormalised", offsets="zero",
                       random_state=0)
    ref = ms.scale_info[ms.scales[0]]["cutlines"]
    for s in ms.scales:
        info = ms.scale_info[s]
        assert info["renormalised"] is True
        assert np.allclose(info["cutlines"], ref), \
            f"shared mode must reuse one set of cutlines; s={s} differs"
        # cutlines_raw is the same thresholds expressed in this scale's units.
        assert np.allclose(info["cutlines_raw"],
                           ref * info["paa_std"] + info["paa_mean"])
        assert np.all(np.diff(info["cutlines_raw"]) > 0)
        assert len(info["representatives_raw"]) == info["alphabet_size"]

    # Under per_scale the cutlines genuinely differ between scales, which is
    # exactly why symbols are not comparable across scales in that mode.
    ps = MultiScaleSAX(x, fs=1.0, method="psax", scales=(2, 1024), alphabet_size=8,
                       cutline_mode="per_scale", offsets="zero", random_state=0)
    a = ps.scale_info[ps.scales[0]]["cutlines"]
    b = ps.scale_info[ps.scales[-1]]["cutlines"]
    assert not np.allclose(a, b), \
        "per_scale produced identical cutlines at the extreme scales — " \
        "the modes are not actually different"
    for s in ps.scales:
        info = ps.scale_info[s]
        assert info["renormalised"] is False
        assert np.allclose(info["cutlines"], info["cutlines_raw"])

    print("PASS test_cross_scale_units")


# ──────────────────────────────────────────────────────────────────────────────
#  Benchmark (opt-in: needs DATA/ on disk)
# ──────────────────────────────────────────────────────────────────────────────

def bench(channel="DATA/derived/channels/M2_concat_fs1/CH2.npy", fs=1.0):
    """Wall-clock cost of one full channel at all scales, offsets='all' vs 'zero'."""
    path = _REPO_ROOT / channel
    if not path.exists():
        print(f"SKIP bench (channel not found: {path})")
        return

    x = np.load(path)
    print(f"\nBENCH {channel}: {len(x)} samples "
          f"({len(x) / fs / 3600:.1f} h at fs={fs} Hz)")
    print(f"{'method':>6} {'offsets':>8} {'n_enc':>7} {'train_s':>9} "
          f"{'encode_s':>9} {'total_s':>9}")
    for method in ("psax", "csax"):
        for off in ("zero", "all"):
            t0 = time.perf_counter()
            ms = MultiScaleSAX(x, fs=fs, method=method, scales=(2, 4096),
                               alphabet_size=8, cutline_mode="shared_renormalised",
                               offsets=off, max_offsets=16, random_state=0)
            wall = time.perf_counter() - t0
            print(f"{method:>6} {off:>8} {len(ms.encodings):>7} "
                  f"{ms.timings['train']:>9.2f} {ms.timings['encode']:>9.2f} "
                  f"{wall:>9.2f}")
            if method == "psax" and off == "zero":
                print(ms.describe())


# ──────────────────────────────────────────────────────────────────────────────

def main(run_bench=False):
    t0 = time.perf_counter()
    test_scale_expansion()
    test_index_mapping()
    test_constant_signal()
    test_linear_ramp()
    test_variance()
    test_offsets()
    test_encode_segment()
    test_numerosity_reduction()
    test_offset_resolution_and_boundaries()
    test_cross_scale_units()
    print(f"\nALL TESTS PASSED in {time.perf_counter() - t0:.1f}s")
    if run_bench:
        bench()


if __name__ == "__main__":
    main(run_bench="--bench" in _sys.argv)
