"""
run_sax_detection.py
====================
Calibrated seeded detection end to end, then cross-method validation against
three independent methods already in this repo.

    python "Experimentation/Detection experiments/run_sax_detection.py"
    python "Experimentation/Detection experiments/run_sax_detection.py" --quick
    python "Experimentation/Detection experiments/run_sax_detection.py" \
        --no-show --n-surrogates 200 --span 0:400000

Sections
--------
1. Sanity: does the calibration work at all? A positive control (synthetic
   signal with a planted motif) and a negative control (the same detector run
   on a surrogate, where the false-positive rate must land near alpha). If the
   negative control is not calibrated, nothing downstream is interpretable.
2. Surrogate comparison: fourier vs IAAFT vs block bootstrap, on the same seed.
3. Scale signature for one seed.
4. Real channel: detection with a seed from a human-labelled "interesting"
   10-minute window.
5. Cross-method validation - the headline:
     - stumpy matrix-profile motifs (Jaccard on sample spans)
     - ruptures change points (distance to nearest, vs a permutation null)
     - manual labels + CNN scores (odds ratio with confidence interval)

Carried forward from stage 3, deliberately: the detector defaults to the
mindist->edit cascade, `exact` is gone, and the ladder is capped at sps<=128.

Preprocessing differs between the two halves, for a measured reason. Stage 3
preferred `detrend` on synthetic data (recall 0.85 vs 0.61). On this real
channel `detrend` leaves 90% of symbols in one bin, so every observed and
surrogate distance collapses to 0.0 and the significance test has NO POWER -
which reads as a clean negative if you are not looking. The real-channel
sections therefore use `rolling_z`, which lifts the realised alphabet from 38%
to 100%. `sax_detection.detect` carries a power guard that refuses to let a
degenerate test be reported as a negative result.

Nothing is saved unless --save-dir is given. Run from the repo root.
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

import argparse
import json
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from Working.database.schema import get_connection
from Working.database.queries import list_annotations, get_recording_by_id
from Working.Detection.rupture.rupture_detect import detect_change_points

from multiscale_sax import MultiScaleSAX
from sax_seed_search import Seed
import run_seed_search as S3
import sax_detection as D

FS = 1.0
MOTIF_LEN = 600
ALPHABET = 8
DETECT_SCALES = (8, 128)          # stage 3: MINDIST prunes nothing above 128


def rule(title):
    print("\n" + "=" * 78)
    print(f"  {title}")
    print("=" * 78)


def build(sig, offsets="zero", max_offsets=8):
    return MultiScaleSAX(sig, fs=FS, method="psax", scales=DETECT_SCALES,
                         alphabet_size=ALPHABET,
                         cutline_mode="shared_renormalised",
                         offsets=offsets, max_offsets=max_offsets, random_state=0)


# ──────────────────────────────────────────────────────────────────────────────
#  Overlap / enrichment statistics
# ──────────────────────────────────────────────────────────────────────────────

def spans_to_mask(spans, n):
    """Boolean sample mask from a list of (start, end) spans."""
    m = np.zeros(n, dtype=bool)
    for a, b in spans:
        m[max(0, int(a)):min(n, int(b))] = True
    return m


def jaccard(spans_a, spans_b, n):
    """Jaccard index on sample coverage - not on span counts."""
    a, b = spans_to_mask(spans_a, n), spans_to_mask(spans_b, n)
    union = np.count_nonzero(a | b)
    return float(np.count_nonzero(a & b) / union) if union else 0.0


def jaccard_null(spans_a, spans_b, n, n_perm=500, rng=None):
    """
    Jaccard against a null that circularly shifts one set of spans.

    Circular shift preserves the number of spans and their lengths - the two
    things that drive Jaccard mechanically - so what remains is co-location.
    Comparing a raw Jaccard against zero would be meaningless: two methods that
    each mark 20% of a recording overlap ~4% by arithmetic alone.
    """
    rng = rng or np.random.default_rng(0)
    obs = jaccard(spans_a, spans_b, n)
    null = np.empty(n_perm)
    for k in range(n_perm):
        sh = int(rng.integers(0, n))
        shifted = [((a + sh) % n, (a + sh) % n + (b - a)) for a, b in spans_a]
        null[k] = jaccard(shifted, spans_b, n)
    p = (1.0 + np.count_nonzero(null >= obs)) / (1.0 + n_perm)
    return {"jaccard": obs, "null_mean": float(null.mean()),
            "null_p95": float(np.percentile(null, 95)), "p_value": float(p),
            "ratio": obs / null.mean() if null.mean() > 0 else np.inf}


def distance_to_nearest(points, targets):
    """Distance from each point to the nearest target."""
    if len(targets) == 0 or len(points) == 0:
        return np.array([np.nan])
    t = np.sort(np.asarray(targets, dtype=float))
    p = np.asarray(points, dtype=float)
    idx = np.clip(np.searchsorted(t, p), 1, len(t) - 1)
    return np.minimum(np.abs(p - t[idx - 1]), np.abs(p - t[idx]))


def changepoint_proximity(spans, bkps, n, n_perm=500, rng=None):
    """
    Are detection boundaries nearer change points than chance?

    Null: the same number of boundaries placed uniformly at random. Reports the
    median distance and a permutation p-value. A detector that fires on drift
    steps will beat this easily; one that fires on shape will not necessarily,
    and that is informative either way.
    """
    rng = rng or np.random.default_rng(0)
    if len(spans) == 0 or len(bkps) == 0:
        return {"median_dist": np.nan, "null_median": np.nan, "p_value": np.nan}
    edges = np.array([e for s in spans for e in (s[0], s[1])], dtype=float)
    obs = float(np.median(distance_to_nearest(edges, bkps)))
    null = np.empty(n_perm)
    for k in range(n_perm):
        rand_edges = rng.uniform(0, n, size=len(edges))
        null[k] = float(np.median(distance_to_nearest(rand_edges, bkps)))
    p = (1.0 + np.count_nonzero(null <= obs)) / (1.0 + n_perm)
    return {"median_dist": obs, "null_median": float(null.mean()),
            "p_value": float(p),
            "ratio": obs / null.mean() if null.mean() > 0 else np.nan}


def odds_ratio_ci(a, b, c, d):
    """
    Odds ratio for a 2x2 table with a 95% CI.

        a = significant & interesting      b = significant & not
        c = not significant & interesting  d = not significant & not

    Uses scipy's conditional MLE odds ratio when available, else a Woolf
    log-OR interval with the Haldane-Anscombe +0.5 correction (which is what
    keeps a zero cell from producing an infinite point estimate).
    """
    try:
        from scipy.stats import contingency, fisher_exact
        res = contingency.odds_ratio([[a, b], [c, d]])
        ci = res.confidence_interval(confidence_level=0.95)
        _, p = fisher_exact([[a, b], [c, d]])
        return {"odds_ratio": float(res.statistic), "lo": float(ci.low),
                "hi": float(ci.high), "p_value": float(p), "method": "conditional MLE"}
    except Exception:                                          # noqa: BLE001
        A, B, C, Dd = a + 0.5, b + 0.5, c + 0.5, d + 0.5
        orat = (A * Dd) / (B * C)
        se = np.sqrt(1 / A + 1 / B + 1 / C + 1 / Dd)
        return {"odds_ratio": float(orat),
                "lo": float(orat * np.exp(-1.96 * se)),
                "hi": float(orat * np.exp(1.96 * se)),
                "p_value": np.nan, "method": "Woolf + Haldane-Anscombe"}


# ──────────────────────────────────────────────────────────────────────────────
#  1. Calibration
# ──────────────────────────────────────────────────────────────────────────────

def calibration(args):
    """
    Positive and negative control.

    The negative control is the one that matters: run the identical detector on
    a signal that IS a surrogate, where by construction there is nothing to
    find. The realised false-positive rate must land near alpha. If it does
    not, every downstream number is uninterpretable, so this runs first.
    """
    rule("1. CALIBRATION - positive and negative control")
    n = 40_000 if args.quick else 120_000
    ns = 40 if args.quick else args.n_surrogates

    x, truth, span = S3.make_synthetic(n=n, seed=0)
    # rolling_z, NOT detrend. Stage 3 preferred detrend for synthetic recall,
    # but on this real channel detrend leaves 90% of symbols in a single bin,
    # every observed and surrogate distance collapses to 0.0, and the
    # significance test has no power at all. rolling_z raises the realised
    # alphabet from 38% to 100% and gives a null with actual spread. See the
    # power guard in sax_detection.detect.
    sig = S3.rolling_z(x, args.preproc_window)
    ms = build(sig)
    ms.channel = 0
    seed = Seed.from_span(ms, span[0], span[1], scale=16, seed_id="synthetic")
    print(f"  synthetic: {n} samples, 12 planted instances, "
          f"seed uses {D.seed_alphabet_fraction(ms, seed):.0%} of the alphabet")

    t0 = time.perf_counter()
    hits, null = D.detect(ms, seed, matcher="cascade", alpha=args.alpha,
                          surrogate="fourier", n_surrogates=ns,
                          cache=not args.no_cache, n_jobs=args.n_jobs)
    print(f"  {null}")
    print(f"  detect: {time.perf_counter()-t0:.1f}s  ({null.seconds:.1f}s null)")

    sig_hits = hits[hits["significant"]]
    inst = truth[truth["kind"] == "instance"]
    found = 0
    for _, ev in inst.iterrows():
        c = 0.5 * (sig_hits["start_sample"] + sig_hits["end_sample"])
        pad = 0.5 * (ev["end"] - ev["start"])
        if ((c >= ev["start"] - pad) & (c <= ev["end"] + pad)).any():
            found += 1
    print(f"\n  POSITIVE control: {len(sig_hits)}/{len(hits)} hits significant "
          f"at alpha={args.alpha}; recovered {found}/{len(inst)} planted instances")
    print(f"    critical p = {hits.attrs['critical_p']:.2e}, "
          f"null resolution = {hits.attrs['p_resolution']:.4f}, "
          f"{hits.attrs['n_below_resolution']} hits below it")

    # Negative control: the SAME detector, same seed, on a surrogate.
    rng = np.random.default_rng(123)
    xs = D.make_surrogate(sig, "fourier", rng)
    ms_n = build(xs)
    ms_n.channel = 0
    seed_n = Seed(symbols=seed.symbols.copy(), scale=seed.scale,
                  start_sample=seed.start_sample, end_sample=seed.end_sample,
                  channel=0, seed_id="synthetic_on_null", origin="span")
    hits_n, null_n = D.detect(ms_n, seed_n, matcher="cascade", alpha=args.alpha,
                              surrogate="fourier", n_surrogates=ns,
                              cache=not args.no_cache, n_jobs=args.n_jobs,
                              warn=False, exclude_self=False)
    fp = int(hits_n["significant"].sum()) if len(hits_n) else 0
    rate = fp / max(len(hits_n), 1)
    print(f"\n  NEGATIVE control (detector run on a surrogate, nothing to find):")
    print(f"    {fp}/{len(hits_n)} 'significant' = {rate:.3f} "
          f"(target <= alpha = {args.alpha})")
    verdict = "CALIBRATED" if rate <= max(args.alpha * 2, 0.02) else "NOT CALIBRATED"
    print(f"    -> {verdict}")
    if verdict != "CALIBRATED":
        print("    Downstream enrichment numbers should be read with that in mind.")
    return {"ms": ms, "seed": seed, "hits": hits, "null": null,
            "truth": truth, "fp_rate": rate, "n_recovered": found,
            "n_instances": len(inst)}


# ──────────────────────────────────────────────────────────────────────────────
#  2. Surrogate comparison
# ──────────────────────────────────────────────────────────────────────────────

def surrogate_comparison(args, cal):
    rule("2. SURROGATE COMPARISON - how strict is each null?")
    ms, seed = cal["ms"], cal["seed"]
    ns = 40 if args.quick else args.n_surrogates
    rows = []
    for kind, kw in [("fourier", {}), ("iaaft", {}),
                     ("block", {"block_length": 600}),
                     ("block", {"block_length": 7200})]:
        t0 = time.perf_counter()
        hits, null = D.detect(ms, seed, matcher="cascade", alpha=args.alpha,
                              surrogate=kind, n_surrogates=ns,
                              surrogate_kwargs=kw, cache=not args.no_cache,
                              n_jobs=args.n_jobs, warn=False)
        name = kind + (f"(L={kw['block_length']})" if kw else "")
        rows.append({
            "surrogate": name, "n_hits": len(hits),
            "n_significant": int(hits["significant"].sum()) if len(hits) else 0,
            "null_median_dist": float(np.median(null.hit_distances)),
            "null_p01": float(np.percentile(null.hit_distances, 1)),
            "null_min": float(null.hit_distances.min()),
            "best_p": float(hits["p_value"].min()) if len(hits) else np.nan,
            "secs": time.perf_counter() - t0,
        })
    df = pd.DataFrame(rows)
    print(f"  {'surrogate':>18} {'hits':>6} {'signif':>7} {'null med':>9} "
          f"{'null p01':>9} {'null min':>9} {'best p':>9} {'secs':>8}")
    for r in df.itertuples():
        print(f"  {r.surrogate:>18} {r.n_hits:>6} {r.n_significant:>7} "
              f"{r.null_median_dist:>9.4f} {r.null_p01:>9.4f} "
              f"{r.null_min:>9.4f} {r.best_p:>9.2e} {r.secs:>8.1f}")
    print("\n  Read the LEFT TAIL, not the median. Significance depends on how")
    print("  good the null's BEST matches are, not its typical ones. Measured")
    print("  here: the block bootstrap has the WORST median yet yields 0")
    print("  significant hits, because it preserves local shape and so")
    print("  occasionally reproduces the motif outright. A median-based reading")
    print("  would call it the weakest null; it is in fact the strongest.")
    print("\n  CAVEAT: block_length must be well BELOW the seed span, or a block")
    print("  can contain the whole motif and the null literally includes what")
    print("  you are testing for. `detect` warns when that happens.")
    return df


# ──────────────────────────────────────────────────────────────────────────────
#  3 + 4. Scale signature and the real channel
# ──────────────────────────────────────────────────────────────────────────────

def load_real(args):
    """Real channel + a seed from a human-labelled 'interesting' window."""
    db = _REPO_ROOT / "DATA" / "db" / "annotations.sqlite"
    if not db.exists():
        print(f"  SKIPPED: no database at {db}")
        return None
    conn = get_connection(str(db))
    rec = get_recording_by_id(conn, args.recording_id)
    npy = _REPO_ROOT / rec["npy_path"]
    if not npy.exists():
        print(f"  SKIPPED: channel file missing: {npy}")
        return None

    anns = list(list_annotations(conn, args.recording_id))
    conn.close()
    x = np.load(npy)
    lo, hi = (0, len(x)) if not args.span else (
        int(args.span.split(":")[0]), int(args.span.split(":")[1]))
    hi = min(hi, len(x))
    x = x[lo:hi]

    spans = defaultdict(list)
    for a in anns:
        s0, s1 = int(a["start_idx"]) - lo, int(a["end_idx"]) - lo
        if a["verdict"] in ("interesting", "not_interesting") and 0 <= s0 < len(x):
            spans[a["verdict"]].append((s0, min(s1, len(x))))

    interesting = [s for s in spans["interesting"] if s[1] - s[0] == MOTIF_LEN]
    if not interesting:
        print("  SKIPPED: no 10-minute 'interesting' window in this span")
        return None

    # rolling_z, NOT detrend. Stage 3 preferred detrend for synthetic recall,
    # but on this real channel detrend leaves 90% of symbols in a single bin,
    # every observed and surrogate distance collapses to 0.0, and the
    # significance test has no power at all. rolling_z raises the realised
    # alphabet from 38% to 100% and gives a null with actual spread. See the
    # power guard in sax_detection.detect.
    sig = S3.rolling_z(x, args.preproc_window)
    ms = build(sig)
    ms.channel = int(rec["channel"])
    s0, s1 = interesting[args.ann_index % len(interesting)]
    seed = Seed.from_span(ms, s0, s1, scale=16, seed_id=f"real_{s0}")
    print(f"  recording {rec['id']}: {rec['source_file']} CH{rec['channel']}, "
          f"span [{lo}, {hi}) = {len(x)} samples ({len(x)/3600:.1f} h)")
    print(f"  labels in span: {len(spans['interesting'])} interesting, "
          f"{len(spans['not_interesting'])} not-interesting")
    print(f"  seed = [{s0}, {s1}) at {s0/3600:.2f} h, "
          f"uses {D.seed_alphabet_fraction(ms, seed):.0%} of the alphabet")
    return {"x": x, "sig": sig, "ms": ms, "seed": seed, "spans": spans,
            "rec": rec, "offset": lo}


def real_detection(args, real):
    rule("3+4. REAL CHANNEL - scale signature and detection")
    ms, seed = real["ms"], real["seed"]
    ns = 40 if args.quick else args.n_surrogates

    sigdf = D.scale_signature(ms, seed, matcher="cascade", alpha=args.alpha,
                              surrogate="fourier", n_surrogates=ns,
                              cache=not args.no_cache, n_jobs=args.n_jobs)
    print(f"  {'sps':>6} {'mins':>6} {'w':>5} {'hits':>6} {'signif':>7} "
          f"{'covered':>8} {'best p':>10} {'best z':>8}")
    for r in sigdf.itertuples():
        print(f"  {int(r.scale):>6} {r.minutes:>6.1f} {int(r.n_symbols):>5} "
              f"{int(r.n_hits):>6} {int(r.n_significant):>7} "
              f"{r.frac_covered:>8.3f} {r.best_p:>10.2e} {r.best_z:>8.2f}")
    print(f"  -> scale signature: {sigdf.attrs['signature']}")
    print("     (single-scale is weaker evidence than a band: a lone scale is")
    print("      often just where the PAA grid happened to average well)")

    hits, null = D.detect(ms, seed, matcher="cascade", alpha=args.alpha,
                          surrogate="fourier", n_surrogates=ns,
                          cache=not args.no_cache, n_jobs=args.n_jobs)
    n_sig = int(hits["significant"].sum()) if len(hits) else 0
    print(f"\n  all scales together: {n_sig}/{len(hits)} significant at "
          f"alpha={args.alpha}")
    if n_sig:
        cov = int((hits.loc[hits['significant'], 'end_sample']
                   - hits.loc[hits['significant'], 'start_sample']).sum())
        print(f"  significant recurrences cover {cov/len(real['x']):.1%} of the span")
    return sigdf, hits, null


# ──────────────────────────────────────────────────────────────────────────────
#  5. Cross-method validation
# ──────────────────────────────────────────────────────────────────────────────

def cross_method(args, real, hits, exploratory_topk=0):
    """
    Compare detections against three independent methods.

    `exploratory_topk` is a deliberate escape hatch, not a fallback that fires
    silently: when nothing survives FDR, comparing the top-k UNCORRECTED hits
    still says something useful about whether the method is pointing anywhere
    real, but it is not a significance claim and must never be quoted as one.
    It is opt-in, banner-marked, and every returned dict is tagged exploratory.
    """
    rule("5. CROSS-METHOD VALIDATION (the headline)")
    x, ms = real["x"], real["ms"]
    n = len(x)
    sig = hits[hits["significant"]] if len(hits) else hits
    exploratory = False
    if len(sig) == 0 and exploratory_topk and len(hits) and not hits.attrs.get("degenerate"):
        sig = hits.nsmallest(exploratory_topk, "p_value")
        exploratory = True
        print("\n  " + "!" * 68)
        print(f"  EXPLORATORY ONLY: nothing survived FDR at alpha={args.alpha}.")
        print(f"  Using the top {len(sig)} hits by UNCORRECTED p-value "
              f"(p {sig['p_value'].min():.2e}-{sig['p_value'].max():.2e}).")
        print("  Everything below is descriptive. It is NOT evidence that the")
        print("  method detects anything, and must not be reported as such.")
        print("  " + "!" * 68)
    spans = list(zip(sig["start_sample"], sig["end_sample"]))
    out = {}

    if hits.attrs.get("degenerate"):
        print("  ABORTED: the detection test was degenerate (no power) - see the")
        print("  [ERROR] above. Validating a powerless test against other methods")
        print("  would manufacture a negative result. Fix the encoding first.")
        return {}, None, None
    if not spans:
        print("  No significant recurrences at alpha - and the test DID have")
        print(f"  power (null spread {hits.attrs.get('null_spread', float('nan')):.4f}, "
              f"{hits.attrs.get('n_distinct_distances', 0)} distinct distances).")
        print("  That is a real negative result and should be reported as one.")
        return {}, None, None

    # ── 5a. Matrix profile ────────────────────────────────────────────────────
    print(f"\n  --- 5a. stumpy matrix profile (m={MOTIF_LEN}) ---")
    try:
        import stumpy
        t0 = time.perf_counter()
        prof = stumpy.stump(x.astype(float), m=MOTIF_LEN)
        mp = prof[:, 0].astype(float)
        print(f"  computed in {time.perf_counter()-t0:.1f}s")
        motif_idx = D.matrix_profile_motifs(mp, MOTIF_LEN, top_k=max(len(spans), 10))
        mp_spans = [(i, i + MOTIF_LEN) for i in motif_idx]
        j = jaccard_null(spans, mp_spans, n, n_perm=200 if args.quick else 500)
        print(f"  {len(spans)} seeded vs {len(mp_spans)} matrix-profile motifs")
        print(f"  Jaccard {j['jaccard']:.4f}  |  shift-null mean "
              f"{j['null_mean']:.4f} (p95 {j['null_p95']:.4f})  |  "
              f"ratio {j['ratio']:.2f}x  |  p = {j['p_value']:.3f}")
        print("  -> " + ("ABOVE chance" if j["p_value"] < 0.05
                         else "NOT above chance"))
        out["matrix_profile"] = j
    except Exception as exc:                                   # noqa: BLE001
        print(f"  SKIPPED: {exc}")
        mp, mp_spans = None, []

    # ── 5b. Change points ─────────────────────────────────────────────────────
    print(f"\n  --- 5b. ruptures change points ---")
    try:
        t = np.arange(n) / FS
        t0 = time.perf_counter()
        cp = detect_change_points(x, t, algo="pelt", cost_model="l2",
                                  penalty=args.cp_penalty, jump=50)
        print(f"  {cp.n_bkps} change points in {time.perf_counter()-t0:.1f}s "
              f"(pelt/l2, pen={args.cp_penalty})")
        prox = changepoint_proximity(spans, cp.bkps_idx, n,
                                     n_perm=200 if args.quick else 500)
        print(f"  median distance from a detection boundary to the nearest "
              f"change point: {prox['median_dist']:.0f} samples")
        print(f"  random-placement null: {prox['null_median']:.0f} samples  |  "
              f"ratio {prox['ratio']:.2f}x  |  p = {prox['p_value']:.3f}")
        print("  -> " + ("CLOSER than chance" if prox["p_value"] < 0.05
                         else "NOT closer than chance"))
        out["changepoints"] = prox
    except Exception as exc:                                   # noqa: BLE001
        print(f"  SKIPPED: {exc}")

    # ── 5c. Manual labels and CNN scores ──────────────────────────────────────
    print(f"\n  --- 5c. manual labels + CNN scores ---")
    lab_i = real["spans"]["interesting"]
    lab_n = real["spans"]["not_interesting"]
    det_mask = spans_to_mask(spans, n)

    def overlaps(sp):
        return bool(det_mask[max(0, sp[0]):min(n, sp[1])].any())

    a = sum(1 for s in lab_i if overlaps(s))          # interesting & detected
    c = len(lab_i) - a                                 # interesting & not
    b = sum(1 for s in lab_n if overlaps(s))          # not-interesting & detected
    d = len(lab_n) - b
    print(f"  2x2 over labelled windows:")
    print(f"    {'':>18} {'detected':>10} {'not':>8}")
    print(f"    {'interesting':>18} {a:>10} {c:>8}")
    print(f"    {'not_interesting':>18} {b:>10} {d:>8}")
    if (a + c) and (b + d):
        orr = odds_ratio_ci(a, b, c, d)
        print(f"  odds ratio {orr['odds_ratio']:.3f} "
              f"[95% CI {orr['lo']:.3f}, {orr['hi']:.3f}]  "
              f"p = {orr['p_value']:.3f}  ({orr['method']})")
        crosses = orr["lo"] <= 1.0 <= orr["hi"]
        print("  -> " + ("CI includes 1: NO enrichment demonstrated" if crosses
                         else "CI excludes 1: enrichment"))
        out["labels"] = orr
    else:
        print("  Not enough labelled windows of both classes in this span.")

    # CNN scores, where available
    cnn_path = (_REPO_ROOT / "DATA" / "derived" / "windows" / "10min_fs1.0"
                / "labels" / "10min_cnn_predictions_fs_1.00.json")
    if cnn_path.exists():
        try:
            preds = json.loads(cnn_path.read_text())
            chan_len = int(real["rec"]["n_samples"])
            ch = int(real["rec"]["channel"])
            scores, marks = [], []
            for k, v in preds.items():
                g = int(k)
                c_i, local = divmod(g, chan_len)
                if c_i != ch:
                    continue
                loc = local - real["offset"]
                if not (0 <= loc < n):
                    continue
                p_int = float(v["probabilities"][0])
                scores.append(p_int)
                marks.append(bool(det_mask[loc:min(n, loc + MOTIF_LEN)].any()))
            scores, marks = np.asarray(scores), np.asarray(marks)
            if marks.sum() and (~marks).sum():
                from scipy.stats import mannwhitneyu
                u, pu = mannwhitneyu(scores[marks], scores[~marks],
                                     alternative="greater")
                print(f"\n  CNN P(interesting) on {len(scores)} windows in span: "
                      f"detected mean {scores[marks].mean():.3f} (n={marks.sum()}) "
                      f"vs undetected {scores[~marks].mean():.3f} "
                      f"(n={(~marks).sum()})")
                print(f"  Mann-Whitney U one-sided p = {pu:.3f}  -> "
                      + ("higher than chance" if pu < 0.05 else "NOT higher"))
                out["cnn"] = {"p_value": float(pu),
                              "mean_detected": float(scores[marks].mean()),
                              "mean_undetected": float(scores[~marks].mean())}
            else:
                print("\n  CNN scores: detections do not split the windows; skipped.")
        except Exception as exc:                               # noqa: BLE001
            print(f"\n  CNN scores SKIPPED: {exc}")

    for v in out.values():
        v["exploratory"] = exploratory
    return out, mp, mp_spans


# ──────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(description="Calibrated seeded SAX detection.")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--n-surrogates", type=int, default=200)
    p.add_argument("--n-jobs", type=int, default=1)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--recording-id", type=int, default=3)
    p.add_argument("--ann-index", type=int, default=0)
    p.add_argument("--span", default="0:400000",
                   help="'START:END' of the real channel (default first ~111 h). "
                        "The null is 200 searches, so the whole 721 h is slow.")
    p.add_argument("--cp-penalty", type=float, default=30.0)
    p.add_argument("--exploratory-topk", type=int, default=0,
                   help="If nothing survives FDR, additionally compare the top-N "
                        "UNCORRECTED hits against the other methods. Descriptive "
                        "only - never a significance claim. 0 = off.")
    p.add_argument("--preproc-window", type=int, default=MOTIF_LEN,
                   help="Window for the rolling_z preprocessing of the real "
                        "channel (default = motif length).")
    p.add_argument("--skip-real", action="store_true")
    p.add_argument("--no-show", action="store_true")
    p.add_argument("--save-dir", default=None)
    args = p.parse_args(argv)

    figs = {}
    cal = calibration(args)
    figs["timeline_synthetic"] = D.plot_detection_timeline(
        cal["ms"], cal["hits"], cal["null"], seed=cal["seed"])
    surrogate_comparison(args, cal)

    if not args.skip_real:
        rule("REAL CHANNEL LOAD")
        real = load_real(args)
        if real is not None:
            sigdf, hits, null = real_detection(args, real)
            figs["scale_signature"] = D.plot_significance_by_scale(
                sigdf, seed_id=real["seed"].seed_id)
            figs["timeline_real"] = D.plot_detection_timeline(
                real["ms"], hits, null, seed=real["seed"])
            res, mp, mp_spans = cross_method(args, real, hits,
                                             exploratory_topk=args.exploratory_topk)
            if mp is not None:
                figs["vs_matrix_profile"] = D.plot_vs_matrix_profile(
                    real["ms"], hits, mp, MOTIF_LEN)

            rule("SUMMARY")
            print(f"  negative-control false-positive rate: {cal['fp_rate']:.3f} "
                  f"(alpha={args.alpha})")
            print(f"  synthetic recovery: {cal['n_recovered']}/{cal['n_instances']}")
            print(f"  real channel: {int(hits['significant'].sum())}/{len(hits)} "
                  f"significant, scale signature = {sigdf.attrs['signature']}")
            for k, v in res.items():
                pv = v.get("p_value", np.nan)
                tag = "  [EXPLORATORY - not a significance claim]" if v.get("exploratory") else ""
                print(f"  {k:>16}: p = {pv:.3f}"
                      + (f"  OR = {v['odds_ratio']:.2f} "
                         f"[{v['lo']:.2f}, {v['hi']:.2f}]"
                         if "odds_ratio" in v else "") + tag)

    if args.save_dir:
        rule("SAVE")
        out = _Path(args.save_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, fig in figs.items():
            path = out / f"detection_{name}.png"
            fig.savefig(path, dpi=140, bbox_inches="tight")
            print(f"  {name:>22} -> {path}")

    if not args.no_show:
        plt.show()
    return figs


if __name__ == "__main__":
    main()
