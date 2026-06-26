"""Unit tests for fhrpy.preprocess (DSP primitives + preprocessing chain)."""

import os

import numpy as np
import pytest

from fhrpy.io import read_fhr
from fhrpy.preprocess import (
    avgsubsamp,
    avgwin,
    butterfilt,
    filtfilt,
    interpol_fhr,
    linearinterpolation,
    preprocess,
    removesmallpart,
)
from fhrpy.preprocess.dsp import butter_coeffs, lfilter_zi

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "sample.rcfm")


# ---------------------------------------------------------------------------
# linearinterpolation / interpolFHR exact unit tests
# ---------------------------------------------------------------------------
def test_linearinterpolation_known():
    # Control points (1, 10), (3, 30): slope 10, intercept 0.
    x = [1, 3]
    y = [10, 30]
    xx = np.array([0, 1, 2, 3, 4])
    yy = linearinterpolation(x, y, xx)
    # Extrapolate below x[0] with the same single segment; at/after x[-1] too.
    np.testing.assert_allclose(yy, [0, 10, 20, 30, 40])


def test_linearinterpolation_multi_segment():
    x = [0, 2, 4]
    y = [0, 20, 0]
    xx = np.array([-1, 0, 1, 2, 3, 4, 5])
    yy = linearinterpolation(x, y, xx)
    # seg1 slope +10 (extrapolated left), seg2 slope -10 (extrapolated right).
    np.testing.assert_allclose(yy, [-10, 0, 10, 20, 10, 0, -10])


def test_interpol_fhr_known_gap():
    # Crafted signal: leading gap, a middle gap, trailing gap.
    # samples:        0   1   2    3    4    5    6   7
    fhr = np.array([0, 0, 120, 0, 0, 150, 0, 0], dtype=float)
    fhri, d, f = interpol_fhr(fhr)
    # First valid sample is index 2 (value 120); last valid is index 5 (150).
    assert d == 2
    assert f == 5
    # Leading gap held at 120; trailing gap held at 150.
    np.testing.assert_allclose(fhri[:3], [120, 120, 120])
    np.testing.assert_allclose(fhri[5:], [150, 150, 150])
    # Middle gap (indices 3,4) linearly interpolated 120 -> 150.
    np.testing.assert_allclose(fhri, [120, 120, 120, 130, 140, 150, 150, 150])
    assert not np.isnan(fhri).any()


def test_interpol_fhr_no_zeros_after():
    rng = np.random.default_rng(0)
    fhr = rng.uniform(120, 150, 400)
    fhr[50:60] = 0  # a gap
    fhr[:10] = 0  # leading gap
    fhri, d, f = interpol_fhr(fhr)
    assert (fhri > 0).all()
    assert not np.isnan(fhri).any()


# ---------------------------------------------------------------------------
# removesmallpart
# ---------------------------------------------------------------------------
def test_removesmallpart_clips_range():
    fhr = np.array([40, 60, 230, 150, 200], dtype=float)
    out = removesmallpart(fhr)
    # 40 (<50) and 230 (>220) -> 0; others kept (subject to run-length rules).
    assert out[0] == 0
    assert out[2] == 0


def test_removesmallpart_drops_short_runs():
    # A 12-sample valid run (< 5 s = 20 samples) surrounded by zeros is removed.
    fhr = np.zeros(200)
    fhr[100:112] = 140.0
    out = removesmallpart(fhr)
    assert np.all(out[100:112] == 0)


def test_removesmallpart_keeps_long_runs():
    fhr = np.zeros(200)
    fhr[50:150] = 140.0  # 100 samples = 25 s, well above thresholds
    out = removesmallpart(fhr)
    assert np.all(out[50:150] == 140.0)


# ---------------------------------------------------------------------------
# avgwin / avgsubsamp
# ---------------------------------------------------------------------------
def test_avgwin_edges():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = avgwin(x, 1)
    # Centred mean over [i-1, i+1] clamped at the edges.
    np.testing.assert_allclose(y, [1.5, 2.0, 3.0, 4.0, 4.5])


def test_avgsubsamp_block_mean():
    x = np.arange(10, dtype=float)
    y = avgsubsamp(x, 3)
    # floor(10/3)=3 blocks: mean([0,1,2]), mean([3,4,5]), mean([6,7,8]); 9 dropped.
    np.testing.assert_allclose(y, [1, 4, 7])


# ---------------------------------------------------------------------------
# filtfilt / butterfilt
# ---------------------------------------------------------------------------
def test_lfilter_zi_matches_scipy():
    from scipy.signal import lfilter_zi as sp_zi

    b, a = butter_coeffs(1, 2 * 2 / 240, "low")
    np.testing.assert_allclose(lfilter_zi(b, a), sp_zi(b, a))


def test_filtfilt_order1_matches_scipy_padlen():
    # For order-1 Butterworth the pure-NumPy filtfilt is bit-identical to scipy
    # filtfilt with odd padding of length 3*(order-1) (matches multisigfilter.c).
    from scipy.signal import filtfilt as sp_filtfilt

    b, a = butter_coeffs(1, 2 * 2 / 240, "low")
    x = np.cumsum(np.random.default_rng(1).standard_normal(2000)) + 140
    y = filtfilt(b, a, x)
    nfact = 3 * (len(b) - 1)
    ys = sp_filtfilt(b, a, x, padtype="odd", padlen=nfact)
    np.testing.assert_allclose(y, ys, atol=1e-9)


def test_filtfilt_zero_phase_symmetry():
    # Zero-phase: filtering a symmetric signal stays symmetric.
    b, a = butter_coeffs(1, 0.1, "low")
    n = 401
    x = np.exp(-((np.arange(n) - n // 2) ** 2) / (2 * 20.0**2))
    y = filtfilt(b, a, x)
    np.testing.assert_allclose(y, y[::-1], atol=1e-9)


def test_butterfilt_multichannel():
    b_x = np.cumsum(np.random.default_rng(2).standard_normal(1500)) + 140
    X = np.vstack([b_x, b_x[::-1]])
    Y = butterfilt(X, 240, 0, 2, 1, True)
    assert Y.shape == X.shape
    # Each row equals the single-channel result.
    np.testing.assert_allclose(Y[0], butterfilt(b_x, 240, 0, 2, 1, True))


# ---------------------------------------------------------------------------
# full preprocess on the sample recording
# ---------------------------------------------------------------------------
def test_preprocess_sample():
    rec = read_fhr(SAMPLE)
    fhri, fhr, toco, d, f = preprocess(rec.fhr1, rec.fhr2, rec.toco)
    assert len(fhri) == len(rec)
    assert len(fhr) == len(rec)
    # FHRi is gap-free and physiological.
    assert (fhri > 0).all()
    assert not np.isnan(fhri).any()
    assert fhri.min() >= 50 and fhri.max() <= 220
    # FHR (with NaN) has NaN only where the merged signal was missing.
    assert np.isnan(fhr).any() or (fhr > 0).all()
    # d, f are sane 0-based indices.
    assert 0 <= d <= f < len(rec)


def test_preprocess_unreliable_signal_minutes():
    # unreliable_signal rows are in MINUTES; ensure the right window is zeroed
    # before interpolation (so FHRi interpolates across it).
    rng = np.random.default_rng(3)
    n = 240 * 4  # 4 minutes at 4 Hz
    fhr1 = rng.uniform(130, 140, n)
    fhr2 = np.zeros(n)
    # Zero out minute [1, 2): samples ~ round(1*240+1) .. round(2*240) (1-based).
    fhri, fhr, toco, d, f = preprocess(fhr1, fhr2, None, unreliable_signal=[[1.0, 2.0]])
    # The flagged minute is interpolated (still finite/positive in FHRi)...
    assert (fhri > 0).all()
    # ...and marked NaN in the raw FHR over roughly that window.
    assert np.isnan(fhr[300]) or np.isnan(fhr[400])


@pytest.mark.skip(reason="needs Octave parity harness — Étape 3 follow-up")
def test_preprocess_matlab_parity():
    # TODO(Étape 3): compare FHRi/FHR against MATLAB preprocess.m output on the
    # FHRMAdataset via an Octave docker harness. Assert array-level equality
    # (interpolation, removesmallpart boundaries, NaN placement).
    raise NotImplementedError
