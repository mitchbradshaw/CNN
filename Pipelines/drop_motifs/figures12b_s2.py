"""
figures12b_s2.py
=================
Section 2 redrawn: S2.2 the scale collapse and S2.3 the asymmetry of
generalisation. S2.1 passed review and is not here; `run_drop12b_figures`
regenerates it through `figures11_s2.plot_fall_angle` unchanged.

What changed, and why
----------------------
S2.2's LEFT panels were unreadable because the x range was set by the
longest event in the sample: one 286-second oyster event framed a panel that
also had to hold a 2-second one, and the short events collapsed into the
left edge. The view here is a common fall-duration scale WITHIN each
species - the frame of that sample's own median event - and the panel states
how many events run past it in time and in depth, and where the 90th
quantile of frame length falls. Both panels' y ranges follow the same rule,
for the same reason in the other direction: one 83 mV event otherwise sets
the height and the aspect lock answers by squeezing the box to a sliver.

S2.2's RIGHT panels showed only the fall, so all three species were the
same monotone descent by construction. They now run -0.5 to 1.5
fall-fractions and are drawn from real samples.

S2.3 was flat lines. Panel A now draws each species' family medoids as real
waveforms with context, tall and locked - and it lays every species out in
one row, which round 11 did not: taking the widest species rather than the
sum dropped the last species' vocabulary off the figure that is about it.
Panel B draws each matched pair as real waveforms rather than as two
resampled vectors. Panel C is unchanged in method and recomputed on the new
store.

The asymmetry verdict is COMPUTED rather than asserted. Round 11 carried it
as a hard-coded sentence, which would have survived the numbers changing
underneath it - and this run's whole purpose is a bigger, differently
sampled store. See `_asymmetry_verdict`.

The clustering is `tree10`, unchanged. This run redraws; it does not
re-cluster, and a second definition of a family is how two figures in one
run come to disagree about which events are alike.
"""

import numpy as np
from matplotlib import gridspec
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

from Pipelines.drop_motifs import (config11, drawing_rules, store11, style7,
                                   tree10)

# S2.2. Sixty was crowded in round 11 at one row per species; forty is the
# work order's fallback and is what is used, stated on the figure.
N_SAMPLE = 40

# The left panel's x range is the frame of the sample's MEDIAN event -
# `PRE_ONSET_FALLS` before its onset to `POST_TROUGH_FALLS` after its
# trough. That is the work order's "common fall-duration scale within that
# species", and it is what stops one 286 s oyster event framing a panel that
# also has to hold a 2 s one.
#
# `X_QUANTILE` is the quantile whose frame length is REPORTED beside it, so a
# reader can see how far the sample runs past the view without the view
# having to accommodate it. Events beyond the view are drawn and run off the
# panel; the count is printed.
X_QUANTILE = 0.90

# The y range, in multiples of the sample's own median depth, and the
# quantile of the normalised panel's z kept in view. Same rule and the same
# reason: one 83 mV oyster event otherwise sets the height for a 5 mV median
# and the aspect lock answers by squeezing the box to a sliver.
DEPTH_BELOW = 2.4
DEPTH_ABOVE = 0.6
Z_QUANTILE = 0.995

ALPHA_SAMPLE = 0.30
LW_SAMPLE = 0.8
LW_MEDIAN = 2.0

# The fraction of a panel's sampled events that must reach a point on the
# common grid before a pointwise median is drawn there. `figures11_s2`'s
# rule and its reason: below this the "median" describes the two or three
# longest events rather than the sample.
MEDIAN_SUPPORT = 0.8

MEDOIDS_PER_SPECIES = tree10.COARSE_K

# Panel A draws the largest families covering this fraction of a species'
# events, and says how many that is. A species with eight families of two
# events each cannot be drawn legibly and the small ones say nothing.
MEDOID_COVERAGE = 0.80


# ==========================================================================
# S2.2  Scale collapse
# ==========================================================================

def _sample(rows, n=N_SAMPLE, species=None):
    """A seeded draw, per species, that survives more data arriving."""
    if len(rows) <= n:
        return list(rows)
    rng = config11.rng_for(species if species is not None
                           else rows[0].get("species"))
    picks = rng.choice(len(rows), size=int(n), replace=False)
    return [rows[int(i)] for i in sorted(picks)]


def _pointwise_median(traces, grid, support=MEDIAN_SUPPORT):
    """Median mV at each time after onset, over traces of unequal length.

    `figures11_s2`'s function, unchanged in method: a point is drawn only
    where `support` of the traces reach it, and only the contiguous stretch
    containing the onset is drawn, so the line cannot step vertically where
    the contributing subset changes.
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


def _phase_median(traces, grid, support=MEDIAN_SUPPORT):
    """The same rule on the phase axis, for the normalised panel's median."""
    return _pointwise_median(traces, grid, support=support)


def plot_scale_collapse(rows, snippets, path, *, store_label="",
                        n_sample=N_SAMPLE):
    """Left: the sample in millivolts and seconds, at a common within-species
    scale. Right: the same events with their values normalised, from -0.5 to
    1.5 fall-fractions. One row per species."""
    config11.apply_style()
    grouped = store11.by_species(rows)
    species = list(grouped)
    resolved = config11.resolve(species)

    # Taller than round 11's 2.55 in per row, because rule 4 asks for
    # panels taller than they are wide and the aspect lock cannot make a
    # panel taller than the cell it is given.
    fig = plt.figure(figsize=(9.4, 4.4 * len(species) + 0.9))
    grid = gridspec.GridSpec(len(species), 2, figure=fig, wspace=0.30,
                             hspace=0.66, top=0.955, bottom=0.045,
                             left=0.085, right=0.975,
                             width_ratios=[1.0, 1.0])

    manifest = {"store": store_label, "run": "drop_motifs12b",
                "n_total": len(rows), "sample_target": int(n_sample),
                "x_range_quantile": X_QUANTILE,
                "median_support_fraction": MEDIAN_SUPPORT,
                "frame": f"{drawing_rules.PRE_ONSET_FALLS} falls before "
                         f"onset to {drawing_rules.POST_TROUGH_FALLS} falls "
                         f"after trough",
                "normalised_axis": [drawing_rules.PHASE_LO,
                                    drawing_rules.PHASE_HI],
                "resampling": "none; every waveform is the event's own "
                              "samples at its own times",
                "duration_orders_of_magnitude":
                    store11.orders_of_magnitude(rows, "fall_duration_s"),
                "amplitude_orders_of_magnitude":
                    store11.orders_of_magnitude(rows, "drop_depth_mv"),
                "species": {}}

    for index, name in enumerate(species):
        own = grouped[name]
        drawn = _sample(own, n=n_sample, species=name)
        colour = resolved[name]["colour"]
        label = resolved[name]["label"]

        left = fig.add_subplot(grid[index, 0])
        right = fig.add_subplot(grid[index, 1])

        # -- native units, at one within-species scale --------------------
        traces, kept = [], []
        for row in drawn:
            t, y, _complete = drawing_rules.framed_trace(row, snippets)
            if t is None or t.size < 3:
                continue
            traces.append((t, y))
            kept.append(row)
            left.plot(t, y, color=colour, lw=LW_SAMPLE, alpha=ALPHA_SAMPLE,
                      solid_capstyle="round", zorder=2)

        beyond_x = beyond_y = 0
        frame_q = median_fall = float("nan")
        aspect, ratio, capped = drawing_rules.figure_aspect(kept or drawn)
        if traces:
            # A common fall-duration scale within the species: the frame of
            # the sample's own MEDIAN event. See X_QUANTILE.
            median_fall = float(np.median(
                [drawing_rules.fall_duration_s(r) for r in kept]))
            median_depth = float(np.median(
                [abs(float(r["drop_depth_mv"])) for r in kept]))
            lo = -drawing_rules.PRE_ONSET_FALLS * median_fall
            hi = (1.0 + drawing_rules.POST_TROUGH_FALLS) * median_fall
            ends = np.array([float(t[-1]) for t, _y in traces])
            frame_q = float(np.quantile(ends, X_QUANTILE))
            beyond_x = int(np.sum(ends > hi))
            depths = np.array([abs(float(r["drop_depth_mv"])) for r in kept])
            beyond_y = int(np.sum(depths > DEPTH_BELOW * median_depth))

            axis = np.linspace(lo, hi, 800)
            left.plot(axis, _pointwise_median(traces, axis), color=colour,
                      lw=LW_MEDIAN, zorder=4, solid_capstyle="round")
            left.set_xlim(lo, hi)
            left.set_ylim(-DEPTH_BELOW * median_depth,
                          DEPTH_ABOVE * median_depth)

        drawing_rules.apply_aspect(left, aspect)
        left.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
                     lw=style7.LW_RULE, alpha=0.55, zorder=1)
        left.axhline(0.0, color=style7.RULE_COLOUR, ls=":",
                     lw=style7.LW_RULE * 0.8, alpha=0.5, zorder=1)
        config11.panel_title(left, f"{label} - native units", n=len(kept))
        duration_range = store11.range_label(drawn, "fall_duration_s", "s")
        depth_range = store11.range_label(drawn, "drop_depth_mv", "mV")
        left.set_xlabel("time from onset (s)")
        left.set_ylabel("amplitude (mV)")
        left.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)

        # -- normalised, from -0.5 to 1.5 fall-fractions -------------------
        phase_traces, phase_rows = drawing_rules.phase_block(drawn, snippets)
        for phase, z in phase_traces:
            right.plot(phase, z, color=colour, lw=LW_SAMPLE,
                       alpha=ALPHA_SAMPLE, zorder=2, solid_capstyle="round")
        if phase_traces:
            axis = np.linspace(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI,
                               400)
            right.plot(axis, _phase_median(phase_traces, axis), color=colour,
                       lw=LW_MEDIAN, zorder=4, solid_capstyle="round")
            depth_z = float(np.median([float(np.ptp(z))
                                       for _p, z in phase_traces]))
            phase_aspect = (drawing_rules.TARGET_RATIO / depth_z
                            if depth_z > 0 else 1.0)
            # One trace reaching z = -6 otherwise sets the height for a
            # sample whose median excursion is 2.8, and the lock answers by
            # squeezing the box. Same rule as the left panel's y.
            pooled = np.concatenate([z for _p, z in phase_traces])
            span = float(np.quantile(np.abs(pooled), Z_QUANTILE))
            right.set_ylim(-span * 1.05, span * 1.05)
            drawing_rules.apply_aspect(right, phase_aspect)
        else:
            phase_aspect = float("nan")
        right.set_xlim(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI)
        right.axvline(0.0, color=style7.RULE_COLOUR, ls="--",
                      lw=style7.LW_RULE, alpha=0.55, zorder=1)
        right.axvline(1.0, color=style7.RULE_COLOUR, ls="--",
                      lw=style7.LW_RULE, alpha=0.35, zorder=1)
        config11.panel_title(right, f"{label} - normalised",
                             n=len(phase_rows))
        right.set_xlabel("fall-fractions from onset "
                         "(0 the onset, 1 the trough)")
        right.set_ylabel("amplitude (z of the fall)")
        right.grid(alpha=0.15, lw=style7.LW_RULE * 0.5)

        # One caption per ROW, hung under the pair, so the long sentences are
        # not axis labels colliding across two columns. Positioned from the
        # gridspec cell because both panels are aspect-locked and have been
        # reshaped inside theirs.
        cell = grid[index, 0].get_position(fig)
        fig.text(0.012, cell.y0 - 0.030,
                 f"{label}  |  sample: fall {duration_range}, depth "
                 f"{depth_range}  |  "
                 f"{drawing_rules.aspect_caption(aspect, ratio, capped)}\n"
                 f"left view is the median event's own "
                 f"{drawing_rules.PRE_ONSET_FALLS}/"
                 f"{drawing_rules.POST_TROUGH_FALLS}-fall frame "
                 f"(fall {median_fall:.3g} s); {beyond_x} of {len(kept)} "
                 f"events run past it in time, {beyond_y} in depth; "
                 f"{X_QUANTILE:.0%} of frames end by {frame_q:.3g} s. "
                 f"Right: both axes normalised per event, real samples, "
                 f"nothing resampled.",
                 fontsize=config11.FS_ANNOT, color="0.30", va="top",
                 linespacing=1.5)

        ok, why = drawing_rules.check_drop_shape(ratio)
        manifest["species"][name] = {
            "label": label,
            "n_in_store": len(own),
            "n_drawn": len(kept),
            "n_normalised": len(phase_rows),
            "n_beyond_x_view": beyond_x,
            "n_beyond_y_view": beyond_y,
            "median_fall_s": median_fall,
            "frame_length_quantile_s": frame_q,
            "seed": config11.seed_for(name),
            "aspect_seconds_per_mv": float(aspect),
            "median_event_drawn_ratio": float(ratio),
            "aspect_capped": bool(capped),
            "drop_shape_ok": bool(ok),
            "drop_shape_note": why,
            "phase_aspect_z_per_fall": float(phase_aspect),
            "fall_duration_s_range": list(
                store11.span_of(drawn, "fall_duration_s")),
            "drop_depth_mv_range": list(
                store11.span_of(drawn, "drop_depth_mv")),
        }

    fig.suptitle("Drop shape in native units and after normalisation",
                 fontsize=config11.FS_SUPTITLE, y=0.998)
    config11.footer(fig, store_label, len(rows),
                    extra=f"{n_sample} events per species, seeded per "
                          f"species; every waveform is real samples")
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


# ==========================================================================
# S2.3  The asymmetry of generalisation
# ==========================================================================

def _species_medoids(rows, snippets, k=MEDOIDS_PER_SPECIES,
                     coverage=MEDOID_COVERAGE):
    """`{species: {...}}` - the family medoids worth drawing, largest first.

    `tree10` unchanged. The only addition is the coverage cut the work
    order asks for: the largest families covering `coverage` of a species'
    events are kept and the rest are counted, so Panel A stays legible
    without a hidden selection.
    """
    out = {}
    for name, own in store11.by_species(rows).items():
        built = tree10.build(own, snippets, coarse_k=k, fine_k=k)
        if built is None:
            continue
        labels = built["coarse"]
        medoids = tree10.medoids(built["features"], labels)
        keys = sorted(medoids, key=lambda key: -int(np.sum(labels == key)))
        sizes = [int(np.sum(labels == key)) for key in keys]
        total = float(sum(sizes)) or 1.0

        running, take = 0.0, 0
        for size in sizes:
            take += 1
            running += size / total
            if running >= coverage:
                break
        out[name] = {
            "vectors": np.vstack([built["features"][medoids[key]]
                                  for key in keys[:take]]),
            "family_ids": keys[:take],
            "sizes": sizes[:take],
            "rows": [built["rows"][medoids[key]] for key in keys[:take]],
            "n_families": len(keys),
            "n_drawn_families": take,
            "coverage": float(running),
            "n": built["n"],
            "dropped": built["dropped"],
            "cophenetic": built["cophenetic"],
        }
    return out


def _nearest(vector, block):
    distances = [drawing_rules.rms(vector, other) for other in block]
    best = int(np.argmin(distances))
    return best, float(distances[best])


def _coverage(features, medoids):
    """Median distance from each EVENT to the nearest medoid of a set."""
    if not len(features) or not len(medoids):
        return float("nan")
    return float(np.median([min(drawing_rules.rms(v, m) for m in medoids)
                            for v in features]))


def _group_ylim(traces, pad=0.12):
    """The y range a group of phase panels shares.

    Without it an aspect-locked panel whose medoid happens to spike to
    z = 4 gets a taller box than the one beside it, and a reader reads the
    difference in box size as a difference in the waveform. Round 11 had no
    locked panels at all, so this is a fault the lock introduces and the
    lock has to answer for.
    """
    pooled = [z for _p, z in traces if np.asarray(z).size]
    if not pooled:
        return None
    low = min(float(np.min(z)) for z in pooled)
    high = max(float(np.max(z)) for z in pooled)
    span = (high - low) or 1.0
    return (low - pad * span, high + pad * span)


def _draw_medoid(ax, row, snippets, colour, *, label, family, size, aspect,
                 ylim=None):
    """One medoid as a real waveform, amplitude-normalised, with context.

    The species goes in the TITLE rather than on the y axis. A y label on
    the first panel of each group was tried and, because the panels are
    aspect-locked and therefore narrower than their cells, "Lion's mane"
    reached back across the panel to its left.
    """
    phase, z = drawing_rules.phase_trace(row, snippets)
    if phase is None:
        ax.set_axis_off()
        return
    fall = drawing_rules.fall_duration_s(row)
    ax.axvspan(0.0, 1.0, color=colour, alpha=0.14, lw=0.0, zorder=1)
    ax.plot(phase, z, color=colour, lw=1.7, zorder=3, solid_capstyle="round")
    ax.set_xlim(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI)
    if ylim is not None:
        ax.set_ylim(*ylim)
    drawing_rules.apply_aspect(ax, aspect)
    ax.set_yticks([])
    ax.set_xticks([0.0, 1.0])
    ax.tick_params(labelsize=config11.FS_TICK)
    ax.set_title(f"{label} F{family}  n={size}\n{fall:.3g} s / "
                 f"{abs(float(row['drop_depth_mv'])):.3g} mV",
                 fontsize=config11.FS_ANNOT, pad=3.0)
    ax.grid(axis="x", alpha=0.14, lw=style7.LW_RULE * 0.5)


def _pair_traces(pair, snippets):
    """`[(phase, z)]` for the two members of a pair, in drawing order."""
    out = []
    for key in ("query_row", "match_row"):
        phase, z = drawing_rules.phase_trace(pair[key], snippets)
        if phase is not None:
            out.append((phase, z))
    return out


def _draw_pair(ax, pair, snippets, resolved, aspect, ylim=None):
    """One matched pair, OVERLAID as real waveforms.

    Overlaid rather than offset: the gap between the two lines IS the
    matching distance, which is the only question the panel exists to
    answer. Both are drawn from their own samples on the phase axis, so
    two events three orders of magnitude apart in duration can share it
    without either being resampled.
    """
    for key, species_key, lw, style in (
            ("query_row", "query_species", 1.8, "-"),
            ("match_row", "match_species", 1.5, (0, (4, 2)))):
        phase, z = drawing_rules.phase_trace(pair[key], snippets)
        if phase is None:
            continue
        ax.plot(phase, z, color=resolved[pair[species_key]]["colour"],
                lw=lw, ls=style, zorder=4 if lw > 1.6 else 3,
                solid_capstyle="round")
    ax.set_xlim(drawing_rules.PHASE_LO, drawing_rules.PHASE_HI)
    if ylim is not None:
        ax.set_ylim(*ylim)
    drawing_rules.apply_aspect(ax, aspect)
    ax.set_xticks([0.0, 1.0])
    ax.set_yticks([])
    ax.tick_params(labelsize=config11.FS_TICK)
    ax.set_title(f"{pair['query_label']} F{pair['query_family']}"
                 f"\n{pair['distance']:.2f} z RMS",
                 fontsize=config11.FS_ANNOT, pad=3.0)
    ax.spines["left"].set_visible(False)


def plot_asymmetry(rows, snippets, path, *, store_label="", reference=None,
                   k=MEDOIDS_PER_SPECIES):
    """A: the shape vocabularies. B: matching, both directions. C: duty
    cycle against absolute duration."""
    config11.apply_style()
    medoids = _species_medoids(rows, snippets, k=k)
    species = config11.order(medoids)
    resolved = config11.resolve(species)
    ref = _reference_species(rows, override=reference)
    if ref not in medoids:
        ref = species[-1]
    others = [name for name in species if name != ref]
    duty = store11.duty_by_species(rows)

    blocks, baseline = {}, {}
    for name, own in store11.by_species(rows).items():
        features, _kept = drawing_rules.phase_features(own, snippets)
        blocks[name] = features
        baseline[name] = (_coverage(features, medoids[name]["vectors"])
                          if name in medoids else float("nan"))

    # -- the matching, both directions, on the drawn representation --------
    ref_block = medoids[ref]["vectors"]
    ref_families = medoids[ref]["family_ids"]
    ref_rows = medoids[ref]["rows"]

    forward = []
    for name in others:
        block = medoids[name]
        for vector, family, row in zip(block["vectors"], block["family_ids"],
                                       block["rows"]):
            best, distance = _nearest(vector, ref_block)
            forward.append({"query_row": row, "query_species": name,
                            "query_family": family,
                            "query_label": resolved[name]["label"],
                            "match_row": ref_rows[best], "match_species": ref,
                            "match_family": ref_families[best],
                            "distance": distance})

    pool, pool_species, pool_families, pool_rows = [], [], [], []
    for name in others:
        block = medoids[name]
        for vector, family, row in zip(block["vectors"], block["family_ids"],
                                       block["rows"]):
            pool.append(vector)
            pool_species.append(name)
            pool_families.append(family)
            pool_rows.append(row)

    backward = []
    for vector, family, row in zip(ref_block, ref_families, ref_rows):
        best, distance = _nearest(vector, pool)
        backward.append({"query_row": row, "query_species": ref,
                         "query_family": family,
                         "query_label": resolved[ref]["label"],
                         "match_row": pool_rows[best],
                         "match_species": pool_species[best],
                         "match_family": pool_families[best],
                         "distance": distance})

    other_label = " and ".join(resolved[name]["label"] for name in others)
    forward_median = (float(np.median([p["distance"] for p in forward]))
                      if forward else float("nan"))
    backward_median = (float(np.median([p["distance"] for p in backward]))
                       if backward else float("nan"))
    ref_label = resolved[ref]["label"]
    other_events = [blocks[name] for name in others if len(blocks[name])]
    other_events = (np.vstack(other_events) if other_events
                    else np.empty((0, drawing_rules.N_FEATURE)))
    coverage_forward = _coverage(other_events, ref_block)
    coverage_backward = _coverage(blocks[ref], np.vstack(pool))
    supported, verdict = _asymmetry_verdict(forward_median, backward_median,
                                            baseline)

    # -- layout -----------------------------------------------------------
    # Panel A lays every species' medoids out in ONE row, so its width is
    # the SUM over species and not the largest of them. Taking the largest
    # dropped the last species off the row entirely - Reishi's own family
    # shapes were missing from the figure that is about them.
    n_columns = max(len(forward), len(backward),
                    sum(m["n_drawn_families"] for m in medoids.values()) or 1)
    # A phase panel drawn at TARGET_RATIO is taller than wide, so the
    # strips need real height. 1.45 in of width per column and 3.2 in of
    # height per strip is what keeps a medoid legible.
    fig = plt.figure(figsize=(1.45 * n_columns + 2.0, 15.4))
    outer = gridspec.GridSpec(6, 1, figure=fig, hspace=0.52,
                              top=0.955, bottom=0.045,
                              left=0.075, right=0.975,
                              height_ratios=[1.45, 0.13, 1.05,
                                             0.13, 1.05, 1.10])

    # -- Panel A: the shape vocabularies ----------------------------------
    top = gridspec.GridSpecFromSubplotSpec(1, n_columns,
                                           subplot_spec=outer[0], wspace=0.30)
    column = 0
    a_aspects = {}
    for name in species:
        block = medoids[name]
        traces = [drawing_rules.phase_trace(row, snippets)
                  for row in block["rows"]]
        traces = [tr for tr in traces if tr[0] is not None]
        depth_z = float(np.median([float(np.ptp(z)) for _p, z in traces])) \
            if traces else 1.0
        aspect = drawing_rules.TARGET_RATIO / (depth_z or 1.0)
        a_aspects[name] = aspect
        ylim = _group_ylim(traces)
        for position, row in enumerate(block["rows"]):
            if column >= n_columns:
                break
            ax = fig.add_subplot(top[0, column])
            _draw_medoid(ax, row, snippets, resolved[name]["colour"],
                         label=resolved[name]["label"],
                         family=block["family_ids"][position],
                         size=block["sizes"][position], aspect=aspect,
                         ylim=ylim)
            if column == 0:
                ax.set_ylabel("A   z", fontsize=config11.FS_LABEL)
            column += 1
    for spare in range(column, n_columns):
        fig.add_subplot(top[0, spare]).set_axis_off()

    # -- Panel B: matching, both directions -------------------------------
    pair_aspect = drawing_rules.TARGET_RATIO / max(
        float(np.median([float(np.ptp(v)) for v in ref_block])), 1e-9)
    for row_index, (pairs, heading, coverage) in enumerate((
            (forward, f"B  {other_label} matched to {ref_label}",
             coverage_forward),
            (backward, f"B  {ref_label} matched to {other_label}",
             coverage_backward))):
        median = (float(np.median([p["distance"] for p in pairs]))
                  if pairs else float("nan"))
        heading_ax = config11.legend_axis(
            fig.add_subplot(outer[1 + 2 * row_index]))
        heading_ax.text(0.0, 0.0,
                        f"{heading}   |   medoid pairs, median "
                        f"{median:.2f} z RMS   |   all events, median "
                        f"{coverage:.2f} z RMS",
                        transform=heading_ax.transAxes,
                        fontsize=config11.FS_TITLE, va="bottom", ha="left")
        strip = gridspec.GridSpecFromSubplotSpec(
            1, n_columns, subplot_spec=outer[2 + 2 * row_index], wspace=0.30)
        pooled = [tr for pair in pairs[:n_columns]
                  for tr in _pair_traces(pair, snippets)]
        strip_ylim = _group_ylim(pooled)
        for index, pair in enumerate(pairs[:n_columns]):
            ax = fig.add_subplot(strip[0, index])
            _draw_pair(ax, pair, snippets, resolved, pair_aspect,
                       ylim=strip_ylim)
            if index == 0:
                ax.set_ylabel("z", fontsize=config11.FS_LABEL)
        for spare in range(len(pairs), n_columns):
            fig.add_subplot(strip[0, spare]).set_axis_off()

    # -- Panel C: duty cycle against absolute duration --------------------
    bottom = gridspec.GridSpecFromSubplotSpec(1, 3, subplot_spec=outer[5],
                                              wspace=0.50,
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
        duty_ax.annotate(f"{entry['duty_median']:.4f}",
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
        ax.set_xticklabels(names, rotation=18, ha="right")
        ax.set_xlim(-0.6, len(species) - 0.4 + 0.45)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=0.15, lw=style7.LW_RULE * 0.5)
        config11.panel_title(ax, title)
    duty_ax.set_yscale("log")
    fall_ax.set_yscale("log")

    counts = store11.counts_by_species(rows)
    handles = config11.handles(species, counts=counts, resolved=resolved)
    finite = [v for v in baseline.values() if np.isfinite(v)]
    baseline_handles = [Line2D([0], [0], color="0.55", lw=5, alpha=0.35,
                               label=f"within-species baseline "
                                     f"{min(finite):.2f}-{max(finite):.2f} "
                                     f"z RMS")] if finite else []
    species_legend = legend_ax.legend(
        handles=handles, loc="upper left", frameon=False,
        fontsize=config11.FS_LEGEND, title="Species",
        title_fontsize=config11.FS_LEGEND)
    species_legend.get_title().set_ha("left")
    legend_ax.add_artist(species_legend)
    if baseline_handles:
        legend_ax.legend(handles=baseline_handles, loc="lower left",
                         frameon=False, fontsize=config11.FS_LEGEND)

    fig.suptitle("Family shapes, nearest-shape matching in both directions, "
                 "and the duty cycle",
                 fontsize=config11.FS_SUPTITLE, y=0.999)
    config11.footer(fig, store_label, len(rows),
                    extra=f"one point per channel-span group in C; reference "
                          f"species {ref_label}; medoids drawn as real "
                          f"samples on the phase axis")

    manifest = {
        "store": store_label,
        "run": "drop_motifs12b",
        "n_total": len(rows),
        "reference_species": ref,
        "reference_species_rule": ("highest median duty cycle" if not reference
                                   else "set by --reference-species"),
        "families_per_species": int(k),
        "medoid_coverage_target": MEDOID_COVERAGE,
        "distance": (f"Euclidean over {drawing_rules.N_FEATURE}-point "
                     f"z-normalised PHASE frames "
                     f"({drawing_rules.PHASE_LO} to {drawing_rules.PHASE_HI} "
                     f"fall-fractions), / sqrt(n)"),
        "within_species_baseline": baseline,
        "asymmetry_supported": supported,
        "asymmetry_finding": verdict,
        "asymmetry_test": ("backward - forward median medoid distance, "
                           "against the spread of the within-species "
                           "baseline; computed, not asserted"),
        "forward": {
            "direction": f"{other_label} -> {ref_label}",
            "n_medoid_pairs": len(forward),
            "median_medoid_distance": float(np.median(
                [p["distance"] for p in forward])) if forward else float("nan"),
            "n_events": int(len(other_events)),
            "median_event_coverage": coverage_forward,
            "pairs": [{key: value for key, value in pair.items()
                       if not key.endswith("_row")} for pair in forward],
        },
        "backward": {
            "direction": f"{ref_label} -> {other_label}",
            "n_medoid_pairs": len(backward),
            "median_medoid_distance": float(np.median(
                [p["distance"] for p in backward])) if backward else float("nan"),
            "n_events": int(len(blocks[ref])),
            "median_event_coverage": coverage_backward,
            "pairs": [{key: value for key, value in pair.items()
                       if not key.endswith("_row")} for pair in backward],
        },
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
                         "n_families": medoids[name]["n_families"],
                         "n_drawn_families": medoids[name]["n_drawn_families"],
                         "coverage_drawn": medoids[name]["coverage"],
                         "family_sizes": medoids[name]["sizes"]}
                  for name in species},
    }
    config11.save(fig, path)
    config11.write_manifest(path, manifest)
    return manifest


def _asymmetry_verdict(forward, backward, baseline):
    """Whether the two directions differ by more than the noise on them.

    Round 11 shipped this verdict as a hard-coded sentence in the manifest.
    That is wrong for a run whose whole point is a bigger, differently
    sampled corpus: the sentence would survive the numbers changing under
    it. The test is the same one that sentence described, computed:

      the claim is that foreign shapes sit CLOSE to the reference's
      vocabulary while the reference's shapes sit FAR from theirs, so the
      finding needs `forward < backward` by more than the spread of the
      within-species baseline - the distance events sit from their OWN
      medoids, which is the scale on which any of these numbers is noise.

    Returns `(supported, sentence)`.
    """
    finite = [v for v in baseline.values() if np.isfinite(v)]
    spread = (max(finite) - min(finite)) if len(finite) > 1 else float("nan")
    gap = backward - forward
    if not np.isfinite(gap) or not np.isfinite(spread):
        return False, ("NOT ASSESSED: too few species with a within-species "
                       "baseline to say what a difference of this size means.")
    if gap > spread:
        return True, (
            f"SUPPORTED on this store. The reference's shapes sit "
            f"{backward:.3f} z RMS from the others' vocabulary while the "
            f"others sit {forward:.3f} from the reference's - a gap of "
            f"{gap:.3f}, larger than the {spread:.3f} spread of the "
            f"within-species baseline.")
    direction = ("the same direction as the claim but too small"
                 if gap > 0 else "the OPPOSITE direction to the claim")
    return False, (
        f"NOT SUPPORTED on this store. The two directions are "
        f"{forward:.3f} and {backward:.3f} z RMS, a gap of {gap:+.3f} - "
        f"{direction}, and smaller than the {spread:.3f} spread of the "
        f"within-species baseline. The comparison also carries a "
        f"samples-per-fall confound: see the run's PROVENANCE.md.")


def _reference_species(rows, override=None):
    """Which species the others are matched AGAINST.

    Derived rather than named - the species with the highest median duty
    cycle, the one whose waveforms are broadest relative to their own
    spacing, which is the property the asymmetry is about. Same rule as
    `figures11_s2.reference_species`, restated here only so this module
    does not import a round-11 figure to get a threshold.
    """
    if override:
        return override
    duty = store11.duty_by_species(rows)
    if not duty:
        return None
    return max(duty, key=lambda name: (duty[name]["duty_median"]
                                       if np.isfinite(duty[name]["duty_median"])
                                       else -np.inf))
