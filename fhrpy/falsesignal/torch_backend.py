"""Optional PyTorch / GPU backend for the false-signal GRU networks.

The pure-NumPy :mod:`fhrpy.falsesignal.model` runs the bidirectional stacked
GRUs with an explicit Python time loop. This module maps the very same trained
weights into ``torch.nn.GRU`` (whose cuDNN kernel runs the recurrence on the
GPU) and reproduces the identical bidirectional plumbing in torch, so the output
matches the NumPy reference exactly in float64 (CPU, ~1e-14) and closely in
the default float32 GPU path (~1e-3), while running the recurrence on the GPU.

Key weight mapping — Keras ``GRU(reset_after=True)`` (gate order ``z|r|h``) maps
onto ``torch.nn.GRU`` (which is *already* reset-after, gate order ``r|z|n``):
just reorder the gate blocks ``z|r|h -> r|z|n`` for the kernels and the two bias
rows. torch keeps separate input/recurrent biases, matching Keras' two-row bias.

PyTorch is an OPTIONAL dependency: importing this module requires ``torch``.
"""
from __future__ import annotations

import numpy as np

try:
    import torch
    import torch.nn as nn
except ImportError as e:  # pragma: no cover
    raise ImportError("the torch backend requires PyTorch (`pip install torch`)") from e

from .detect import load_model
from .features import build_dop_features, build_scalp_features


def _gru_from_keras(layer, device, dtype):
    """Build a torch GRU equivalent to a Keras reset_after GRULayer (gate z|r|h)."""
    W, U, B = layer.W, layer.U, layer.B
    m, n = W.shape[0], U.shape[0]
    Wz, Wr, Wh = W[:, :n], W[:, n:2 * n], W[:, 2 * n:3 * n]
    Uz, Ur, Uh = U[:, :n], U[:, n:2 * n], U[:, 2 * n:3 * n]
    g = nn.GRU(m, n, batch_first=False).to(device=device, dtype=dtype)
    with torch.no_grad():
        g.weight_ih_l0.copy_(torch.tensor(np.concatenate([Wr, Wz, Wh], 1).T, dtype=dtype))
        g.weight_hh_l0.copy_(torch.tensor(np.concatenate([Ur, Uz, Uh], 1).T, dtype=dtype))
        bi, br = B[0], B[1]
        g.bias_ih_l0.copy_(torch.tensor(np.concatenate([bi[n:2 * n], bi[:n], bi[2 * n:3 * n]]), dtype=dtype))
        g.bias_hh_l0.copy_(torch.tensor(np.concatenate([br[n:2 * n], br[:n], br[2 * n:3 * n]]), dtype=dtype))
    return g


class _DenseT:
    def __init__(self, dense, device, dtype):
        self.W = torch.tensor(dense.W, device=device, dtype=dtype)
        self.b = torch.tensor(np.asarray(dense.b).reshape(-1), device=device, dtype=dtype)

    def __call__(self, x):
        return torch.sigmoid(x @ self.W + self.b)


class FSDopTorch(nn.Module):
    """GPU port of :class:`fhrpy.falsesignal.model.FSDopModel`."""

    def __init__(self, model=None, device=None, dtype=torch.float32):
        super().__init__()
        model = model or load_model("doppler")
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.dtype = dtype
        self.g1m = _gru_from_keras(model.GRU1MHR, self.device, dtype)
        self.g1 = _gru_from_keras(model.GRU1, self.device, dtype)
        self.g2 = _gru_from_keras(model.GRU2, self.device, dtype)
        self.g3 = _gru_from_keras(model.GRU3, self.device, dtype)
        self.densePmat = _DenseT(model.DensePmat, self.device, dtype)
        self.dense1 = _DenseT(model.Dense1, self.device, dtype)

    @torch.no_grad()
    def forward(self, I):
        """``I``: (T, 5) array/tensor. Returns ``(PDop, PMat)`` numpy arrays."""
        I = torch.as_tensor(np.ascontiguousarray(np.asarray(I)), device=self.device, dtype=self.dtype)
        RevI = torch.flip(I, [0])
        G1M, _ = self.g1m(torch.stack([I, RevI], 1).contiguous())         # (T,2,12)
        PMat = self.densePmat(torch.cat([G1M[:, 0], torch.flip(G1M[:, 1], [0])], 1))[:, 0]
        RPMat = torch.flip(PMat, [0])
        L0 = torch.stack([torch.cat([PMat[:, None], I], 1),
                          torch.cat([RPMat[:, None], RevI], 1)], 1).contiguous()  # (T,2,6)
        G1, _ = self.g1(L0)

        def bidir(G):
            f = torch.cat([G[:, 0], torch.flip(G[:, 1], [0]), PMat[:, None], I], 1)
            r = torch.cat([torch.flip(G[:, 0], [0]), G[:, 1], RPMat[:, None], RevI], 1)
            return torch.stack([f, r], 1).contiguous()

        G2, _ = self.g2(bidir(G1))
        G3, _ = self.g3(bidir(G2))
        CDop = torch.cat([G3[:, 0], torch.flip(G3[:, 1], [0])], 1)
        PDop = self.dense1(CDop)[:, 0]
        return PDop.cpu().numpy(), PMat.cpu().numpy()

    def detect(self, fhr, mhr, stage2_start=None):
        """Run from raw FHR/MHR channels; returns P(false) for the Doppler FHR."""
        I = build_dop_features(np.asarray(fhr), np.asarray(mhr), stage2_start)
        I = I.T if I.shape[0] == 5 else I
        return self.forward(I)[0]


class FSScalpTorch(nn.Module):
    """GPU port of :class:`fhrpy.falsesignal.model.FSScalpModel`."""

    def __init__(self, model=None, device=None, dtype=torch.float32):
        super().__init__()
        model = model or load_model("scalp")
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.dtype = dtype
        self.g1 = _gru_from_keras(model.GRU1, self.device, dtype)
        self.g2 = _gru_from_keras(model.GRU2, self.device, dtype)
        self.g3 = _gru_from_keras(model.GRU3, self.device, dtype)
        self.dense1 = _DenseT(model.Dense1, self.device, dtype)

    @torch.no_grad()
    def forward(self, I):
        I = torch.as_tensor(np.ascontiguousarray(np.asarray(I)), device=self.device, dtype=self.dtype)
        RevI = torch.flip(I, [0])

        def bidir_in(G):
            f = torch.cat([G[:, 0], torch.flip(G[:, 1], [0]), I], 1)
            r = torch.cat([torch.flip(G[:, 0], [0]), G[:, 1], RevI], 1)
            return torch.stack([f, r], 1).contiguous()

        G1, _ = self.g1(torch.stack([I, RevI], 1).contiguous())
        G2, _ = self.g2(bidir_in(G1))
        G3, _ = self.g3(bidir_in(G2))
        CDop = torch.cat([G3[:, 0], torch.flip(G3[:, 1], [0])], 1)
        return self.dense1(CDop)[:, 0].cpu().numpy()

    def detect(self, fhr, stage2_start=None):
        I = build_scalp_features(np.asarray(fhr), stage2_start)[0]  # (I, fhr_cleaned)
        I = I.T if I.shape[0] == 3 else I
        return self.forward(I)
