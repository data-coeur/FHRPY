"""FHRPY baseline subpackage.

NumPy port of the FHRMA Weighted Median Filter Baseline (WMFB) algorithm
(``aamwmfb.m``) plus the acceleration/deceleration detection helpers.
"""

from .features import compute_features
from .wmfb import (
    WMFBResult,
    analyze,
    classify_decelerations,
    detect_contractions,
    simpleaddetection,
    startendlist,
    validaccident,
    wmfb,
)

__all__ = [
    "wmfb",
    "analyze",
    "detect_contractions",
    "classify_decelerations",
    "compute_features",
    "WMFBResult",
    "simpleaddetection",
    "validaccident",
    "startendlist",
]
