"""Tests for uterine contraction detection (amnio BLsam(TOCO*2) port)."""
import numpy as np

import fhrpy.datasets as ds
from fhrpy.baseline import analyze, detect_contractions
from fhrpy.io import read_fhr


def _synthetic_toco(n_contractions=5, fs=4, gap_s=180, width_s=70, amp=60, base=20):
    """A flat TOCO baseline with a few raised-cosine 'contraction' humps."""
    total = n_contractions * gap_s + gap_s
    t = np.full(int(total * fs), float(base))
    w = int(width_s * fs)
    for k in range(n_contractions):
        c = int((gap_s * (k + 1)) * fs)
        bell = amp * 0.5 * (1 - np.cos(np.linspace(0, 2 * np.pi, w)))
        t[c:c + w] += bell
    return t


def test_detects_synthetic_contractions():
    toco = _synthetic_toco(n_contractions=5)
    con = detect_contractions(toco)
    # should find roughly the planted contractions (allow a little slack)
    assert 3 <= len(con) <= 7
    for s0, s1 in con:
        assert s1 > s0


def test_empty_or_flat_toco_returns_none_list():
    assert detect_contractions(np.zeros(4 * 600)) == []
    assert detect_contractions(np.array([])) == []


def test_accepts_record_and_array_equivalently():
    rec = read_fhr(ds.example_path("ctg_example_01"))
    from_rec = detect_contractions(rec)
    from_arr = detect_contractions(rec.toco)
    assert from_rec == from_arr
    assert len(from_rec) > 5          # a 3.7 h labour CTG has many contractions


def test_analyze_populates_contractions():
    rec = read_fhr(ds.example_path("morpho_train21"))
    ma = analyze(rec)
    assert ma["contractions"] is not None
    assert isinstance(ma["contractions"], list)


def test_classify_decelerations_types_and_keys():
    import numpy as np
    from fhrpy.baseline import classify_decelerations

    n = 4 * 600
    baseline = np.full(n, 140.0)
    fhri = baseline.copy()
    # an abrupt, deep dip (variable severe): nadir ~60, reached in ~10 s
    fhri[4 * 100: 4 * 110] = 60.0
    # a gradual V-shaped dip far from any contraction, nadir 40 s in -> 'late'
    grad = np.concatenate([np.linspace(140, 118, 4 * 40), np.linspace(118, 140, 4 * 40)])
    fhri[4 * 300: 4 * 300 + len(grad)] = grad
    decels = [(100, 110), (300, 380)]
    res = classify_decelerations(decels, fhri, baseline, contractions=[])
    assert len(res) == 2
    for d in res:
        assert {"start_s", "end_s", "type", "label", "amplitude",
                "nadir", "duration", "time_to_nadir_s", "surface"} <= set(d)
    assert res[0]["type"].startswith("variable")
    assert res[0]["time_to_nadir_s"] < 30
    # gradual onset (nadir ~40 s) with no contraction -> 'late'
    assert res[1]["type"] == "late"


def test_analyze_exposes_deceleration_types():
    from fhrpy.baseline import analyze
    rec = read_fhr(ds.example_path("morpho_train21"))
    ma = analyze(rec)
    assert isinstance(ma["deceleration_types"], list)
    assert len(ma["deceleration_types"]) == len(ma["decelerations"])


def test_compute_features_standard_keys():
    from fhrpy.baseline import compute_features
    rec = read_fhr(ds.example_path("ctg_example_01"))
    feats = compute_features(rec)
    for k in ("analysis_duration_min", "baseline_mean", "acc_count", "dec_count",
              "dec_early_count", "dec_late_count", "dec_variable_count",
              "contraction_count", "dec_to_contraction_ratio", "stv_msd",
              "ltv_delta_mean", "fhr_time_below_110_percent"):
        assert k in feats
    assert feats["dec_count"] == len(__import__("fhrpy.baseline", fromlist=["analyze"]).analyze(rec)["decelerations"])
    assert feats["contraction_count"] >= 0


def test_signal_loss_percent_nonzero_on_gappy_record():
    # regression: signal_loss_percent must reflect real loss (preprocessed FHR
    # marks gaps with NaN, not 0).
    import numpy as np
    from fhrpy.baseline import analyze, compute_features
    rec = read_fhr(ds.example_path("ctg_example_01"))
    ma = analyze(rec)
    ref = 100.0 * float(np.mean(np.isnan(np.asarray(ma["fhr"])[ma["d"]:ma["f"] + 1])))
    got = compute_features(rec)["signal_loss_percent"]
    assert ref > 5.0                      # this record genuinely has loss
    assert abs(got - ref) < 1e-6
