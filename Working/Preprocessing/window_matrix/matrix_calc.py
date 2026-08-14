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

    def __init__(self, start_indices, x, timescale, fs, step=None,
                 partial_tail=False):
        if timescale <= 0:
            raise ValueError(f"timescale must be > 0 minutes, got {timescale!r}.")
        if fs <= 0:
            raise ValueError(f"fs must be > 0 Hz, got {fs!r}.")

        self._x             = x
        self._timescale     = timescale
        self._fs            = fs
        self._window_samples = int(timescale * 60 * fs)
        # `step` is carried so a matrix can describe its own grid without the
        # caller re-deriving it from consecutive index differences (which is
        # ambiguous for a 1-row matrix and wrong for a non-uniform one, e.g.
        # `create_matrix_from_categories`). None means "not a uniform grid".
        self._step          = int(step) if step is not None else None
        self._partial_tail  = bool(partial_tail)

        if self._window_samples < 1:
            raise ValueError(
                f"timescale={timescale} min at fs={fs} Hz gives a "
                f"{self._window_samples}-sample window — nothing to compute on."
            )

        # DataFrame index = start_idx; columns added incrementally
        self._df = pd.DataFrame(index=pd.Index(list(start_indices), name="start_idx"))

        # Metadata: tracks how each column was created and with what fn
        self._meta: dict[str, dict] = {}

    def save_window(self, path, matrices_dir="MATRICES"):
        """Write the feature table to `path` as CSV.

        `path` is used as given when it contains a directory component;
        a bare filename is placed under `matrices_dir` for backwards
        compatibility with the original API, which prefixed "MATRICES/"
        internally while `load_matrix` took a FULL path — so
        `save_window("a.csv")` and `load_matrix("a.csv")` referred to two
        different files, and neither worked unless the process happened to
        start from the repo root.

        Superseded for real storage by
        `Working.database.window_matrix_store.save_wm` (the v1 `.npz`
        format) — CSV round-tripping loses dtypes, column metadata, and all
        of `timescale`/`fs`/`step`/source identity. Kept for ad-hoc export
        and for reading the pre-v1 files in `MATRICES/`.
        """
        directory = os.path.dirname(path)
        if not directory:
            directory, path = matrices_dir, os.path.join(matrices_dir, path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.df.to_csv(path)
        return path

    # ------------------------------------------------------------------ #
    #  Grid description                                                    #
    # ------------------------------------------------------------------ #

    @property
    def fs(self) -> float:
        """Sample rate in Hz."""
        return self._fs

    @property
    def timescale(self) -> float:
        """Window length in minutes."""
        return self._timescale

    @property
    def window_samples(self) -> int:
        """Window length in samples (`timescale * 60 * fs`)."""
        return self._window_samples

    @property
    def step(self):
        """Step between consecutive window starts, in samples. None when
        the matrix was not built on a uniform grid."""
        return self._step

    @property
    def partial_tail(self) -> bool:
        """True if windows shorter than `window_samples` were retained.
        See `create_matrix_at_timescale` for why the default is False."""
        return self._partial_tail

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
        """Return the raw signal slice for a single window.

        May be SHORTER than `window_samples` only when the matrix was built
        with `partial_tail=True` — otherwise every index in the matrix is
        guaranteed to admit a full window. Use `is_full_window` to check
        without slicing.
        """
        return self._x[start_idx : start_idx + self._window_samples]

    def is_full_window(self, start_idx: int) -> bool:
        """Whether `start_idx` admits a complete `window_samples`-long slice.

        Always True unless the matrix was built with `partial_tail=True`.
        Feature functions computed on a truncated window return values that
        LOOK comparable to the rest of the column and are not — a 3-sample
        "entropy" is not on the same scale as a 600-sample one — so callers
        that accept a partial tail must decide explicitly what to do with it
        rather than letting the truncation pass silently.
        """
        # bool(...): start_idx/window_samples are numpy ints here (df.index
        # entries), so the bare comparison is np.bool_ — callers that do
        # `is False`/`is True` (e.g. tests) get a spurious failure against a
        # correct value, since np.bool_(False) is not the singleton False.
        return bool(start_idx + self._window_samples <= len(self._x))

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
                           names: list = None,
                           overwrite: bool = False) -> "WindowMatrix":
        """
        Expand a vector-valued feature into one scalar column per element.

        By default columns are named ``{prefix}_0``, ``{prefix}_1``, …
        Pass ``names`` to use explicit column names instead.

        Parameters
        ----------
        prefix : str
            Column name prefix (e.g. "stft_bin").
        fn : callable
            Function that takes a 1-D np.ndarray (one window's signal)
            and returns a 1-D array of fixed length.
        n : int, optional
            Expected output length.  Inferred from the first window if omitted.
        names : list of str, optional
            Explicit column names, one per output element.  Length must match
            the output of ``fn``.  When provided, ``prefix`` is still stored in
            metadata but is not used to build column names.
        overwrite : bool
            If False (default), skip silently if the first column already exists.

        Returns
        -------
        self  (for chaining)
        """
        first_col = names[0] if names else f"{prefix}_0"
        if first_col in self._df.columns and not overwrite:
            return self

        # Compute vectors for all windows. Built row by row rather than as
        # one `np.array([...])` comprehension so a window whose output has
        # the wrong length is named in the error — the comprehension form
        # raises an opaque ragged-array dtype error that says only that
        # SOMETHING was inconsistent, across a matrix that can be tens of
        # thousands of rows.
        rows = []
        expected = int(n) if n is not None else None
        for idx in self._df.index:
            vec = np.asarray(fn(self.get_window_signal(idx)))
            if vec.ndim != 1:
                raise ValueError(
                    f"fn must return a 1-D array; window {idx} gave shape {vec.shape}."
                )
            if expected is None:
                expected = vec.shape[0]
            elif vec.shape[0] != expected:
                raise ValueError(
                    f"fn returned {vec.shape[0]} value(s) for window {idx}, but "
                    f"{expected} were expected — a vector column must have a fixed width."
                )
            rows.append(vec)

        vectors = np.stack(rows)  # shape: (n_windows, n_features)
        n = vectors.shape[1]
        if names is not None and len(names) != n:
            raise ValueError(
                f"len(names)={len(names)} does not match fn output length {n}."
            )

        for i in range(n):
            col = names[i] if names else f"{prefix}_{i}"
            self._df[col] = vectors[:, i]
            self._meta[col] = {"type": "vector", "prefix": prefix, "fn": fn}

        return self

    def recompute_column(self, name: str) -> "WindowMatrix":
        """Re-run the stored function for a computed column (e.g. after signal update)."""
        if name not in self._meta:
            raise KeyError(f"Column '{name}' not found.")
        if self._meta[name]["type"] != "computed":
            raise TypeError(
                f"Column '{name}' is marked '{self._meta[name]['type']}' — there is no "
                "stored function to re-run. Note that EVERY column of a matrix "
                "restored by `load_matrix` is marked 'external', because a CSV "
                "cannot carry the callable: recompute a reloaded column by calling "
                "`add_computed_column(name, fn, overwrite=True)` with the function "
                "explicitly."
            )
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

def create_matrix(start_indices, x, timescale, fs, step=None,
                  partial_tail=False) -> WindowMatrix:
    """
    Initialise an empty WindowMatrix from a list of start indices.

    Parameters
    ----------
    start_indices : array-like of int
    x             : np.ndarray   full raw signal
    timescale     : float        window length in minutes
    fs            : float        sample rate in Hz
    step          : int, optional  step between starts, when uniform
    partial_tail  : bool         whether `start_indices` may include starts
                                 that do not admit a full window
    """
    return WindowMatrix(start_indices, x, timescale, fs, step=step,
                        partial_tail=partial_tail)

def create_matrix_at_timescale(stepfrac, x, timescale, fs,
                               partial_tail=False) -> WindowMatrix:
    """
    Initialise an empty WindowMatrix given window size and step size at timescale

    Parameters
    ----------
    stepfrac      : 0 < f <= 1 -> fraction of the window length that each new
                    starting index jumps by. 1.0 = contiguous non-overlapping
                    windows; 0.5 = 50 % overlap.
    x             : np.ndarray   full raw signal
    timescale     : float        window length in minutes
    fs            : float        sample rate in Hz
    partial_tail  : bool         include trailing starts that do not admit a
                    full window (default False)

    The tail
    --------
    The original implementation used ``np.arange(0, len(x), stepsize)``,
    which emits starts right up to ``len(x)`` — so the final
    ``window_samples / step`` windows were SHORTER than a full window.
    ``get_window_signal`` returns the short slice silently, and every
    feature function then computes on it: Catch22 and the entropy measures
    do not check length (only the random-forest path does). The result is
    that the last windows of every matrix built this way carry values that
    look comparable to the rest of their column and are not — a 3-sample
    "sample entropy" is not on the scale of a 600-sample one.

    Default is therefore to stop at the last start that admits a FULL
    window. ``partial_tail=True`` restores the old behaviour for callers
    that genuinely want the ragged tail, and the choice is recorded on the
    matrix (and in the v1 artifact) rather than being inferable only by
    re-deriving it from the last index.
    """
    if not (0 < stepfrac <= 1):
        raise ValueError(
            f"stepfrac must be in (0, 1], got {stepfrac!r} — 1.0 is contiguous "
            "non-overlapping windows, 0.5 is 50 % overlap. A stepfrac of 0 "
            "would give a step of 0 samples and an infinite index sequence."
        )

    winlength = int(fs * timescale * 60)
    if winlength < 1:
        raise ValueError(
            f"timescale={timescale} min at fs={fs} Hz gives a {winlength}-sample "
            "window — nothing to compute on."
        )

    stepsize = int(np.floor(stepfrac * winlength))
    if stepsize < 1:
        # Only reachable for a very short window and a small stepfrac, e.g.
        # winlength=4 with stepfrac=0.1 -> floor(0.4) = 0.
        raise ValueError(
            f"stepfrac={stepfrac} of a {winlength}-sample window rounds down to a "
            "0-sample step. Use a larger stepfrac or a longer timescale."
        )

    if partial_tail:
        stop = len(x)
    else:
        # +1 so a signal that is an exact multiple of the window length keeps
        # its final full window (n=600, m=600 -> one window at index 0).
        stop = len(x) - winlength + 1

    start_indices = np.arange(0, max(stop, 0), stepsize, dtype=np.int64)
    return create_matrix(start_indices, x, timescale, fs, step=stepsize,
                         partial_tail=partial_tail)


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

    What a CSV cannot tell you
    --------------------------
    ``timescale`` and ``fs`` come from the CALLER, not the file — nothing in
    a saved CSV records them. Pass the wrong ``timescale`` and every
    subsequent ``get_window_signal`` returns a wrong-length slice, silently
    and with no error. The v1 ``.npz`` format
    (``Working.database.window_matrix_store``) stores both, plus the source
    file's sha1, precisely so this class of mistake becomes impossible; this
    loader exists for the pre-v1 files in ``MATRICES/``.

    Every restored column is marked ``external`` because a CSV cannot carry
    the callable that produced it — see ``recompute_column``.
    """
    df = pd.read_csv(csv_path)

    # Accept start_idx either as a named column, as the unnamed index, or as
    # the "Unnamed: 0" column pandas writes when a frame is saved with an
    # unnamed index (several of the legacy MATRICES/ files are in this form).
    if "start_idx" in df.columns:
        df = df.set_index("start_idx")
    elif len(df.columns) and str(df.columns[0]).startswith("Unnamed: 0"):
        df = df.rename(columns={df.columns[0]: "start_idx"}).set_index("start_idx")
    else:
        df.index.name = "start_idx"

    df.index = df.index.astype(np.int64)

    # Infer the grid step from the index when it is uniform. Ambiguous for a
    # 0/1-row matrix and meaningless for a non-uniform index (e.g. one built
    # by `create_matrix_from_categories`), so it stays None in those cases
    # rather than being guessed from the first pair.
    step = None
    if len(df.index) > 1:
        diffs = np.diff(df.index.values)
        if len(np.unique(diffs)) == 1 and diffs[0] > 0:
            step = int(diffs[0])

    window_samples = int(timescale * 60 * fs)
    partial_tail = bool(len(df.index)) and int(df.index[-1]) + window_samples > len(x)

    wm = WindowMatrix(df.index.tolist(), x, timescale, fs, step=step,
                      partial_tail=partial_tail)

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
