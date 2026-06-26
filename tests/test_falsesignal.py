"""Unit tests for fhrpy.falsesignal (NumPy false-signal detection)."""

import os

import numpy as np
import pytest

from fhrpy.falsesignal import (
    Dense,
    FSDopModel,
    FSScalpModel,
    GRULayer,
    build_dop_features,
    build_scalp_features,
    detect_false_signals,
    load_model,
    mask_to_segments,
    normalize_hr,
    remove_holds,
)
from fhrpy.falsesignal.features import build_stage2_flag
from fhrpy.io import read_fhr

HERE = os.path.dirname(__file__)
EXAMPLE = os.path.join(HERE, "..", "examples", "example_recording.fhr")
SAMPLE = os.path.join(HERE, "..", "examples", "sample.rcfm")


# --------------------------------------------------------------------------- #
# GRU forward pass — verified against an independent reset_after=True reference
# --------------------------------------------------------------------------- #
def _keras_gru_reference(I, W, U, B):
    """Independent reference for a Keras GRU (reset_after=True, gate order z|r|h).

    I: (T, m). W: (m, 3n). U: (n, 3n). B: (2, 3n). Returns (T, n).
    This mirrors the Keras/cuDNN recurrence exactly but is written from scratch
    (no shared code with model.GRULayer) so it is a real cross-check.
    """
    T, m = I.shape
    n = U.shape[0]

    def sig(x):
        return 1.0 / (1.0 + np.exp(-x))

    b_in, b_rec = B[0], B[1]
    h = np.zeros(n)
    out = np.zeros((T, n))
    for t in range(T):
        x = I[t]
        xW = x @ W                      # (3n,)
        hU = h @ U                      # (3n,)
        z = sig(xW[:n] + hU[:n] + b_in[:n] + b_rec[:n])
        r = sig(xW[n:2 * n] + hU[n:2 * n] + b_in[n:2 * n] + b_rec[n:2 * n])
        # reset_after: reset applied to (recurrent matmul + recurrent bias)
        hh = np.tanh(
            xW[2 * n:3 * n] + b_in[2 * n:3 * n]
            + r * (hU[2 * n:3 * n] + b_rec[2 * n:3 * n])
        )
        h = z * h + (1.0 - z) * hh
        out[t] = h
    return out


def test_gru_matches_independent_reference():
    rng = np.random.default_rng(0)
    T, m, n = 17, 4, 5
    W = rng.standard_normal((m, 3 * n))
    U = rng.standard_normal((n, 3 * n))
    B = rng.standard_normal((2, 3 * n))
    I = rng.standard_normal((T, m))

    ref = _keras_gru_reference(I, W, U, B)
    got = GRULayer(W, U, B).forward(I)  # 2-D path (single page)
    np.testing.assert_allclose(got, ref, rtol=1e-10, atol=1e-10)


def test_gru_page_dim_independent():
    """The page (batch) dimension must be processed independently."""
    rng = np.random.default_rng(1)
    T, m, n = 9, 3, 4
    W = rng.standard_normal((m, 3 * n))
    U = rng.standard_normal((n, 3 * n))
    B = rng.standard_normal((2, 3 * n))
    g = GRULayer(W, U, B)
    Ia = rng.standard_normal((T, m))
    Ib = rng.standard_normal((T, m))
    stacked = g.forward(np.stack([Ia, Ib], axis=2))
    np.testing.assert_allclose(stacked[:, :, 0], g.forward(Ia), atol=1e-12)
    np.testing.assert_allclose(stacked[:, :, 1], g.forward(Ib), atol=1e-12)


def test_dense_sigmoid():
    W = np.array([[1.0], [2.0]])
    b = np.array([0.5])
    d = Dense(W, b)
    out = d.forward(np.array([[1.0, 1.0]]))
    expected = 1.0 / (1.0 + np.exp(-(1.0 + 2.0 + 0.5)))
    np.testing.assert_allclose(out[0, 0], expected)


# --------------------------------------------------------------------------- #
# feature construction
# --------------------------------------------------------------------------- #
def test_normalize_hr():
    hr = np.array([0.0, 120.0, 180.0, 60.0])
    norm, mask = normalize_hr(hr)
    np.testing.assert_allclose(norm, [0.0, 0.0, 1.0, -1.0])
    np.testing.assert_array_equal(mask, [0.0, 1.0, 1.0, 1.0])


def test_build_dop_features_shape_and_values():
    fhr = np.array([0.0, 150.0, 120.0])
    mhr = np.array([90.0, 0.0, 120.0])
    I = build_dop_features(fhr, mhr, stage2_start=2)
    assert I.shape == (5, 3)
    # row layout: [FHRnorm, FHRmask, MHRnorm, MHRmask, isStage2]
    np.testing.assert_allclose(I[0], [0.0, 0.5, 0.0])      # FHR norm
    np.testing.assert_array_equal(I[1], [0.0, 1.0, 1.0])   # FHR mask
    np.testing.assert_allclose(I[2], [-0.5, 0.0, 0.0])     # MHR norm
    np.testing.assert_array_equal(I[3], [1.0, 0.0, 1.0])   # MHR mask
    np.testing.assert_array_equal(I[4], [0.0, 0.0, 1.0])   # isStage2 from idx 2


def test_build_scalp_features_shape():
    fhr = np.full(100, 140.0)
    I, cleaned = build_scalp_features(fhr, stage2_start=None)
    assert I.shape == (3, 100)
    assert cleaned.shape == (100,)


def test_build_stage2_flag():
    np.testing.assert_array_equal(build_stage2_flag(5, None), np.zeros(5))
    np.testing.assert_array_equal(build_stage2_flag(5, 2), [0, 0, 1, 1, 1])
    np.testing.assert_array_equal(build_stage2_flag(5, -1), np.ones(5))  # antepartum


def test_remove_holds_zeroes_long_holds():
    # 140, then a 20-sample hold at 150, then 140 again.
    fhr = np.full(60, 140.0)
    fhr[20:40] = 150.0
    cleaned = remove_holds(fhr)
    # The constant 150 hold (>=12 identical) should be zeroed out.
    assert np.all(cleaned[22:39] == 0.0)
    # Non-held regions are preserved.
    assert np.all(cleaned[:18] == 140.0)


# --------------------------------------------------------------------------- #
# model loading
# --------------------------------------------------------------------------- #
def test_load_models_shapes():
    dop = load_model("doppler")
    assert isinstance(dop, FSDopModel)
    assert dop.GRU1MHR.W.shape == (5, 36) and dop.GRU1MHR.units == 12
    assert dop.GRU1.W.shape == (6, 72) and dop.GRU1.units == 24
    assert dop.GRU2.W.shape == (54, 72)
    assert dop.GRU3.W.shape == (54, 72)
    assert dop.Dense1.W.shape == (48, 1)

    scalp = load_model("scalp")
    assert isinstance(scalp, FSScalpModel)
    assert scalp.GRU1.W.shape == (3, 72) and scalp.GRU1.units == 24
    assert scalp.GRU2.W.shape == (51, 54) and scalp.GRU2.units == 18
    assert scalp.GRU3.W.shape == (39, 36) and scalp.GRU3.units == 12
    assert scalp.Dense1.W.shape == (24, 1)


def test_load_model_cached():
    assert load_model("doppler") is load_model("dop")


# --------------------------------------------------------------------------- #
# mask -> segments
# --------------------------------------------------------------------------- #
def test_mask_to_segments():
    mask = np.array([0, 1, 1, 0, 0, 1, 0], dtype=bool)
    segs = mask_to_segments(mask, fs=4.0)
    # run [1,2] -> (0.25, 0.75); run [5,5] -> (1.25, 1.5)
    assert segs == [(0.25, 0.75), (1.25, 1.5)]
    assert mask_to_segments(np.zeros(5, bool)) == []


# --------------------------------------------------------------------------- #
# end-to-end on the example recordings
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.path.exists(EXAMPLE), reason="example recording missing")
def test_detect_doppler_example():
    rec = read_fhr(EXAMPLE)
    n = len(rec)
    res = detect_false_signals(rec, kind="doppler")
    prob = res["prob"]
    assert prob.shape == (n,)
    assert not np.isnan(prob).any()
    assert prob.min() >= 0.0 and prob.max() <= 1.0
    assert res["mask"].shape == (n,)
    assert res["mask"].dtype == bool
    assert isinstance(res["segments"], list)
    for start_s, end_s in res["segments"]:
        assert 0.0 <= start_s < end_s <= n / res["fs"] + 1
    # Doppler also returns an MHR-false probability of the right shape.
    assert res["prob_mhr"].shape == (n,)
    assert not np.isnan(res["prob_mhr"]).any()


@pytest.mark.skipif(not os.path.exists(SAMPLE), reason="sample recording missing")
def test_detect_scalp_sample():
    rec = read_fhr(SAMPLE)
    n = len(rec)
    res = detect_false_signals(rec, kind="scalp", channel="fhr1")
    prob = res["prob"]
    assert prob.shape == (n,)
    assert not np.isnan(prob).any()
    assert prob.min() >= 0.0 and prob.max() <= 1.0
    assert res["prob_mhr"] is None
    assert res["fhr_clean"] is not None and res["fhr_clean"].shape == (n,)
    for start_s, end_s in res["segments"]:
        assert end_s > start_s


def test_detect_synthetic_mhr_confusion():
    """Inject a clear Doppler-grabs-maternal-HR window and expect a detection.

    Builds a clean fetal trace at ~140 bpm with a maternal trace at ~80 bpm, then
    overwrites a window of the FHR with the MHR value (the classic confusion). The
    model should flag elevated P(false) inside that window relative to outside.
    """
    from fhrpy.io import FHRRecord

    n = 4 * 60 * 20  # 20 min
    fhr = np.full(n, 140.0)
    mhr = np.full(n, 80.0)
    a, b = n // 2, n // 2 + 4 * 60 * 3  # 3-min confusion window
    fhr[a:b] = mhr[a:b]  # FHR now tracks the maternal HR
    rec = FHRRecord(fhr1=fhr, fhr2=np.zeros(n), mhr=mhr, toco=np.zeros(n))
    res = detect_false_signals(rec, kind="doppler")
    inside = res["prob"][a:b].mean()
    outside = np.concatenate([res["prob"][:a], res["prob"][b:]]).mean()
    assert inside > outside  # confusion window scores more "false" than the rest


# --------------------------------------------------------------------------- #
# MATLAB-parity placeholders (Étape 2 follow-up)
# --------------------------------------------------------------------------- #
def test_viewer_injects_urs_markers(tmp_path):
    """FHRViewer(false_signals=True) injects ``$ URS`` grey zones for detections."""
    from fhrpy.io import FHRRecord, write_fhr
    from fhrpy.viewer import FHRViewer

    n = 4 * 60 * 20
    fhr = np.full(n, 140.0)
    mhr = np.full(n, 80.0)
    a, b = n // 2, n // 2 + 4 * 60 * 4
    fhr[a:b] = mhr[a:b]
    rec = FHRRecord(fhr1=fhr, fhr2=np.zeros(n), mhr=mhr, toco=np.zeros(n))
    path = tmp_path / "confusion.fhrm"
    write_fhr(path, rec, with_mhr=True)

    v = FHRViewer(str(path), false_signals=True, height=400)
    urs = [m for m in v.markers if str(m[1]).startswith("$ URS")]
    assert urs, "expected at least one $ URS marker for the confusion window"
    for samp, text in urs:
        assert samp >= 0
        assert int(str(text).split()[2]) > 0
    # The page bundles fine and the JS shades URS grey (drawPeriods type URS).
    assert "URS" in v._build_html()


@pytest.mark.skip(reason="needs Octave/MATLAB FS reference — Étape 2 parity follow-up")
def test_fsdop_matlab_parity():
    # TODO(Étape 2): compare per-sample PDop/PMat against FalseSigDetectDopMHR.m
    # (MyFSDopMethodAnalysis.mat) on the FSdataset DopMHR files, and the
    # Sensitivity/Specificity/AUC table from EvalFSForDataset.m. Verify GRU gate
    # ordering / reset_after, feature normalization, and that FSDop reuses the
    # frozen FSMHR (GRU1MHR + DensePmat) weights bit-for-bit.
    raise NotImplementedError


@pytest.mark.skip(reason="needs Octave/MATLAB FS reference — Étape 2 parity follow-up")
def test_fsscalp_matlab_parity():
    # TODO(Étape 2): compare per-sample PFHR against FalseSigDetectScalp.m on the
    # ScalpECG test files, including the removeholds() pre-cleaning.
    raise NotImplementedError
