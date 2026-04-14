import numpy as np
import scipy.io
import glob
import os
import re

def load_start_indices(folder_name):
    # function returns the three arrays stored in the folder with the name folder_name
    # in order: array of interesting, not interesting and flag starting indexes
    # from .mat files formatted as [folder_name]_interesting_..., [folder_name]_notinteresting_..., [folder_name]_flag
    # variable in .mat file containing indexes is called idx_vec
    # also derive fs from file name and return that number too

    def find_and_load(keyword):
        minutes_folder = folder_name.removesuffix("min") + "_MINUTES"
        base = os.path.join("DATA", minutes_folder, folder_name)
        pattern = os.path.join(base, f"{folder_name}_{keyword}_*.mat")
        matches = glob.glob(pattern)
        if not matches:
            raise FileNotFoundError(f"No file found matching: {pattern}")
        mat = scipy.io.loadmat(matches[0])
        return mat["idx_vec"].flatten(), matches[0]

    interesting, path_i = find_and_load("interesting")
    notinteresting, _ = find_and_load("notinteresting")
    flag, path_f = find_and_load("flag")

    # Extract fs from filename, e.g. "10min_interesting_fs_1.00.mat" -> 1.00
    fs_match = re.search(r"fs_(\d+(?:\.\d+)?)", os.path.basename(path_i))
    fs = float(fs_match.group(1)) if fs_match else None

    return interesting, notinteresting, flag, fs

def load_raw_data(filename, fs, matname="x"):
    # returns the time-series data x stored in filename
    # also returns t, the time points based on sampling freq fs
    # supports .mat and .npy files, determined from the filename extension
    path = os.path.join("DATA", "RAW", filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".npy":
        x = np.load(path).flatten()
    elif ext == ".mat":
        x = scipy.io.loadmat(path)[matname].flatten()
    else:
        raise ValueError(f"Unsupported file type '{ext}' for '{filename}'. Expected .mat or .npy.")

    t = np.arange(len(x)) / fs
    return x, t

def cut_raw_data(filename, fs, percent, matname="x"):
    # cuts a larger dataset to the first specified 'percent'age and saves the smaller dataset to the same folder
    mat = scipy.io.loadmat(os.path.join("DATA", "RAW", filename))
    x = mat[matname].flatten()
    t = np.arange(len(x)) / fs

    cut = int(np.floor(percent * len(x)))
    x = x[:cut]
    t = t[:cut]

    filename = f"{percent}_percent_{filename}" 

    scipy.io.savemat(os.path.join("DATA","RAW",filename),{matname: x})
    return x, t 