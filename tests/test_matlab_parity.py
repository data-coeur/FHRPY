"""MATLAB/Octave parity tests for the FHRPY NumPy ports.

These tests compare the FHRPY pipeline against reference outputs produced by the
ORIGINAL FHRMA MATLAB sources run under GNU Octave (see ``docker/octave/``).

To (re)generate the references::

    bash docker/octave/run.sh

That writes ``docker/octave/out/ref_<name>.mat`` (MATLAB v7, scipy-readable)
plus copies the dataset inputs into ``docker/octave/out/extra_inputs/``. If the
references are absent (e.g. on a machine without Docker/the dataset), every test
in this module is skipped with a clear reason -- it never fails the suite.

What is checked, and the parity achieved on the three reference recordings
(example_recording = train01, ~58 min; train03 ~40 min; train19 ~29 min):

* ``read_fhr`` vs ``fhropen``           -> EXACT (max abs diff 0.0).
* ``preprocess`` FHRi vs ``preprocess`` -> EXACT (max abs diff 0.0).
* order-1 ``butterfilt`` (the 1 cpm low-pass) -> ~1e-12 (machine precision;
  Octave used the original ``multisigfilter`` C path, not the filtfilt fallback).
* WMFB ``baseline`` -> mean abs diff ~0.27-0.49 bpm, 95th pct <= ~1.5 bpm, but
  with localized blocks up to ~45-87 bpm (signal tail + a few interior regions)
  caused by the documented WMFB port risks: the ``decimate``/``interp`` FIR
  approximations and weighted-median tie-breaking. We therefore assert on
  ROBUST statistics (mean / percentile / matched-event boundaries), not the raw
  max, and record the measured numbers below.
* accel/decel segments -> matched events agree to ~1-2 s; event *counts* can
  differ by +-1 from the same tie-breaking sensitivity, so we allow a small
  count slack.

Tolerances are deliberately a bit looser than the best observed values so the
test is stable across SciPy/BLAS versions; tighten if the port improves.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

HERE = os.path.dirname(__file__)
REPO = os.path.dirname(HERE)
OUTDIR = os.path.join(REPO, "docker", "octave", "out")

scipy_io = pytest.importorskip("scipy.io", reason="scipy required for parity tests")

from fhrpy.io import read_fhr  # noqa: E402
from fhrpy.preprocess.preprocess import preprocess  # noqa: E402
from fhrpy.preprocess.dsp import butterfilt  # noqa: E402
from fhrpy.baseline import wmfb  # noqa: E402


# Map reference name -> the .fhr input that produced it. The example lives in
# the repo; the dataset files are staged next to the references by run.sh.
_CASES = {
    "example_recording": os.path.join(REPO, "examples", "example_recording.fhr"),
    "train03": os.path.join(OUTDIR, "extra_inputs", "train03.fhr"),
    "train19": os.path.join(OUTDIR, "extra_inputs", "train19.fhr"),
}


def _available_cases():
    cases = []
    for name, path in _CASES.items():
        ref = os.path.join(OUTDIR, f"ref_{name}.mat")
        if os.path.exists(ref) and os.path.exists(path):
            cases.append((name, path, ref))
    return cases


_AVAILABLE = _available_cases()

pytestmark = pytest.mark.skipif(
    not _AVAILABLE,
    reason=(
        "Octave reference .mat files not found in docker/octave/out/. "
        "Generate them with: bash docker/octave/run.sh"
    ),
)


def _ids(cases):
    return [c[0] for c in cases]


@pytest.fixture(scope="module")
def loaded():
    """Load each reference + compute the FHRPY pipeline once per case."""
    out = {}
    for name, path, ref in _AVAILABLE:
        m = scipy_io.loadmat(ref)
        rec = read_fhr(path)
        fhri, fhr, toco, d, f = preprocess(rec.fhr1, rec.fhr2, rec.toco)
        baseline, acc, dec, facc, fdec = wmfb(fhri)
        out[name] = dict(
            mat=m, rec=rec, fhri=fhri, d=d, f=f,
            baseline=baseline, acc=acc, dec=dec,
        )
    return out


# ---------------------------------------------------------------------------
# 1. read_fhr vs fhropen  -- must be EXACT
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,path,ref", _AVAILABLE, ids=_ids(_AVAILABLE))
def test_read_fhr_exact(name, path, ref):
    m = scipy_io.loadmat(ref)
    rec = read_fhr(path)
    for py, key in (
        (rec.fhr1, "FHR1raw"),
        (rec.fhr2, "FHR2raw"),
        (rec.toco, "TOCO"),
    ):
        mat = m[key].ravel()
        assert len(py) == len(mat), f"{key} length mismatch"
        # Decoded signals are integers/4 or /2 -> must be bit-exact.
        assert np.array_equal(py, mat), (
            f"{key} differs from fhropen (max abs "
            f"{np.max(np.abs(py - mat))})"
        )


# ---------------------------------------------------------------------------
# 2. preprocess FHRi  -- must be EXACT
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,path,ref", _AVAILABLE, ids=_ids(_AVAILABLE))
def test_preprocess_exact(name, path, ref):
    m = scipy_io.loadmat(ref)
    rec = read_fhr(path)
    fhri, fhr, toco, d, f = preprocess(rec.fhr1, rec.fhr2, rec.toco)
    ref_fhri = m["FHRi"].ravel()
    assert len(fhri) == len(ref_fhri)
    maxabs = float(np.max(np.abs(fhri - ref_fhri)))
    assert maxabs == 0.0, f"preprocess FHRi max abs diff {maxabs}"
    # MATLAB d/f are 1-based; FHRPY returns 0-based.
    assert d == int(m["d"].ravel()[0]) - 1
    assert f == int(m["f"].ravel()[0]) - 1


# ---------------------------------------------------------------------------
# 3. order-1 butterfilt (the 1 cpm low-pass) -- machine precision
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,path,ref", _AVAILABLE, ids=_ids(_AVAILABLE))
def test_butterfilt_order1(name, path, ref, loaded):
    m = loaded[name]["mat"]
    fhri = loaded[name]["fhri"]
    bl1 = butterfilt(fhri, 240, 0, 1, 1, True)
    ref_bl1 = m["bl_FHR1"].ravel()
    maxabs = float(np.max(np.abs(bl1 - ref_bl1)))
    # Octave used the original multisigfilter C path; order-1 matches to ~1e-12.
    assert maxabs < 1e-8, f"butterfilt(order1) max abs diff {maxabs}"


# ---------------------------------------------------------------------------
# 4. WMFB baseline -- robust-statistic parity (documented divergence)
# ---------------------------------------------------------------------------
# Observed (Octave 9.2.0, SciPy at port time):
#   example: mean 0.27, p95 0.53, max 87    (max is tail + a few interior blocks)
#   train03: mean 0.49, p95 1.48, max 46
#   train19: mean 0.27, p95 0.42, max 42
# We assert on mean and the 95th percentile (loosened for cross-version
# stability) rather than the raw max, which is dominated by the interp/decimate
# FIR edge behaviour and weighted-median tie-breaking.
_BASELINE_MEAN_TOL = 1.0   # bpm  (best observed <= 0.49)
_BASELINE_P95_TOL = 3.0    # bpm  (best observed <= 1.48)


@pytest.mark.parametrize("name,path,ref", _AVAILABLE, ids=_ids(_AVAILABLE))
def test_wmfb_baseline_robust(name, path, ref, loaded):
    m = loaded[name]["mat"]
    base = loaded[name]["baseline"]
    ref_base = m["baseline"].ravel()
    assert len(base) == len(ref_base)
    diff = np.abs(base - ref_base)

    mean_d = float(diff.mean())
    p95_d = float(np.percentile(diff, 95))
    # Reported for visibility in -s / -rA runs.
    print(
        f"\n[{name}] WMFB baseline: mean={mean_d:.4f} p95={p95_d:.4f} "
        f"p99={np.percentile(diff, 99):.3f} max={diff.max():.3f} bpm"
    )
    assert mean_d <= _BASELINE_MEAN_TOL, f"{name}: mean baseline diff {mean_d:.3f} bpm"
    assert p95_d <= _BASELINE_P95_TOL, f"{name}: p95 baseline diff {p95_d:.3f} bpm"
    # The vast majority of samples must agree within 1 bpm.
    assert np.mean(diff <= 1.0) >= 0.90, (
        f"{name}: only {np.mean(diff <= 1.0):.3f} of samples within 1 bpm"
    )


# ---------------------------------------------------------------------------
# 5. accel / decel segment boundaries
# ---------------------------------------------------------------------------
def _ref_segments(mat_arr):
    """``(>=2, k)`` MATLAB [start;end;...] (seconds) -> list[(start, end)]."""
    if mat_arr.size == 0:
        return []
    return [(float(mat_arr[0, i]), float(mat_arr[1, i])) for i in range(mat_arr.shape[1])]


def _match_events(py_segs, ref_segs, tol_s):
    """Greedy event matching by combined start+end distance.

    A python event is considered *matched* to a reference event only when BOTH
    its start and end fall within ``tol_s``. Events that do not (e.g. one side
    split a single accident into two, or shifted a boundary by more than the
    tolerance because of a local baseline difference) are returned as unmatched
    on the respective side -- the caller absorbs a small number of these via the
    event-count slack. Returns ``(matched_pairs, n_py_unmatched, n_ref_unmatched)``.
    """
    ref_left = list(ref_segs)
    matched = []
    py_unmatched = 0
    for ps, pe in py_segs:
        best, bj = None, None
        for j, (rs, re) in enumerate(ref_left):
            d = abs(ps - rs) + abs(pe - re)
            if best is None or d < best:
                best, bj = d, j
        if (
            bj is not None
            and abs(ps - ref_left[bj][0]) <= tol_s
            and abs(pe - ref_left[bj][1]) <= tol_s
        ):
            matched.append(((ps, pe), ref_left.pop(bj)))
        else:
            py_unmatched += 1
    return matched, py_unmatched, len(ref_left)


_EVENT_TOL_S = 2.5       # matched events: start/end agreement (seconds)
_EVENT_COUNT_SLACK = 2   # allowed event-count difference per signal (see below)
_COVERAGE_TOL = 0.92     # fraction of ref event-time that must be covered by py


def _coverage(py_segs, ref_segs):
    """Fraction of total reference event-time overlapped by python events."""
    ref_total = sum(re - rs for rs, re in ref_segs)
    if ref_total == 0:
        return 1.0
    covered = 0.0
    for rs, re in ref_segs:
        for ps, pe in py_segs:
            covered += max(0.0, min(pe, re) - max(ps, rs))
    return covered / ref_total


@pytest.mark.parametrize("name,path,ref", _AVAILABLE, ids=_ids(_AVAILABLE))
def test_accel_decel_boundaries(name, path, ref, loaded):
    m = loaded[name]["mat"]
    for kind, py_segs, ref_key in (
        ("acc", loaded[name]["acc"], "acc"),
        ("dec", loaded[name]["dec"], "dec"),
    ):
        ref_segs = _ref_segments(m[ref_key])
        matched, py_unmatched, ref_unmatched = _match_events(
            py_segs, ref_segs, _EVENT_TOL_S
        )
        cov = _coverage(py_segs, ref_segs)
        print(
            f"\n[{name}] {kind}: py={len(py_segs)} ref={len(ref_segs)} "
            f"matched={len(matched)} py_unmatched={py_unmatched} "
            f"ref_unmatched={ref_unmatched} coverage={cov:.3f}"
        )

        # Count parity within a small slack. The WMFB baseline divergence can
        # occasionally split one accident into two (or merge two), changing the
        # count by 1-2 -- see train19 dec (446-530 s) where py emits two
        # sub-decelerations for MATLAB's single one.
        assert abs(len(py_segs) - len(ref_segs)) <= _EVENT_COUNT_SLACK, (
            f"{name} {kind}: count py={len(py_segs)} ref={len(ref_segs)}"
        )

        # Every cleanly-matched event must agree on start AND end to ~tol.
        for (ps, pe), (rs, re) in matched:
            assert abs(ps - rs) <= _EVENT_TOL_S, f"{name} {kind}: start {ps} vs {rs}"
            assert abs(pe - re) <= _EVENT_TOL_S, f"{name} {kind}: end {pe} vs {re}"

        # The bulk of MATLAB's event-time must still be detected by FHRPY, even
        # where a boundary was split/shifted (coverage is robust to splits).
        assert cov >= _COVERAGE_TOL, (
            f"{name} {kind}: event-time coverage {cov:.3f} < {_COVERAGE_TOL}"
        )
        # Almost all events should match cleanly; allow the slack for split/merge.
        assert ref_unmatched <= _EVENT_COUNT_SLACK, (
            f"{name} {kind}: {ref_unmatched} ref events unmatched"
        )
