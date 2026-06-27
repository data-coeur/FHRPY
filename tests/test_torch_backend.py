"""Parity of the optional torch/GPU FS backend vs the NumPy reference."""
import numpy as np
import pytest

torch = pytest.importorskip("torch", reason="torch backend test needs PyTorch")

import fhrpy.datasets as ds
from fhrpy.falsesignal.detect import load_model
from fhrpy.falsesignal.features import build_dop_features, build_scalp_features
from fhrpy.io import read_fhr


def test_fsdop_torch_matches_numpy():
    from fhrpy.falsesignal.torch_backend import FSDopTorch

    rec = read_fhr(ds.example_path("fs_dopmhr_01"))
    ref = load_model("doppler")(build_dop_features(rec.fhr1, rec.mhr))[0]
    got = FSDopTorch(device="cpu", dtype=torch.float64).detect(rec.fhr1, rec.mhr)
    assert np.max(np.abs(ref - got)) < 1e-9


def test_fsscalp_torch_matches_numpy():
    from fhrpy.falsesignal.torch_backend import FSScalpTorch

    rec = read_fhr(ds.example_path("fs_dopmhr_01"))
    ref = load_model("scalp")(build_scalp_features(rec.fhr1)[0])
    got = FSScalpTorch(device="cpu", dtype=torch.float64).detect(rec.fhr1)
    assert np.max(np.abs(ref - got)) < 1e-9


@pytest.mark.skipif(not torch.cuda.is_available(), reason="no CUDA GPU")
def test_fsdop_gpu_float32_close():
    from fhrpy.falsesignal.torch_backend import FSDopTorch

    rec = read_fhr(ds.example_path("ctg_example_01"))
    ref = load_model("doppler")(build_dop_features(rec.fhr1, rec.mhr))[0]
    got = FSDopTorch().detect(rec.fhr1, rec.mhr)   # default float32 on GPU
    assert np.max(np.abs(ref - got)) < 5e-3


def test_fstf_matches_numpy_if_available():
    tf = pytest.importorskip("tensorflow", reason="TF backend test needs TensorFlow")
    from fhrpy.falsesignal.tf_backend import FSDopTF

    rec = read_fhr(ds.example_path("fs_dopmhr_01"))
    ref = load_model("doppler")(build_dop_features(rec.fhr1, rec.mhr))[0]
    got = FSDopTF().detect(rec.fhr1, rec.mhr)
    assert np.max(np.abs(ref - got)) < 5e-3
