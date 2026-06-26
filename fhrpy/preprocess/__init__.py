"""FHRPY preprocessing subpackage.

NumPy port of the FHRMA MATLAB preprocessing chain and shared DSP primitives:
FHR1/FHR2 merge, range clipping, small-part removal, linear gap interpolation,
and the Butterworth / zero-phase ``filtfilt`` building blocks.
"""

from .dsp import butter_coeffs, butterfilt, filtfilt, lfilter_zi
from .preprocess import (
    avgsubsamp,
    avgwin,
    interpolFHR,
    interpol_fhr,
    linearinterpolation,
    preprocess,
    removesmallpart,
    resamp,
)

__all__ = [
    "preprocess",
    "removesmallpart",
    "interpol_fhr",
    "interpolFHR",
    "linearinterpolation",
    "avgwin",
    "avgsubsamp",
    "resamp",
    "butterfilt",
    "filtfilt",
    "lfilter_zi",
    "butter_coeffs",
]
