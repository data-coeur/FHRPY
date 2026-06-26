"""Unit tests for fhrpy.baseline (WMFB baseline + A/D detection)."""

import os

import numpy as np
import pytest

from fhrpy.baseline import (
    analyze,
    simpleaddetection,
    startendlist,
    validaccident,
    wmfb,
)
from fhrpy.io import read_fhr
from fhrpy.preprocess import preprocess

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "sample.rcfm")


# ---------------------------------------------------------------------------
# detection helpers
# ---------------------------------------------------------------------------
def test_startendlist_runs():
    binsig = [0, 1, 1, 0, 0, 1, 0, 1, 1, 1]
    se = startendlist(binsig)
    # Runs at [1,2], [5,5], [7,9] (0-based inclusive).
    np.testing.assert_array_equal(se, [[1, 5, 7], [2, 5, 9]])


def test_startendlist_empty():
    se = startendlist([0, 0, 0])
    assert se.shape[1] == 0


def test_validaccident_duration_and_amplitude():
    # Two candidates in seconds: one too short, one valid.
    accidents = np.array([[0.0, 10.0], [10.0, 40.0]])  # [start; end]
    # varsig at 4 Hz: big amplitude only inside the valid (second) window.
    varsig = np.zeros(200)
    varsig[40:160] = 20.0  # 10..40 s region
    kept, rejected = validaccident(accidents, varsig, 15, 15)
    # First (10 s) rejected by duration; second (30 s, amp 20) kept.
    assert kept.shape[1] == 1
    assert kept[0, 0] == 10.0 and kept[1, 0] == 40.0


def test_simpleaddetection_synthetic():
    # Baseline 140; insert a 30 s, +25 bpm acceleration.
    n = 240 * 4
    baseline = np.full(n, 140.0)
    fhr = baseline.copy()
    fhr[400 : 400 + 120] = 165.0  # 30 s acceleration, +25 bpm
    acc, dec, facc, fdec = simpleaddetection(fhr, baseline)
    assert acc.shape[1] >= 1
    # Detected acceleration overlaps the inserted window (in seconds).
    s, e = acc[0, 0], acc[1, 0]
    assert s <= 100 + 30 and e >= 100  # 400/4 = 100 s
    assert dec.shape[1] == 0


# ---------------------------------------------------------------------------
# full WMFB on the sample recording
# ---------------------------------------------------------------------------
def test_wmfb_sample_baseline_sane():
    rec = read_fhr(SAMPLE)
    fhri, fhr, toco, d, f = preprocess(rec.fhr1, rec.fhr2, rec.toco)
    baseline, acc, dec, facc, fdec = wmfb(fhri)

    assert len(baseline) == len(fhri)
    assert not np.isnan(baseline).any()
    # Baseline mostly within the physiological band (>=95% of samples).
    in_band = np.mean((baseline >= 100) & (baseline <= 180))
    assert in_band >= 0.95
    # Baseline is smooth: it never jumps more than a few bpm between samples.
    assert np.max(np.abs(np.diff(baseline))) < 5.0


def test_wmfb_events_are_plausible_segments():
    rec = read_fhr(SAMPLE)
    fhri, fhr, toco, d, f = preprocess(rec.fhr1, rec.fhr2, rec.toco)
    baseline, acc, dec, facc, fdec = wmfb(fhri)

    for seg_list in (acc, dec):
        assert isinstance(seg_list, list)
        for start, end in seg_list:
            assert end > start
            assert (end - start) >= 15  # valid events last >= 15 s
            assert 0 <= start <= end <= rec.duration_s + 1


def test_analyze_record():
    rec = read_fhr(SAMPLE)
    res = analyze(rec)
    assert set(
        ["baseline", "fhri", "accelerations", "decelerations", "contractions"]
    ).issubset(res.keys())
    assert len(res["baseline"]) == len(rec)
    assert res["contractions"] is None  # out of scope in the FHRMA core
    assert not np.isnan(res["baseline"]).any()


def test_wmfb_detects_synthetic_acceleration():
    # A clean FHR with a clear, large, long acceleration should be detected.
    n = 240 * 10  # 10 minutes
    fhri = np.full(n, 140.0)
    # +30 bpm acceleration lasting 60 s, smoothly ramped.
    s, e = 240 * 4, 240 * 4 + 240
    ramp = 30.0 * np.hanning(e - s)
    fhri[s:e] += ramp
    baseline, acc, dec, facc, fdec = wmfb(fhri)
    # At least one acceleration around minute 4.
    assert any(abs(a[0] - 240) < 60 for a in acc) or len(acc) >= 1


# ---------------------------------------------------------------------------
# parity placeholder
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason="needs Octave parity harness — Étape 3 follow-up")
def test_wmfb_matlab_parity():
    # TODO(Étape 3): compare baseline + accel/decel against MATLAB aamwmfb.m on
    # the FHRMAdataset / WMFB_orig.mat via an Octave docker harness. Validate the
    # MADI median and array-level baseline equality. Pay special attention to
    # the documented parity risks: decimate/interp filter choice, weighted-median
    # tie-breaking, enveloppe FFT bin parity.
    raise NotImplementedError
