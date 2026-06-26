"""Dependency-light NumPy implementation of the FHRMA false-signal (FS)
inference networks.

This is a faithful port of the MATLAB inference code in ``FalseSigDetectDopMHR.m``
and ``FalseSigDetectScalp.m`` (FHRMA toolbox, paper [6], Biosensors 2022). The
networks are bidirectional stacked GRUs whose weights were trained in
TensorFlow/Keras and exported to ``FSDop.mat`` / ``FSScalp.mat`` via
``scipy.io.savemat``. **No TensorFlow is required at inference time** — every
layer is re-implemented here as plain NumPy matrix ops.

GRU convention (matches Keras ``GRU`` with ``reset_after=True``)
---------------------------------------------------------------
Keras ``layer.get_weights()`` returns ``[W, U, B]`` where

* ``W`` is the input kernel of shape ``(m, 3n)``,
* ``U`` is the recurrent kernel of shape ``(n, 3n)``,
* ``B`` is the bias of shape ``(2, 3n)`` — row 0 = input bias, row 1 =
  recurrent bias (the two-row layout exists *because* ``reset_after=True``).

The ``3n`` columns are ordered ``[z (update) | r (reset) | h (candidate)]``
(Keras' fixed gate order). The recurrence, with ``reset_after=True``, applies
the reset gate **after** the recurrent matmul + recurrent bias (this is what
lets the two bias rows be kept separate):

    z = sigmoid( x @ Wz + h_{t-1} @ Uz + bz_in + bz_rec )
    r = sigmoid( x @ Wr + h_{t-1} @ Ur + br_in + br_rec )
    hh = tanh( x @ Wh + bh_in + r * (h_{t-1} @ Uh + bh_rec) )
    h_t = z * h_{t-1} + (1 - z) * hh

(``h_0 = (1 - z) * hh`` with ``h_{-1} = 0``.) This is exactly the recurrence
hand-coded in the MATLAB ``GRU`` local function; see ``model`` notes there.

Bidirectionality is handled exactly as in MATLAB: the input ``I`` and its
time-reverse ``flipud(I)`` are stacked along a "batch" page dimension, a single
forward GRU is run over both pages, then for each layer the forward result is
concatenated (along the feature axis) with the time-flip of the reverse result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class GRULayer:
    """A single forward GRU (Keras ``reset_after=True``, gate order z|r|h).

    Weights:
        W : input kernel, shape ``(m, 3n)``
        U : recurrent kernel, shape ``(n, 3n)``
        B : bias, shape ``(2, 3n)`` (row 0 = input bias, row 1 = recurrent bias)
    """

    W: np.ndarray
    U: np.ndarray
    B: np.ndarray

    @property
    def units(self) -> int:
        return self.U.shape[0]

    def forward(self, I: np.ndarray) -> np.ndarray:
        """Run the GRU over time.

        Parameters
        ----------
        I : array, shape ``(T, m, P)``
            ``T`` time steps, ``m`` input features, ``P`` pages (the batch/page
            dimension carrying forward + reverse copies). A 2-D ``(T, m)`` input
            is treated as a single page.

        Returns
        -------
        O : array, shape ``(T, n, P)`` — hidden state sequence per page.
        """
        squeeze = I.ndim == 2
        if squeeze:
            I = I[:, :, None]
        T, m, P = I.shape
        n = self.units
        W, U, B = self.W, self.U, self.B

        # Wx[t] = I[t] @ W, batched over the page dim. Shape (T, 3n, P).
        # einsum over (t,m,p) x (m,3n) -> (t,3n,p)
        Wx = np.einsum("tmp,mk->tkp", I, W)

        b_in = B[0]            # (3n,)
        b_rec = B[1]           # (3n,)
        bz = (b_in[:n] + b_rec[:n])[None, :]            # (1, n)
        br = (b_in[n:2 * n] + b_rec[n:2 * n])[None, :]  # (1, n)
        bh_in = b_in[2 * n:3 * n][None, :]              # (1, n)
        bh_rec = b_rec[2 * n:3 * n][None, :]            # (1, n)

        O = np.zeros((T, n, P), dtype=np.float64)
        h_prev = np.zeros((n, P), dtype=np.float64)
        for t in range(T):
            if t > 0:
                # Uh[k,p] = sum_j h_prev[j,p] * U[j,k]  -> (3n, P)
                Uh = U.T @ h_prev
            else:
                Uh = np.zeros((3 * n, P), dtype=np.float64)

            wx = Wx[t]  # (3n, P)
            z = sigmoid(wx[:n] + Uh[:n] + bz.T)
            r = sigmoid(wx[n:2 * n] + Uh[n:2 * n] + br.T)
            hh = np.tanh(wx[2 * n:3 * n] + bh_in.T + r * (Uh[2 * n:3 * n] + bh_rec.T))
            if t > 0:
                h = z * h_prev + (1.0 - z) * hh
            else:
                h = (1.0 - z) * hh
            O[t] = h
            h_prev = h

        return O[:, :, 0] if squeeze else O


@dataclass
class Dense:
    """Fully connected layer with sigmoid activation: ``sigmoid(I @ W + b)``."""

    W: np.ndarray
    b: np.ndarray

    def forward(self, I: np.ndarray) -> np.ndarray:
        # I: (T, m, P) or (T, m). W: (m, k). b: scalar / (k,) / (1, k).
        out = np.einsum("...m,mk->...k", I, self.W) + np.asarray(self.b).reshape(-1)
        return sigmoid(out)


def _unpack_cell(cell) -> list[np.ndarray]:
    """Turn a scipy ``loadmat`` cell array (object array of arrays) into a list
    of plain float64 numpy arrays in stored order."""
    arrs = cell.ravel() if isinstance(cell, np.ndarray) and cell.dtype == object else cell
    return [np.asarray(a, dtype=np.float64) for a in arrs]


@dataclass
class FSDopModel:
    """The FSDop network (Doppler-FHR false-signal detector + reused FSMHR).

    Input feature layout (per 4 Hz sample), 5 channels, built by
    :mod:`fhrpy.falsesignal.features`::

        [ (FHR>0)*(FHR-120)/60, FHR>0, (MHR>0)*(MHR-120)/60, MHR>0, isStage2 ]
    """

    GRU1MHR: GRULayer
    DensePmat: Dense
    GRU1: GRULayer
    GRU2: GRULayer
    GRU3: GRULayer
    Dense1: Dense

    @classmethod
    def from_mat(cls, mat: dict) -> "FSDopModel":
        g1m = _unpack_cell(mat["GRU1MHR"])
        dpm = _unpack_cell(mat["DensePmat"])
        g1 = _unpack_cell(mat["GRU1"])
        g2 = _unpack_cell(mat["GRU2"])
        g3 = _unpack_cell(mat["GRU3"])
        d1 = _unpack_cell(mat["Dense1"])
        return cls(
            GRU1MHR=GRULayer(*g1m),
            DensePmat=Dense(dpm[0], dpm[1]),
            GRU1=GRULayer(*g1),
            GRU2=GRULayer(*g2),
            GRU3=GRULayer(*g3),
            Dense1=Dense(d1[0], d1[1]),
        )

    def __call__(self, I: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Run FSDop.

        Parameters
        ----------
        I : array, shape ``(5, T)`` (channels x time), matching the MATLAB
            ``I`` layout, or ``(T, 5)``.

        Returns
        -------
        (PDop, PMat) : two ``(T,)`` arrays — P(FHR false) and P(MHR false).
        """
        I = _as_time_first(I, n_feat=5)            # (T, 5)
        RevI = I[::-1]                              # (T, 5)
        # Page 0 = forward, page 1 = reverse.
        IfB = np.stack([I, RevI], axis=2)          # (T, 5, 2)

        # --- MHR sub-model (frozen, reused from FSMHR) ---
        GRU1M = self.GRU1MHR.forward(IfB)          # (T, 12, 2)
        # PMat from bidir GRU1MHR concat: [forward, flip(reverse)] -> (T, 24)
        IPMat = np.concatenate([GRU1M[:, :, 0], GRU1M[::-1, :, 1]], axis=1)
        PMat = self.DensePmat.forward(IPMat)[:, 0]  # (T,)
        RPMat = PMat[::-1]

        # --- Doppler stack: input = [PMat, I] (6 features) per direction ---
        fwd0 = np.concatenate([PMat[:, None], I], axis=1)      # (T, 6)
        rev0 = np.concatenate([RPMat[:, None], RevI], axis=1)  # (T, 6)
        L0 = np.stack([fwd0, rev0], axis=2)                    # (T, 6, 2)
        GRU1 = self.GRU1.forward(L0)                           # (T, 24, 2)

        # L1: per direction concat [GRU1 bidir(48), PMat, I] = 54 features
        L1 = _bidir_with_extra(GRU1, PMat, RPMat, I, RevI)     # (T, 54, 2)
        GRU2 = self.GRU2.forward(L1)                           # (T, 24, 2)
        L2 = _bidir_with_extra(GRU2, PMat, RPMat, I, RevI)     # (T, 54, 2)
        GRU3 = self.GRU3.forward(L2)                           # (T, 24, 2)

        CDop = np.concatenate([GRU3[:, :, 0], GRU3[::-1, :, 1]], axis=1)  # (T, 48)
        PDop = self.Dense1.forward(CDop)[:, 0]                 # (T,)
        return PDop, PMat


@dataclass
class FSScalpModel:
    """The FSScalp network (scalp-ECG FHR false-signal detector).

    Input feature layout (3 channels)::

        [ (FHR>0)*(FHR-120)/60, FHR>0, isStage2 ]
    """

    GRU1: GRULayer
    GRU2: GRULayer
    GRU3: GRULayer
    Dense1: Dense

    @classmethod
    def from_mat(cls, mat: dict) -> "FSScalpModel":
        g1 = _unpack_cell(mat["GRU1"])
        g2 = _unpack_cell(mat["GRU2"])
        g3 = _unpack_cell(mat["GRU3"])
        d1 = _unpack_cell(mat["Dense1"])
        return cls(
            GRU1=GRULayer(*g1),
            GRU2=GRULayer(*g2),
            GRU3=GRULayer(*g3),
            Dense1=Dense(d1[0], d1[1]),
        )

    def __call__(self, I: np.ndarray) -> np.ndarray:
        """Run FSScalp. Returns ``PFHR`` of shape ``(T,)``."""
        I = _as_time_first(I, n_feat=3)
        RevI = I[::-1]
        IfB = np.stack([I, RevI], axis=2)               # (T, 3, 2)

        GRU1 = self.GRU1.forward(IfB)                   # (T, 24, 2)
        L1 = _bidir_with_input(GRU1, I, RevI)           # (T, 48+3, 2)
        GRU2 = self.GRU2.forward(L1)                    # (T, 18, 2)
        L2 = _bidir_with_input(GRU2, I, RevI)           # (T, 36+3, 2)
        GRU3 = self.GRU3.forward(L2)                    # (T, 12, 2)
        CDop = np.concatenate([GRU3[:, :, 0], GRU3[::-1, :, 1]], axis=1)  # (T, 24)
        return self.Dense1.forward(CDop)[:, 0]


# --------------------------------------------------------------------------- #
# bidirectional plumbing helpers
# --------------------------------------------------------------------------- #
def _as_time_first(I: np.ndarray, n_feat: int) -> np.ndarray:
    I = np.asarray(I, dtype=np.float64)
    if I.ndim != 2:
        raise ValueError(f"expected 2-D input, got shape {I.shape}")
    if I.shape[0] == n_feat and I.shape[1] != n_feat:
        I = I.T  # (channels, T) -> (T, channels)
    return I


def _bidir_with_input(GRU: np.ndarray, I: np.ndarray, RevI: np.ndarray) -> np.ndarray:
    """Build the next-layer input for the Scalp graph.

    Forward page  = [GRU_fwd, flip(GRU_rev), I]
    Reverse page  = [flip(GRU_fwd), GRU_rev, RevI]
    matching the MATLAB ``cat(3, cat(2,...), cat(2,...))`` lines.
    """
    GfF, GfR = GRU[:, :, 0], GRU[:, :, 1]
    fwd = np.concatenate([GfF, GfR[::-1], I], axis=1)
    rev = np.concatenate([GfF[::-1], GfR, RevI], axis=1)
    return np.stack([fwd, rev], axis=2)


def _bidir_with_extra(
    GRU: np.ndarray, PMat: np.ndarray, RPMat: np.ndarray, I: np.ndarray, RevI: np.ndarray
) -> np.ndarray:
    """Build the next-layer input for the Dop graph: bidir GRU + PMat + I."""
    GfF, GfR = GRU[:, :, 0], GRU[:, :, 1]
    fwd = np.concatenate([GfF, GfR[::-1], PMat[:, None], I], axis=1)
    rev = np.concatenate([GfF[::-1], GfR, RPMat[:, None], RevI], axis=1)
    return np.stack([fwd, rev], axis=2)
