"""High-level false-signal (FS) detection API.

Detects, at 4 Hz, samples where a heart-rate channel is a *false signal* —
typically a Doppler probe tracking the **maternal** heart rate instead of the
fetal one (MHR/FHR confusion), or sensor holds/artefacts. Outputs a per-sample
probability ``P(false)`` thresholded at ``0.5``.

Weights ``FSDop.mat`` / ``FSScalp.mat`` are bundled in
``fhrpy/falsesignal/weights/`` and read via :mod:`importlib.resources` so they
survive a pip install.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .features import build_dop_features, build_scalp_features
from .model import FSDopModel, FSScalpModel

try:  # Python 3.9+: read packaged data after pip install
    from importlib import resources as _resources
except ImportError:  # pragma: no cover
    import importlib_resources as _resources  # type: ignore

__all__ = ["detect_false_signals", "load_model", "mask_to_segments"]

_WEIGHT_FILES = {"doppler": "FSDop.mat", "scalp": "FSScalp.mat"}


def _load_mat(name: str) -> dict:
    from scipy.io import loadmat

    pkg = "fhrpy.falsesignal.weights"
    try:
        with _resources.as_file(_resources.files(pkg).joinpath(name)) as p:
            return loadmat(str(p))
    except (AttributeError, FileNotFoundError):  # pragma: no cover
        from pathlib import Path

        here = Path(__file__).resolve().parent / "weights" / name
        return loadmat(str(here))


@lru_cache(maxsize=None)
def _load_model_cached(kind: str):
    mat = _load_mat(_WEIGHT_FILES[kind])
    return FSDopModel.from_mat(mat) if kind == "doppler" else FSScalpModel.from_mat(mat)


def load_model(kind: str = "doppler"):
    """Load and cache the FS model for ``kind`` in ``{"doppler", "scalp"}``.

    Accepts the same aliases as :func:`detect_false_signals` (e.g. ``"dop"``)
    and returns the same cached instance regardless of the alias used.
    """
    return _load_model_cached(_canon_kind(kind))


def _canon_kind(kind: str) -> str:
    k = str(kind).lower()
    if k in ("doppler", "dop", "fsdop"):
        return "doppler"
    if k in ("scalp", "ecg", "scalpecg", "fsscalp"):
        return "scalp"
    raise ValueError(f"unknown kind {kind!r}; expected 'doppler' or 'scalp'")


def mask_to_segments(mask: np.ndarray, fs: float = 4.0) -> list[tuple[float, float]]:
    """Turn a boolean per-sample mask into a list of ``(start_s, end_s)`` segments.

    ``end_s`` is exclusive of the sample after the run, i.e. a run of samples
    ``[a, b]`` (inclusive) maps to ``(a/fs, (b+1)/fs)``.
    """
    mask = np.asarray(mask, dtype=bool)
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.nonzero(edges == 1)[0]
    ends = np.nonzero(edges == -1)[0]  # exclusive end index
    return [(float(s) / fs, float(e) / fs) for s, e in zip(starts, ends)]


def detect_false_signals(
    record,
    kind: str = "doppler",
    stage2_start: int | None = None,
    *,
    channel: str | None = None,
    threshold: float = 0.5,
) -> dict:
    """Detect false-signal episodes in an :class:`~fhrpy.io.FHRRecord`.

    Parameters
    ----------
    record : FHRRecord
        The recording (4 Hz). The FHR channel used is ``record.fhr1`` by default;
        for scalp recordings the scalp ECG is usually ``fhr2`` — pass
        ``channel="fhr2"`` to select it. The Doppler model also uses
        ``record.mhr`` (zeros if absent — equivalent to running FSDop without
        MHR, i.e. the ``censorMHR`` mode of ``EvalFSForDataset.m``).
    kind : {"doppler", "scalp"}
        Which model to run.
    stage2_start : int, optional
        4 Hz sample index where the second stage of labor begins (``isStage2``
        becomes 1 from there). ``None`` => first stage throughout. A negative
        value flags the whole record as second stage (antepartum/2nd-stage).
    channel : str, optional
        Which record attribute holds the FHR to analyse (``"fhr1"`` default,
        ``"fhr2"`` for scalp).
    threshold : float
        Decision threshold on ``P(false)`` (default 0.5).

    Returns
    -------
    dict with keys:
        ``prob``       : ``(N,)`` float per-sample P(false) for the FHR channel.
        ``mask``       : ``(N,)`` bool, ``prob >= threshold``.
        ``segments``   : list of ``(start_s, end_s)`` false-signal segments.
        ``prob_mhr``   : ``(N,)`` float P(MHR false) — Doppler only, else ``None``.
        ``fhr_clean``  : FHR after hold removal — Scalp only, else ``None``.
        ``kind``       : the resolved model kind.
        ``fs``         : sampling rate.
    """
    kind = _canon_kind(kind)
    fs = float(getattr(record, "fs", 4.0) or 4.0)
    chan = channel or ("fhr2" if kind == "scalp" else "fhr1")
    fhr = np.asarray(getattr(record, chan), dtype=np.float64)

    model = load_model(kind)
    prob_mhr = None
    fhr_clean = None

    if kind == "doppler":
        mhr = np.asarray(getattr(record, "mhr", np.zeros_like(fhr)), dtype=np.float64)
        if mhr.shape != fhr.shape:
            mhr = np.zeros_like(fhr)
        I = build_dop_features(fhr, mhr, stage2_start)
        prob, prob_mhr = model(I)
    else:
        I, fhr_clean = build_scalp_features(fhr, stage2_start)
        prob = model(I)

    prob = np.asarray(prob, dtype=np.float64)
    mask = prob >= threshold
    segments = mask_to_segments(mask, fs=fs)

    return {
        "prob": prob,
        "mask": mask,
        "segments": segments,
        "prob_mhr": prob_mhr,
        "fhr_clean": fhr_clean,
        "kind": kind,
        "fs": fs,
    }
