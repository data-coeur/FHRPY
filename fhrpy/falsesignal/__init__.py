"""FHRPY false-signal (FS) detection subpackage.

NumPy port of the FHRMA deep-learning false-signal detectors (paper [6],
Biosensors 2022): bidirectional stacked GRU networks that flag, at 4 Hz, samples
where a heart-rate channel is a false signal (Doppler tracking the maternal HR
instead of the fetal one, or sensor holds/artefacts). Inference needs no
TensorFlow — weights are loaded from the bundled ``FSDop.mat`` / ``FSScalp.mat``.
"""

from .detect import detect_false_signals, load_model, mask_to_segments
from .features import (
    build_dop_features,
    build_scalp_features,
    normalize_hr,
    remove_holds,
)
from .model import Dense, FSDopModel, FSScalpModel, GRULayer, sigmoid

__all__ = [
    "detect_false_signals",
    "load_model",
    "mask_to_segments",
    "build_dop_features",
    "build_scalp_features",
    "normalize_hr",
    "remove_holds",
    "GRULayer",
    "Dense",
    "FSDopModel",
    "FSScalpModel",
    "sigmoid",
]
