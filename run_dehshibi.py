"""
Simple use-case: run the Dehshibi & Adamatzky (2021) spike-detection pipeline
on one channel of the fungal recording.

Usage:
    python testing.py

The script has two modes controlled by the USE_SLIDING_WINDOW flag:

  USE_SLIDING_WINDOW = False (default for a quick test)
    -- Analyses a single CHUNK_SIZE-sample window starting at START.
    -- Fast.  Use this to tune parameters on a known-active region.

  USE_SLIDING_WINDOW = True
    -- Slides a window of WINDOW_SIZE samples across the whole recording,
       stepping STEP_SIZE samples at a time, then aggregates all detections.
    -- Correct approach for long recordings where spikes are small relative
       to the full signal duration.

Why sliding window?
    The pipeline's wavelet normalisation (Eq. 3) and histogram slicer (Sect. 3.1)
    both scale relative to the amplitude range of the chunk they receive.
    A 5-minute spike sitting in a 100-hour window contributes <0.1% of the
    samples, so its wavelet energy is dwarfed by the global statistics and
    the spike is missed.  Processing the recording in ~1-hour chunks keeps
    spike amplitudes significant within each window.
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import uniform_filter1d

from manage_data.load_data import load_raw_data
from analysis.dehshibi_detection_analysis import (
    detect_spikes,
    detect_spikes_sliding_window,
    compute_all_complexity_measures,
    plot_spike_detection,
    # diagnostic helpers
    estimate_state_levels,
    slice_signal,
    compute_morse_wavelet_transform,
    normalise_wavelet_coefficients,
)

# =============================================================================
# Configuration -- edit these
# =============================================================================

FILENAME = "0.01_percent_M2_concat_fs1.mat"   # any .mat or .npy in DATA/RAW/
MATNAME  = "VECTOR"                            # variable name inside the .mat file
FS       = 1.0                                 # sampling frequency (Hz)

# ---- Single-window mode -----------------------------------------------------
USE_SLIDING_WINDOW = True   # set True to scan the whole file

START      = 0   # sample index to start from  (hour 29 -- highest activity)
CHUNK_SIZE = 1000     # number of samples to analyse (3600 s = 1 hour at 1 Hz)

# ---- Tuning parameters (single-window mode) ---------------------------------
#
# When to adjust each knob:
#
#   SMOOTH_WINDOW     : if Chunks >> expected (micro-oscillations causing many
#                       mid-ref crossings).  Try 5-15.  Paper assumes no noise.
#
#   EPSILON_FACTOR    : if B >> expected AND C=D=0 (tiny ROIs all filtered) OR
#                       if C regions are too SMALL to contain R regions (Algorithm
#                       4 Case 1 never fires).  Higher = fewer, wider ROIs.
#                       Paper: 0.05.  Try 0.3-0.6 for oscillatory signals.
#
#   N_P               : min samples between envelope extrema in Algorithm 3.
#                       Lower = smaller R regions, which helps Case 1 (R inside C).
#                       Paper: 60.  Try 20-40 for shorter/frequent spikes.
#
#   MIN_ROI           : minimum wavelet ROI width for Algorithm 2.
#                       Lower = fewer silent skips in Algorithm 2.
#                       Paper: 30.
#
#   MIN_SPIKE_DUR     : final spike minimum length.  Lower = keep short detections.
#                       Paper: 60.

SMOOTH_WINDOW  = 7     # rolling-mean pre-filter window (0 = off)
EPSILON_FACTOR = 0.5   # Omega prominence threshold (paper=0.05)
N_P            = 30    # envelope extrema min separation (paper=60)
MIN_ROI        = 15    # min wavelet ROI width in samples (paper=30)
MIN_SPIKE_DUR  = 30    # min final spike duration in samples (paper=60)

# ---- Sliding-window mode ----------------------------------------------------
WINDOW_SIZE = 3600     # samples per window (~1 hour at 1 Hz)
STEP_SIZE   = 3600     # advance per step (= WINDOW_SIZE means no overlap)
#   Use STEP_SIZE = WINDOW_SIZE // 2 for 50% overlap if you are worried about
#   spikes that fall exactly on a window boundary.

# =============================================================================
# 1. Load the signal
# =============================================================================

x, t = load_raw_data(FILENAME, FS, matname=MATNAME)

print(f"Loaded '{FILENAME}'")
print(f"  Total samples : {len(x)}  ({len(x) / FS / 3600:.1f} hours at {FS} Hz)")
print(f"  Amplitude range: [{x.min():.4f}, {x.max():.4f}] V")

# =============================================================================
# Optional: scan for the most active window
# =============================================================================
# Uncomment the block below to print the 10 windows with the highest standard
# deviation. High std usually means more spike activity. Use the START value
# that is printed to re-run in single-window mode.
#
# chunk = CHUNK_SIZE
# windows = [(s, float(np.std(x[s:s + chunk])))
#            for s in range(0, len(x) - chunk, chunk)]
# windows.sort(key=lambda w: w[1], reverse=True)
# print("\nMost variable windows:")
# for s, sd in windows[:10]:
#     print(f"  START={s}  (hour {s // 3600})  std={sd:.5f}")

# =============================================================================
# 2. Run spike detection
# =============================================================================

if USE_SLIDING_WINDOW:
    # ---- Sliding-window mode: scan the whole recording ----------------------
    print("\nRunning sliding-window spike detection on the full recording...")
    spikes, pseudo_spikes = detect_spikes_sliding_window(
        x,
        fs=FS,
        window_size=WINDOW_SIZE,
        step_size=STEP_SIZE,
        verbose=True,
    )
    signal = x          # for plotting -- we plot the full signal
    plot_start = 0      # global offset already baked into indices

else:
    # ---- Single-window mode: analyse one chunk -------------------------------
    signal = x[START : START + CHUNK_SIZE]
    print(f"\nAnalysing samples [{START}, {START + CHUNK_SIZE}]  "
          f"({CHUNK_SIZE / FS / 60:.0f} minutes)")

    # Optional pre-smoothing: removes micro-oscillations that cause
    # slice_signal to fragment the window into many tiny sub-chunks.
    if SMOOTH_WINDOW > 1:
        signal_for_detection = uniform_filter1d(signal, size=SMOOTH_WINDOW)
        print(f"Pre-smoothed with {SMOOTH_WINDOW}-sample rolling mean.")
    else:
        signal_for_detection = signal

    print(f"Parameters: smooth={SMOOTH_WINDOW}, epsilon_factor={EPSILON_FACTOR}, "
          f"n_p={N_P}, min_roi={MIN_ROI}, min_spike={MIN_SPIKE_DUR}")
    print("\nRunning spike detection pipeline...")

    spikes, pseudo_spikes, info = detect_spikes(
        signal_for_detection,
        fs=FS,
        epsilon_factor=EPSILON_FACTOR,
        min_roi_wavelet=MIN_ROI,
        n_p=N_P,
        min_spike_duration=MIN_SPIKE_DUR,
    )

    print(f"\n--- Pipeline intermediate counts ---")
    print(f"  Chunks (signal slices)    : {len(info['chunks'])}")
    chunk_sizes = [e - s for s, e in info['chunks']]
    print(f"    sizes: {chunk_sizes}")
    print(f"  Wavelet ROIs found (B)    : {len(info['B'])}")
    if info['B']:
        b_sizes = [e - s for s, e in info['B']]
        print(f"    sizes: {b_sizes}")
    print(f"  Wavelet spike candidates  : {len(info['C'])}")
    if info['C']:
        c_sizes = [e - s for s, e in info['C']]
        print(f"    sizes: {c_sizes}")
    print(f"  Wavelet pseudo-spike cands: {len(info['D'])}")
    r_regions = [r for r in info['R'] if r.shape[0] > 0]
    n_env = sum(r.shape[0] for r in r_regions)
    print(f"  Envelope ROIs found (R)   : {n_env}")
    for r in r_regions:
        r_sizes = [int(row[1]) - int(row[0]) for row in r]
        print(f"    sizes: {r_sizes}")

    # ---- Diagnostic: plot Omega(tau) ----------------------------------------
    print("\n--- Wavelet diagnostic (Omega(tau) on smoothed signal) ---")
    low_state, high_state = estimate_state_levels(signal_for_detection)
    mid_ref = (low_state + high_state) / 2.0
    chunks_diag = slice_signal(signal_for_detection)
    print(f"  State levels: low={low_state:.4f} V  high={high_state:.4f} V  "
          f"mid_ref={mid_ref:.4f} V")
    print(f"  Chunks from slice_signal: {len(chunks_diag)}  "
          f"(sizes: {[e-s for s,e in chunks_diag]})")

    phi_full, _ = compute_morse_wavelet_transform(signal_for_detection, fs=FS)
    _, g_sum_full = normalise_wavelet_coefficients(phi_full)
    omega_range = float(g_sum_full.max() - g_sum_full.min())
    epsilon_diag = EPSILON_FACTOR * omega_range
    print(f"  Omega(tau) range: {omega_range:.2f}  |  epsilon={epsilon_diag:.2f}")

    # Plot: raw + smoothed signal on top, Omega on bottom
    fig_diag, (ax_sig, ax_om) = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    t_axis = np.arange(len(signal)) / FS
    ax_sig.plot(t_axis, signal, lw=0.6, color='lightsteelblue', label='raw')
    if SMOOTH_WINDOW > 1:
        ax_sig.plot(t_axis, signal_for_detection, lw=1.0, color='steelblue',
                    label=f'smoothed (w={SMOOTH_WINDOW})')
    ax_sig.axhline(mid_ref, color='orange', ls='--', lw=0.9,
                   label=f'mid_ref={mid_ref:.3f}')
    # Mark chunk boundaries
    for s, e in chunks_diag:
        ax_sig.axvspan(s / FS, e / FS, alpha=0.08, color='green')
    ax_sig.set_ylabel('Amplitude (V)')
    ax_sig.set_title(f'Signal  (START={START},  CHUNK={CHUNK_SIZE},  '
                     f'smooth={SMOOTH_WINDOW})  --  '
                     f'{len(chunks_diag)} slice chunks (green)')
    ax_sig.legend(fontsize=8)

    ax_om.plot(t_axis, g_sum_full, lw=0.8, color='darkgreen')
    ax_om.axhline(g_sum_full.min() + epsilon_diag, color='red', ls='--', lw=0.8,
                  label=f'epsilon (={epsilon_diag:.0f})')
    ax_om.set_ylabel('Omega(tau)')
    ax_om.set_xlabel('Time (sec)')
    ax_om.set_title(f'Omega(tau) -- range={omega_range:.0f}  |  '
                    f'epsilon_factor={EPSILON_FACTOR}')
    ax_om.legend(fontsize=8)
    fig_diag.tight_layout()
    plt.show()
    # -------------------------------------------------------------------------

    plot_start = START   # for converting local -> absolute times in printout

# =============================================================================
# 3. Print results
# =============================================================================

print(f"\n--- Final results ---")
print(f"  Confirmed spikes    : {len(spikes)}")
for i, (s, e) in enumerate(spikes):
    t_start = (plot_start + s) / FS if USE_SLIDING_WINDOW else (START + s) / FS
    t_end   = (plot_start + e) / FS if USE_SLIDING_WINDOW else (START + e) / FS
    amp     = x[s:e].max() if USE_SLIDING_WINDOW else signal[s:e].max()
    print(f"    Spike {i+1}: t = [{t_start:.0f} s, {t_end:.0f} s]  "
          f"duration = {e - s} s  "
          f"amplitude peak = {amp:.4f} V")

print(f"  Pseudo-spikes       : {len(pseudo_spikes)}")

# =============================================================================
# 4. Complexity measures  (only meaningful when we have spikes)
# =============================================================================

sig_len = len(x) if USE_SLIDING_WINDOW else len(signal)

if spikes:
    print("\n--- Complexity measures (Sect. 4.2) ---")
    if len(spikes) < 2:
        print("  NOTE: fewer than 2 spikes -- entropy-based measures (H, PCI, E)")
        print("        require a population of spikes to be meaningful.")
    metrics = compute_all_complexity_measures(spikes, sig_len)
    labels = {
        'n_spikes':           'Number of spikes',
        'shannon_entropy':    'Shannon entropy (H)',
        'simpsons_diversity': "Simpson's diversity (S)",
        'space_filling':      'Space filling (D)',
        'expressiveness':     'Expressiveness (E = H/D)',
        'lz_complexity':      'Lempel-Ziv complexity (LZ)',
        'kolmogorov':         'Kolmogorov complexity (K)',
        'pci':                'Perturbation complexity index (PCI)',
    }
    for key, label in labels.items():
        val = metrics[key]
        if isinstance(val, float):
            if val != val:   # nan
                print(f"  {label:<40s}: N/A (undefined)")
            else:
                print(f"  {label:<40s}: {val:.6f}")
        else:
            print(f"  {label:<40s}: {val}")
else:
    print("\nNo spikes detected.")
    if not USE_SLIDING_WINDOW:
        print("Try a different START position, a longer CHUNK_SIZE,")
        print("or set USE_SLIDING_WINDOW = True to scan the whole file.")

# =============================================================================
# 5. Plot
# =============================================================================

# In sliding-window mode the full recording can be very long, so we plot only
# the portion that contains detections (with a margin), or the first 3 hours.
if USE_SLIDING_WINDOW and spikes:
    margin  = WINDOW_SIZE
    p_start = max(0, spikes[0][0] - margin)
    p_end   = min(len(x), spikes[-1][1] + margin)
    plot_signal  = x[p_start:p_end]
    plot_spikes  = [(s - p_start, e - p_start) for (s, e) in spikes
                    if e > p_start and s < p_end]
    plot_pseudo  = [(s - p_start, e - p_start) for (s, e) in pseudo_spikes
                    if e > p_start and s < p_end]
    title = (f"Dehshibi & Adamatzky (2021) -- {FILENAME}  "
             f"samples [{p_start}:{p_end}]  (sliding window)")
elif USE_SLIDING_WINDOW:
    # No spikes: plot first 3 hours
    p_end   = min(len(x), 3 * 3600)
    plot_signal = x[:p_end]
    plot_spikes = []
    plot_pseudo = []
    title = f"Dehshibi & Adamatzky (2021) -- {FILENAME}  (no spikes found)"
else:
    plot_signal = signal
    plot_spikes = spikes
    plot_pseudo = pseudo_spikes
    title = (f"Dehshibi & Adamatzky (2021) -- {FILENAME}  "
             f"samples [{START}:{START + CHUNK_SIZE}]")

fig = plot_spike_detection(
    plot_signal,
    plot_spikes,
    plot_pseudo,
    fs=FS,
    title=title,
)
plt.show()
