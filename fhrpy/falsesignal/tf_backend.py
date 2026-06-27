"""Optional TensorFlow / Keras GPU backend for the false-signal GRU networks.

The FS weights were trained in Keras and exported to ``FSDop.mat`` / ``FSScalp.mat``
as ``[W, U, B]`` per GRU — exactly what ``tf.keras.layers.GRU(reset_after=True)``
expects from ``set_weights``. So the mapping is direct (no gate reordering, unlike
the torch backend): each GRU layer is a native Keras GRU loaded with its three
arrays; the bidirectional plumbing (the custom forward/reverse concatenations of
the FHRMA graph) is reproduced with ``tf`` ops, matching
:class:`fhrpy.falsesignal.model.FSDopModel` / ``FSScalpModel``.

TensorFlow is an OPTIONAL dependency (``pip install tensorflow``); it is not a
FHRPY requirement. Runs on the GPU when a TF-GPU build is available, else on CPU.
The notebook ``examples/gpu_inference_tensorflow.ipynb`` self-verifies the output
against the NumPy reference.
"""
from __future__ import annotations

import numpy as np

try:
    import tensorflow as tf
except ImportError as e:  # pragma: no cover
    raise ImportError("the TF backend requires TensorFlow (`pip install tensorflow`)") from e

from .detect import load_model
from .features import build_dop_features, build_scalp_features


def _keras_gru(layer):
    """A native Keras GRU (reset_after=True) loaded with the exported [W, U, B]."""
    n = layer.U.shape[0]
    g = tf.keras.layers.GRU(n, return_sequences=True, reset_after=True,
                            recurrent_activation="sigmoid")
    g.build((None, None, layer.W.shape[0]))
    g.set_weights([np.asarray(layer.W), np.asarray(layer.U), np.asarray(layer.B)])
    return g


def _dense(d):
    W = tf.constant(np.asarray(d.W), dtype=tf.float32)
    b = tf.constant(np.asarray(d.b).reshape(-1), dtype=tf.float32)
    return lambda x: tf.sigmoid(tf.matmul(x, W) + b)


class FSDopTF:
    """TensorFlow port of :class:`fhrpy.falsesignal.model.FSDopModel`."""

    def __init__(self, model=None):
        model = model or load_model("doppler")
        self.g1m, self.g1 = _keras_gru(model.GRU1MHR), _keras_gru(model.GRU1)
        self.g2, self.g3 = _keras_gru(model.GRU2), _keras_gru(model.GRU3)
        self.densePmat, self.dense1 = _dense(model.DensePmat), _dense(model.Dense1)

    def __call__(self, I):
        """``I``: (T, 5). Returns ``(PDop, PMat)`` numpy arrays."""
        I = tf.constant(np.ascontiguousarray(np.asarray(I, dtype=np.float32)))
        RevI = tf.reverse(I, [0])
        G1M = self.g1m(tf.stack([I, RevI], 0))                 # (2, T, 12)
        IPMat = tf.concat([G1M[0], tf.reverse(G1M[1], [0])], 1)
        PMat = self.densePmat(IPMat)[:, 0]
        RPMat = tf.reverse(PMat, [0])
        L0 = tf.stack([tf.concat([PMat[:, None], I], 1),
                       tf.concat([RPMat[:, None], RevI], 1)], 0)
        G1 = self.g1(L0)

        def bidir(G):
            f = tf.concat([G[0], tf.reverse(G[1], [0]), PMat[:, None], I], 1)
            r = tf.concat([tf.reverse(G[0], [0]), G[1], RPMat[:, None], RevI], 1)
            return tf.stack([f, r], 0)

        G2 = self.g2(bidir(G1))
        G3 = self.g3(bidir(G2))
        CDop = tf.concat([G3[0], tf.reverse(G3[1], [0])], 1)
        return self.dense1(CDop)[:, 0].numpy(), PMat.numpy()

    def detect(self, fhr, mhr, stage2_start=None):
        I = build_dop_features(np.asarray(fhr), np.asarray(mhr), stage2_start)
        I = I.T if I.shape[0] == 5 else I
        return self(I)[0]


class FSScalpTF:
    """TensorFlow port of :class:`fhrpy.falsesignal.model.FSScalpModel`."""

    def __init__(self, model=None):
        model = model or load_model("scalp")
        self.g1, self.g2 = _keras_gru(model.GRU1), _keras_gru(model.GRU2)
        self.g3, self.dense1 = _keras_gru(model.GRU3), _dense(model.Dense1)

    def __call__(self, I):
        I = tf.constant(np.ascontiguousarray(np.asarray(I, dtype=np.float32)))
        RevI = tf.reverse(I, [0])

        def bidir_in(G):
            f = tf.concat([G[0], tf.reverse(G[1], [0]), I], 1)
            r = tf.concat([tf.reverse(G[0], [0]), G[1], RevI], 1)
            return tf.stack([f, r], 0)

        G1 = self.g1(tf.stack([I, RevI], 0))
        G2 = self.g2(bidir_in(G1))
        G3 = self.g3(bidir_in(G2))
        CDop = tf.concat([G3[0], tf.reverse(G3[1], [0])], 1)
        return self.dense1(CDop)[:, 0].numpy()

    def detect(self, fhr, stage2_start=None):
        I = build_scalp_features(np.asarray(fhr), stage2_start)[0]
        I = I.T if I.shape[0] == 3 else I
        return self(I)
