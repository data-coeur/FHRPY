"""FHR preprocessing chain, ported from the FHRMA MATLAB toolbox.

Public entry point :func:`preprocess` mirrors ``preprocess.m``:

* merge FHR1/FHR2 with an element-wise ``max``,
* optionally zero-out operator-flagged unreliable segments,
* :func:`removesmallpart` -- clip to 50-220 bpm and drop untrustworthy short runs,
* :func:`interpol_fhr` -- linear interpolation over the remaining gaps,

and returns the same set of intermediate signals MATLAB produces.

Helper functions ported here (all 1-D, 4 Hz unless a ``srate`` is passed):
:func:`removesmallpart`, :func:`interpol_fhr`, :func:`linearinterpolation`,
:func:`avgwin`, :func:`avgsubsamp`, :func:`resamp`. The Butterworth/filtfilt
primitives live in :mod:`fhrpy.preprocess.dsp`.

Indexing note
-------------
MATLAB is 1-based; this port uses 0-based NumPy indexing. The returned ``d`` and
``f`` (first/last valid sample) are therefore **0-based indices**. Where MATLAB
code computes things like ``5*4`` (5 s at 4 Hz) the same sample counts are used.
"""

from __future__ import annotations

import numpy as np

from .dsp import butterfilt

__all__ = [
    "preprocess",
    "removesmallpart",
    "interpol_fhr",
    "linearinterpolation",
    "avgwin",
    "avgsubsamp",
    "resamp",
]


def linearinterpolation(x, y, xx) -> np.ndarray:
    """Piecewise-linear interpolation/extrapolation (port of ``linearinterpolation.m``).

    Same calling convention as MATLAB ``spline``: given control points
    ``(x, y)`` (``x`` strictly increasing), evaluate the piecewise-linear curve
    at the query points ``xx``. Points below ``x[0]`` use the first segment's
    slope (extrapolation); points ``>= x[-1]`` use the last segment's slope.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    y = np.asarray(y, dtype=np.float64).ravel()
    xx = np.asarray(xx, dtype=np.float64)
    yy = np.zeros_like(xx, dtype=np.float64)

    # Below the first control point: extrapolate with the first segment slope.
    a = (y[1] - y[0]) / (x[1] - x[0])
    b = y[0] - a * x[0]
    mask = xx < x[0]
    yy[mask] = a * xx[mask] + b

    for i in range(len(x) - 1):
        a = (y[i + 1] - y[i]) / (x[i + 1] - x[i])
        b = y[i] - a * x[i]
        mask = (xx >= x[i]) & (xx < x[i + 1])
        yy[mask] = a * xx[mask] + b

    # At/after the last control point: extrapolate with the last segment slope
    # (a, b retain the final loop iteration's values, matching MATLAB).
    mask = xx >= x[-1]
    yy[mask] = a * xx[mask] + b
    return yy


def removesmallpart(fhr) -> np.ndarray:
    """Remove aberrant / untrustworthy samples (port of ``removesmallpart.m``).

    1. Clip out-of-range values: ``fhr > 220 | fhr < 50`` -> 0 (missing).
    2. Drop valid runs shorter than ``5*4 = 20`` samples (< 5 s).
    3. Drop valid runs shorter than ``30*4 = 120`` samples (< 30 s) that are a
       large jump (> 25 bpm) away from both neighbouring valid samples.

    Operates on a copy; missing signal is coded as 0.
    """
    fhr = np.asarray(fhr, dtype=np.float64).copy()
    n_total = len(fhr)
    fhr[(fhr > 220) | (fhr < 50)] = 0.0

    def _zero_to_pos_starts(sig):
        # MATLAB: find(FHR(1:end-1)==0 & FHR(2:end)>0)+1  (1-based) -> 0-based idx.
        return np.where((sig[:-1] == 0) & (sig[1:] > 0))[0] + 1

    # --- pass 1: remove valid runs < 5 s ---
    starts = _zero_to_pos_starts(fhr)
    for n in starts:
        tail = np.where(fhr[n:] == 0)[0]
        if tail.size == 0:
            continue
        f = tail[0] + 1  # MATLAB find(...,'first') is 1-based -> length of run
        if f < 5 * 4:
            fhr[n : min(n + f + 1, n_total)] = 0.0

    # --- pass 2: remove valid runs < 30 s that are big jumps on both sides ---
    starts = _zero_to_pos_starts(fhr)
    for n in starts:
        tail = np.where(fhr[n:] == 0)[0]
        if tail.size == 0:
            continue
        f = tail[0] + 1
        if f < 30 * 4:
            lastvalid_idx = np.where(fhr[:n] > 0)[0]
            nextvalid_rel = np.where(fhr[n + f :] > 0)[0]
            if lastvalid_idx.size == 0 or nextvalid_rel.size == 0:
                continue  # mirrors MATLAB try/catch swallowing edge cases
            lastvalid = lastvalid_idx[-1]
            nextvalid = nextvalid_rel[0] + n + f
            # MATLAB uses FHR(n) and FHR(n+f-2): 1-based -> 0-based n-1, n+f-3.
            left = fhr[n - 1]
            right = fhr[n + f - 3] if (n + f - 3) >= 0 else fhr[n - 1]
            if (left - fhr[lastvalid] < -25) and (right - fhr[nextvalid] < -25):
                fhr[n : min(n + f + 1, n_total)] = 0.0
            if (left - fhr[lastvalid] > 25) and (right - fhr[nextvalid] > 25):
                fhr[n : min(n + f + 1, n_total)] = 0.0

    return fhr


def interpol_fhr(fhr):
    """Linear interpolation over missing (0/NaN) parts (port of ``interpolFHR.m``).

    Returns ``(fhri, d, f)`` where ``fhri`` is gap-free, ``d`` is the first valid
    sample index and ``f`` is the last valid sample index (both **0-based**).
    The leading gap is filled by holding the first valid value; the trailing gap
    by holding the last valid value.
    """
    fhr = np.asarray(fhr, dtype=np.float64).copy()
    length = len(fhr)
    valid = (fhr > 0) & (~np.isnan(fhr))

    first = np.where(valid)[0]
    if first.size == 0:
        # No valid data at all: mirror MATLAB returning the array unchanged.
        return fhr, 0, length - 1
    n = first[0]
    fhr[: n + 1] = fhr[n]
    d = n

    # MATLAB loops with 1-based n; we keep a 0-based running pointer.
    while n is not None and n < length - 1:
        miss = np.where((fhr[n:] == 0) | np.isnan(fhr[n:]))[0]
        if miss.size == 0:
            break
        gap_start = miss[0] + n  # first missing sample at/after n
        rest = np.where((fhr[gap_start:] > 0) & (~np.isnan(fhr[gap_start:])))[0]
        if rest.size == 0:
            n = None
            break
        nf = rest[0] + gap_start  # next valid sample
        # MATLAB: FHR(n-1:nf) = linspace(FHR(n-1), FHR(nf), nf-n+2)
        # here gap_start is MATLAB's n; fill inclusive [gap_start-1 .. nf].
        fhr[gap_start - 1 : nf + 1] = np.linspace(
            fhr[gap_start - 1], fhr[nf], nf - gap_start + 2
        )
        n = nf

    valid = (fhr > 0) & (~np.isnan(fhr))
    f = np.where(valid)[0][-1]
    fhr[f:] = fhr[f]
    return fhr, d, f


def avgwin(x, winl) -> np.ndarray:
    """Centred moving average over ``[i-winl, i+winl]`` clamped to edges.

    Port of ``avgwin.m``. Window length varies near the borders (mean of the
    available samples), so this is *not* a fixed-window convolution.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    n = len(x)
    csum = np.concatenate([[0.0], np.cumsum(x)])
    i = np.arange(n)
    lo = np.maximum(0, i - winl)
    hi = np.minimum(n - 1, i + winl)
    counts = hi - lo + 1
    sums = csum[hi + 1] - csum[lo]
    return sums / counts


def avgsubsamp(x, factor) -> np.ndarray:
    """Non-overlapping block-mean downsample by ``factor`` (port of ``avgsubsamp.m``).

    ``y[i] = mean(x[i*factor : (i+1)*factor])`` for ``i`` in
    ``0 .. floor(len(x)/factor)-1``. A trailing partial block is dropped.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    ny = len(x) // factor
    if ny == 0:
        return np.zeros(0)
    return x[: ny * factor].reshape(ny, factor).mean(axis=1)


def resamp(x, factor, length, lin=None) -> np.ndarray:
    """Resample by ``factor`` then pad to ``length`` with the last value.

    Port of ``resamp.m``. When ``lin`` is provided (truthy), uses piecewise
    linear up-sampling that inserts ``factor`` points between consecutive
    samples (MATLAB's explicit ``linspace`` branch). Otherwise falls back to
    MATLAB ``interp`` (here approximated with FIR interpolation via
    ``scipy.signal.resample_poly`` -- see parity notes).
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    if lin is not None:
        y = np.zeros((len(x) - 1) * factor)
        for i in range(len(x) - 1):
            pt = np.linspace(x[i], x[i + 1], factor + 1)
            y[i * factor : (i + 1) * factor] = pt[1:]
    else:
        from scipy.signal import resample_poly

        try:
            y = resample_poly(x, factor, 1, padtype="line")
        except TypeError:  # pragma: no cover - very old SciPy
            y = resample_poly(x, factor, 1)
    if len(y) < length:
        y = np.concatenate([y, np.full(length - len(y), y[-1])])
    else:
        y = y[:length]
    return y


def preprocess(fhr1, fhr2, toco=None, unreliable_signal=None):
    """Standard FHR preprocessing (port of ``preprocess.m``).

    Parameters
    ----------
    fhr1, fhr2:
        The two FHR sensor channels at 4 Hz (bpm; missing coded as 0).
    toco:
        Optional TOCO channel (returned unchanged).
    unreliable_signal:
        Optional ``(k, 2)`` array of operator-flagged unreliable intervals **in
        minutes** ``[start, end]``. Each is zeroed via ``round(start*240+1) ..
        round(end*240)`` (1-based in MATLAB; converted to 0-based here).

    Returns
    -------
    fhri : np.ndarray
        Gap-free FHR (linear interpolation), suitable for analysis.
    fhr : np.ndarray
        Merged FHR with ``NaN`` on the missing samples.
    toco : np.ndarray
        The TOCO channel unchanged (zeros if not supplied).
    d, f : int
        First / last valid sample indices (0-based).
    """
    fhr1 = np.asarray(fhr1, dtype=np.float64).ravel()
    fhr2 = np.asarray(fhr2, dtype=np.float64).ravel()
    fhr = np.maximum(fhr1, fhr2)

    if unreliable_signal is not None:
        us = np.asarray(unreliable_signal, dtype=np.float64).reshape(-1, 2)
        for r0, r1 in us:
            # MATLAB: FHR(round(r1*240+1):round(r2*240))=0  (1-based inclusive).
            start = int(round(r0 * 240 + 1)) - 1  # -> 0-based
            stop = int(round(r1 * 240))  # 1-based inclusive == 0-based exclusive
            start = max(0, start)
            stop = min(len(fhr), stop)
            if stop > start:
                fhr[start:stop] = 0.0

    fhr = removesmallpart(fhr)
    fhri, d, f = interpol_fhr(fhr)

    fhr = fhr.copy()
    fhr[fhr == 0] = np.nan

    if toco is None:
        toco = np.zeros(len(fhr))
    else:
        toco = np.asarray(toco, dtype=np.float64).ravel()

    return fhri, fhr, toco, d, f


# Backwards/parity-friendly alias matching the helper's MATLAB name.
interpolFHR = interpol_fhr
