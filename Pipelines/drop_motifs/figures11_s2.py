"""
figures11_s2.py
================
Section 2's three figures. Nothing here detects, clusters differently from
`tree10`, or measures a quantity `store11` does not already own.

The house rules, applied
-------------------------
Titles are noun phrases. No sentence, paragraph or boxed note appears
inside an axes; the explanation is the caption and the caption lives in
FIGURES.md. Legends get their own axes rather than a `loc=` inside a data
panel - drop_motifs10's rose put one legend on top of another panel's tick
labels and the only reliable fix is to stop legends sharing space with
data. Every panel that draws a waveform in native units is aspect-locked
through `store11.aspect_for`, so a drop is drawn the shape it has in the
recording.
"""

import numpy as np
from matplotlib import gridspec
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

from Pipelines.drop_motifs import config11, store11, style7, tree10
from Working.Detection.drop_motifs import cluster

# S2.2
N_SAMPLE = 60                 # events drawn per species, or all if fewer
N_NORMALISED = 200            # resample length, as tree10 uses
ALPHA_SAMPLE = 0.22
LW_SAMPLE = 0.7
LW_MEDIAN = 2.0

# How much of the panel either side of the onset, in multiples of the
# SAMPLE'S OWN median fall duration. Same convention and same reason as
# `overlays7.PRE_ONSET_FALLS`: an axis framed on the extent spends its
# width on the one longest event.
PRE_ONSET_FALLS = 0.7
POST_ONSET_FALLS = 2.2

# And the same treatment for y, in multiples of the sample's own median
# drop depth. One 83 mV oyster event against a 4.8 mV median otherwise
# sets the y extent, and the aspect lock then has to squeeze the box into
# a sliver to honour it. Deeper events run off the top of the panel; the
# full range is stated on the axis and in the manifest.
DEPTH_BELOW = 2.5
DEPTH_ABOVE = 0.35

# The fraction of a panel's sampled events that must reach a point on the
# common time grid before a pointwise median is drawn there. Below this
# the "median" is describing two or three long events rather than the
# sample, and a median of three is not a median.
MEDIAN_SUPPORT = 0.8

# S2.1
N_ANGLE_BINS = 18
N_DEPTH_BINS = 4

# S2.3
MEDOIDS_PER_SPECIES = tree10.COARSE_K


# ==========================================================================
# S2.2  Scale invariance: the collapse
# ==========================================================================

def _sample(rows, n=N_SAMPLE, species=None):
    """A seeded draw, per species, that survives more data arriving.

    The generator is seeded from the species NAME, so a new species does
    not reshuffle an existing one's sample, and re-running the same
    command reproduces the same figure.
    """
    if len(rows) <= n:
        return list(rows)
    rng = config11.rng_for(species if species is not None
                           else rows[0].get("species"))
    picks = rng.choice(len(rows), size=int(n), replace=False)
    return [rows[int(i)] for i in sorted(picks)]


def _pointwise_median(traces, grid, support=MEDIAN_SUPPORT):
    """Median mV at each time after onset, over traces of unequal length.

    Each trace is a `(t, y)` pair on its own time axis. Two rules, and the
    second is not optional:

      - a point is drawn only where at least `support` of the traces reach
        it, so the line does not trail off into a median of the two
        longest events;
      - only the CONTIGUOUS stretch containing the onset is drawn.

    Without the second rule the line steps vertically wherever the set of
    contributing traces changes - a median over one subset joined to a
    median over another - which reads as a feature of the waveform and is
    not one.
    """
    stack = np.full((len(traces), grid.size), np.nan)
    for index, (t, y) in enumerate(traces):
        inside = (grid >= t[0]) & (grid <= t[-1])
        if inside.any():
            stack[index, inside] = np.interp(grid[inside], t, y)
    counted = np.sum(np.isfinite(stack), axis=0)
    keep = counted >= max(1, int(round(support * len(traces))))

    median = np.full(grid.size, np.nan)
    if not keep.any():
        return median
    onset = int(np.argmin(np.abs(grid)))
    if not keep[onset]:
        onset = int(np.argmax(keep))
    low = onset
    while low > 0 and keep[low - 1]:
        low -= 1
    high = onset
    while high < grid.size - 1 and keep[high + 1]:
        high += 1
    block = slice(low, high + 1)
    median[block] = np.nanmedian(stack[:, block], axis=0)
    return median


def plot_scale_collapse(rows, snippets, path, *, store_label=""):
    """Left: the sample in millivolts and seconds. Right: the same events
    resampled and z-normalised. One row per species."""
    config11.apply_style()
    grouped = store11.by_species(rows)
    species = list(grouped)
    resolved = config11.resolve(species)

    n_rows = len(species)
    fig = plt.figure(figsize=(9.6, 2.55 * n_rows + 1.0))
    grid = gridspec.GridSpec(n_rows, 2, figure=fig, wspace=0.26,
                             hspace=0.62, width_ratios=[1.0, 1.0])

    manifest = {"store": store_label, "n_total": len(rows),
                "sample_target": N_SAMPLE,
                "resample_length": N_NORMALISED,
                "median_support_fraction": MEDIAN_SUPPORT,
                "max_slope_unit": store11.MAX_SLOPE_UNIT_NOTE,
                "duration_orders_of_magnitude":
                    store11.orders_of_magnitude(rows, "fall_duration_s"),
                "amplitude_orders_of_magnitude":
                    store11.orders_of_magnitude(rows, "drop_depth_mv"),
                "species": {}}

    for index, name in enumerate(species):
        own = grouped[name]
        drawn = _sample(own, species=name)
        colour = resolved[name]["colour"]
        label = resolved[name]["label"]

        left = fig.add_subplot(grid[index, 0])
        right = fig.add_subplot(grid[index, 1])

        # -- native units -------------------------------------------------
        traces = []
        for row in drawn:
            t, y = store11.native_trace(row, snippets)
            if t is None or t.size < 3:
                continue
            traces.append((t, y))
            left.plot(t, y, color=colour, lw=LW_SAMPLE, alpha=ALPHA_SAMPLE,
                      solid_capstyle="round", zorder=2)
        if traces:
            # Framed on the sample's MEDIAN fall, not on its longest event.
            # Framing on the extent lets one 279 s oyster event set the
            # axis and squashes the other fifty-nine onto the y axis - the
            # same fault `overlays7.event_xlim` was written to fix. The
            # longest events run off the panel; this is a crop, it rescales
            # nothing, and the full extent is printed in the panel and in
            # the manifest.
            median_fall = float(np.median(
                [abs(float(r["fall_duration_s"])) for r in drawn]))
            lo = max(min(float(t[0]) for t, _ in traces),
                     -PRE_ONSET_FALLS * median_fall)
            hi = min(max(float(t[-1]) for t, _ in traces),
                     POST_ONSET_FALLS * median_fall)
            axis = np.linspace(lo, hi, 600)
            median = _pointwise_median(traces, axis)
            left.plot(axis, median, color=colour, lw=LW_MEDIAN, zorder=4,
                      solid_capstyle="round")
            left.set_xlim(lo, hi)
            median_depth = float(np.median(
                [abs(float(r["drop_depth_mv"])) for r in drawn]))
            left.set_ylim(-DEPTH_BELOW * median_depth,
                          DEPTH_ABOVE * median_depth)

        aspect, true_ratio, capped = store11.aspect_for(drawn)
        style7.apply_aspect(left, aspect, adjustable="box")
        left.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
                     lw=style7.LW_RULE, alpha=0.55, zorder=1)
        left.axhline(0.0, color=style7.RULE_COLOUR, ls=":",
                     lw=style7.LW_RULE * 0.8, alpha=0.5, zorder=1)
        config11.panel_title(left, f"{label} - native units", n=len(drawn))

        # The sample's full extent goes under the axis, not inside it: an
        # in-axes annotation lands on the traces on whichever species has
        # the deepest events, and moving it per species is how a figure
        # stops being reproducible.
        duration_range = store11.range_label(drawn, "fall_duration_s", "s")
        depth_range = store11.range_label(drawn, "drop_depth_mv", "mV")
        left.set_xlabel(f"time from onset (s)\n"
                        f"sample: fall {duration_range}, depth {depth_range}")
        left.set_ylabel("amplitude (mV)")
        left.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)

        # -- normalised ---------------------------------------------------
        features, kept, dropped = store11.normalised_block(
            drawn, snippets, n=N_NORMALISED)
        phase = np.linspace(0.0, 1.0, N_NORMALISED)
        for vector in features:
            right.plot(phase, vector, color=colour, lw=LW_SAMPLE,
                       alpha=ALPHA_SAMPLE, zorder=2)
        if len(features):
            right.plot(phase, np.median(features, axis=0), color=colour,
                       lw=LW_MEDIAN, zorder=4)
        config11.panel_title(right, f"{label} - normalised", n=len(kept))
        right.set_xlabel("fraction of the fall")
        right.set_ylabel("amplitude (z)")
        right.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)
        right.axhline(0.0, color=style7.RULE_COLOUR, ls=":",
                      lw=style7.LW_RULE * 0.8, alpha=0.5, zorder=1)

        manifest["species"][name] = {
            "label": label,
            "n_in_store": len(own),
            "n_drawn": len(drawn),
            "n_normalised": len(kept),
            "dropped": dropped,
            "seed": config11.seed_for(name),
            "aspect_seconds_per_mv": float(aspect),
            "aspect_true_ratio": float(true_ratio),
            "aspect_capped": bool(capped),
            "fall_duration_s_range": list(
                store11.span_of(drawn, "fall_duration_s")),
            "drop_depth_mv_range": list(
                store11.span_of(drawn, "drop_depth_mv")),
        }

    fig.suptitle("Drop shape in native units and after normalisation",
                 fontsize=config11.FS_SUPTITLE, y=0.995)
    config11.footer(fig, store_label, len(rows),
                    extra=f"{N_SAMPLE} events per species, seeded per species")
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


# ==========================================================================
# S2.3  The asymmetry of generalisation
# ==========================================================================

def _species_medoids(rows, snippets, k=MEDOIDS_PER_SPECIES):
    """`{species: {"vectors", "labels", "sizes", "n"}}` - family shapes.

    One tree per species, cut at the run's coarse k, and the medoid of
    each family taken as its representative. A medoid rather than a mean
    because a mean of z-normalised vectors is not a waveform any event
    has and cannot honestly be drawn as one.
    """
    out = {}
    for name, own in store11.by_species(rows).items():
        built = tree10.build(own, snippets, coarse_k=k, fine_k=k)
        if built is None:
            continue
        labels = built["coarse"]
        medoids = tree10.medoids(built["features"], labels)
        keys = sorted(medoids)
        out[name] = {
            "vectors": np.vstack([built["features"][medoids[key]]
                                  for key in keys]),
            "family_ids": keys,
            "sizes": [int(np.sum(labels == key)) for key in keys],
            "rows": [built["rows"][medoids[key]] for key in keys],
            "n": built["n"],
            "dropped": built["dropped"],
            "cophenetic": built["cophenetic"],
        }
    return out


def _rms_distance(a, b):
    """Euclidean distance divided by sqrt(n), so it reads as the RMS
    z-score difference per sample and stays comparable across lengths."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return float(np.linalg.norm(a - b) / np.sqrt(a.size))


def _nearest(vector, block):
    distances = [_rms_distance(vector, other) for other in block]
    best = int(np.argmin(distances))
    return best, float(distances[best])


def reference_species(rows, override=None):
    """Which species the others are matched AGAINST.

    Derived, not named: the reference is the species with the highest
    median duty cycle - the one whose waveforms are broadest relative to
    their own spacing. That is the property the asymmetry is about, so
    deriving the reference from it keeps the figure self-consistent when
    a fourth species arrives. `override` exists for re-plotting a
    deliberate subset and is recorded in the manifest when used.
    """
    if override:
        return override
    duty = store11.duty_by_species(rows)
    if not duty:
        return None
    return max(duty, key=lambda name: (duty[name]["duty_median"]
                                       if np.isfinite(duty[name]["duty_median"])
                                       else -np.inf))


def _coverage(features, medoids):
    """Median distance from each EVENT to the nearest medoid of a set.

    Far better powered than the medoid-to-medoid pairing that Panel B
    draws - thousands of events against four representatives, rather than
    four against four - and it is the number the manifest quotes. The
    drawn pairs are what a reader can SEE; this is what the claim rests
    on, and the two are reported side by side rather than one standing in
    for the other.
    """
    if not len(features) or not len(medoids):
        return float("nan")
    return float(np.median([min(_rms_distance(v, m) for m in medoids)
                            for v in features]))


def _draw_pair(ax, pair, resolved):
    """One matched pair, OVERLAID rather than offset.

    Offsetting the two shapes and joining them with a rule was tried and
    is unreadable at eight pairs: the eye cannot tell which two of sixteen
    lines belong together, and "how well do these agree" - the only
    question the panel exists to answer - becomes invisible. Overlaid, the
    gap between the two lines IS the matching distance.
    """
    phase = np.linspace(0.0, 1.0, N_NORMALISED)
    ax.plot(phase, pair["query"], color=resolved[pair["query_species"]]["colour"],
            lw=1.7, zorder=4, solid_capstyle="round")
    ax.plot(phase, pair["match"], color=resolved[pair["match_species"]]["colour"],
            lw=1.5, ls=resolved[pair["match_species"]]["dash"], zorder=3)
    ax.fill_between(phase, pair["query"], pair["match"], color="0.55",
                    alpha=0.16, lw=0, zorder=2)
    ax.set_xlim(0.0, 1.0)
    ax.set_xticks([0.0, 0.5, 1.0])
    ax.set_yticks([])
    ax.tick_params(labelsize=config11.FS_TICK)
    ax.set_title(f"{pair['query_label']} F{pair['query_family']}"
                 f"\n{pair['distance']:.2f} z RMS",
                 fontsize=config11.FS_ANNOT, pad=3.0)
    for spine in ("left",):
        ax.spines[spine].set_visible(False)


def plot_asymmetry(rows, snippets, path, *, store_label="",
                   reference=None, k=MEDOIDS_PER_SPECIES):
    """A: the family shapes side by side. B: nearest-shape matching in both
    directions, against the within-species baseline. C: duty cycle beside
    absolute fall duration."""
    config11.apply_style()
    medoids = _species_medoids(rows, snippets, k=k)
    species = config11.order(medoids)
    resolved = config11.resolve(species)
    ref = reference_species(rows, override=reference)
    if ref not in medoids:
        ref = species[-1]
    others = [name for name in species if name != ref]
    duty = store11.duty_by_species(rows)

    # Event-level feature blocks, for the coverage numbers and the
    # within-species baseline that stops Panel B being over-read.
    blocks, baseline = {}, {}
    for name, own in store11.by_species(rows).items():
        features, _, _ = store11.normalised_block(own, snippets,
                                                  n=N_NORMALISED)
        blocks[name] = features
        baseline[name] = _coverage(features, medoids[name]["vectors"]) \
            if name in medoids else float("nan")

    # -- the matching, both directions ----------------------------------
    ref_block = medoids[ref]["vectors"]
    ref_families = medoids[ref]["family_ids"]

    forward = []
    for name in others:
        block = medoids[name]
        for vector, family in zip(block["vectors"], block["family_ids"]):
            best, distance = _nearest(vector, ref_block)
            forward.append({"query": vector, "query_species": name,
                            "query_family": family,
                            "query_label": resolved[name]["label"],
                            "match": ref_block[best], "match_species": ref,
                            "match_family": ref_families[best],
                            "distance": distance})

    pool, pool_species, pool_families = [], [], []
    for name in others:
        for vector, family in zip(medoids[name]["vectors"],
                                  medoids[name]["family_ids"]):
            pool.append(vector)
            pool_species.append(name)
            pool_families.append(family)

    backward = []
    for vector, family in zip(ref_block, ref_families):
        best, distance = _nearest(vector, pool)
        backward.append({"query": vector, "query_species": ref,
                         "query_family": family,
                         "query_label": resolved[ref]["label"],
                         "match": pool[best],
                         "match_species": pool_species[best],
                         "match_family": pool_families[best],
                         "distance": distance})

    other_label = " and ".join(resolved[name]["label"] for name in others)
    ref_label = resolved[ref]["label"]

    other_events = np.vstack([blocks[name] for name in others
                              if len(blocks[name])])
    coverage_forward = _coverage(other_events, ref_block)
    coverage_backward = _coverage(blocks[ref], np.vstack(pool))

    # -- layout ----------------------------------------------------------
    n_columns = max(len(forward), len(backward), len(species))
    fig = plt.figure(figsize=(1.32 * n_columns + 1.6, 12.0))
    # Each Panel B strip gets its OWN heading row rather than a figure-level
    # text placed above it. A heading positioned by figure fraction lands on
    # the strip's panel titles as soon as the number of pairs changes, and
    # the number of pairs changes the moment a fourth species arrives.
    outer = gridspec.GridSpec(6, 1, figure=fig, hspace=0.62,
                              height_ratios=[1.30, 0.16, 0.86,
                                             0.16, 0.86, 1.05])

    # -- Panel A ---------------------------------------------------------
    top = gridspec.GridSpecFromSubplotSpec(1, len(species),
                                           subplot_spec=outer[0], wspace=0.16)
    phase = np.linspace(0.0, 1.0, N_NORMALISED)
    offset_step = 3.4
    for index, name in enumerate(species):
        ax = fig.add_subplot(top[0, index])
        block = medoids[name]
        centres = []
        for position, vector in enumerate(block["vectors"]):
            centre = -offset_step * position
            centres.append(centre)
            ax.plot(phase, vector + centre, color=resolved[name]["colour"],
                    lw=1.6, zorder=3, solid_capstyle="round")
        # Family identity goes on the y axis, not on top of the traces.
        ax.set_yticks(centres)
        ax.set_yticklabels([f"F{family}  n={size}" for family, size
                            in zip(block["family_ids"], block["sizes"])],
                           fontsize=config11.FS_ANNOT)
        ax.set_ylim(centres[-1] - 2.6, centres[0] + 2.6)
        ax.set_xlim(0.0, 1.0)
        ax.set_xlabel("fraction of the fall")
        config11.panel_title(ax, f"A  {resolved[name]['label']}", n=block["n"])
        ax.grid(axis="x", alpha=0.15, lw=style7.LW_RULE * 0.5)
        ax.tick_params(axis="y", length=0)

    # -- Panel B, two rows of overlaid pairs ------------------------------
    for row_index, (pairs, heading, coverage) in enumerate((
            (forward, f"B  {other_label} matched to {ref_label}",
             coverage_forward),
            (backward, f"B  {ref_label} matched to {other_label}",
             coverage_backward))):
        median = float(np.median([p["distance"] for p in pairs])) \
            if pairs else float("nan")
        heading_ax = config11.legend_axis(
            fig.add_subplot(outer[1 + 2 * row_index]))
        heading_ax.text(0.0, 0.0,
                        f"{heading}   |   medoid pairs, median "
                        f"{median:.2f} z RMS   |   all events, median "
                        f"{coverage:.2f} z RMS",
                        transform=heading_ax.transAxes,
                        fontsize=config11.FS_TITLE, va="bottom", ha="left")

        strip = gridspec.GridSpecFromSubplotSpec(
            1, n_columns, subplot_spec=outer[2 + 2 * row_index], wspace=0.18)
        for column, pair in enumerate(pairs):
            ax = fig.add_subplot(strip[0, column])
            _draw_pair(ax, pair, resolved)
            if column == 0:
                ax.set_ylabel("z", fontsize=config11.FS_LABEL)

    # -- Panel C -----------------------------------------------------------
    bottom = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=outer[5],
                                              wspace=0.46,
                                              width_ratios=[1.0, 1.0, 0.62])
    duty_ax = fig.add_subplot(bottom[0, 0])
    fall_ax = fig.add_subplot(bottom[0, 1])
    legend_ax = config11.legend_axis(fig.add_subplot(bottom[0, 2]))

    for index, name in enumerate(species):
        entry = duty.get(name)
        if entry is None:
            continue
        colour = resolved[name]["colour"]
        marker = resolved[name]["marker"]

        values = np.asarray(entry["duty_values"], dtype=float)
        if values.size:
            duty_ax.plot([index] * values.size, values, marker, color=colour,
                         alpha=0.28, markersize=4, lw=0, zorder=2)
            duty_ax.plot([index, index], [entry["duty_q1"], entry["duty_q3"]],
                         color=colour, lw=2.4, alpha=0.5, zorder=3,
                         solid_capstyle="round")
        duty_ax.plot([index], [entry["duty_median"]], marker, color=colour,
                     markersize=9, zorder=4, markeredgecolor="white",
                     markeredgewidth=0.8)
        duty_ax.annotate(f"{entry['duty_median']:.3f}",
                         xy=(index, entry["duty_median"]),
                         xytext=(10, 0), textcoords="offset points",
                         fontsize=config11.FS_ANNOT, color="0.30", va="center")

        falls = np.asarray(entry["fall_values"], dtype=float)
        falls = falls[np.isfinite(falls) & (falls > 0)]
        if falls.size:
            fall_ax.plot([index] * falls.size, falls, marker, color=colour,
                         alpha=0.28, markersize=4, lw=0, zorder=2)
        fall_ax.plot([index], [entry["fall_median_s"]], marker, color=colour,
                     markersize=9, zorder=4, markeredgecolor="white",
                     markeredgewidth=0.8)
        fall_ax.annotate(f"{entry['fall_median_s']:.3g} s",
                         xy=(index, entry["fall_median_s"]),
                         xytext=(10, 0), textcoords="offset points",
                         fontsize=config11.FS_ANNOT, color="0.30", va="center")

    ticks = list(range(len(species)))
    names = [resolved[name]["label"] for name in species]
    for ax, ylabel, title in ((duty_ax, "fall duration / median interval",
                               "C  Duty cycle"),
                              (fall_ax, "fall duration (s)",
                               "C  Absolute fall duration")):
        ax.set_xticks(ticks)
        ax.set_xticklabels(names)
        ax.set_xlim(-0.6, len(species) - 0.4 + 0.45)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=0.15, lw=style7.LW_RULE * 0.5)
        config11.panel_title(ax, title)
    fall_ax.set_yscale("log")

    counts = store11.counts_by_species(rows)
    handles = config11.handles(species, counts=counts, resolved=resolved)
    baseline_handles = [Line2D([0], [0], color="0.55", lw=5, alpha=0.35,
                               label=f"within-species baseline "
                                     f"{min(baseline.values()):.2f}-"
                                     f"{max(baseline.values()):.2f} z RMS")]
    species_legend = legend_ax.legend(
        handles=handles, loc="upper left", frameon=False,
        fontsize=config11.FS_LEGEND, title="Species",
        title_fontsize=config11.FS_LEGEND)
    species_legend.get_title().set_ha("left")
    legend_ax.add_artist(species_legend)
    legend_ax.legend(handles=baseline_handles, loc="lower left", frameon=False,
                     fontsize=config11.FS_LEGEND)

    fig.suptitle("Family shapes, nearest-shape matching in both directions, "
                 "and the duty cycle",
                 fontsize=config11.FS_SUPTITLE, y=0.997)
    config11.footer(fig, store_label, len(rows),
                    extra=f"one point per channel-span group in C; "
                          f"reference species {ref_label}")

    manifest = {
        "store": store_label,
        "n_total": len(rows),
        "reference_species": ref,
        "reference_species_rule": ("highest median duty cycle" if not reference
                                   else "set by --reference-species"),
        "families_per_species": int(k),
        "distance": "Euclidean over 200-point z-normalised falls, / sqrt(200) "
                    "= RMS z-score difference per sample",
        "within_species_baseline": baseline,
        "forward": {
            "direction": f"{other_label} -> {ref_label}",
            "n_medoid_pairs": len(forward),
            "median_medoid_distance": float(np.median(
                [p["distance"] for p in forward])) if forward else float("nan"),
            "n_events": int(len(other_events)),
            "median_event_coverage": coverage_forward,
            "pairs": [{key: value for key, value in pair.items()
                       if key not in ("query", "match")} for pair in forward],
        },
        "backward": {
            "direction": f"{ref_label} -> {other_label}",
            "n_medoid_pairs": len(backward),
            "median_medoid_distance": float(np.median(
                [p["distance"] for p in backward])) if backward else float("nan"),
            "n_events": int(len(blocks[ref])),
            "median_event_coverage": coverage_backward,
            "pairs": [{key: value for key, value in pair.items()
                       if key not in ("query", "match")} for pair in backward],
        },
        "asymmetry_finding": (
            "NOT SUPPORTED on this store. The two directions differ by less "
            "than the spread of the within-species baseline, and where they "
            "differ the sign is opposite to the claim: reishi events sit "
            "closer to the narrow species' medoids than the reverse. The "
            "comparison is also confounded by sampling rate - a reishi fall "
            "is a median of 7 samples resampled to 200 points, so its "
            "normalised shape is smooth and close to almost anything. See "
            "APPENDIX_rigour.md."),
        "duty_cycle": {name: {
            "n_groups": duty[name]["n_groups"],
            "duty_median": duty[name]["duty_median"],
            "duty_q1": duty[name]["duty_q1"],
            "duty_q3": duty[name]["duty_q3"],
            "fall_median_s": duty[name]["fall_median_s"],
            "iei_median_s": duty[name]["iei_median_s"],
            "cv_iei_median": duty[name]["cv_iei_median"],
        } for name in species if name in duty},
        "trees": {name: {"n": medoids[name]["n"],
                         "cophenetic": medoids[name]["cophenetic"],
                         "dropped": medoids[name]["dropped"],
                         "family_sizes": medoids[name]["sizes"]}
                  for name in species},
    }
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest



# ==========================================================================
# S2.1  Fall angle by species
# ==========================================================================

def _rose(ax, angles, colour, *, n_bins=N_ANGLE_BINS, lo=-np.pi / 2, hi=0.0,
          bottom=None, label=None, alpha=0.75):
    """One rose, on its OWN radial scale.

    Deliberately not a shared radial ceiling across the species row. The
    counts differ by a factor of thirty-two - 2,425 reishi against 76
    Lion's mane - and a shared ceiling draws Lion's mane as a smear at the
    origin, which says nothing about its angles. What must be shared is
    the ANGULAR grid, and that is fixed here for every rose; each panel
    states its own n in the title and its own radial ticks on the axis.

    `bottom` stacks this band on top of a previous one, which is how the
    depth-binned rose is drawn: four translucent overlaid roses hide each
    other, a stack does not.
    """
    edges = np.linspace(lo, hi, n_bins + 1)
    counts, _ = np.histogram(np.clip(angles, lo, hi), bins=edges)
    width = (hi - lo) / n_bins
    centres = edges[:-1] + width / 2.0
    ax.bar(centres, counts, width=width * 0.94,
           bottom=0.0 if bottom is None else bottom, color=colour,
           alpha=alpha, edgecolor="white", linewidth=0.4, label=label,
           align="center")
    ax.set_thetamin(np.rad2deg(lo))
    ax.set_thetamax(np.rad2deg(hi))
    ax.set_theta_zero_location("E")
    ax.set_thetagrids(np.arange(-90, 1, 15),
                      labels=[f"{d}°" for d in range(-90, 1, 15)],
                      fontsize=config11.FS_TICK)
    ax.tick_params(labelsize=config11.FS_TICK)
    ax.grid(alpha=0.25, lw=style7.LW_RULE * 0.5)
    return counts


def plot_fall_angle(rows, path, *, store_label=""):
    """Top: one rose per species. Bottom: the pooled rose binned by depth,
    depth against angle, and a per-species summary of fall angle."""
    config11.apply_style()
    grouped = store11.by_species(rows)
    species = list(grouped)
    resolved = config11.resolve(species)

    reference = store11.pooled_reference_mv_s(rows)
    angles = {name: np.array([store11.fall_angle_rad(r, reference)
                              for r in own], dtype=float)
              for name, own in grouped.items()}
    pooled = np.concatenate([angles[name] for name in species]) \
        if species else np.array([])

    n_top = len(species)
    fig = plt.figure(figsize=(4.1 * max(n_top, 3), 9.2))
    outer = gridspec.GridSpec(3, 1, figure=fig, hspace=0.30,
                              height_ratios=[1.0, 0.10, 1.16])
    top = gridspec.GridSpecFromSubplotSpec(1, n_top, subplot_spec=outer[0],
                                           wspace=0.34)
    bottom = gridspec.GridSpecFromSubplotSpec(
        1, 4, subplot_spec=outer[2], wspace=0.52,
        width_ratios=[1.0, 1.20, 1.0, 0.44])

    per_species = {}
    for index, name in enumerate(species):
        ax = fig.add_subplot(top[0, index], projection="polar")
        counts = _rose(ax, angles[name], resolved[name]["colour"])
        ax.set_title(f"{resolved[name]['label']}  (n = {len(angles[name]):,})",
                     fontsize=config11.FS_TITLE, pad=18.0)
        per_species[name] = {"n": int(len(angles[name])),
                             "counts": counts.tolist(),
                             "radial_max": int(counts.max()) if counts.size else 0}

    # -- pooled rose binned by drop depth -------------------------------
    depth_ax = fig.add_subplot(bottom[0, 0], projection="polar")
    depths = np.array([abs(float(r["drop_depth_mv"])) for r in rows])
    quartiles = np.percentile(depths[depths > 0],
                              np.linspace(0, 100, N_DEPTH_BINS + 1))
    ramp = plt.get_cmap("cividis")
    depth_bands = []
    # Stacked, not overlaid: four translucent roses on one axes hide each
    # other and the last one drawn wins. Stacked, the total is the pooled
    # rose and each band's contribution to it is legible.
    stack = np.zeros(N_ANGLE_BINS)
    for band in range(N_DEPTH_BINS):
        low, high = quartiles[band], quartiles[band + 1]
        mask = (depths >= low) & (depths <= high if band == N_DEPTH_BINS - 1
                                  else depths < high)
        if not mask.any():
            continue
        shade = ramp(0.12 + 0.76 * band / max(N_DEPTH_BINS - 1, 1))
        counts = _rose(depth_ax, pooled[mask], shade, bottom=stack, alpha=0.9,
                       label=f"{low:.3g}-{high:.3g} mV")
        stack = stack + counts
        depth_bands.append({"band": band, "low_mv": float(low),
                            "high_mv": float(high), "n": int(mask.sum())})
    depth_ax.set_title(f"Fall angle by drop depth  (n = {len(rows):,})",
                       fontsize=config11.FS_TITLE, pad=18.0)

    # -- depth against angle --------------------------------------------
    scatter_ax = fig.add_subplot(bottom[0, 1])
    for index, name in enumerate(species):
        own = grouped[name]
        scatter_ax.scatter(np.rad2deg(angles[name]),
                           [abs(float(r["drop_depth_mv"])) for r in own],
                           s=9, alpha=0.42, linewidths=0,
                           color=resolved[name]["colour"],
                           marker=resolved[name]["marker"], zorder=3)
    scatter_ax.set_yscale("log")
    scatter_ax.set_xlabel("fall angle (degrees)")
    scatter_ax.set_ylabel("drop depth (mV)")
    scatter_ax.set_xlim(-92, 2)
    scatter_ax.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)
    config11.panel_title(scatter_ax, "Drop depth by fall angle", n=len(rows))

    # -- per-species summary --------------------------------------------
    box_ax = fig.add_subplot(bottom[0, 2])
    data = [np.rad2deg(angles[name]) for name in species]
    parts = box_ax.boxplot(data, vert=True, patch_artist=True, widths=0.55,
                           showfliers=False,
                           medianprops={"color": "white", "lw": 1.6})
    for patch, name in zip(parts["boxes"], species):
        patch.set_facecolor(resolved[name]["colour"])
        patch.set_alpha(0.75)
        patch.set_edgecolor(resolved[name]["colour"])
    for element in ("whiskers", "caps"):
        for artist in parts[element]:
            artist.set_color("0.35")
    box_ax.set_xticks(range(1, len(species) + 1))
    box_ax.set_xticklabels([resolved[name]["label"] for name in species])
    box_ax.set_ylabel("fall angle (degrees)")
    box_ax.grid(axis="y", alpha=0.15, lw=style7.LW_RULE * 0.5)
    config11.panel_title(box_ax, "Fall angle by species", n=len(rows))

    # -- legends, in their own axes -------------------------------------
    legend_ax = config11.legend_axis(fig.add_subplot(bottom[0, 3]))
    counts = store11.counts_by_species(rows)
    species_legend = legend_ax.legend(
        handles=config11.handles(species, counts=counts, resolved=resolved),
        loc="upper left", frameon=False, fontsize=config11.FS_LEGEND,
        title="Species", title_fontsize=config11.FS_LEGEND)
    species_legend.get_title().set_ha("left")
    legend_ax.add_artist(species_legend)
    depth_handles = [
        Line2D([0], [0], color=ramp(0.12 + 0.76 * band["band"]
                                    / max(N_DEPTH_BINS - 1, 1)),
               lw=5, alpha=0.6,
               label=f"{band['low_mv']:.3g}-{band['high_mv']:.3g} mV")
        for band in depth_bands]
    legend_ax.legend(handles=depth_handles, loc="lower left", frameon=False,
                     fontsize=config11.FS_LEGEND, title="Drop depth",
                     title_fontsize=config11.FS_LEGEND)

    fig.suptitle("Fall angle by species", fontsize=config11.FS_SUPTITLE,
                 y=0.995)
    # The angle reference, stated ONCE and given its own row rather than
    # floated at a figure fraction. An angle is `arctan(slope / reference)`
    # and is meaningless without it; a label positioned by figure fraction
    # drifts onto a panel the moment the layout changes.
    reference_ax = config11.legend_axis(fig.add_subplot(outer[1]))
    reference_ax.text(0.5, 0.2, f"45° = {reference:.3g} mV/s "
                                "(pooled median steepest slope)",
                      transform=reference_ax.transAxes, ha="center",
                      va="center", fontsize=config11.FS_ANNOT, color="0.35")
    config11.footer(fig, store_label, len(rows),
                    extra=store11.MAX_SLOPE_UNIT_NOTE)

    manifest = {
        "store": store_label,
        "n_total": len(rows),
        "angle_reference_mv_s": reference,
        "angle_reference_rule": "pooled median |max_slope|, all species",
        "max_slope_unit": store11.MAX_SLOPE_UNIT_NOTE,
        "n_angle_bins": N_ANGLE_BINS,
        "depth_bands": depth_bands,
        "per_species": {name: dict(per_species[name], **{
            "label": resolved[name]["label"],
            "median_angle_deg": float(np.median(np.rad2deg(angles[name]))),
            "median_max_slope_mv_s": float(np.median(
                [store11.max_slope_mv_s(r) for r in grouped[name]])),
            "median_depth_mv": float(np.median(
                [abs(float(r["drop_depth_mv"])) for r in grouped[name]])),
        }) for name in species},
        "not_claimed": "depth against fall angle is largely arithmetic - "
                       "slope is depth over duration - and a block-shuffle "
                       "surrogate reproduces it; see APPENDIX_rigour.md",
    }
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest
