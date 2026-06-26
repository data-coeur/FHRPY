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
