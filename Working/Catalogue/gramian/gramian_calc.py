import numpy as np
from scipy.spatial.distance import cdist
from skimage.transform import resize
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from PIL import Image

plt.rc('image', cmap='gray')
plt.rc('figure', autolayout=True)

def _polar_encode(x):
    """Rescale x to [-1,1] and return phi = arccos(x_scaled)."""
    x_min, x_max = x.min(), x.max()
    x_scaled = 2 * (x - x_min) / (x_max - x_min) - 1
    x_scaled = np.clip(x_scaled, -1, 1)
    return np.arccos(x_scaled)


def compute_GASF(x):
    """Gramian Angular Summation Field: G[i,j] = cos(phi_i + phi_j)."""
    phi = _polar_encode(x)
    return np.cos(np.add.outer(phi, phi))


def compute_GADF(x):
    """Gramian Angular Difference Field: G[i,j] = sin(phi_i - phi_j)."""
    phi = _polar_encode(x)
    return np.sin(np.subtract.outer(phi, phi))


def compute_recurrence(x, m=3, tau=4):
    """Recurrence plot via time-delay embedding with dimension m and delay tau."""
    n_rows = len(x) - (m - 1) * tau
    Y = np.column_stack([x[(i * tau):(i * tau + n_rows)] for i in range(m)])
    return cdist(Y, Y)


def compute_fusion(x, m=3, tau=4):
    """RGB fusion of GASF (R), GADF (G), and recurrence plot (B), all scaled to [0,1]."""
    gasf = compute_GASF(x)
    gadf = compute_GADF(x)
    rec  = compute_recurrence(x, m=m, tau=tau)

    target = gasf.shape
    rec_resized = resize(rec, target, anti_aliasing=True)

    def norm(a):
        a_min, a_max = a.min(), a.max()
        return (a - a_min) / (a_max - a_min) if a_max > a_min else np.zeros_like(a)

    return np.stack([norm(gasf), norm(gadf), norm(rec_resized)], axis=-1)


def plot_gramian_suite(x, t, m=3, tau=4):
    """Plot GASF, GADF, recurrence, fusion, and the input signal in one figure."""
    gasf    = compute_GASF(x)
    gadf    = compute_GADF(x)
    rec     = compute_recurrence(x, m=m, tau=tau)
    fusion  = compute_fusion(x, m=m, tau=tau)

    # Layout mirrors MATLAB: top row = 3 images, bottom-left wide = signal, bottom-right = fusion
    fig = plt.figure(figsize=(14, 8))
    gs  = gridspec.GridSpec(2, 3, figure=fig)

    ax_gasf   = fig.add_subplot(gs[0, 0])
    ax_gadf   = fig.add_subplot(gs[0, 1])
    ax_rec    = fig.add_subplot(gs[0, 2])
    ax_signal = fig.add_subplot(gs[1, 0:2])
    ax_fusion = fig.add_subplot(gs[1, 2])

    im = ax_gasf.imshow(gasf, aspect="auto", cmap="turbo", origin="lower")
    ax_gasf.set_title("GASF")
    fig.colorbar(im, ax=ax_gasf)

    im = ax_gadf.imshow(gadf, aspect="auto", cmap="turbo", origin="lower")
    ax_gadf.set_title("GADF")
    fig.colorbar(im, ax=ax_gadf)

    im = ax_rec.imshow(rec, aspect="auto", cmap="jet", origin="lower")
    ax_rec.set_title("Recurrence Plot")
    ax_rec.set_xlabel("Time")
    ax_rec.set_ylabel("Time")
    fig.colorbar(im, ax=ax_rec)

    ax_signal.plot(t, x)
    ax_signal.set_title("Signal")
    ax_signal.set_xlabel("Time (s)")
    ax_signal.set_ylabel("Amplitude (mV)")

    ax_fusion.imshow(fusion, aspect="auto", origin="lower")
    ax_fusion.set_title("Fusion (RGB)")
    ax_fusion.set_xlabel("Time")
    ax_fusion.set_ylabel("Time")

    plt.tight_layout()
    plt.show()


def to_uint8(mat):
    """Normalise a 2D float matrix to uint8 [0, 255]."""
    m, M = mat.min(), mat.max()
    if M > m:
        return ((mat - m) / (M - m) * 255).astype(np.uint8)
    return np.zeros_like(mat, dtype=np.uint8)

def save_gramian_windows(x, start_indexes, timescale, fs, label, window_samples, suffix=""):
    import os
    names = ["GASF", "GADF", "recurrence", "fusion"]
    folders = {}
    from Working.Preprocessing.manage_data.load_data import window_root
    win_root = window_root(timescale, fs)
    suffix_part = f"_{suffix}" if suffix else ""
    for name in names:
        # encoding as parent, class as child -> each encoding dir is a valid ImageFolder root
        folder = os.path.join(win_root, f"{name}{suffix_part}", label)
        os.makedirs(folder, exist_ok=True)
        folders[name] = folder

    def norm(a):
        lo, hi = a.min(), a.max()
        return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)

    n = len(start_indexes)
    for i, start in enumerate(start_indexes):
        win = x[start:start + window_samples]

        # Compute each matrix once and reuse for fusion
        gasf = compute_GASF(win)
        gadf = compute_GADF(win)
        rec  = compute_recurrence(win)
        rec_resized = resize(rec, gasf.shape, anti_aliasing=True)
        fusion = np.stack([norm(gasf), norm(gadf), norm(rec_resized)], axis=-1)

        saves = {
            "GASF":       (to_uint8(gasf),                  "L"),
            "GADF":       (to_uint8(gadf),                  "L"),
            "recurrence": (to_uint8(rec),                   "L"),
            "fusion":     ((fusion * 255).astype(np.uint8), "RGB"),
        }
        for name, (arr, mode) in saves.items():
            Image.fromarray(arr, mode=mode).save(
                os.path.join(folders[name], f"{name}_{start}.png"), optimize=True
            )
        print(f"\r  {label}: {i + 1}/{n}", end="", flush=True)
    print()
