import argparse
import os
import re
import sys
from pathlib import Path

import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

# Allow running directly from inside the cnn/ subfolder or from the project root
# ── Repo-root bootstrap ───────────────────────────────────────────────────────
# Makes `Working.*` / `Pipelines.*` importable when this file is run directly.
# Walks up to the directory containing Working/, so it survives future moves.
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))
from Working.Preprocessing.manage_data.load_data import load_raw_data

# ── Config ────────────────────────────────────────────────────────────────────
CH         = 0
FILE       = f"0.01_percent_M2_concat_fs1.mat"
FS         = 1.0          # Hz
WINDOW_MIN = 5          # minutes
OUT_DIR    = "Results/Detection/matrix_profile"

window_size = WINDOW_MIN * 60 * FS
x, t = load_raw_data(FILE,FS,matname="VECTOR")

# anomaly detection 
def detect_anomaly(x,window_size):
    from aeon.anomaly_detection.distance_based import STOMP
    stomp = STOMP(window_size=window_size)
    scores = est.fit_predict(x)
    return scores

# segmentation
def segmentation(x):
    from aeon.segmentation import ClaSPSegmenter
    clasp = ClaSPSegmenter()
    clasp.fit(data)
    clasp.fit_predict(ts)
    return clasp

# multivariate testing
# classifier
def classifier_KN(x,labels):
    from aeon.classification.distance_based import KNeighborsTimeSeriesClassifier
    X = [[[1, 2, 3, 4, 5, 6, 7]],  # 3D array example (univariate)
        [[4, 4, 4, 5, 6, 7, 3]]]  # Two samples, one channel, seven series length
    y = [0, 1]  # class labels for each sample
    X = np.array(X)
    y = np.array(y)
    clf = KNeighborsTimeSeriesClassifier(distance="dtw")
    clf.fit(X, y)  # fit the classifier on train data

    X_test = np.array([[2, 2, 2, 2, 2, 2, 2], [4, 4, 4, 4, 4, 4, 4]])
    clf.predict(X_test)  # make class predictions on new data
    return clf

# regression - forecasting method
def regression_forecast_v1(x,y,xtest,ytest):
    from aeon.regression.distance_based import KNeighborsTimeSeriesRegressor
    from aeon.datasets import load_covid_3month
    from sklearn.metrics import mean_squared_error
    X_train, y_train = load_covid_3month(split="train")
    X_test, y_test = load_covid_3month(split="test")
    reg = KNeighborsTimeSeriesRegressor(distance="dtw")
    reg.fit(X_train, y_train)  # fit the regressor on train data

    y_pred = reg.predict(X_test)  # make label predictions on new data
    y_pred[:6]

    mean_squared_error(y_test, y_pred)
    return y_pred

# clustering - gives labels to similar data
def clustering_kmeans(x,y):
    from aeon.clustering import TimeSeriesKMeans
    from aeon.datasets import load_arrow_head
    from sklearn.metrics import rand_score
    X, y = load_arrow_head()
    kmeans = TimeSeriesKMeans(n_clusters=3, metric="dtw")
    kmeans.fit(X) # fit the clusterer

    kmeans.labels_[0:10]  # cluster labels

    rand_score(y, kmeans.labels_)
    return kmeans

# similarity search
def sim_search(x,t):
    import numpy as np
    from aeon.similarity_search.series import StompMotif
    X1 = np.array([1, 1, 2, 4, 6, 6, 7])  # single series (univariate)
    X2 = np.array([0, 1, 2, 2, 4, 5, 7, 9, 4, 6])  # single series (univariate)
    top_k = StompMotif(4).fit(X1) # 4 is length of the motif to search
    distances, indexes = top_k.predict(X2, k=1)
    return distances

# catch22 - transform t series into 22 summary statistics
def transformations(x,t):
    from aeon.transformations.collection.feature_based import Catch22
    import numpy as np
    X = np.random.RandomState().random(size=(4, 1, 10))  # four cases of 10 timepoints
    c22 = Catch22(replace_nans=True)  # transform to four cases of 22 features
    c22.fit_transform(X)[0]
    return c22


# pipeline - combining catch22 and classification
def pipeline_v1(x,t):
    from aeon.datasets import load_italy_power_demand
    from aeon.transformations.collection.feature_based import Catch22
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import accuracy_score

    # Load the italy power demand dataset
    X_train, y_train = load_italy_power_demand(split="train")
    X_test, y_test = load_italy_power_demand(split="test")

    # Create and fit the pipeline
    pipe = make_pipeline(
        Catch22(replace_nans=True),
        RandomForestClassifier(random_state=42),
    )
    pipe.fit(X_train, y_train)

    # Make predictions like any other sklearn estimator
    accuracy_score(pipe.predict(X_test), y_test)
    return pipe

def grid_search_KN(x,y):
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import GridSearchCV, KFold
    from aeon.classification.distance_based import KNeighborsTimeSeriesClassifier
    from aeon.datasets import load_italy_power_demand

    # Load the italy power demand dataset
    X_train, y_train = load_italy_power_demand(split="train")
    X_test, y_test = load_italy_power_demand(split="test")

    knn = KNeighborsTimeSeriesClassifier()
    param_grid = {"n_neighbors": [1, 5], "distance": ["euclidean", "dtw"]}

    gscv = GridSearchCV(knn, param_grid, cv=KFold(n_splits=4))
    gscv.fit(X_train, y_train)

    y_pred = gscv.predict(X_test)
    y_pred[:6]

    accuracy_score(y_test, y_pred)

    gscv.best_params_
    return gscv





