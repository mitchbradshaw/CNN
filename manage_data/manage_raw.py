import numpy as np
import os


def save_windows(x, t, start_indexes, timescale, fs, label):
    """Save each window's x and t data to .npy files.

    Files are saved to: [timescale]min_fs[fs]_[label]_rawdata/[start_idx].npy
    Each file stores a (2, window_samples) array: row 0 = x, row 1 = t.
    """
    window_samples = int(timescale * 60 * fs)
    folder = os.path.join("DATA", f"{timescale:g}_MINUTES", f"{timescale:g}min_fs{fs}_{label}_rawdata")
    os.makedirs(folder, exist_ok=True)

    for start in start_indexes:
        end = start + window_samples
        data = np.stack([x[start:end], t[start:end]])
        np.save(os.path.join(folder, f"{start}.npy"), data)

    print(f"Saved {len(start_indexes)} windows to '{folder}/'")


def load_window(start_idx, timescale, fs, label):
    """Load a previously saved window by its start index. Returns (x, t)."""
    folder = os.path.join("DATA", f"{timescale:g}_MINUTES", f"{timescale:g}min_fs{fs}_{label}_rawdata")
    data = np.load(os.path.join(folder, f"{start_idx}.npy"))
    return data[0], data[1]

