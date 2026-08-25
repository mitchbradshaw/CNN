"""
drop_motifs
============
Spike-drop motif discovery: the sharp negative-going fall that follows the
rise of a spike, located by TREND CLASSIFICATION rather than by
nearest-neighbour search.

This is the complement to `Working/Detection/matrix_profiling`, not a
replacement for it. Matrix-profile discovery answers "which whole
subsequences recur"; this answers "does the rise-then-drop dynamic itself
have a small vocabulary of shapes". The two find different things on the
same recording and the difference is the point.

Three modules, split along the one boundary that matters:

  detect.py  - detrend, dSAX trend encoding, UP-region walk, drop-onset
               scan, event windowing. Pure numpy/scipy.
  cluster.py - shape distance, linkage, roughness QC, cluster composition.
               Pure numpy/scipy.
  store.py   - the event table, the snippet store and the run manifest.
               Pure numpy/pandas.

None of them import a plotting library, which is what lets a detection run
happen on a compute node and what makes a figure reproducible from storage
alone (CLAUDE.md rule 1).
"""
