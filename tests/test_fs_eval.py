"""Evaluation-protocol test for the false-signal detector.

The labeled FS dataset is not bundled in the repo, so this test skips unless the
dataset path is provided via the ``FHRPY_FS_DATASET`` environment variable (the
directory containing the ``.fhrm`` files and ``expertAnnotations.mat``).

It checks that the ``EvalFSForDataset``-style protocol runs and that the detector
reaches a strong AUC on a small labeled subset (sanity, not a parity assertion).
"""

import os

import pytest

FS_ROOT = os.environ.get("FHRPY_FS_DATASET")


@pytest.mark.skipif(
    not (FS_ROOT and os.path.exists(os.path.join(FS_ROOT, "expertAnnotations.mat"))),
    reason="set FHRPY_FS_DATASET to the FS dataset dir to run this evaluation",
)
def test_fs_doppler_auc_on_subset():
    from fhrpy.falsesignal import evaluate_dataset

    m = evaluate_dataset("DopMHRTrain", stage=0, kind="doppler",
                         fs_root=FS_ROOT, max_files=8)
    d = m.as_dict()
    assert d["n_files"] >= 1
    assert d["annotated_samples"] > 1000
    # The detector should clearly separate true vs false signals.
    assert d["auc"] > 0.9
    assert d["sensitivity"] > 0.8
