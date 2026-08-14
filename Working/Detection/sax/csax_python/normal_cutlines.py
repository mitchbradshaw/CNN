# Author: Konstantinos Bountrogiannis
# Contact: kbountrogiannis@gmail.com
# Date: July 2020

import numpy as np
from scipy.stats import norm


def normal_cutlines(alphabet_size):
    """
    Compute equiprobable interval boundaries under the standard Gaussian.

    Parameters
    ----------
    alphabet_size : int — number of SAX symbols

    Returns
    -------
    cutlines : np.ndarray, shape (alphabet_size - 1,)
    """
    x = np.arange(1, alphabet_size) / alphabet_size   # 1/a, 2/a, ..., (a-1)/a
    return norm.ppf(x)
