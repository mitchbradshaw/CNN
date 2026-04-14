"""
matrix_calc.py

Incremental feature matrix over time-ordered EEG windows.

Each row  = one window, identified by its start sample index.
Each col  = one feature (computed or externally supplied).

Backed by a pandas DataFrame for free NaN handling, named columns,
and efficient row/column access — no need to reinvent that wheel.
"""

import os
import numpy as np
import pandas as pd


class WindowMatrix:
    """
    A feature matrix whose rows are EEG windows and whose columns are
    analyses computed on (or externally assigned to) those windows.

    Parameters
    ----------
    start_indices : array-like of int
        Ordered start sample indices, one per window.
    x : np.ndarray
        Full raw signal. Used to extract each window on demand.
    timescale : float
        Window length in minutes.
    fs : float
        Sample rate in Hz.
    """

    def __init__(self, start_indices, x, timescale, fs):
        self._x             = x
        self._timescale     = timescale
        self._fs            = fs
        self._window_samples = int(timescale * 60 * fs)

        # DataFrame index = start_idx; columns added incrementally
        self._df = pd.DataFrame(index=pd.Index(list(start_indices), name="start_idx"))

        # Metadata: tracks how each column was created and with what fn
        self._meta: dict[str, dict] = {}

    def save_window(self, filename):
        os.makedirs("MATRICES", exist_ok=True)
        self.df.to_csv(f"MATRICES/{filename}")

    # ------------------------------------------------------------------ #
    #  Raw signal access                                                   #
    # ------------------------------------------------------------------ #

    def get_entire_signal(self):
        """Return the entire signal stored in matrix"""
        return self._x

    # ------------------------------------------------------------------ #
    #  Raw window access                                                   #
    # ------------------------------------------------------------------ #

    def get_window_signal(self, start_idx: int) -> np.ndarray:
        """Return the raw signal slice for a single window."""
        return self._x[start_idx : start_idx + self._window_samples]

    # ------------------------------------------------------------------ #
    #  Adding columns                                                      #
    # ------------------------------------------------------------------ #

    def add_computed_column(self, name: str, fn, overwrite: bool = False) -> "WindowMatrix":
        """
        Compute a scalar feature for every window and store it as a column.

        Parameters
        ----------
        name : str
            Column name (e.g. "entropy", "std_dev").
        fn : callable
            Function that takes a 1-D np.ndarray (one window's signal)
            and returns a scalar or array.  Arrays are stored as object dtype.
        overwrite : bool
            If False (default), skip silently if the column already exists.

        Returns
        -------
        self  (for chaining)
        """
        if name in self._df.columns and not overwrite:
            return self

        self._df[name] = [
            fn(self.get_window_signal(idx)) for idx in self._df.index
        ]
        self._meta[name] = {"type": "computed", "fn": fn}
        return self

    def add_external_column(self, name: str, values, overwrite: bool = False) -> "WindowMatrix":
        """
        Add a column from externally supplied values (e.g. category labels).

        Parameters
        ----------
        name : str
            Column name (e.g. "category", "manual_label").
        values : dict or array-like
            - dict  {start_idx: value}  — partial coverage OK; missing rows → NaN
            - list/array                — must be the same length as the matrix rows,
                                          aligned positionally
        overwrite : bool
            If False (default), skip silently if the column already exists.

        Returns
        -------
        self  (for chaining)
        """
        if name in self._df.columns and not overwrite:
            return self

        if isinstance(values, dict):
            # Align by index; missing keys become NaN automatically
            self._df[name] = pd.Series(values, dtype=object)
        else:
            if len(values) != len(self._df):
                raise ValueError(
                    f"Length of values ({len(values)}) does not match "
                    f"number of windows ({len(self._df)})."
                )
            self._df[name] = list(values)

        self._meta[name] = {"type": "external"}
        return self

    def add_vector_columns(self, prefix: str, fn, n: int = None,
                           overwrite: bool = False) -> "WindowMatrix":
        """
        Expand a vector-valued feature into one scalar column per element.

        Each column is named ``{prefix}_0``, ``{prefix}_1``, …, ``{prefix}_{n-1}``.

        Parameters
        ----------
        prefix : str
            Column name prefix (e.g. "stft_bin").
        fn : callable
            Function that takes a 1-D np.ndarray (one window's signal)
            and returns a 1-D array of fixed length.
        n : int, optional
            Expected output length.  Inferred from the first window if omitted.
        overwrite : bool
            If False (default), skip silently if the first column already exists.

        Returns
        -------
        self  (for chaining)
        """
        first_col = f"{prefix}_0"
        if first_col in self._df.columns and not overwrite:
            return self

        # Compute vectors for all windows
        vectors = np.array([
            fn(self.get_window_signal(idx)) for idx in self._df.index
        ])  # shape: (n_windows, n_features)

        if vectors.ndim != 2:
            raise ValueError(
                f"fn must return a 1-D array; got shape {vectors.shape[1:]}"
            )

        n = vectors.shape[1]
        for i in range(n):
            col = f"{prefix}_{i}"
            self._df[col] = vectors[:, i]
            self._meta[col] = {"type": "vector", "prefix": prefix, "fn": fn}

        return self

    def recompute_column(self, name: str) -> "WindowMatrix":
        """Re-run the stored function for a computed column (e.g. after signal update)."""
        if name not in self._meta:
            raise KeyError(f"Column '{name}' not found.")
        if self._meta[name]["type"] != "computed":
            raise TypeError(f"Column '{name}' is external — nothing to recompute.")
        return self.add_computed_column(name, self._meta[name]["fn"], overwrite=True)

    # ------------------------------------------------------------------ #
    #  Querying                                                            #
    # ------------------------------------------------------------------ #

    def get_column(self, name: str) -> pd.Series:
        """Return a column as a pd.Series indexed by start_idx."""
        return self._df[name]

    def get_row(self, start_idx: int) -> pd.Series:
        """Return all features for one window as a pd.Series."""
        return self._df.loc[start_idx]

    def get_value(self, start_idx: int, name: str):
        """Return a single cell."""
        return self._df.at[start_idx, name]

    @property
    def columns(self) -> list[str]:
        """List of feature column names currently in the matrix."""
        return list(self._df.columns)

    @property
    def df(self) -> pd.DataFrame:
        """Direct access to the underlying DataFrame (read-only convention)."""
        return self._df

    def __len__(self) -> int:
        return len(self._df)

    def __repr__(self) -> str:
        return (
            f"WindowMatrix({len(self._df)} windows, "
            f"columns={self.columns})"
        )


# ------------------------------------------------------------------ #
#  Factory helpers                                                     #
# ------------------------------------------------------------------ #

def create_matrix(start_indices, x, timescale, fs) -> WindowMatrix:
    """
    Initialise an empty WindowMatrix from a list of start indices.

    Parameters
    ----------
    start_indices : array-like of int
    x             : np.ndarray   full raw signal
    timescale     : float        window length in minutes
    fs            : float        sample rate in Hz
    """
    return WindowMatrix(start_indices, x, timescale, fs)

def create_matrix_at_timescale(stepfrac,x,timescale,fs) -> WindowMatrix:
    """
    Initialise an empty WindowMatrix given window size and step size at timescale

    Parameters
    ----------
    stepfrac      : 0 - 1 -> percentage of window length that each new starting index jumps to
    x             : np.ndarray   full raw signal
    timescale     : float        window length in minutes
    fs            : float        sample rate in Hz
    """
    winlength = int(fs * timescale * 60)
    stepsize = int(np.floor(stepfrac * winlength))
    start_indices = np.arange(0, len(x), stepsize)
    return create_matrix(start_indices,x,timescale,fs)


def load_matrix(csv_path: str, x, timescale, fs) -> WindowMatrix:
    """
    Reconstruct a WindowMatrix from a CSV file previously saved from ``wm.df``.

    The CSV must have a ``start_idx`` column (or index) whose values match
    the window start sample indices.  All other columns are restored as
    external columns so existing feature data is preserved.

    Parameters
    ----------
    csv_path  : str        Path to the CSV file.
    x         : np.ndarray Full raw signal (needed for future window extraction).
    timescale : float      Window length in minutes.
    fs        : float      Sample rate in Hz.

    Returns
    -------
    WindowMatrix with all CSV columns loaded as external columns.
    """
    df = pd.read_csv(csv_path)

    # Accept start_idx either as a named column or as the unnamed index
    if "start_idx" in df.columns:
        df = df.set_index("start_idx")
    else:
        df.index.name = "start_idx"

    df.index = df.index.astype(int)

    wm = WindowMatrix(df.index.tolist(), x, timescale, fs)

    for col in df.columns:
        wm._df[col] = df[col].values
        wm._meta[col] = {"type": "external"}

    return wm


def create_matrix_from_categories(categories: dict, x, timescale, fs) -> WindowMatrix:
    """
    Initialise a WindowMatrix from a category dict and immediately add
    a "category" column.

    Parameters
    ----------
    categories : dict  {label: array of start_indices}
                 e.g. {"interesting": [...], "notinteresting": [...]}
    """
    all_indices = sorted(
        idx for indices in categories.values() for idx in indices
    )
    wm = WindowMatrix(all_indices, x, timescale, fs)

    label_map = {
        idx: label
        for label, indices in categories.items()
        for idx in indices
    }
    wm.add_external_column("category", label_map)
    return wm
