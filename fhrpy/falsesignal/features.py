"""Feature construction for the FHRMA false-signal (FS) detectors.

Ports the inference-time input encoding from ``FalseSigDetectDopMHR.m`` /
``FalseSigDetectScalp.m`` (and the identically-normalized training encoding in
the ``FS training python sources``).

All signals are at 4 Hz, missing signal coded as ``0`` bpm. Normalization for a
heart-rate channel ``hr`` is::

    [(hr>0)*(hr-120)/60, hr>0]

i.e. a normalized HR (zeroed where the signal is missing) plus a present/absent
mask. ``isStage2`` is a 0/1 flag (1 during the second stage of labor).

Channel layouts
---------------
FSDop  (5 channels): ``[FHRnorm, FHRmask, MHRnorm, MHRmask, isStage2]``
FSScalp (3 channels): ``[FHRnorm, FHRmask, isStage2]`` (after :func:`remove_holds`)
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "normalize_hr",
    "build_stage2_flag",
    "build_dop_features",
    "build_scalp_features",
    "remove_holds",
]


def normalize_hr(hr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(hr_norm, mask)`` for one HR channel.

    ``hr_norm = (hr>0) * (hr - 120) / 60`` (0 where missing); ``mask = hr>0``.
    """
    hr = np.asarray(hr, dtype=np.float64)
    mask = (hr > 0).astype(np.float64)
    hr_norm = mask * (hr - 120.0) / 60.0
    return hr_norm, mask


def build_stage2_flag(n: int, stage2_start: int | None) -> np.ndarray:
    """Build the per-sample ``isStage2`` flag (length ``n``).

    ``stage2_start`` is the 4 Hz sample index at which the second stage begins
    (matching ``DB(i).Stage2_Start`` in the FS dataset). ``None`` (or a value
    past the end) means first-stage throughout.
    """
    flag = np.zeros(n, dtype=np.float64)
    if stage2_start is not None:
        s = int(stage2_start)
        if 0 <= s < n:
            flag[s:] = 1.0
        elif s < 0:
            flag[:] = 1.0
    return flag


def build_dop_features(
    fhr: np.ndarray, mhr: np.ndarray, stage2_start: int | None = None
) -> np.ndarray:
    """Build the ``5 x N`` FSDop input matrix (channels x time).

    Matches ``I=[(FHR>0).*(FHR-120)/60;FHR>0;(MHR>0).*(MHR-120)/60;MHR>0;isStage2]``.
    """
    fhr = np.asarray(fhr, dtype=np.float64)
    mhr = np.asarray(mhr, dtype=np.float64)
    n = len(fhr)
    fhr_n, fhr_m = normalize_hr(fhr)
    mhr_n, mhr_m = normalize_hr(mhr)
    stage2 = build_stage2_flag(n, stage2_start)
    return np.vstack([fhr_n, fhr_m, mhr_n, mhr_m, stage2])


def build_scalp_features(
    fhr: np.ndarray, stage2_start: int | None = None, remove_holds_first: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """Build the ``3 x N`` FSScalp input matrix (channels x time).

    Returns ``(I, fhr_cleaned)``. ``fhr_cleaned`` is the FHR after
    :func:`remove_holds` (sensor-hold removal), which the MATLAB code runs before
    feature construction.
    """
    fhr = np.asarray(fhr, dtype=np.float64).copy()
    if remove_holds_first:
        fhr = remove_holds(fhr)
    n = len(fhr)
    fhr_n, fhr_m = normalize_hr(fhr)
    stage2 = build_stage2_flag(n, stage2_start)
    return np.vstack([fhr_n, fhr_m, stage2]), fhr


def remove_holds(fhr: np.ndarray) -> np.ndarray:
    """Zero out sensor *holds*: runs of >=12 consecutive identical samples, plus
    short-tail cleanups. Faithful port of the MATLAB ``removeholds`` local
    function in ``FalseSigDetectScalp.m`` (1-based -> 0-based indices).
    """
    f = np.asarray(fhr, dtype=np.float64).copy()
    N = len(f)
    if N < 6:
        return f

    # n = find( f(1:end-4) ~= f(2:end-3) & f(2:end-3)>0 & f(2:end-3)==f(3:end-2)
    #           & f(2:end-3)==f(4:end-1) & f(2:end-3)==f(5:end) )   [1-based]
    a = f[0:N - 4]
    b = f[1:N - 3]
    c = f[2:N - 2]
    d = f[3:N - 1]
    e = f[4:N]
    cond = (a != b) & (b > 0) & (b == c) & (b == d) & (b == e)
    starts = np.nonzero(cond)[0]  # 0-based i where MATLAB i = idx+1
    for i in starts:  # MATLAB index i0 = i+1
        i0 = i + 1  # 1-based
        # h = find( f(i+2 : min(N, i+30*240)) ~= f(i+1), 1 ) [1-based offsets]
        seg_start = i0 + 2  # 1-based
        seg_end = min(N, i0 + 30 * 240)  # 1-based inclusive
        if seg_start > seg_end:
            continue
        seg = f[seg_start - 1:seg_end]  # 0-based slice
        ref = f[i0]  # f(i+1) 1-based = f[i0] 0-based
        ne = np.nonzero(seg != ref)[0]
        h = (ne[0] + 1) if ne.size else (len(seg) + 1)  # 1-based position; if none, past end
        if h >= 12:
            # f(i+1 : i+h) = 0   (1-based) -> 0-based [i0-1 ... i0+h-1)
            f[i0:i0 + h] = 0.0  # i0 (0-based) corresponds to f(i+1)..

    # n = find( f(1:end-1)>0 & f(2:end)==0 )   [1-based]
    idx = np.nonzero((f[0:N - 1] > 0) & (f[1:N] == 0))[0]  # 0-based i, MATLAB i=idx+1
    for i in idx:
        i0 = i + 1  # 1-based
        # h = find( f(i-1:-1:max(i-17,1)) ~= f(i), 1 )
        lo = max(i0 - 17, 1)  # 1-based
        # sequence f(i-1), f(i-2), ..., f(lo)  (1-based, descending)
        rng = list(range(i0 - 1, lo - 1, -1))  # 1-based indices
        ref = f[i0 - 1]  # f(i)
        h = None
        for pos, j1 in enumerate(rng, start=1):
            if f[j1 - 1] != ref:
                h = pos
                break
        if h is None:
            continue
        if h > 4:
            # f(i-h+2 : i) = 0   (1-based)
            f[(i0 - h + 2) - 1:i0] = 0.0

    # n = find( f(2:end-1)>0 & f(3:end)==0 & f(1:end-2)==0 )+1  [1-based]
    if N >= 3:
        c2 = (f[1:N - 1] > 0) & (f[2:N] == 0) & (f[0:N - 2] == 0)
        for i in np.nonzero(c2)[0]:  # 0-based k, MATLAB n = k+1 +1 = k+2
            n1 = i + 2  # 1-based n
            f[n1 - 1] = 0.0

    # n = find( f(2:end-2)>0 & f(2:end-2)==f(3:end-1) & f(4:end)==0 & f(1:end-3)==0 )+1
    if N >= 4:
        c3 = (
            (f[1:N - 2] > 0)
            & (f[1:N - 2] == f[2:N - 1])
            & (f[3:N] == 0)
            & (f[0:N - 3] == 0)
        )
        for i in np.nonzero(c3)[0]:
            n1 = i + 2  # 1-based n
            f[n1 - 1:n1 + 1] = 0.0  # f(n:n+1)=0

    # n = find( f(2:end-3)>0 & f(2:end-3)==f(3:end-2) & f(2:end-3)==f(4:end-1)
    #           & f(5:end)==0 & f(1:end-4)==0 )+1
    if N >= 5:
        c4 = (
            (f[1:N - 3] > 0)
            & (f[1:N - 3] == f[2:N - 2])
            & (f[1:N - 3] == f[3:N - 1])
            & (f[4:N] == 0)
            & (f[0:N - 4] == 0)
        )
        for i in np.nonzero(c4)[0]:
            n1 = i + 2  # 1-based n
            f[n1 - 1:n1 + 2] = 0.0  # f(n:n+2)=0

    return f
