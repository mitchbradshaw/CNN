"""
run_matrix_profile.py
---------------------
Loads M2_aug_concat_fs1.mat, computes the matrix profile using stumpy's
GPU-accelerated gpu_stump (falls back to CPU stump if no GPU is found),
and saves the result to DATA/MATRIX_PROFILE/.

Usage (called by mp_job.sh):
    python run_matrix_profile.py
"""

import os
import sys
import time
import numpy as np
import scipy.io
import stumpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from manage_data.load_data import load_raw_data

# ── Config ────────────────────────────────────────────────────────────────────
CH         = 2
FILE       = f"M2_concat_fs1_CH{CH}.npy"
FS         = 1.0          # Hz
WINDOW_MIN = 50          # minutes
OUT_DIR    = "matrix_profiling/results"

# ── Load data ─────────────────────────────────────────────────────────────────
def load_matrix_data(FILE, FS, WINDOW_MIN):
    # ── Derived 
    m = int(WINDOW_MIN * 60 * FS)   # 600 samples

    print(f"Loading {FILE} ...")
    x, t = load_raw_data(FILE, FS)
    print(f"  n = {len(x):,} samples  |  m = {m} samples  |  duration = {len(x)/FS/3600:.2f} h")
    return x, t, m

# ── Compute matrix profile ────────────────────────────────────────────────────
def matrix_profile(x,t,m):
    print(f"\nComputing matrix profile (m={m}) ...")
    t0 = time.time()
    GPUuse = 0

    try:
        import numba.cuda
        if numba.cuda.is_available():
            all_gpu_devices = [device.id for device in numba.cuda.list_devices()]
            print("  GPU detected — using stumpy.gpu_stump")
            profile = stumpy.gpu_stump(x, m=m, device_id=all_gpu_devices)
            GPUuse = 1
        else:
            raise RuntimeError("no GPU")
    except Exception as e:
        print(f"  GPU unavailable ({e}) — falling back to stumpy.stump (CPU)")
        profile = stumpy.stump(x, m=m)

    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s ({elapsed/60:.2f} min)")

    mp   = profile[:, 0].astype(np.float32)   # distances
    mpi  = profile[:, 1].astype(np.int32)     # nearest-neighbour indices
    t_mp = t[:len(mp)].astype(np.float32)     # time stamps
    return mp, mpi, t_mp, GPUuse

# ── Time Series Chains ──────────────────────────────────────────────────────────────────────
def compute_chains(x,t,m):
    mp, mpi, t_mp = matrix_profile(x,t,m)
    return stumpy.allc(mp.left_I_, mp.right_I_)

# ── Save ──────────────────────────────────────────────────────────────────────
def save_matrix_profile(mp,mpi,t_mp,GPUuse,FILE,WINDOW_MIN,OUT_DIR):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{GPUuse}_mp_{os.path.splitext(FILE)[0]}_WIN{WINDOW_MIN}.npz")
    np.savez_compressed(out_path, mp=mp, mpi=mpi, t_mp=t_mp,
                        m=np.array(m), fs=np.array(FS), window_min=np.array(WINDOW_MIN))
    print(f"\nSaved → {out_path}")
    print(f"  mp   shape: {mp.shape}")
    print(f"  mpi  shape: {mpi.shape}")
    print(f"  t_mp shape: {t_mp.shape}")





x, t, m = load_matrix_data(FILE,FS,WINDOW_MIN)
mp, mpi, t_mp, GPUuse = matrix_profile(x,t,m)
save_matrix_profile(mp,mpi,t_mp,GPUuse,FILE,WINDOW_MIN,OUT_DIR)
