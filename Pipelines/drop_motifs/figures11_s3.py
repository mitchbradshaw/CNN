"""
figures11_s3.py
================
Section 3: what a sequence of events does to a waveform. Every figure here
selects its sequence from `sequences.csv` by a rule in `sequences11`, never
by hand, so re-running on a larger store picks the sequence the rule picks
rather than the one that happened to look good once.

The argument the pair of panels in S3.1 makes
----------------------------------------------
Left, native units: events of visibly different size, which is what a
detector sees. Right, per-event normalised: the same events revealed as one
shape changing slowly. Neither panel alone is the point; the pair is.

The two narrow panels underneath turn that into a number. Every step along
the sequence is small; the first and last events are far apart. A shape
clustering cutting at any height puts the two ends in different families,
and the sequence between them is continuous. That is the Section 3 claim.
"""

import numpy as np
from matplotlib import colors as mcolors
from matplotlib import gridspec
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

from Pipelines.drop_motifs import (config11, sequences11, store11, style7,
                                   tree10)

N_NORMALISED = 200

# A waterfall of 114 traces is a smear. Above this the drawn sequence is
# thinned to evenly spaced members - the FIGURE is thinned, never the
# measurement: the difference and overlay panels below still run over every
# event, and the thinning is stated on the panel and in the manifest.
MAX_DRAWN = 42

# Vertical separation between successive traces in a waterfall, in units of
# the panel's own median event depth (native) or z (normalised).
OFFSET_NATIVE = 0.85
OFFSET_NORMALISED = 1.15

LW_TRACE = 1.0


def _thin(members, limit=MAX_DRAWN):
    """Evenly spaced members, first and last always kept."""
    if len(members) <= limit:
        return list(members), False
    picks = np.unique(np.linspace(0, len(members) - 1, limit).round().astype(int))
    return [members[int(i)] for i in picks], True


def _species_ramp(species):
    """A light-to-dark ramp through the SPECIES' own hue.

    `style7.family_colours` grades by time the way the shipped
    drop_motifs8 overlays do, but its ramp is chosen by family index, so
    an oyster sequence came out in reishi's green while the step panel
    beside it stayed oyster blue - the same species drawn in two colours
    inside one figure. Colour carries species everywhere else in this run
    and it has to carry it here too, so the ramp is built from the
    species' own colour and time is graded within it.
    """
    base = np.array(mcolors.to_rgb(config11.colour_of(species)))
    light = 1.0 - 0.78 * (1.0 - base)          # towards white, not to it
    dark = 0.45 * base                          # towards black, not to it
    return mcolors.LinearSegmentedColormap.from_list(
        f"time_{species}", [light, base, dark], N=256)


def _time_colours(members, species):
    """`(colours, norm, cmap)` - one colour per event, oldest to newest.

    The norm runs over time FROM THE START OF THE SEQUENCE, not absolute
    seconds in the recording. An oyster sequence starting at 1,362,824 s
    gives a colourbar reading "1.3630 ... 1.3665, x1e6", which is a number
    nobody can use; elapsed seconds is the quantity the reader wants.
    """
    onsets = np.array([float(row["onset_s"]) for row in members], dtype=float)
    cmap = _species_ramp(species)
    if onsets.size == 0:
        return [], None, cmap
    elapsed = onsets - onsets.min()
    high = float(elapsed.max())
    norm = mcolors.Normalize(vmin=0.0, vmax=high if high > 0 else 1.0)
    return [cmap(norm(value)) for value in elapsed], norm, cmap


def _families_of(rows, snippets, k):
    """`({event_id: family}, cophenetic)` at one cut of the pooled tree.

    Pooled over everything handed in, not per species: the question the
    start-versus-end panel asks is whether a shape clustering would split
    the two ends, and it is the clustering the rest of the run uses.
    """
    built = tree10.build(rows, snippets, coarse_k=k, fine_k=k)
    if built is None:
        return {}, float("nan")
    return ({row["event_id"]: int(label)
             for row, label in zip(built["rows"], built["coarse"])},
            float(built["cophenetic"]))


def _normalised_sequence(members, snippets):
    """`(features, kept)` - every member's normalised fall, in time order."""
    features, kept = [], []
    for row in members:
        vector = store11.normalised_fall(row, snippets, n=N_NORMALISED)
        if vector is None:
            continue
        features.append(vector)
        kept.append(row)
    if not features:
        return np.empty((0, N_NORMALISED)), []
    return np.vstack(features), kept


def _rms(a, b):
    return float(np.linalg.norm(a - b) / np.sqrt(np.asarray(a).size))


# ==========================================================================
# S3.1  A waveform morphing across a sequence
# ==========================================================================

def plot_sequence_morph(run, snippets, path, *, store_label="",
                        families=None, family_k=None, selection=""):
    """One sequence, drawn twice, with the step sizes and the two ends."""
    config11.apply_style()
    members = run["rows"]
    species = run["species"]
    resolved = config11.resolve([species])
    label = resolved[species]["label"]

    features, kept = _normalised_sequence(members, snippets)
    drawn, thinned = _thin(kept)
    colours, norm, cmap = _time_colours(kept, species)
    colour_by_id = {row["event_id"]: colour
                    for row, colour in zip(kept, colours)}

    fig = plt.figure(figsize=(11.0, 10.4))
    outer = gridspec.GridSpec(2, 1, figure=fig, hspace=0.32,
                              height_ratios=[2.35, 1.0])
    top = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=outer[0],
                                           wspace=0.20,
                                           width_ratios=[1.0, 1.0, 0.05])
    bottom = gridspec.GridSpecFromSubplotSpec(1, 2, subplot_spec=outer[1],
                                              wspace=0.26,
                                              width_ratios=[1.55, 1.0])

    native_ax = fig.add_subplot(top[0, 0])
    norm_ax = fig.add_subplot(top[0, 1])
    bar_ax = fig.add_subplot(top[0, 2])

    # -- left: native units, oldest at top --------------------------------
    depth_step = OFFSET_NATIVE * float(np.median(
        [abs(float(r["drop_depth_mv"])) for r in drawn]))
    for position, row in enumerate(drawn):
        t, y = store11.native_trace(row, snippets, pre_falls=0.5,
                                    post_falls=1.5)
        if t is None:
            continue
        native_ax.plot(t, y - depth_step * position,
                       color=colour_by_id[row["event_id"]], lw=LW_TRACE,
                       solid_capstyle="round", zorder=3)
    native_ax.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
                      lw=style7.LW_RULE, alpha=0.5, zorder=1)
    native_ax.set_yticks([])
    native_ax.set_xlabel("time from onset (s)")
    native_ax.set_ylabel("amplitude (mV), successive events offset")
    config11.panel_title(native_ax, f"{label} - native units", n=len(drawn))
    native_ax.grid(axis="x", alpha=0.15, lw=style7.LW_RULE * 0.5)

    # A drawn scale bar, because the y axis is offsets rather than volts.
    # Placed a little inside the left spine, with the label clear of it -
    # drawn exactly ON the spine the two overprint each other.
    low, high = native_ax.get_xlim()
    bar_x = low + 0.03 * (high - low)
    native_ax.plot([bar_x, bar_x], [0, -depth_step], color=style7.RULE_COLOUR,
                   lw=2.2, zorder=5, solid_capstyle="butt")
    native_ax.annotate(f"{depth_step:.3g} mV", xy=(bar_x, -depth_step / 2),
                       xytext=(6, 0), textcoords="offset points",
                       fontsize=config11.FS_ANNOT, color="0.30", va="center",
                       ha="left", zorder=5)

    # -- right: the same events, each z-normalised -------------------------
    phase = np.linspace(0.0, 1.0, N_NORMALISED)
    drawn_ids = {row["event_id"] for row in drawn}
    position = 0
    for row, vector in zip(kept, features):
        if row["event_id"] not in drawn_ids:
            continue
        norm_ax.plot(phase, vector - OFFSET_NORMALISED * position,
                     color=colour_by_id[row["event_id"]], lw=LW_TRACE,
                     solid_capstyle="round", zorder=3)
        position += 1
    norm_ax.set_yticks([])
    norm_ax.set_xlim(0.0, 1.0)
    norm_ax.set_xlabel("fraction of the fall")
    norm_ax.set_ylabel("amplitude (z), successive events offset")
    config11.panel_title(norm_ax, f"{label} - per-event normalised",
                         n=len(drawn))
    norm_ax.grid(axis="x", alpha=0.15, lw=style7.LW_RULE * 0.5)

    if norm is not None:
        bar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
                           cax=bar_ax)
        bar.set_label("time from sequence start (s)",
                      fontsize=config11.FS_LABEL)
        bar.ax.tick_params(labelsize=config11.FS_TICK)

    # -- successive difference --------------------------------------------
    step_ax = fig.add_subplot(bottom[0, 0])
    steps = [_rms(features[i], features[i + 1])
             for i in range(len(features) - 1)]
    endpoints = _rms(features[0], features[-1]) if len(features) >= 2 \
        else float("nan")
    step_ax.step(np.arange(1, len(steps) + 1), steps, where="mid",
                 color=resolved[species]["colour"], lw=1.4, zorder=3)
    step_ax.axhline(endpoints, color=style7.RULE_COLOUR, ls="--",
                    lw=style7.LW_RULE * 1.4, zorder=2)
    step_ax.annotate(f"first to last {endpoints:.2f}",
                     xy=(0.99, endpoints), xycoords=("axes fraction", "data"),
                     xytext=(0, 4), textcoords="offset points", ha="right",
                     va="bottom", fontsize=config11.FS_ANNOT, color="0.30")
    # How many steps are smaller than the net displacement is the whole
    # quantitative content of this panel, and it is not the same for every
    # sequence - one of the three shipped runs has half its steps LARGER
    # than its first-to-last distance, which is a wandering sequence rather
    # than a morph. Printing the count stops the reference line being read
    # as "every step is small" when it is not.
    below = sum(1 for step in steps if step < endpoints)
    step_ax.set_xlabel(f"step along the sequence\n"
                       f"{below} of {len(steps)} steps smaller than the "
                       f"first-to-last distance")
    step_ax.set_ylabel("distance (z RMS)")
    step_ax.set_ylim(0.0, max(max(steps, default=0.1), endpoints) * 1.35)
    config11.panel_title(step_ax, "Distance between successive events",
                         n=len(steps))
    step_ax.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)

    # -- start against end -------------------------------------------------
    ends_ax = fig.add_subplot(bottom[0, 1])
    first_family = (families or {}).get(kept[0]["event_id"])
    last_family = (families or {}).get(kept[-1]["event_id"])
    if len(features) >= 2:
        ends_ax.plot(phase, features[0], color=colours[0], lw=1.9,
                     zorder=3, label=f"first, F{first_family}")
        ends_ax.plot(phase, features[-1], color=colours[-1], lw=1.9,
                     ls=(0, (4, 2)), zorder=3, label=f"last, F{last_family}")
        ends_ax.fill_between(phase, features[0], features[-1], color="0.55",
                             alpha=0.16, lw=0, zorder=2)
    ends_ax.set_xlim(0.0, 1.0)
    ends_ax.set_xlabel("fraction of the fall")
    ends_ax.set_ylabel("amplitude (z)")
    same = first_family is not None and first_family == last_family
    config11.panel_title(
        ends_ax,
        f"First and last event  -  families F{first_family} and F{last_family}"
        if not same else
        f"First and last event  -  both family F{first_family}")
    ends_ax.legend(loc="upper right", frameon=False,
                   fontsize=config11.FS_LEGEND)
    ends_ax.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)

    fig.suptitle(f"{label} sequence {run['sequence_key']}",
                 fontsize=config11.FS_SUPTITLE, y=0.995)
    config11.footer(fig, store_label, run["n"],
                    extra=f"{selection}; {'thinned to ' + str(len(drawn)) + ' of ' + str(len(kept)) + ' events for drawing' if thinned else 'every event drawn'}")

    manifest = {
        "store": store_label,
        "selection_rule": selection,
        "sequence": {key: run[key] for key in sequences11.FIELDS},
        "n_events": run["n"],
        "n_normalised": len(kept),
        "n_drawn": len(drawn),
        "thinned_for_drawing": bool(thinned),
        "family_cut_k": family_k,
        "first_family": first_family,
        "last_family": last_family,
        "ends_in_same_family": bool(same),
        "step_distance_z_rms": {
            "median": float(np.median(steps)) if steps else float("nan"),
            "max": float(np.max(steps)) if steps else float("nan"),
            "n_steps": len(steps),
        },
        "first_to_last_z_rms": endpoints,
        "steps_below_endpoint_distance":
            int(sum(1 for s in steps if s < endpoints)),
        "distance": "Euclidean over 200-point z-normalised falls, / sqrt(200)",
    }
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


# ==========================================================================
# S3.2  The same morph at different scales
# ==========================================================================

def plot_morph_across_scales(runs, snippets, path, *, store_label="",
                             summary=None, candidates=None):
    """One row per species, its clearest qualifying sequence as a compact
    normalised waterfall, rows ordered by native event duration."""
    config11.apply_style()
    species = config11.order({run["species"] for run in runs})
    resolved = config11.resolve(species)

    chosen = {}
    for name in species:
        run = sequences11.clearest(runs, name)
        if run is not None:
            chosen[name] = run
    # Ordered by the row's own native event duration, shortest first, so
    # the figure reads as one morph seen at three time scales rather than
    # as three unrelated species.
    ordered = sorted(chosen, key=lambda name: chosen[name]["median_fall_s"])

    # Narrower and taller than square: a normalised waterfall is read
    # down the page, and a wide short panel flattens 114 traces into
    # a smear.
    fig = plt.figure(figsize=(7.4, 3.5 * max(len(ordered), 1) + 1.0))
    grid = gridspec.GridSpec(max(len(ordered), 1), 2, figure=fig,
                             wspace=0.10, hspace=0.66,
                             width_ratios=[1.0, 0.028])

    manifest = {"store": store_label, "rows": [],
                "selection_rule": "sequences11.clearest - longest, then most "
                                  "regular among runs within 60% of that "
                                  "length",
                "row_order": "ascending median native fall duration",
                "sequence_thresholds": (summary or {}).get("thresholds")}

    phase = np.linspace(0.0, 1.0, N_NORMALISED)
    for index, name in enumerate(ordered):
        run = chosen[name]
        ax = fig.add_subplot(grid[index, 0])
        bar_ax = fig.add_subplot(grid[index, 1])

        features, kept = _normalised_sequence(run["rows"], snippets)
        drawn, thinned = _thin(kept)
        colours, norm, cmap = _time_colours(kept, name)
        colour_by_id = {row["event_id"]: colour
                        for row, colour in zip(kept, colours)}

        drawn_ids = {row["event_id"] for row in drawn}
        position = 0
        for row, vector in zip(kept, features):
            if row["event_id"] not in drawn_ids:
                continue
            ax.plot(phase, vector - OFFSET_NORMALISED * position,
                    color=colour_by_id[row["event_id"]], lw=LW_TRACE,
                    solid_capstyle="round", zorder=3)
            position += 1
        ax.set_yticks([])
        ax.set_xlim(0.0, 1.0)
        ax.set_ylabel("z, events offset")
        ax.grid(axis="x", alpha=0.15, lw=style7.LW_RULE * 0.5)

        duration_range = store11.range_label(run["rows"], "fall_duration_s", "s")
        depth_range = store11.range_label(run["rows"], "drop_depth_mv", "mV")
        config11.panel_title(ax, f"{resolved[name]['label']} - "
                                 f"{run['sequence_key']}", n=run["n"])

        # The Lion's mane row is expected to be the near-empty case, and it
        # says so with the counts rather than by being left out.
        per = (summary or {}).get("per_species", {}).get(name, {})
        pool = (candidates or {}).get(name)
        scarcity = ""
        if pool is not None and per:
            scarcity = (f"; {per.get('runs', 0)} of {pool} candidate runs "
                        f"pass the regularity gate")
        ax.set_xlabel(f"fraction of the fall\n"
                      f"native: fall {duration_range}, depth {depth_range}"
                      f"{scarcity}")

        if norm is not None:
            bar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap),
                               cax=bar_ax)
            bar.set_label("elapsed (s)", fontsize=config11.FS_ANNOT)
            bar.ax.tick_params(labelsize=config11.FS_TICK)

        manifest["rows"].append({
            "species": name,
            "label": resolved[name]["label"],
            "sequence_key": run["sequence_key"],
            "n_events": run["n"],
            "n_drawn": len(drawn),
            "thinned_for_drawing": bool(thinned),
            "cv_interval": run["cv_interval"],
            "r2_trend": run["r2_trend"],
            "drift_ratio": run["drift_ratio"],
            "arm": run["arm"],
            "median_fall_s": run["median_fall_s"],
            "median_depth_mv": run["median_depth_mv"],
            "fall_duration_s_range": list(
                store11.span_of(run["rows"], "fall_duration_s")),
            "drop_depth_mv_range": list(
                store11.span_of(run["rows"], "drop_depth_mv")),
            "qualifying_runs": per.get("runs"),
            "candidate_runs": pool,
        })

    fig.suptitle("One qualifying sequence per species, normalised",
                 fontsize=config11.FS_SUPTITLE, y=0.997)
    config11.footer(fig, store_label,
                    sum(run["n"] for run in chosen.values()),
                    extra="rows ordered by native fall duration")
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


# ==========================================================================
# S3.3  Isolated events - a probe, drawn only if the effect exists
# ==========================================================================

def probe_isolated_pairs(rows, species, path, *, store_label="",
                         n_shuffles=1000, draw=True):
    """Does a shallow drop tend to precede a deeper one?

    For every pair and triplet of consecutive events on one channel
    separated by less than that species' median interval, the depth ratio
    of first to second is measured, and compared against a null in which
    the order WITHIN EACH PAIR is shuffled. Shuffling within the pair and
    not across pairs is the point: it destroys the ordering and preserves
    every other property of the set, so a difference can only be ordering.

    Returns a result dict. The figure is drawn only if the observed median
    log ratio falls outside the shuffled null's central 95%; this is a
    probe and an absent effect is a one-line answer, not a panel.
    """
    own = [r for r in rows if r.get("species") == species]
    if len(own) < 4:
        return {"species": species, "n_pairs": 0, "effect": False,
                "reason": "fewer than four events"}

    intervals = []
    for members in store11.groups(own).values():
        onsets = np.array([r["onset_s"] for r in members], dtype=float)
        intervals.extend(np.diff(onsets)[np.diff(onsets) > 0].tolist())
    if not intervals:
        return {"species": species, "n_pairs": 0, "effect": False,
                "reason": "no positive intervals"}
    threshold = float(np.median(intervals))

    pairs, triplets = [], 0
    for members in store11.groups(own).values():
        run_length = 1
        for index in range(len(members) - 1):
            gap = members[index + 1]["onset_s"] - members[index]["onset_s"]
            if 0 < gap < threshold:
                first = abs(float(members[index]["drop_depth_mv"]))
                second = abs(float(members[index + 1]["drop_depth_mv"]))
                if first > 0 and second > 0:
                    pairs.append((first, second))
                run_length += 1
            else:
                if run_length >= 3:
                    triplets += 1
                run_length = 1
        if run_length >= 3:
            triplets += 1

    if len(pairs) < 3:
        return {"species": species, "n_pairs": len(pairs), "effect": False,
                "median_interval_s": threshold,
                "reason": f"only {len(pairs)} close pairs"}

    block = np.array(pairs, dtype=float)
    # Log ratio, because a ratio is multiplicative: 2 and 0.5 are the same
    # size of effect in opposite directions, and their arithmetic mean is
    # 1.25, which would report an effect where there is none.
    observed = float(np.median(np.log10(block[:, 0] / block[:, 1])))
    deeper = int(np.sum(block[:, 0] > block[:, 1]))

    rng = np.random.default_rng(config11.seed_for(species))
    null = np.empty(int(n_shuffles))
    for index in range(int(n_shuffles)):
        flip = rng.random(len(block)) < 0.5
        first = np.where(flip, block[:, 1], block[:, 0])
        second = np.where(flip, block[:, 0], block[:, 1])
        null[index] = np.median(np.log10(first / second))
    low, high = np.percentile(null, [2.5, 97.5])

    # A two-sided permutation p, not just "outside the 2.5-97.5 interval".
    # On a few dozen pairs the median of a log ratio is a coarse, lumpy
    # statistic and the null piles up on a handful of values, so the
    # observed value can land exactly ON a percentile bound - which the
    # interval test would silently call either way. Counting how much of
    # the null is at least as extreme has no such edge, and it is also the
    # number that says the probe was underpowered rather than negative.
    centre = float(np.median(null))
    p_value = float((np.sum(np.abs(null - centre) >= abs(observed - centre)) + 1)
                    / (int(n_shuffles) + 1))
    effect = bool(p_value < 0.05)

    result = {
        "species": species,
        "label": config11.label_of(species),
        "n_pairs": len(pairs),
        "n_triplet_runs": triplets,
        "median_interval_s": threshold,
        "pair_rule": "consecutive events on one channel separated by less "
                     "than the species median inter-event interval",
        "statistic": "median log10(first depth / second depth)",
        "observed": observed,
        "observed_ratio": float(10.0 ** observed),
        "direction": "first drop deeper than second"
                     if observed > 0 else "first drop shallower than second",
        "n_first_deeper": deeper,
        "null_median": centre,
        "null_95": [float(low), float(high)],
        "p_two_sided": p_value,
        "null_distinct_values": int(np.unique(null).size),
        "n_shuffles": int(n_shuffles),
        "seed": config11.seed_for(species),
        "effect": effect,
        "figure_drawn": False,
    }
    if not effect or not draw:
        return result

    config11.apply_style()
    resolved = config11.resolve([species])
    fig, ax = plt.subplots(figsize=(6.0, 4.2))
    ax.hist(null, bins=40, color="0.72", edgecolor="white", linewidth=0.4,
            zorder=2, label=f"order shuffled ({n_shuffles:,}x)")
    ax.axvline(observed, color=resolved[species]["colour"], lw=2.2, zorder=3,
               label=f"observed {10.0 ** observed:.2f}x, first deeper")
    # The direction, stated as a count rather than left to a reader to infer
    # from the sign of a log ratio. The hypothesis put to this probe was
    # that a SHALLOW drop precedes a deeper one; the measurement runs the
    # other way, and the figure has to say which way it runs.
    ax.set_xlabel(f"median log10(first depth / second depth)\n"
                  f"first drop deeper in {deeper} of {len(pairs)} pairs; "
                  f"two-sided permutation p = {p_value:.3f}")
    ax.set_ylabel("shuffles")
    config11.panel_title(ax, f"{config11.label_of(species)} - depth ratio "
                             f"within close pairs", n=len(pairs))
    ax.legend(loc="upper left", frameon=False, fontsize=config11.FS_LEGEND)
    ax.grid(axis="y", alpha=0.15, lw=style7.LW_RULE * 0.5)
    config11.footer(fig, store_label, len(pairs),
                    extra=f"pairs closer than {threshold:.3g} s; the null "
                          f"takes only {int(np.unique(null).size)} distinct "
                          f"values, so p is coarse")
    config11.save(fig, path)
    result["figure_drawn"] = True
    config11.write_manifest(path, result)
    return result
