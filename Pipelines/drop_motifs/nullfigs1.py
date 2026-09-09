"""
nullfigs1.py
=============
Every figure the `nulls_v1` set ships. Matplotlib Agg only, no Panel, no
HoloViews - `CLAUDE.md` rule 1 and the "headless, one command" constraint.

DRAWING RULES THIS MODULE HOLDS TO, because the figures go into a
submission and the arguments they carry are quantitative:

  A PANEL THAT STATES A NUMBER STATES ITS N AND ITS p. Every caption
  carries them. The JSON beside the figure carries the same numbers so the
  paper quotes the JSON, never the PNG.

  A NULL IS DRAWN AS A DISTRIBUTION, NOT AS AN ERROR BAR. Violins, because
  a rank-based p is a statement about where the observed value sits in an
  empirical distribution, and an error bar implies a symmetric parametric
  one that was never assumed.

  WHEN THE NULL REPRODUCES THE OBSERVATION, THE TITLE SAYS SO. Panel D of
  NULL_surrogate.png is the specific case: if the surrogates recover the
  depth-angle correlation, the panel is titled to say the correlation is a
  property of the detector's geometry rather than of the signal. A figure
  that reports its own negative result is worth more than one that has to
  be read against a caveat elsewhere.

  TRUNCATION IS DRAWN, NOT DESCRIBED. Panel A of NUISANCE_vs_SIGNAL.png
  draws the pre-floor depth distributions faintly behind the post-floor
  ones, so the 0.1 mV gate's effect on CH2 is visible rather than being a
  sentence a reader has to take on trust.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from Pipelines.drop_motifs import nulls1 as n1

CHANNEL_COLOURS = ["#1b4965", "#c1666b", "#5fa8a0", "#e0a458", "#7d5ba6"]
GENERATOR_COLOURS = {"aaft": "#c1666b", "block50": "#5fa8a0",
                     "block5": "#e0a458"}
# Two-line tick labels. The full names are too long for a violin's width,
# and "block shuffle" alone is ambiguous between the 50 s and 5 s runs -
# which is exactly what the first draft printed under both of them.
GENERATOR_SHORT = {"aaft": "AAFT\nphase rand.",
                   "block50": "block shuffle\n50 s blocks",
                   "block5": "block shuffle\n5 s blocks"}
OBSERVED_COLOUR = "#12232e"
BIN_COLOURS = {"common_mode": "#c1666b", "propagation": "#2a9d8f",
               "independent": "#b8b8b8"}

TITLE_SIZE = 12
LABEL_SIZE = 10
CAPTION_SIZE = 8.5


def _save(fig, out_path):
    out_path = str(out_path)
    fig.savefig(out_path, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def _violin(ax, position, values, colour, width=0.62):
    """One null distribution. Returns False when there is nothing to draw
    so the caller can mark the slot as empty rather than leaving a gap the
    reader will read as a zero."""
    values = np.asarray([v for v in values if v is not None
                         and np.isfinite(v)], dtype=float)
    if values.size < 3 or values.min() == values.max():
        if values.size:
            ax.plot([position], [values[0]], marker="_", ms=16,
                    color=colour, lw=2)
        return False
    parts = ax.violinplot([values], positions=[position], widths=width,
                          showextrema=False, showmedians=False)
    for body in parts["bodies"]:
        body.set_facecolor(colour)
        body.set_edgecolor(colour)
        body.set_alpha(0.42)
        body.set_linewidth(0.8)
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    ax.plot([position, position], [q1, q3], color=colour, lw=2.4,
            solid_capstyle="butt", zorder=3)
    ax.plot([position], [med], marker="o", ms=3.6, color="white",
            markeredgecolor=colour, markeredgewidth=1.1, zorder=4)
    return True


def _observed_marker(ax, position, value, *, size=9, label=None):
    if value is None or not np.isfinite(value):
        return
    ax.plot([position], [value], marker="D", ms=size, color=OBSERVED_COLOUR,
            markeredgecolor="white", markeredgewidth=1.2, zorder=6,
            label=label, linestyle="none")


def _p_text(p):
    if p is None:
        return "p n/a"
    if p <= 1.0 / 101.0 + 1e-9:
        return "p = %.3f (floor)" % p
    return "p = %.3f" % p


# ===========================================================================
# Task 1 - NULL_surrogate.png
# ===========================================================================

def plot_null_surrogate(payload, realisations, out_path):
    """Four panels: detections per channel, family count at fixed height,
    within-family dispersion, and the depth-angle geometry.

    Panel D is the one that may report against the paper, and its title is
    computed from the result rather than written in advance.
    """
    observed = payload["observed"]
    tests = payload["tests"]
    n_per = payload["n_realisations_completed"]
    generators = list(n1.GENERATORS)

    fig = plt.figure(figsize=(21.0, 6.4))
    grid = fig.add_gridspec(1, 4, wspace=0.28, left=0.045, right=0.99,
                            top=0.80, bottom=0.20)
    axes = [fig.add_subplot(grid[0, i]) for i in range(4)]

    # ---- A. detections after the floor, per channel --------------------
    ax = axes[0]
    step = 1.0 / (len(generators) + 1.4)
    best_p = []
    for channel in range(5):
        base = channel
        for index, generator in enumerate(generators):
            values = [entry["n_after_floor"]
                      for result in realisations
                      if result["generator"] == generator
                      for entry in result["per_channel"]
                      if entry["channel"] == channel]
            position = base + (index - (len(generators) - 1) / 2.0) * step
            _violin(ax, position, values, GENERATOR_COLOURS[generator],
                    width=step * 0.85)
        _observed_marker(ax, base, n1.channel_entry(
            observed["per_channel"], channel)["n_after_floor"])
        ps = [tests["detections"]["CH%d" % channel][g]["p"]
              for g in generators]
        best_p.append(min([p for p in ps if p is not None], default=None))

    # Headroom is reserved AFTER every violin and marker is placed, then
    # the labels go into it. Annotating inside the loop cannot work: the
    # y limits are still growing, so `get_ylim()[1]` puts each label at a
    # different height, and a fixed axes fraction lands on whichever
    # observed marker happens to be high.
    lo, hi = ax.get_ylim()
    ax.set_ylim(lo, hi + 0.14 * (hi - lo))
    for channel, p in enumerate(best_p):
        # Compact form here, not `_p_text`: five labels share this axis
        # and "p = 0.010 (floor)" five times overlaps into one smear.
        label = ("p<%.3f" % (1.0 / (payload["n_realisations_per_generator"]
                                    + 1) + 1e-9)
                 if p is not None and p <= 1.0 / 101.0 + 1e-9
                 else ("p=%.3f" % p if p is not None else "p n/a"))
        ax.annotate(label, (channel, 0.985),
                    xycoords=("data", "axes fraction"), ha="center",
                    va="top", fontsize=CAPTION_SIZE - 0.5)
    ax.set_xticks(range(5))
    ax.set_xticklabels(n1.CHANNEL_NAMES)
    ax.set_ylabel("detections after the 0.1 mV floor", fontsize=LABEL_SIZE)

    # The heading is computed. "The detector finds more in the recording"
    # is true of most channels and FALSE of at least one - CH2, whose
    # observed count sits below all three of its nulls - and a title that
    # generalises over a visible counter-example is the kind of thing a
    # reviewer opens with.
    above = []
    below = []
    for channel in range(5):
        observed_n = n1.channel_entry(observed["per_channel"],
                                      channel)["n_after_floor"]
        medians = [tests["detections"]["CH%d" % channel][g]["null_median"]
                   for g in generators]
        medians = [m for m in medians if m is not None]
        if medians and observed_n > max(medians):
            above.append(n1.CHANNEL_NAMES[channel])
        elif medians and observed_n < min(medians):
            below.append(n1.CHANNEL_NAMES[channel])
    if below:
        heading = ("A  the detector finds more in the recording than in its\n"
                   "surrogates on %s - and FEWER on %s"
                   % (", ".join(above) or "no channel", ", ".join(below)))
    else:
        heading = ("A  the detector finds more in the recording\n"
                   "than in its surrogates, on every channel")
    ax.set_title(heading, fontsize=TITLE_SIZE)
    ax.set_xlabel("p annotated is the smallest across the three generators",
                  fontsize=CAPTION_SIZE)

    # ---- B. families at the fixed merge height -------------------------
    ax = axes[1]
    mode = "fall"
    for index, generator in enumerate(generators):
        values = [(result["family"][mode] or {})
                  .get("n_families_at_height_min_members")
                  for result in realisations
                  if result["generator"] == generator]
        _violin(ax, index, values, GENERATOR_COLOURS[generator])
        node = tests["family"][mode]["n_families_at_height"][generator]
        ax.annotate(_p_text(node["p"]), (index, 0.02),
                    xycoords=("data", "axes fraction"), ha="center",
                    va="bottom", fontsize=CAPTION_SIZE)
    _observed_marker(ax, -0.75,
                     observed["family"][mode]["n_families_at_height_min_members"])
    ax.axhline(observed["family"][mode]["n_families_at_height_min_members"],
               color=OBSERVED_COLOUR, lw=1.1, ls="--", alpha=0.55)
    ax.set_xlim(-1.2, len(generators) - 0.4)
    ax.set_xticks(range(len(generators)))
    ax.set_xticklabels([GENERATOR_SHORT[g] for g in generators],
                       fontsize=CAPTION_SIZE)
    ax.set_ylabel("families with >= %d members\nat the real tree's k=4 height"
                  % n1.MIN_FAMILY_MEMBERS, fontsize=LABEL_SIZE)
    ax.set_title("B  family count at a FIXED merge height\n"
                 "(k is not imposed on either side)", fontsize=TITLE_SIZE)
    ax.set_xlabel("cut height %.1f, from the real tree"
                  % payload["cut_height_k4_from_real_tree"][mode],
                  fontsize=CAPTION_SIZE)

    # ---- C. within-family dispersion at k = 4 --------------------------
    ax = axes[2]
    for index, generator in enumerate(generators):
        values = [(result["family"][mode] or {}).get("within_family_dispersion")
                  for result in realisations
                  if result["generator"] == generator]
        _violin(ax, index, values, GENERATOR_COLOURS[generator])
        node = tests["family"][mode]["within_family_dispersion"][generator]
        ax.annotate(_p_text(node["p"]), (index, 0.02),
                    xycoords=("data", "axes fraction"), ha="center",
                    va="bottom", fontsize=CAPTION_SIZE)
    dispersion = observed["family"][mode]["within_family_dispersion"]
    _observed_marker(ax, -0.75, dispersion)
    ax.axhline(dispersion, color=OBSERVED_COLOUR, lw=1.1, ls="--", alpha=0.55)
    ax.set_xlim(-1.2, len(generators) - 0.4)
    ax.set_xticks(range(len(generators)))
    ax.set_xticklabels([GENERATOR_SHORT[g] for g in generators],
                       fontsize=CAPTION_SIZE)
    ax.set_ylabel("mean distance to own family centroid\n"
                  "(z-normalised feature space)", fontsize=LABEL_SIZE)
    ax.set_title("C  are the real families TIGHTER?\n"
                 "the limited-repertoire claim", fontsize=TITLE_SIZE)
    ax.set_xlabel("lower is tighter; observed is the dashed line",
                  fontsize=CAPTION_SIZE)

    # ---- D. rho and the control exponent -------------------------------
    ax = axes[3]
    rho_observed = observed["angle_spearman_rho_depth_vs_angle"]
    reproduced = []
    for index, generator in enumerate(generators):
        values = [result["angle_spearman_rho_depth_vs_angle"]
                  for result in realisations
                  if result["generator"] == generator]
        _violin(ax, index, values, GENERATOR_COLOURS[generator])
        node = tests["geometry"]["spearman_rho"][generator]
        # "Reproduced" uses the SAME rule the README's section 4 uses -
        # the rank p failing to reject at 0.05 - rather than a
        # range-containment test of its own. Two criteria for one word in
        # two places is how a figure and its write-up come to disagree.
        if node["p"] is not None and node["p"] > 0.05:
            reproduced.append(generator)
        ax.annotate(_p_text(node["p"]), (index, 0.02),
                    xycoords=("data", "axes fraction"), ha="center",
                    va="bottom", fontsize=CAPTION_SIZE)
    _observed_marker(ax, -0.75, rho_observed)
    ax.axhline(rho_observed, color=OBSERVED_COLOUR, lw=1.1, ls="--",
               alpha=0.55)
    ax.set_xlim(-1.2, len(generators) - 0.4)
    ax.set_xticks(range(len(generators)))
    ax.set_xticklabels([GENERATOR_SHORT[g] for g in generators],
                       fontsize=CAPTION_SIZE)
    ax.set_ylabel("Spearman rho (drop depth vs fall angle)",
                  fontsize=LABEL_SIZE)

    if reproduced:
        title = ("D  the null REPRODUCES rho on %s\n"
                 "-> rho is the detector's geometry, not the signal's"
                 % ", ".join(reproduced))
    else:
        title = ("D  rho is outside every null's range\n"
                 "-> the correlation is a property of the signal")
    ax.set_title(title, fontsize=TITLE_SIZE)

    inset = ax.inset_axes((0.60, 0.60, 0.37, 0.33))
    for index, generator in enumerate(generators):
        values = [result["angle_duration_vs_depth_exponent"]
                  for result in realisations
                  if result["generator"] == generator]
        _violin(inset, index, values, GENERATOR_COLOURS[generator], width=0.5)
    b_observed = observed["angle_duration_vs_depth_exponent"]
    inset.axhline(b_observed, color=OBSERVED_COLOUR, lw=1.0, ls="--")
    inset.set_xticks([])
    inset.tick_params(labelsize=6.5)
    inset.set_title("control b  (obs %.3f)" % b_observed, fontsize=7)

    handles = [Line2D([], [], marker="D", ls="none", color=OBSERVED_COLOUR,
                      markeredgecolor="white", ms=8,
                      label="observed (real recording)")]
    handles += [Line2D([], [], marker="s", ls="none",
                       color=GENERATOR_COLOURS[g], alpha=0.6, ms=10,
                       label="%s  (N = %d)" % (n1.GENERATOR_LABELS[g],
                                               n_per.get(g, 0)))
                for g in generators]
    fig.legend(handles=handles, loc="upper center", ncol=4, frameon=False,
               fontsize=LABEL_SIZE, bbox_to_anchor=(0.5, 1.005))

    fig.text(0.5, 0.012,
             "Rank p = (1 + #{surrogate >= observed}) / (1 + N), one-sided, "
             "N = %d per generator per channel. Counts exclude the first and "
             "last %g s of every channel and every surrogate (FFT surrogates "
             "are circular; the boundary join is a step). Detection: "
             "passes9.detect_sliding, %g s windows at %.0f%% overlap, then "
             "refine9 at a %.2f mV floor - identical arguments on both sides."
             % (payload["n_realisations_per_generator"],
                payload["edge_handling"]["trim_s"],
                payload["detect_kwargs"]["window_s"],
                100 * payload["detect_kwargs"]["overlap"],
                payload["min_depth_mv"]),
             ha="center", va="bottom", fontsize=CAPTION_SIZE)
    return _save(fig, out_path)


# ===========================================================================
# Task 2 - NUISANCE_vs_SIGNAL.png
# ===========================================================================

def plot_nuisance_vs_signal(payload, out_path):
    """Three panels: amplitude belongs to the electrode, shape does not,
    and the two on one pair of axes."""
    depth = payload["depth_test"]
    coarse = payload["family_by_channel"]["coarse_k%d" % n1.COARSE_K]
    spread = payload["shape_spread"]

    fig = plt.figure(figsize=(19.5, 6.6))
    grid = fig.add_gridspec(1, 3, width_ratios=(1.15, 1.25, 1.0),
                            wspace=0.26, left=0.05, right=0.985,
                            top=0.845, bottom=0.155)

    # ---- A. per-channel depth, pre and post floor ----------------------
    ax = fig.add_subplot(grid[0, 0])
    post = payload["_post_floor_depths"]
    pre = payload["_pre_floor_depths"]
    for channel in range(5):
        colour = CHANNEL_COLOURS[channel]
        y = 4 - channel
        for values, alpha, height, label in (
                (pre.get(channel), 0.20, 0.40, "before the floor"),
                (post.get(channel), 0.72, 0.30, "after the floor")):
            if values is None or not len(values):
                continue
            values = np.asarray(values, dtype=float)
            values = values[values > 0]
            parts = ax.violinplot([np.log10(values)], positions=[y],
                                  widths=height * 2, vert=False,
                                  showextrema=False, showmedians=False)
            for body in parts["bodies"]:
                body.set_facecolor(colour)
                body.set_alpha(alpha)
                body.set_edgecolor(colour)
        values = np.asarray(post[channel], dtype=float)
        median = float(np.median(values))
        ax.plot([np.log10(median)], [y], marker="D", ms=7, color="white",
                markeredgecolor=colour, markeredgewidth=1.8, zorder=5)
        # White stroke: the label sits on top of its own violin, which is
        # the same hue, and unstroked coloured text on it is unreadable.
        ax.annotate("%.3f mV  (n=%d)" % (median, values.size),
                    (np.log10(median), y), xytext=(9, 10),
                    textcoords="offset points", fontsize=CAPTION_SIZE,
                    color=colour, fontweight="bold", zorder=8,
                    path_effects=[path_effects.withStroke(
                        linewidth=2.6, foreground="white")])
    ax.axvline(np.log10(n1.MIN_DEPTH_MV), color="#12232e", lw=1.4, ls="--")
    ax.annotate("0.1 mV instrument floor", (np.log10(n1.MIN_DEPTH_MV), 4.55),
                xytext=(-6, 0), textcoords="offset points", rotation=90,
                ha="right", va="top", fontsize=CAPTION_SIZE)
    ticks = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0]
    ax.set_xticks(np.log10(ticks))
    ax.set_xticklabels(["%g" % t for t in ticks])
    ax.set_yticks(range(5))
    ax.set_yticklabels(list(reversed(n1.CHANNEL_NAMES)))
    ax.set_xlabel("drop depth (mV, log scale)", fontsize=LABEL_SIZE)
    ax.set_title("A  AMPLITUDE BELONGS TO THE ELECTRODE\n"
                 "Kruskal-Wallis H = %.1f, p = %.2g, "
                 "$\\epsilon^2$ = %.3f, n = %d\n"
                 "median depth spans %.2fx across the five channels"
                 % (depth["H"], depth["p"], depth["epsilon_squared"],
                    depth["n"], depth["median_ratio_max_over_min"]),
                 fontsize=TITLE_SIZE)
    ax.legend(handles=[
        Line2D([], [], marker="s", ls="none", color="#666", alpha=0.22, ms=11,
               label="before the 0.1 mV floor (raw store, n = %d)"
                     % payload["n_raw_store"]),
        Line2D([], [], marker="s", ls="none", color="#666", alpha=0.72, ms=11,
               label="after the floor (refined store, n = %d)"
                     % depth["n"])],
        loc="lower left", frameon=False, fontsize=CAPTION_SIZE)

    # ---- B. family x channel composition -------------------------------
    ax = fig.add_subplot(grid[0, 1])
    table = np.asarray(coarse["table"], dtype=float)
    marginal = np.asarray(coarse["channel_marginal_proportion"], dtype=float)
    residuals = np.asarray(coarse["standardised_residuals"], dtype=float)
    proportions = table / table.sum(axis=1, keepdims=True)

    positions = np.arange(table.shape[0])
    left = np.zeros(table.shape[0])
    for channel in range(5):
        ax.barh(positions, proportions[:, channel], left=left, height=0.62,
                color=CHANNEL_COLOURS[channel], edgecolor="white", lw=0.8,
                label=n1.CHANNEL_NAMES[channel])
        for family in positions:
            z = residuals[family, channel]
            if abs(z) > 2.0 and proportions[family, channel] > 0.03:
                ax.annotate("z=%+.1f" % z,
                            (left[family] + proportions[family, channel] / 2,
                             family), ha="center", va="center",
                            fontsize=CAPTION_SIZE, color="white",
                            fontweight="bold")
        left = left + proportions[:, channel]

    running = 0.0
    for channel in range(5):
        running += marginal[channel]
        if channel < 4:
            ax.axvline(running, color="#12232e", lw=1.3, ls=":", zorder=5)
    ax.set_yticks(positions)
    ax.set_yticklabels(["F%d\nn = %d" % (coarse["families"][i],
                                         int(table[i].sum()))
                        for i in positions], fontsize=CAPTION_SIZE)
    ax.set_xlim(0, 1)
    ax.set_xlabel("share of the family's members", fontsize=LABEL_SIZE)

    # The heading is COMPUTED, not asserted. The first draft of this figure
    # said "SHAPE DOES NOT" before the permutation test had been run; the
    # test then rejected independence, and a title that contradicts the
    # number printed beneath it is worse than no title. What survives is a
    # claim about DEGREE, so the heading states the degree.
    independent = coarse["permutation_p"] > 0.05
    ratio = (coarse["cramers_v"] / coarse["null_cramers_v_median"]
             if coarse["null_cramers_v_median"] else float("nan"))
    if independent:
        heading = "B  SHAPE DOES NOT - family membership is channel-independent"
    else:
        heading = ("B  SHAPE DOES, BUT ONLY WEAKLY - V = %.3f against a "
                   "null median of %.3f (%.1fx)"
                   % (coarse["cramers_v"], coarse["null_cramers_v_median"],
                      ratio))
    ax.set_title("%s\n"
                 "permutation p = %.4f (%d shuffles of the channel label), "
                 "Cramer's V = %.3f\n"
                 "dotted lines = the marginal channel proportion; "
                 "%d of %d families hold all five channels"
                 % (heading, coarse["permutation_p"], coarse["n_permutations"],
                    coarse["cramers_v"],
                    coarse["n_families_with_all_five_channels"],
                    coarse["n_families"]),
                 fontsize=TITLE_SIZE)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.20), ncol=5,
              frameon=False, fontsize=CAPTION_SIZE)

    # ---- C. the two axes together --------------------------------------
    ax = fig.add_subplot(grid[0, 2])
    for channel in range(5):
        stats = spread["per_channel"]["CH%d" % channel]
        ax.errorbar(stats["median_depth_mv"], stats["median_shape_distance"],
                    xerr=stats["iqr_depth_mv"] / 2,
                    yerr=stats["iqr_shape_distance"] / 2,
                    fmt="o", ms=11, color=CHANNEL_COLOURS[channel],
                    ecolor=CHANNEL_COLOURS[channel], elinewidth=1.2,
                    capsize=3, alpha=0.9, markeredgecolor="white",
                    markeredgewidth=1.2)
        ax.annotate("CH%d" % channel,
                    (stats["median_depth_mv"], stats["median_shape_distance"]),
                    xytext=(11, -4), textcoords="offset points",
                    fontsize=LABEL_SIZE, color=CHANNEL_COLOURS[channel],
                    fontweight="bold")
    ax.set_xlabel("median drop depth (mV)  -  the nuisance axis",
                  fontsize=LABEL_SIZE)
    ax.set_ylabel("median shape distance to the global medoid\n"
                  "-  the signal axis", fontsize=LABEL_SIZE)
    ax.set_title("C  THE ARGUMENT IN ONE PANEL\n"
                 "the electrodes spread %.2fx further apart in amplitude\n"
                 "than in normalised shape (%.0f%% vs %.0f%% of the median)"
                 % (spread["separation_ratio_depth_over_shape"],
                    100 * spread["depth_spread_ratio"],
                    100 * spread["shape_spread_ratio"]),
                 fontsize=TITLE_SIZE)
    ax.grid(alpha=0.18, ls=":")

    fig.text(0.5, 0.012,
             "Panel A: pre-floor distributions are the raw drop_motifs9 "
             "store (n = %d), post-floor the refined_v2 store (n = %d); the "
             "gate removes %.0f%% of CH2. Panel B: the null shuffles the "
             "CHANNEL LABEL across events, so both margins are preserved and "
             "the unequal channel contribution is nulled rather than "
             "assumed away; z are adjusted standardised (Haberman) "
             "residuals. Panel C: shape distance in the same 200-point "
             "z-normalised space every family statistic uses; bars are IQR/2."
             % (payload["n_raw_store"], depth["n"],
                100 * payload["pre_floor_depth_by_channel"]["CH2"]
                ["fraction_at_or_below_floor"]),
             ha="center", va="bottom", fontsize=CAPTION_SIZE)
    return _save(fig, out_path)


# ===========================================================================
# Task 3 - CROSS_CHANNEL.png
# ===========================================================================

def plot_cross_channel(payload, out_path):
    from Pipelines.drop_motifs import crosschan1 as cc

    pairs = payload["_pairs"]
    rotation = payload["rotation_null"]
    counts = payload["bin_counts"]

    fig = plt.figure(figsize=(16.0, 6.6))
    grid = fig.add_gridspec(2, 2, width_ratios=(1.55, 1.0),
                            height_ratios=(1.0, 4.4), hspace=0.06,
                            wspace=0.24, left=0.055, right=0.985,
                            top=0.845, bottom=0.135)

    lags = np.asarray([p["peak_lag_s"] for p in pairs
                       if p["peak_lag_s"] is not None], dtype=float)
    rs = np.asarray([p["peak_r"] for p in pairs
                     if p["peak_lag_s"] is not None], dtype=float)
    bins = [p["bin"] for p in pairs if p["peak_lag_s"] is not None]

    ax_hist = fig.add_subplot(grid[0, 0])
    ax_hist.hist(lags, bins=np.arange(-cc.MAX_LAG_S, cc.MAX_LAG_S + 0.1, 0.1),
                 color="#4a6572", alpha=0.85)
    ax_hist.axvline(0.0, color="#c1666b", lw=1.2)
    ax_hist.set_xlim(-cc.MAX_LAG_S, cc.MAX_LAG_S)
    # tick_params, NOT set_xticklabels([]): the axis is shared with the
    # scatter below, and fixed empty labels set here blank BOTH.
    ax_hist.tick_params(labelbottom=False)
    ax_hist.set_ylabel("pairs", fontsize=CAPTION_SIZE)
    ax_hist.tick_params(labelsize=CAPTION_SIZE)
    # Is there a spike at zero, or is the lag distribution flat? A clean
    # spike is the result the task was looking for; a flat distribution is
    # the other result, and the title has to be able to say either.
    concentration = payload["zero_lag_concentration"]
    ax_hist.set_title("A  every cross-channel pair within +-%g s: "
                      "peak lag against correlation at that lag  "
                      "(%d pairs, %d events)\n"
                      "%s: %.1f%% of peak lags fall within +-%.1f s, "
                      "against %.1f%% expected if lag were uniform (%.2fx)"
                      % (cc.PAIR_WINDOW_S, len(pairs),
                         payload["n_events_considered"],
                         "SPIKE AT ZERO" if concentration["ratio"] >= 1.5
                         else "NO SPIKE AT ZERO - the lag distribution is "
                              "flat",
                         100 * concentration["observed_fraction"],
                         concentration["half_width_s"],
                         100 * concentration["uniform_fraction"],
                         concentration["ratio"]),
                      fontsize=TITLE_SIZE)

    ax = fig.add_subplot(grid[1, 0], sharex=ax_hist)
    for name in cc.BINS:
        mask = np.asarray([b == name for b in bins])
        if not mask.any():
            continue
        ax.scatter(lags[mask], rs[mask], s=17, alpha=0.55,
                   color=BIN_COLOURS[name], edgecolors="none",
                   label="%s  (n = %d, %.1f%%)"
                         % (name, counts[name],
                            100.0 * counts[name] / max(len(pairs), 1)))
    thresholds = cc.DEFAULT_THRESHOLDS
    ax.add_patch(Rectangle((-thresholds.common_lag_s, thresholds.common_r),
                           2 * thresholds.common_lag_s,
                           1.02 - thresholds.common_r,
                           fill=False, edgecolor=BIN_COLOURS["common_mode"],
                           lw=1.9, ls="--", zorder=5))
    # Anchored to the axes corner, not to the box: the box sits in the
    # densest part of the scatter and any label placed beside it lands on
    # top of a hundred points.
    ax.annotate("COMMON MODE (boxed)\n|lag| <= %.1f s and r >= %.2f\n"
                "%d pairs, %d distinct events (%.1f%% of the store)"
                % (thresholds.common_lag_s, thresholds.common_r,
                   counts["common_mode"], payload["n_common_mode_events"],
                   100 * payload["common_mode_event_fraction"]),
                (0.015, 0.06), xycoords="axes fraction", ha="left",
                va="bottom", fontsize=CAPTION_SIZE,
                color=BIN_COLOURS["common_mode"], fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                          edgecolor=BIN_COLOURS["common_mode"], alpha=0.9))
    ax.axhline(thresholds.propagation_r, color="#2a9d8f", lw=1.0, ls=":")
    ax.axvline(-thresholds.propagation_lag_s, color="#2a9d8f", lw=1.0, ls=":")
    ax.axvline(thresholds.propagation_lag_s, color="#2a9d8f", lw=1.0, ls=":")
    ax.set_xlim(-cc.MAX_LAG_S, cc.MAX_LAG_S)
    ax.set_ylim(-0.35, 1.03)
    # sharex with the histogram above suppresses these; the scatter is the
    # panel a reader measures lags off, so it needs them back.
    ax.tick_params(labelbottom=True)
    ax.set_xlabel("peak lag (s) - positive means the higher-numbered "
                  "channel is later", fontsize=LABEL_SIZE)
    ax.set_ylabel("Pearson r at the peak lag", fontsize=LABEL_SIZE)
    ax.legend(loc="lower right", frameon=False, fontsize=CAPTION_SIZE)
    ax.grid(alpha=0.15, ls=":")

    # ---- B. the rotation null ------------------------------------------
    ax2 = fig.add_subplot(grid[:, 1])
    null = np.asarray(rotation["null"], dtype=float)
    ax2.hist(null, bins=34, color="#8fb8ad", alpha=0.85,
             label="rotation null (%d trials)" % rotation["n_trials"])
    ax2.axvline(rotation["observed_coincidences"], color=OBSERVED_COLOUR,
                lw=2.4, label="observed = %d"
                              % rotation["observed_coincidences"])
    ax2.set_xlabel("cross-channel onset coincidences within +-%g s"
                   % rotation["pair_window_s"], fontsize=LABEL_SIZE)
    ax2.set_ylabel("rotation trials", fontsize=LABEL_SIZE)
    ratio = rotation["ratio_observed_over_null_median"]
    ax2.set_title("B  do the events co-occur more than event density "
                  "alone explains?\n"
                  "observed %d vs null median %.0f  (%.2fx),  %s"
                  % (rotation["observed_coincidences"],
                     rotation["null_median"],
                     ratio if ratio else float("nan"),
                     _p_text(rotation["p"])),
                  fontsize=TITLE_SIZE)
    ax2.legend(loc="upper right", frameon=False, fontsize=CAPTION_SIZE)

    survives = payload["family_result_without_common_mode"]
    fig.text(0.5, 0.012,
             "Bins are stated defaults, not truths: common_mode |lag| <= "
             "%.1f s and r >= %.2f; propagation %.1f < |lag| <= %.1f s and "
             "r >= %.2f. Sensitivity at +-50%% on each is in "
             "CROSS_CHANNEL.json. Removing every common-mode event "
             "(%d of %d) and rebuilding Task 2's family table gives "
             "permutation p = %s (was %s) and Cramer's V %s (was %s) - "
             "the channel-independence result %s."
             % (thresholds.common_lag_s, thresholds.common_r,
                thresholds.common_lag_s, thresholds.propagation_lag_s,
                thresholds.propagation_r,
                survives["n_common_mode_events_removed"],
                survives["n_before"],
                ("%.4f" % survives["permutation_p"])
                if survives.get("permutation_p") is not None else "n/a",
                ("%.4f" % survives["permutation_p_with_common_mode"])
                if survives.get("permutation_p_with_common_mode") is not None
                else "n/a",
                ("%.4f" % survives["cramers_v"])
                if survives.get("cramers_v") is not None else "n/a",
                ("%.4f" % survives["cramers_v_with_common_mode"])
                if survives.get("cramers_v_with_common_mode") is not None
                else "n/a",
                "SURVIVES" if survives.get("survives") else "DOES NOT survive"),
             ha="center", va="bottom", fontsize=CAPTION_SIZE)
    return _save(fig, out_path)


# ===========================================================================
# Task 4 - CLUSTER_K.png
# ===========================================================================

def plot_cluster_k(payload, out_path):
    rows = payload["per_k"]
    selection = payload["selection"]
    ks = [row["k"] for row in rows]

    fig, ax = plt.subplots(figsize=(10.5, 6.0))
    ax.plot(ks, [row["silhouette"] for row in rows], marker="o", lw=2.0,
            color="#1b4965", label="mean silhouette")
    ax.set_xlabel("number of families, k", fontsize=LABEL_SIZE)
    ax.set_ylabel("mean silhouette", color="#1b4965", fontsize=LABEL_SIZE)
    ax.tick_params(axis="y", labelcolor="#1b4965")

    ax2 = ax.twinx()
    gaps = np.asarray([row["gap"] for row in rows], dtype=float)
    errors = np.asarray([row["gap_se"] for row in rows], dtype=float)
    ax2.errorbar(ks, gaps, yerr=errors, marker="s", lw=1.7, color="#c1666b",
                 capsize=3, label="gap statistic (%d uniform references)"
                                  % payload["n_gap_references"])
    ax2.set_ylabel("gap statistic", color="#c1666b", fontsize=LABEL_SIZE)
    ax2.tick_params(axis="y", labelcolor="#c1666b")

    selected = selection["selected_k"]
    ax.axvline(selected, color="#12232e", lw=1.8, ls="--")
    ax.annotate("selected k = %d" % selected, (selected, 0.985),
                xycoords=("data", "axes fraction"), xytext=(7, 0),
                textcoords="offset points", ha="left", va="top",
                fontsize=LABEL_SIZE, fontweight="bold")
    if selection["gap_selected_k"] and selection["gap_selected_k"] != selected:
        ax.axvline(selection["gap_selected_k"], color="#c1666b", lw=1.2,
                   ls=":")
        ax.annotate("gap rule: k = %d" % selection["gap_selected_k"],
                    (selection["gap_selected_k"], 0.90),
                    xycoords=("data", "axes fraction"), xytext=(7, 0),
                    textcoords="offset points", fontsize=CAPTION_SIZE,
                    color="#c1666b")
    if n1.COARSE_K != selected:
        ax.axvline(n1.COARSE_K, color="#7d5ba6", lw=1.2, ls="-.")
        ax.annotate("shipped cut: k = %d" % n1.COARSE_K,
                    (n1.COARSE_K, 0.82), xycoords=("data", "axes fraction"),
                    xytext=(7, 0), textcoords="offset points",
                    fontsize=CAPTION_SIZE, color="#7d5ba6")

    ax.set_xticks(ks)
    ax.grid(alpha=0.16, ls=":")
    ax.set_title("Choosing k by a rule written down before the answer "
                 "was read\n"
                 "RULE: %s\n"
                 "-> k = %d (silhouette %.3f).  Cophenetic r = %.3f "
                 "(a property of the LINKAGE, not of k), n = %d motifs"
                 % (selection["rule"], selected,
                    selection["selected_silhouette"],
                    payload["cophenetic_r"], payload["n"]),
                 fontsize=TITLE_SIZE)

    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, loc="upper right",
              frameon=False, fontsize=CAPTION_SIZE)

    fig.text(0.5, 0.005, payload["gap_caveat"], ha="center", va="bottom",
             fontsize=CAPTION_SIZE, wrap=True)
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    return _save(fig, out_path)


# ===========================================================================
# Task 5 - SEQUENCE.png
# ===========================================================================

def plot_sequence(payload, out_path):
    grouped = payload["_grouped"]
    stats = payload["per_channel"]

    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.6))
    fig.subplots_adjust(hspace=0.34, wspace=0.22, top=0.86, bottom=0.10,
                        left=0.06, right=0.985)

    # A. ISI distribution per channel
    ax = axes[0, 0]
    for channel in range(5):
        isi = grouped[channel]["isi_s"]
        isi = isi[isi > 0]
        if not isi.size:
            continue
        ax.hist(np.log10(isi), bins=34, histtype="step", lw=1.8,
                color=CHANNEL_COLOURS[channel],
                label="CH%d  median %.1f s" % (channel, np.median(isi)))
    ticks = [-1, 0, 1, 2]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["%g" % (10.0 ** t) for t in ticks])
    ax.set_xlabel("inter-event interval (s, log scale)", fontsize=LABEL_SIZE)
    ax.set_ylabel("intervals", fontsize=LABEL_SIZE)
    ax.set_title("A  ISI distribution per channel", fontsize=TITLE_SIZE)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE)

    def _smooth(values, window=15):
        values = np.asarray(values, dtype=float)
        if values.size < window:
            return values
        kernel = np.ones(window) / window
        return np.convolve(values, kernel, mode="valid")

    # B. ISI against event index
    ax = axes[0, 1]
    for channel in range(5):
        isi = grouped[channel]["isi_s"]
        if isi.size < 16:
            continue
        smoothed = _smooth(isi)
        ax.plot(np.arange(smoothed.size), smoothed, lw=1.9,
                color=CHANNEL_COLOURS[channel],
                label="CH%d  r$^2$ = %.3f" % (
                    channel, stats["CH%d" % channel]["isi_drift"]["r2"] or 0))
    ax.set_xlabel("event index within the channel", fontsize=LABEL_SIZE)
    ax.set_ylabel("ISI (s), 15-interval moving mean", fontsize=LABEL_SIZE)
    ax.set_title("B  does the ISI rise across the recording?\n"
                 "the draft's \"stegosaurus\" pattern - %s"
                 % ("VISIBLE on "
                    + ", ".join(payload["archetypes"]
                                ["channels_with_rising_isi"])
                    if payload["archetypes"]["channels_with_rising_isi"]
                    else "NOT visible on any channel"),
                 fontsize=TITLE_SIZE)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE, ncol=2)

    # C. depth against event index
    ax = axes[1, 0]
    for channel in range(5):
        depths = grouped[channel]["depths_mv"]
        if depths.size < 16:
            continue
        smoothed = _smooth(depths)
        ax.plot(np.arange(smoothed.size), smoothed, lw=1.9,
                color=CHANNEL_COLOURS[channel],
                label="CH%d  r$^2$ = %.3f" % (
                    channel,
                    stats["CH%d" % channel]["depth_drift"]["r2"] or 0))
    ax.set_xlabel("event index within the channel", fontsize=LABEL_SIZE)
    ax.set_ylabel("drop depth (mV), 15-event moving mean",
                  fontsize=LABEL_SIZE)
    ax.set_title("C  amplitude drift across the recording - %s"
                 % ("VISIBLE on "
                    + ", ".join(payload["archetypes"]
                                ["channels_with_depth_drift"])
                    if payload["archetypes"]["channels_with_depth_drift"]
                    else "NOT visible on any channel"),
                 fontsize=TITLE_SIZE)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE, ncol=2)

    # D. CV
    ax = axes[1, 1]
    cvs = [stats["CH%d" % c]["cv"] or 0.0 for c in range(5)]
    ax.bar(range(5), cvs, color=CHANNEL_COLOURS, width=0.6,
           edgecolor="white", lw=1.2)
    ax.axhline(1.0, color="#12232e", lw=1.8, ls="--")
    ax.annotate("CV = 1  (Poisson)", (4.45, 1.0), xytext=(0, 5),
                textcoords="offset points", ha="right", fontsize=CAPTION_SIZE)
    ax.axhspan(1.0 - 0.15, 1.0 + 0.15, color="#12232e", alpha=0.08)
    for channel, cv in enumerate(cvs):
        ax.annotate("%.2f\n%s" % (cv, stats["CH%d" % channel]["regularity"]
                                  .split(" (")[0]),
                    (channel, cv), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=CAPTION_SIZE)
    ax.set_xticks(range(5))
    ax.set_xticklabels(n1.CHANNEL_NAMES)
    ax.set_ylabel("ISI coefficient of variation", fontsize=LABEL_SIZE)
    ax.set_ylim(0, max(cvs) * 1.32)
    ax.set_title("D  regularity: CV < 1 regular, CV > 1 bursting",
                 fontsize=TITLE_SIZE)

    fig.suptitle("Sequence structure over 20 minutes, from the refined "
                 "store's own columns (n = %d events)\n%s"
                 % (payload["n"], payload["archetypes"]["verdict"]),
                 fontsize=TITLE_SIZE + 1.5, y=0.985)
    return _save(fig, out_path)


# ===========================================================================
# Task 6 - the three small panels
# ===========================================================================

def plot_quant_duration(payload, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0))
    samples = np.asarray(payload["_duration_samples"], dtype=float)
    seconds = np.asarray(payload["_duration_seconds"], dtype=float)

    # Clipped to the 99th percentile. The full range runs to 132 samples,
    # and drawn in full the tail compresses the 6-11 sample bulk - which is
    # the entire point of the panel - into three bars. The clipped count is
    # annotated so nothing is hidden.
    limit = float(np.percentile(samples, 99))
    beyond = int((samples > limit).sum())

    edges = np.arange(samples.min() - 0.5, limit + 1.5, 1.0)
    axes[0].hist(samples, bins=edges, color="#1b4965", alpha=0.88)
    axes[0].set_xlim(samples.min() - 1, limit + 1)
    axes[0].annotate("%d motifs beyond %g samples\n(longest %d)"
                     % (beyond, limit, payload["max_samples"]),
                     (0.97, 0.86), xycoords="axes fraction", ha="right",
                     fontsize=CAPTION_SIZE)
    axes[0].set_xlabel("fall duration (SAMPLES at 10 Hz)", fontsize=LABEL_SIZE)
    axes[0].set_ylabel("motifs", fontsize=LABEL_SIZE)
    axes[0].set_title("in samples - the honest unit\n"
                      "median %g samples, IQR %g-%g, %d distinct values"
                      % (payload["median_samples"], payload["q1_samples"],
                         payload["q3_samples"], payload["n_distinct_samples"]),
                      fontsize=TITLE_SIZE)

    axes[1].hist(seconds, bins=np.arange(seconds.min() - 0.05,
                                         limit / 10.0 + 0.15, 0.1),
                 color="#c1666b", alpha=0.88)
    axes[1].set_xlim((samples.min() - 1) / 10.0, (limit + 1) / 10.0)
    axes[1].set_xlabel("fall duration (seconds)", fontsize=LABEL_SIZE)
    axes[1].set_title("in seconds - the same histogram\n"
                      "median %.1f s, IQR %.1f-%.1f s, step = %.1f s"
                      % (payload["median_seconds"], payload["q1_seconds"],
                         payload["q3_seconds"], payload["quantum_s"]),
                      fontsize=TITLE_SIZE)

    fig.suptitle("Any claim about fall duration is a claim about a few "
                 "samples (n = %d motifs, fs = 10 Hz)" % payload["n"],
                 fontsize=TITLE_SIZE + 1)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, out_path)


def plot_alphabet(payload, out_path):
    """Per-channel dSAX letter occupancy.

    The verdict goes in a WRAPPED caption below the axes, not in the
    title: it is a three-line sentence, and matplotlib's tight bounding
    box will widen the whole canvas to fit a one-line title, which turned
    the first version of this figure into a 5600-pixel-wide strip with a
    postage stamp in the middle.
    """
    letters = payload["letters"]
    fig, ax = plt.subplots(figsize=(11.0, 6.0))
    width = 0.15
    for channel in range(5):
        counts = np.asarray(payload["per_channel"]["CH%d" % channel]
                            ["proportions"], dtype=float)
        ax.bar(np.arange(len(letters)) + (channel - 2) * width, counts,
               width=width, color=CHANNEL_COLOURS[channel],
               label="CH%d" % channel, edgecolor="white", lw=0.7)
    ax.set_xticks(range(len(letters)))
    ax.set_xticklabels(["%s\n%s" % (letter,
                                    payload["letter_meaning"][letter])
                        for letter in letters], fontsize=LABEL_SIZE)
    ax.set_ylabel("share of dSAX segments", fontsize=LABEL_SIZE)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE, ncol=5,
              loc="upper right")
    ax.grid(axis="y", alpha=0.15, ls=":")
    met = payload["expectation_met"]
    ax.set_title("dSAX alphabet occupancy per channel\n"
                 "k = %d, %g-sigma noise-floor split, %d segments over "
                 "the 47 windows of each channel\n"
                 "expected: S dominant [%s] and d, u rare [%s]"
                 % (payload["k"], payload["sigma"],
                    payload["per_channel"]["CH0"]["n_segments"],
                    "YES" if met["S_dominant"] else "NO",
                    "YES" if met["d_and_u_rare"] else "NO"),
                 fontsize=TITLE_SIZE)

    wrapped = _wrap(payload["verdict"], 108)
    fig.tight_layout(rect=(0, 0.02 + 0.028 * len(wrapped), 1, 1))
    fig.text(0.5, 0.015, "\n".join(wrapped), ha="center", va="bottom",
             fontsize=CAPTION_SIZE)
    return _save(fig, out_path)


def _wrap(text, width):
    """Greedy word wrap. `fig.text(..., wrap=True)` only wraps against the
    figure width AFTER layout, which does not help when the caption is what
    decides the layout."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def plot_windowing(payload, out_path):
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4),
                             gridspec_kw={"width_ratios": (1.15, 1.0)})
    ax = axes[0]
    positions = np.arange(5)
    whole = [payload["per_channel"]["CH%d" % c]["whole_channel"]
             for c in range(5)]
    sliding = [payload["per_channel"]["CH%d" % c]["sliding"] for c in range(5)]
    ax.bar(positions - 0.19, whole, width=0.38, color="#8d99ae",
           label="whole-channel (drop_motifs8)", edgecolor="white")
    ax.bar(positions + 0.19, sliding, width=0.38, color="#1b4965",
           label="sliding window (drop_motifs9)", edgecolor="white")
    for channel in range(5):
        ax.annotate("%.1fx" % (sliding[channel] / max(whole[channel], 1)),
                    (channel, max(whole[channel], sliding[channel])),
                    xytext=(0, 4), textcoords="offset points", ha="center",
                    fontsize=CAPTION_SIZE, fontweight="bold")
    ax.set_xticks(positions)
    ax.set_xticklabels(n1.CHANNEL_NAMES)
    ax.set_ylabel("motifs detected (before the depth floor)",
                  fontsize=LABEL_SIZE)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE)
    ax.set_title("A  what the sliding window adds\n"
                 "%d -> %d pooled;  CH2 %d -> %d"
                 % (payload["total_whole"], payload["total_sliding"],
                    payload["per_channel"]["CH2"]["whole_channel"],
                    payload["per_channel"]["CH2"]["sliding"]),
                 fontsize=TITLE_SIZE)

    ax = axes[1]
    added = np.asarray(payload["_added_depths"], dtype=float)
    shared = np.asarray(payload["_shared_depths"], dtype=float)
    for values, colour, label in ((shared, "#8d99ae",
                                   "found by both (n = %d)" % len(shared)),
                                  (added, "#1b4965",
                                   "added by the sliding window (n = %d)"
                                   % len(added))):
        values = values[values > 0]
        if values.size:
            ax.hist(np.log10(values), bins=40, histtype="stepfilled",
                    alpha=0.6, color=colour, label=label)
    ax.axvline(np.log10(n1.MIN_DEPTH_MV), color="#12232e", lw=1.5, ls="--")
    ticks = [0.01, 0.03, 0.1, 0.3, 1.0]
    ax.set_xticks(np.log10(ticks))
    ax.set_xticklabels(["%g" % t for t in ticks])
    ax.set_xlabel("drop depth (mV, log scale)", fontsize=LABEL_SIZE)
    ax.set_ylabel("motifs", fontsize=LABEL_SIZE)
    ax.legend(frameon=False, fontsize=CAPTION_SIZE)
    fraction = payload["added_above_floor_fraction"]
    ax.set_title("B  is the extra count real signal or inflation?\n"
                 "%s: %.0f%% of what the sliding window adds is above the "
                 "0.1 mV floor (%d of %d)"
                 % ("MOSTLY SIGNAL" if fraction >= 0.5 else "MOSTLY GATED "
                    "AWAY", 100 * fraction,
                    payload.get("n_added_above_floor", 0),
                    payload["n_added"]),
                 fontsize=TITLE_SIZE)

    fig.text(0.5, 0.005, payload["reading"], ha="center", va="bottom",
             fontsize=CAPTION_SIZE, wrap=True)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    return _save(fig, out_path)
