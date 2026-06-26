"""Unit tests for fhrpy.io.fhr_file."""

import os

import numpy as np
import pytest

from fhrpy.io import FHRRecord, read_fhr, write_fhr

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "sample.rcfm")


def test_read_sample_rcfm():
    rec = read_fhr(SAMPLE)
    # 8-byte header + 1199 samples of 8 bytes each (9600-byte file).
    assert len(rec) == 1199
    assert rec.fs == 4.0
    # FHR1 has physiological values; TOCO spans a plausible 0..~100 range.
    phys = rec.fhr1[(rec.fhr1 > 50) & (rec.fhr1 < 220)]
    assert phys.size > 500
    assert rec.toco.max() > 50
    assert rec.toco.max() <= 127.5
    # Quality flags decoded for the .rcfm layout.
    assert "Q1" in rec.infos


@pytest.mark.parametrize("ext,with_mhr", [(".fhr", False), (".fhrm", True)])
def test_roundtrip(tmp_path, ext, with_mhr):
    n = 240
    rng = np.random.default_rng(0)
    # Values on the 0.25-bpm / 0.5-toco quantization grid so encoding is exact.
    fhr1 = np.round(rng.uniform(110, 160, n) * 4) / 4
    fhr2 = np.round(rng.uniform(110, 160, n) * 4) / 4
    mhr = np.round(rng.uniform(70, 100, n) * 4) / 4 if with_mhr else np.zeros(n)
    toco = np.round(rng.uniform(0, 100, n) * 2) / 2
    rec = FHRRecord(fhr1=fhr1, fhr2=fhr2, mhr=mhr, toco=toco, timestamp=1700000000)

    path = tmp_path / f"rt{ext}"
    write_fhr(path, rec, with_mhr=with_mhr)
    back = read_fhr(path, header=4)

    assert back.timestamp == 1700000000
    np.testing.assert_allclose(back.fhr1, fhr1)
    np.testing.assert_allclose(back.fhr2, fhr2)
    np.testing.assert_allclose(back.toco, toco)
    if with_mhr:
        np.testing.assert_allclose(back.mhr, mhr)


def test_quality_byte_roundtrip(tmp_path):
    n = 10
    z = np.zeros(n)
    rec = FHRRecord(
        fhr1=np.full(n, 140.0), fhr2=z, mhr=np.full(n, 80.0), toco=z, timestamp=0,
        infos={"Q1": np.ones(n, bool), "isECG1": np.zeros(n, bool),
               "isIUP": np.ones(n, bool)},
    )
    path = tmp_path / "q.fhrm"
    write_fhr(path, rec, with_mhr=True)
    back = read_fhr(path, header=4)
    assert back.infos["Q1"].all()
    assert not back.infos["isECG1"].any()
    assert back.infos["isIUP"].all()
