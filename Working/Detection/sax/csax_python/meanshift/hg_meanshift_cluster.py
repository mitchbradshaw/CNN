# Modified version of:
#   Mean Shift Clustering (c) 2006 Bart Finkston
#   meanshift_matlab (c) 2015 Han Gong, University of East Anglia
#
# Main modification: Epanechnikov kernel + minor algorithmic changes.
#
# Author: Konstantinos Bountrogiannis
# Contact: kbountrogiannis@gmail.com
# Date: July 2022

import numpy as np
from scipy.stats import iqr

from .gaussfun   import gaussfun
from .epanechfun import epanechfun


def hg_meanshift_cluster(data_pts, kernel, multi_factor=1.0):
    """
    Mean-Shift clustering with a chosen kernel.

    Parameters
    ----------
    data_pts     : array-like, shape (numDim, numPts) or (numPts,) for 1-D data
    kernel       : str — 'flat', 'gaussian', or 'epanechnikov'
    multi_factor : float — bandwidth multiplier (default 1.0)

    Returns
    -------
    clust_cent         : np.ndarray, shape (numDim, numClust) — cluster centres
    data2cluster       : np.ndarray, shape (numPts,)          — cluster index per point (0-based)
    cluster2data_list  : list of np.ndarray                   — point indices per cluster
    """
    data_pts = np.atleast_2d(np.asarray(data_pts, dtype=float))
    if data_pts.shape[0] > data_pts.shape[1]:
        # Ensure (numDim, numPts) orientation
        data_pts = data_pts.T

    num_dim, num_pts = data_pts.shape

    # ── Bandwidth selection ──────────────────────────────────────────────────
    std_per_dim = np.std(data_pts, axis=1, ddof=1)
    iqr_per_dim = iqr(data_pts, axis=1) / 1.34
    sig = np.minimum(std_per_dim, iqr_per_dim)
    zero_mask = sig == 0
    if np.any(zero_mask):
        sig[zero_mask] = np.maximum(std_per_dim, iqr_per_dim)[zero_mask]
    # Scalar sigma for 1-D case
    sig = float(sig.ravel()[0]) if num_dim == 1 else sig

    if kernel == 'flat':
        C          = 2.3449
        bandwidth  = sig * C * num_pts ** (-1 / 5) + np.finfo(float).eps
        neigh_rad  = bandwidth ** 2
        kmean      = lambda x, d: np.mean(x, axis=1)
    elif kernel == 'gaussian':
        C          = 0.9686
        bandwidth  = multi_factor * sig * C * num_pts ** (-1 / 7) + np.finfo(float).eps * (sig == 0)
        neigh_rad  = bandwidth ** 2
        kmean      = lambda x, d: gaussfun(x, d, bandwidth)
    elif kernel == 'epanechnikov':
        C          = 1.5232
        bandwidth  = sig * C * num_pts ** (-1 / 7) + np.finfo(float).eps * (sig == 0)
        neigh_rad  = bandwidth ** 2
        kmean      = lambda x, d: epanechfun(x, d, bandwidth)
    else:
        raise ValueError(f"Unknown kernel '{kernel}'. Choose 'flat', 'gaussian', or 'epanechnikov'.")

    stop_thresh = 1e-3 * neigh_rad

    # ── Initialise ──────────────────────────────────────────────────────────
    been_visited  = np.zeros(num_pts, dtype=bool)
    cluster_votes = []          # list of (numPts,) uint16 arrays, one per cluster
    clust_cent    = []          # list of (numDim,) arrays
    clust_membs   = []          # list of index arrays

    init_pt_inds = np.arange(num_pts)

    while len(init_pt_inds) > 0:
        num_init = len(init_pt_inds)

        # Pick a random seed point
        rand_idx = int(np.ceil((num_init - 1e-6) * np.random.rand())) - 1
        rand_idx = max(0, rand_idx)
        st_ind   = init_pt_inds[rand_idx]

        my_mean    = data_pts[:, st_ind].copy()
        my_members = np.array([], dtype=int)
        this_cluster_votes = np.zeros(num_pts, dtype=np.uint16)

        while True:
            sq_dist = np.sum((my_mean[:, None] - data_pts) ** 2, axis=0)  # (numPts,)
            in_inds = np.where(sq_dist < neigh_rad)[0]

            if len(in_inds) == 0:
                my_old_mean = my_mean.copy()
            else:
                this_cluster_votes[in_inds] += 1
                my_old_mean = my_mean.copy()
                my_mean     = kmean(data_pts[:, in_inds], sq_dist[in_inds])
                my_members  = np.union1d(my_members, in_inds)
                been_visited[my_members] = True

            if np.linalg.norm(my_mean - my_old_mean) <= stop_thresh:
                # Check for merge with existing cluster
                merge_with = -1
                for c_n in range(len(clust_cent)):
                    dist_to_other = np.linalg.norm(my_mean - clust_cent[c_n]) ** 2
                    if dist_to_other < neigh_rad / 2 and len(clust_cent) >= 2:
                        merge_with = c_n
                        break

                if merge_with >= 0:
                    nc = len(my_members)
                    no = len(clust_membs[merge_with])
                    w  = np.array([nc, no]) / (nc + no)
                    clust_membs[merge_with]   = np.union1d(clust_membs[merge_with], my_members)
                    clust_cent[merge_with]    = my_mean * w[0] + my_old_mean * w[1]
                    cluster_votes[merge_with] = cluster_votes[merge_with] + this_cluster_votes
                else:
                    clust_cent.append(my_mean.copy())
                    clust_membs.append(my_members.copy())
                    cluster_votes.append(this_cluster_votes.copy())

                break

        init_pt_inds = np.where(~been_visited)[0]

    # ── Assign each point to the cluster with the most votes ─────────────────
    if not cluster_votes:
        return np.array([]).reshape(num_dim, 0), np.zeros(num_pts, dtype=int), []

    votes_matrix = np.array(cluster_votes, dtype=int)   # (numClust, numPts)
    data2cluster = np.argmax(votes_matrix, axis=0)       # (numPts,) 0-indexed

    clust_cent_arr = np.column_stack(clust_cent)         # (numDim, numClust)

    # Sort cluster centres (ascending) so cutlines computed downstream are ordered
    sort_order     = np.argsort(clust_cent_arr[0])
    clust_cent_arr = clust_cent_arr[:, sort_order]

    cluster2data_list = [
        np.where(data2cluster == c)[0] for c in range(len(clust_cent))
    ]

    return clust_cent_arr, data2cluster, cluster2data_list
