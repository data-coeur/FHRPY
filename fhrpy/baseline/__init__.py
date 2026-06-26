"""FHRPY baseline subpackage.

NumPy port of the FHRMA Weighted Median Filter Baseline (WMFB) algorithm
(``aamwmfb.m``) plus the acceleration/deceleration detection helpers.
"""

from .wmfb import (
    WMFBResult,
    analyze,
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
    "WMFBResult",
    "simpleaddetection",
    "validaccident",
    "startendlist",
]
