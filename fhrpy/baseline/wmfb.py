"""Weighted Median Filter Baseline (WMFB) -- port of ``aamwmfb.m``.

Reference: Boudet, Houze de l'Aulnoit, Demailly, Peyrodie, Beuscart, Houze de
l'Aulnoit -- *Fetal heart rate baseline computation with a weighted median
filter*, Computers in Biology and Medicine, 2019.

Public API
----------
* :func:`wmfb` -- the full baseline pipeline. Given a gap-free FHR at 4 Hz
  (``FHRi`` from :func:`fhrpy.preprocess.preprocess`), returns the baseline at
  4 Hz plus acceleration / deceleration / false-event segment lists.
* :func:`analyze` -- convenience wrapper running preprocessing + WMFB on a loaded
  :class:`fhrpy.io.FHRRecord`.
* :func:`simpleaddetection` -- the trivial reference A/D detector (``simpleaddetection.m``).
* :func:`validaccident`, :func:`startendlist` -- detection helpers.

All ``srate=240`` values are preserved verbatim from MATLAB (240 = 4 Hz x 60;
cutoffs are in cycles/min). Accel/decel segments are returned in **seconds**
as lists of ``(start, end)`` tuples (the ``max`` peak sample is also available
through the lower-level functions).
"""

from __future__ import annotations

import numpy as np

from ..preprocess.dsp import butterfilt, butter_coeffs, filtfilt

__all__ = [
    "wmfb",
    "analyze",
    "simpleaddetection",
    "validaccident",
    "startendlist",
    "WMFBResult",
]


# Logistic coefficients for the per-sample trust weight P (aamwmfb.m line 60).
_Q = np.array([-2.4744, 0.0266, 0.0413, 0.0105, 0.0036], dtype=np.float64)
_SRATE = 240.0
_DECIM = 24


def _sigmoid(x):
    # MATLAB writes exp(x)/(1+exp(x)); use the numerically stable expit form.
    return np.where(x >= 0, 1.0 / (1.0 + np.exp(-x)), np.exp(x) / (1.0 + np.exp(x)))


# ---------------------------------------------------------------------------
# enveloppe (local function in aamwmfb.m)
# ---------------------------------------------------------------------------
def _enveloppe(x, srate, f0, f1, return_band=False):
    """Band envelope via FFT band-selection (port of ``enveloppe`` in aamwmfb.m).

    Returns the analytic-magnitude envelope ``y = 2*abs(ifft(banded))``. When
    ``return_band`` is set, also returns the (real) band-passed ``x``.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    fftx = np.fft.fft(x)
    n = len(x)
    siglen = n / srate
    # MATLAB 1-based sample indices -> 0-based.
    firstsamp = int(round(f0 * siglen + 1))  # 1-based
    lastsamp = int(round(f1 * siglen + 1))  # 1-based, inclusive

    ffty = np.zeros(n, dtype=complex)
    band = fftx[firstsamp - 1 : lastsamp]  # MATLAB fftx(firstsamp:lastsamp)
    width = lastsamp - firstsamp  # number of bins minus 1

    if width % 2 == 1:
        # MATLAB: ffty([end-(L-3)/2:end  1:(3+L)/2]) where L = lastsamp-firstsamp
        k = (width - 3) // 2
        m = (3 + width) // 2
        idx = np.concatenate([np.arange(n - 1 - k, n), np.arange(0, m)])
    else:
        k = (width - 2) // 2
        m = (2 + width) // 2
        idx = np.concatenate([np.arange(n - 1 - k, n), np.arange(0, m)])
    ffty[idx] = band

    y = 2.0 * np.abs(np.fft.ifft(ffty))

    if return_band:
        fx = fftx.copy()
        # MATLAB zeros bins [1:firstsamp-1, lastsamp+1:end-lastsamp+1, end-firstsamp+2:end]
        fx[: firstsamp - 1] = 0
        fx[lastsamp : n - lastsamp + 1] = 0
        fx[n - firstsamp + 1 :] = 0
        return y, np.real(np.fft.ifft(fx))
    return y


# ---------------------------------------------------------------------------
# MATLAB-equivalent decimate / interp for the weighted-median bank
# ---------------------------------------------------------------------------
def _matlab_decimate(x, r):
    """Approximate MATLAB ``decimate(x, r)`` (default IIR / Chebyshev-I path).

    MATLAB default: 8th-order Chebyshev type I low-pass (0.05 dB ripple,
    cutoff ``0.8/r`` of Nyquist), applied with ``filtfilt``, then ``x(1:r:end)``.
    """
    from scipy.signal import cheby1

    x = np.asarray(x, dtype=np.float64).ravel()
    b, a = cheby1(8, 0.05, 0.8 / r)
    y = filtfilt(b, a, x)
    return y[::r]


def _matlab_interp(x, r, length_out=None):
    """Approximate MATLAB ``interp(x, r)`` (FIR interpolation, l=4, alpha=0.5).

    MATLAB designs a length ``2*l*r+1`` low-pass FIR (l=4) with gain ``r`` and
    convolves the zero-stuffed signal, compensating the FIR group delay. We use
    ``scipy.signal.resample_poly`` with a matching Kaiser-windowed FIR, which is
    a close (not necessarily bit-exact) equivalent -- see parity notes.
    """
    from scipy.signal import resample_poly

    x = np.asarray(x, dtype=np.float64).ravel()
    try:
        # padtype='line' extends with the edge slope, avoiding the spurious
        # droop-to-zero that the default zero-padding produces at the tail --
        # closer to MATLAB ``interp`` edge behaviour. (Requires SciPy >= 1.6.)
        y = resample_poly(x, r, 1, padtype="line")
    except TypeError:  # pragma: no cover - very old SciPy
        y = resample_poly(x, r, 1)
    if length_out is not None:
        if len(y) < length_out:
            y = np.concatenate([y, np.full(length_out - len(y), y[-1])])
        else:
            y = y[:length_out]
    return y


# ---------------------------------------------------------------------------
# medgliss -- the weighted sliding-median core (aamwmfb.m lines 128-185)
# ---------------------------------------------------------------------------
def _medgliss(X, win, coef, decim, X2=None, p2=None, c=None):
    """Weighted sliding-median filter (port of ``medgliss``).

    Parameters
    ----------
    X : array
        Input signal at 4 Hz.
    win : array
        Triangular position weights (length 401 in WMFB), possibly raised to a
        power by the caller.
    coef : array
        Per-sample trust weights ``P`` (same length as ``X``).
    decim : int
        Decimation factor (24 in WMFB).
    X2, p2, c :
        Optional attraction to a previous baseline ``X2`` with weight ``c`` and
        per-sample trust ``p2``.

    Returns
    -------
    Y : array
        The baseline estimate at 4 Hz (length of ``X``).
    mp : array
        Per-sample mean weight (length of ``X``).
    """
    X = np.asarray(X, dtype=np.float64).ravel()
    win = np.asarray(win, dtype=np.float64).ravel()
    coef = np.asarray(coef, dtype=np.float64).ravel()

    # Anti-alias low-pass (order 8 zero-phase) then decimate.
    Xd = butterfilt(X, _SRATE, 0, _SRATE / 2.2 / decim, 8, True)
    Xd = Xd[::decim]
    have_attract = X2 is not None
    if have_attract:
        X2d = np.asarray(X2, dtype=np.float64).ravel()[::decim]
        p2 = np.asarray(p2, dtype=np.float64).ravel()

    coefd = _matlab_decimate(coef, decim)
    coefd = coefd * (coefd > 0)

    L = len(Xd)
    # coefd / X2d / mp(decimated) must all be length L; guard tiny mismatches.
    if len(coefd) < L:
        coefd = np.concatenate([coefd, np.full(L - len(coefd), coefd[-1])])
    coefd = coefd[:L]
    midwin = (len(win) - 1) // 2

    Yd = np.zeros(L)
    mp = np.zeros(L)

    # --- tolerance band: local 10-min min/max envelopes (lines 140-149) ---
    mintolerated = np.zeros(L)
    maxtolerated = 255.0 * np.ones(L)
    step = int(_SRATE / 2 / decim)  # = 5
    span = int(10 * _SRATE / decim)  # = 100
    i = 0
    # MATLAB: for i=1:step:length(Xd)-span  (1-based); twin=i:i+span inclusive.
    last = L - span  # MATLAB loop upper bound (1-based) -> 0-based stop is L-span
    while i < last:
        twin = np.arange(i, min(i + span + 1, L))
        mi = Xd[twin].min()
        ma = Xd[twin].max()
        sel = twin[mintolerated[twin] <= mi]
        mintolerated[sel] = mi
        sel = twin[maxtolerated[twin] <= ma]
        maxtolerated[sel] = ma
        i += step

    # --- main weighted-median loop ---
    for i in range(L):
        if i < midwin:
            mwm = i
            mwp = min(max(mwm, (midwin - mwm) // 2), L - 1 - i)
        elif (L - 1 - i) < midwin:
            mwp = L - 1 - i
            mwm = min(max(mwp, (midwin - mwp) // 2), i)
        else:
            mwm = midwin
            mwp = midwin

        lo = i - mwm
        hi = i + mwp  # inclusive
        Xpoints = Xd[lo : hi + 1]
        wseg = win[midwin - mwm : midwin + mwp + 1]
        inband = (Xpoints >= mintolerated[i]) & (Xpoints <= maxtolerated[i])
        coefwin = coefd[lo : hi + 1] * wseg * inband
        s = coefwin.sum()
        scoef = wseg.sum()

        if have_attract:
            Xpoints = np.concatenate([Xpoints, [X2d[i]]])
            extra = max(0.0, c * p2[i] * scoef - s)
            coefwin = np.concatenate([coefwin, [extra]])
            s = coefwin.sum()

        order = np.argsort(Xpoints, kind="stable")
        cw = np.cumsum(coefwin[order])
        # First index whose cumulative weight reaches half the total.
        k = np.searchsorted(cw, s / 2.0, side="left")
        if k >= len(order):
            k = len(order) - 1
        Yd[i] = Xpoints[order[k]]
        mp[i] = s / scoef if scoef != 0 else 0.0

    Y = _matlab_interp(Yd, decim, len(X))
    mp_full = _matlab_interp(mp, decim, len(X))
    return Y, mp_full


# ---------------------------------------------------------------------------
# accident detection helpers (aamwmfb.m + validaccident.m + startendlist.m)
# ---------------------------------------------------------------------------
def startendlist(binsig):
    """Runs of 1s in a binary signal -> ``(2, k)`` ``[start; end]`` (0-based).

    Port of ``startendlist.m`` (returns 0-based inclusive sample indices).
    """
    b = np.asarray(binsig).astype(bool).astype(int)
    padded = np.concatenate([[0], b, [0]])
    starts = np.where((padded[1:] != 0) & (padded[:-1] == 0))[0]
    ends = np.where((padded[1:] == 0) & (padded[:-1] != 0))[0] - 1
    return np.vstack([starts, ends])


def _accidentcandidat(s1, s2, seuil):
    """Regions where ``s1 - s2 > seuil`` with peak sample (aamwmfb ``accidentcandidat``).

    Returns a ``(3, k)`` array ``[start; end; peak]`` of 0-based sample indices.
    """
    s1 = np.asarray(s1, dtype=np.float64)
    s2 = np.asarray(s2, dtype=np.float64)
    binsig = (s1 - s2) > seuil
    se = startendlist(binsig)
    if se.shape[1] == 0:
        return np.zeros((3, 0), dtype=int)
    peaks = np.zeros(se.shape[1], dtype=int)
    diff = s1 - s2
    for i in range(se.shape[1]):
        a, b = se[0, i], se[1, i]
        peaks[i] = a + int(np.argmax(diff[a : b + 1]))
    return np.vstack([se, peaks])


def _adjustduration(startend, s):
    """Refine candidate boundaries to zero-crossings, splitting back-to-back events.

    Port of ``adjustduration`` (aamwmfb.m lines 89-113). ``startend`` is a
    ``(3, k)`` 0-based ``[start; end; peak]`` array; ``s`` is the deviation
    signal (FHRi - baseline for accelerations). Returns the refined ``(3, k')``.
    Operates in 4 Hz samples.
    """
    s = np.asarray(s, dtype=np.float64)
    cols = [startend[:, i].astype(int).copy() for i in range(startend.shape[1])]
    i = 0
    while i < len(cols):
        start, end, peak = cols[i]
        # newend: shrink end back to last sample before s<0 after the peak.
        # MATLAB: newend = peak-1 + find([s(peak:end_) < 0, -1], 1, 'first')
        seg = s[peak : end + 1]
        neg = np.where(seg < 0)[0]
        first_neg = neg[0] if neg.size > 0 else len(seg)  # the appended -1 sentinel
        newend = peak + first_neg  # 0-based; (peak-1)+(first_neg+1) in 1-based math

        if (end - newend) >= 15 * 4:
            sub = s[newend + 1 : end + 1]
            if sub.size > 0:
                m = sub.max()
                imax = int(np.argmax(sub))
                if m > 0:
                    cols.append(np.array([newend + 1, end, newend + 1 + imax], dtype=int))

        new_end_final = newend - 1

        # newdeb: shrink start forward to last sample where s<0 before the peak.
        # MATLAB: newdeb = start-1 + find([-1, s(start:peak) < 0], 1, 'last')
        # The prepended -1 sits at 1-based position 1; s(start:peak)<0 elements
        # follow. find(...,'last') (1-based) -> 0-based newdeb below.
        seg2 = s[start : peak + 1]
        neg2 = np.where(seg2 < 0)[0]
        if neg2.size > 0:
            # last negative at 0-based offset neg2[-1] within seg2 -> MATLAB
            # concatenated 1-based pos (neg2[-1]+1)+1; newdeb0 = start + neg2[-1].
            newdeb = start + neg2[-1]
        else:
            # only the sentinel matched -> MATLAB find -> 1 -> newdeb1 = start;
            # newdeb0 = start - 1.
            newdeb = start - 1

        if (newdeb - start) >= 15 * 4:
            sub = s[start:newdeb]
            if sub.size > 0:
                m = sub.max()
                imax = int(np.argmax(sub))
                if m > 0:
                    cols.append(np.array([start, newdeb - 1, start + imax], dtype=int))

        cols[i] = np.array([newdeb, new_end_final, peak], dtype=int)
        i += 1

    if not cols:
        return np.zeros((3, 0), dtype=int)
    return np.vstack(cols).T


def validaccident(accidents, varsig, durationthreshold, amplitudethreshold):
    """Keep events meeting duration and amplitude thresholds (port of ``validaccident.m``).

    ``accidents`` is a ``(>=2, k)`` array whose rows 0/1 are start/end **in
    seconds**. ``varsig`` is the deviation signal at 4 Hz. Returns
    ``(kept, rejected)`` with the same row layout.
    """
    accidents = np.asarray(accidents, dtype=np.float64)
    varsig = np.asarray(varsig, dtype=np.float64)
    if accidents.shape[1] == 0:
        return accidents, accidents

    dur_ok = (accidents[1, :] - accidents[0, :]) >= durationthreshold
    accidents = accidents[:, dur_ok]

    keep = np.zeros(accidents.shape[1], dtype=bool)
    for i in range(accidents.shape[1]):
        a = int(round(accidents[0, i] * 4))
        b = int(round(accidents[1, i] * 4))
        a = max(a, 0)
        b = min(b, len(varsig) - 1)
        if b >= a:
            keep[i] = varsig[a : b + 1].max() >= amplitudethreshold
    return accidents[:, keep], accidents[:, ~keep]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
class WMFBResult:
    """Container for a WMFB analysis."""

    def __init__(self, baseline, accelerations, decelerations, false_acc, false_dec):
        self.baseline = baseline
        self.accelerations = accelerations  # list[(start_s, end_s)]
        self.decelerations = decelerations
        self.false_acc = false_acc
        self.false_dec = false_dec

    def __repr__(self):  # pragma: no cover - convenience only
        return (
            f"WMFBResult(baseline[{len(self.baseline)}], "
            f"acc={len(self.accelerations)}, dec={len(self.decelerations)})"
        )


def _segments_to_list(arr):
    """Convert a ``(>=2, k)`` start/end array (seconds) to a list of tuples."""
    if arr.shape[1] == 0:
        return []
    return [(float(arr[0, i]), float(arr[1, i])) for i in range(arr.shape[1])]


# ---------------------------------------------------------------------------
# WMFB main entry
# ---------------------------------------------------------------------------
def wmfb(fhri, fs: float = 4.0, return_result: bool = False):
    """Compute the WMFB baseline and accel/decel events (port of ``aamwmfb.m``).

    Parameters
    ----------
    fhri:
        Gap-free FHR at 4 Hz (the ``FHRi`` output of
        :func:`fhrpy.preprocess.preprocess`).
    fs:
        Sample rate, for documentation/scaling; the algorithm itself uses the
        FHRMA ``srate=240`` convention internally and assumes 4 Hz samples.
    return_result:
        If True, return a :class:`WMFBResult`; otherwise return the tuple
        ``(baseline, accelerations, decelerations, false_acc, false_dec)``.

    Returns
    -------
    baseline : np.ndarray
        Baseline at 4 Hz (same length as ``fhri``).
    accelerations, decelerations, false_acc, false_dec : list[(start_s, end_s)]
        Event segments in **seconds**.
    """
    fhri = np.asarray(fhri, dtype=np.float64).ravel()

    # --- 5 zero-phase Butterworth low-pass copies (order 1, srate=240) ---
    FHR1 = butterfilt(fhri, _SRATE, 0, 1, 1, True)
    FHR2 = butterfilt(fhri, _SRATE, 0, 2, 1, True)
    FHR4 = butterfilt(fhri, _SRATE, 0, 4, 1, True)
    FHR8 = butterfilt(fhri, _SRATE, 0, 8, 1, True)
    FHR16 = butterfilt(fhri, _SRATE, 0, 16, 1, True)

    # --- per-sample trust probability P (logistic on derivative envelopes) ---
    fcut = [0, 1, 3, 7]
    fdat1 = []  # band-passed signals
    fdat2 = []  # their derivatives x srate
    for j in range(3):
        bp = butterfilt(fhri, _SRATE, fcut[j], fcut[j + 1], 1, True)
        fdat1.append(bp)
        deriv = np.concatenate([[0.0], bp[1:] - bp[:-1]]) * _SRATE
        fdat2.append(deriv)

    t = np.vstack(
        [
            np.abs(fdat2[0]),
            _enveloppe(fdat2[0], _SRATE, 0, 2 * fcut[1]),
            _enveloppe(fdat2[1], _SRATE, 0, 2 * fcut[2]),
            _enveloppe(fdat2[2], _SRATE, 0, 2 * fcut[3]),
        ]
    ).T  # (N, 4)

    lin = _Q[0] + t @ _Q[1:]
    P = 1.0 - _sigmoid(lin)  # = sigmoid(-lin), per-sample trust weight in [0,1]

    # --- iterative weighted-median bank (6 passes) ---
    distancecoef = np.concatenate(
        [np.linspace(0, 1, 200), [1.0], np.linspace(1, 0, 200)]
    )  # length 401

    bl1, mp1 = _medgliss(FHR2, distancecoef, P, _DECIM)
    P2 = P * _sigmoid(3.21 - 0.19 * np.abs(FHR1 - bl1))
    bl2, _ = _medgliss(FHR2, distancecoef**2, P2, _DECIM, bl1, mp1, 0.1)
    P3 = P * _sigmoid(2.5 - 0.19 * np.abs(FHR4 - bl2))
    bl3, _ = _medgliss(FHR4, distancecoef**4, P3, _DECIM, bl2, mp1, 0.1)
    P4 = P * _sigmoid(2.0 - 0.19 * np.abs(FHR8 - bl3))
    bl4, _ = _medgliss(FHR8, distancecoef**8, P4, _DECIM, bl3, mp1, 0.1)
    P5 = P * _sigmoid(1.5 - 0.19 * np.abs(FHR16 - bl4))
    bl5, _ = _medgliss(FHR16, distancecoef**16, P5, _DECIM, bl4, mp1, 0.1)
    P6 = P * _sigmoid(1.0 - 0.19 * np.abs(FHR16 - bl5))
    bl6, _ = _medgliss(FHR16, distancecoef**16, P6, _DECIM, bl5, mp1, 0.1)
    baseline = bl6

    # --- acceleration / deceleration extraction ---
    acc = _accidentcandidat(FHR1, baseline, 5)
    acc = _adjustduration(acc, fhri - baseline).astype(np.float64) / 4.0
    acc, false_acc = validaccident(acc, fhri - baseline, 15, 15)

    dec = _accidentcandidat(baseline, FHR1, 5)
    dec = _adjustduration(dec, baseline - fhri).astype(np.float64) / 4.0
    dec, false_dec = validaccident(dec, baseline - fhri, 15, 15)

    accelerations = _segments_to_list(acc)
    decelerations = _segments_to_list(dec)
    false_acc_l = _segments_to_list(false_acc)
    false_dec_l = _segments_to_list(false_dec)

    if return_result:
        return WMFBResult(baseline, accelerations, decelerations, false_acc_l, false_dec_l)
    return baseline, accelerations, decelerations, false_acc_l, false_dec_l


# ---------------------------------------------------------------------------
# simpleaddetection.m (trivial reference detector)
# ---------------------------------------------------------------------------
def _detectaccident(sig, thre):
    """Peaks ``sig > thre`` extended to surrounding zero-crossings (>15 s kept).

    Port of ``detectaccident`` in ``simpleaddetection.m``. Returns ``(3, n)``
    ``[start; end; max]`` **in seconds**.
    """
    sig = np.asarray(sig, dtype=np.float64)
    n = len(sig)
    peaks = np.where(sig > thre)[0]
    out = []
    while peaks.size > 0:
        p = peaks[0]
        left = np.where(sig[: p + 1] < 0)[0]
        dacc = left[-1] if left.size > 0 else 0
        right = np.where(sig[dacc + 1 :] < 0)[0]
        facc = (right[0] + dacc + 1) if right.size > 0 else (n - 1)
        macc = dacc + int(np.argmax(sig[dacc : facc + 1]))
        if (facc - dacc) > 15 * 4:
            out.append(np.array([dacc, facc, macc], dtype=np.float64) / 4.0)
        peaks = peaks[peaks > facc]
    if not out:
        return np.zeros((3, 0))
    return np.vstack(out).T


def _minusint(a, f):
    """Remove from ``f`` any interval fully inside an interval of ``a`` (``minusint``)."""
    a = np.asarray(a, dtype=np.float64)
    f = np.asarray(f, dtype=np.float64)
    for i in range(a.shape[1]):
        n = np.where((f[0, :] >= a[0, i]) & (f[1, :] <= a[1, i]))[0]
        if n.size > 0:
            f = np.delete(f, n[0], axis=1)
    return f


def simpleaddetection(fhr, baseline):
    """Trivial reference A/D detector (port of ``simpleaddetection.m``).

    Returns ``(acc, dec, falseacc, falsedec)``, each a ``(3, n)`` array
    ``[start; end; max]`` in **seconds**.
    """
    fhr = np.asarray(fhr, dtype=np.float64)
    baseline = np.asarray(baseline, dtype=np.float64)
    acc = _detectaccident(fhr - baseline, 15)
    dec = _detectaccident(baseline - fhr, 15)
    falseacc = _minusint(acc, _detectaccident(fhr - baseline, 5))
    falsedec = _minusint(dec, _detectaccident(baseline - fhr, 5))
    return acc, dec, falseacc, falsedec


# ---------------------------------------------------------------------------
# Convenience: analyse a loaded FHRRecord
# ---------------------------------------------------------------------------
def analyze(record, unreliable_signal=None, return_result: bool = False):
    """Preprocess then run WMFB on a loaded :class:`fhrpy.io.FHRRecord`.

    Returns a dict with ``baseline``, ``fhri``, ``accelerations``,
    ``decelerations``, ``false_acc``, ``false_dec``, ``contractions`` (a
    placeholder ``None`` -- there is no contraction algorithm in the FHRMA core;
    TOCO is carried through unchanged), and ``d``/``f`` (first/last valid
    sample). Accel/decel are lists of ``(start_s, end_s)``.
    """
    from ..preprocess.preprocess import preprocess

    fhri, fhr, toco, d, f = preprocess(
        record.fhr1, record.fhr2, record.toco, unreliable_signal
    )
    baseline, acc, dec, facc, fdec = wmfb(fhri)

    result = {
        "baseline": baseline,
        "fhri": fhri,
        "fhr": fhr,
        "toco": toco,
        "accelerations": acc,
        "decelerations": dec,
        "false_acc": facc,
        "false_dec": fdec,
        "contractions": None,  # out of scope in the FHRMA core (see spec section 4.4)
        "d": d,
        "f": f,
    }
    if return_result:
        return WMFBResult(baseline, acc, dec, facc, fdec)
    return result
