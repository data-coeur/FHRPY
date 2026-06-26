"""Evaluation of the false-signal detector against the expert annotations.

Port of the scoring protocol in FHRMA's ``EvalFSForDataset.m``: the model is run
on the whole recording, then metrics are computed **only on expert-annotated
samples** — the union of the true-signal (``TS_*``) and false-signal (``FS_*``)
ranges — at the 0.5 threshold, plus a threshold-free AUC.

The labeled datasets are ``DopMHRTrain`` / ``DopMHRVal`` (Doppler) and
``ScalpTrain`` / ``ScalpVal`` (scalp ECG). The ``*TestCP`` / ``*TestDbS`` sets
carry no labels and cannot be scored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from ..io import read_fhr
from .detect import detect_false_signals


def _ranges(v) -> np.ndarray:
    """Normalize an annotation field to an ``(k, 2)`` int array of [start, end]."""
    a = np.atleast_2d(np.asarray(v))
    if a.size == 0:
        return np.zeros((0, 2), dtype=int)
    if a.shape[1] != 2 and a.shape[0] == 2:
        a = a.T
    return a.astype(int)


@dataclass
class FSMetrics:
    dataset: str
    stage: int
    n_files: int = 0
    tn: int = 0
    fn: int = 0
    fp: int = 0
    tp: int = 0
    _auc_label: list = field(default_factory=list)
    _auc_prob: list = field(default_factory=list)

    @property
    def annotated(self) -> int:
        return self.tn + self.fn + self.fp + self.tp

    @property
    def sensitivity(self) -> float:
        return self.tp / max(1, self.tp + self.fn)

    @property
    def specificity(self) -> float:
        return self.tn / max(1, self.tn + self.fp)

    @property
    def ppv(self) -> float:
        return self.tp / max(1, self.tp + self.fp)

    @property
    def npv(self) -> float:
        return self.tn / max(1, self.tn + self.fn)

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / max(1, self.annotated)

    @property
    def auc(self) -> float:
        y = np.asarray(self._auc_label)
        s = np.asarray(self._auc_prob)
        n_pos = int((y == 1).sum())
        n_neg = int((y == 0).sum())
        if n_pos == 0 or n_neg == 0:
            return float("nan")
        order = np.argsort(s, kind="mergesort")
        ranks = np.empty(len(s), float)
        ranks[order] = np.arange(1, len(s) + 1)
        # average ranks for ties
        s_sorted = s[order]
        i = 0
        while i < len(s_sorted):
            j = i
            while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
                j += 1
            if j > i:
                ranks[order[i : j + 1]] = (i + 1 + j + 1) / 2.0
            i = j + 1
        sum_pos = ranks[y == 1].sum()
        return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)

    def as_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "stage": self.stage,
            "n_files": self.n_files,
            "annotated_samples": self.annotated,
            "sensitivity": round(self.sensitivity, 4),
            "specificity": round(self.specificity, 4),
            "ppv": round(self.ppv, 4),
            "npv": round(self.npv, 4),
            "accuracy": round(self.accuracy, 4),
            "auc": round(self.auc, 4),
        }


def _stage_match(stage: int, s2) -> bool:
    is_ante = isinstance(s2, str) or (hasattr(s2, "dtype") and s2.dtype.kind in "US")
    s2_num = None
    if not is_ante:
        try:
            s2_num = int(np.asarray(s2))
        except (TypeError, ValueError):
            s2_num = None
    if stage == 0:
        return True
    if stage == -1:
        return is_ante
    if stage == 1:
        return s2_num is None or s2_num > 1
    if stage == 2:
        return s2_num is not None and not is_ante
    return False


def evaluate_dataset(
    dataset: str,
    stage: int = 0,
    kind: str = "doppler",
    fs_root: str | os.PathLike | None = None,
    annotations=None,
    max_files: int | None = None,
    censor_mhr: bool = False,
    threshold: float = 0.5,
) -> FSMetrics:
    """Score the FS detector on ``dataset`` following ``EvalFSForDataset.m``.

    ``fs_root`` is the directory holding the ``.fhrm`` files and
    ``expertAnnotations.mat`` (or pass ``annotations`` = a loaded ``DB`` array).
    Returns aggregated :class:`FSMetrics`.
    """
    import scipy.io as sio

    if annotations is None:
        if fs_root is None:
            raise ValueError("provide fs_root or annotations")
        d = sio.loadmat(os.path.join(fs_root, "expertAnnotations.mat"),
                        squeeze_me=True, struct_as_record=False)
        annotations = d["DB"]

    sig_idx = 1 if kind == "doppler" else 2  # TS/FS column: MHR->0, FHR->1 (here Dop uses FHR)
    m = FSMetrics(dataset=dataset, stage=stage)

    # Index available files by basename for a robust lookup under fs_root.
    files = {}
    if fs_root is not None:
        for root, _, names in os.walk(fs_root):
            for nm in names:
                if nm.lower().endswith(".fhrm"):
                    files[nm] = os.path.join(root, nm)

    for e in annotations:
        if str(e.dataset) != dataset:
            continue
        if not _stage_match(stage, e.Stage2_Start):
            continue
        fn = str(e.filename)
        path = files.get(fn)
        if path is None:
            continue
        ts = _ranges(e.TS_FHR if kind == "doppler" else e.TS_FHR)
        fsr = _ranges(e.FS_FHR if kind == "doppler" else e.FS_FHR)
        if ts.size == 0 and fsr.size == 0:
            continue

        rec = read_fhr(path)
        if censor_mhr:
            rec.mhr[:] = 0
        s2 = e.Stage2_Start
        s2_num = None
        try:
            s2_num = int(np.asarray(s2))
        except (TypeError, ValueError):
            s2_num = None
        out = detect_false_signals(rec, kind=kind, stage2_start=s2_num)
        prob = np.asarray(out["prob"], float)
        n = len(prob)

        label = np.full(n, -1, dtype=int)  # -1 = unannotated
        for a, b in ts:
            label[max(0, a) : min(n, b)] = 0
        for a, b in fsr:
            label[max(0, a) : min(n, b)] = 1

        # Stage restriction on the scored range.
        lo, hi = 0, n
        if stage == 2 and s2_num:
            lo = max(0, s2_num)
        elif stage == 1 and s2_num:
            hi = min(n, max(0, s2_num))
        sel = (label[lo:hi] >= 0)
        if not sel.any():
            continue
        y = label[lo:hi][sel]
        p = prob[lo:hi][sel]
        pred = (p >= threshold).astype(int)
        m.tp += int(((pred == 1) & (y == 1)).sum())
        m.tn += int(((pred == 0) & (y == 0)).sum())
        m.fp += int(((pred == 1) & (y == 0)).sum())
        m.fn += int(((pred == 0) & (y == 1)).sum())
        m._auc_label.extend(y.tolist())
        m._auc_prob.extend(p.tolist())
        m.n_files += 1
        if max_files is not None and m.n_files >= max_files:
            break

    return m
