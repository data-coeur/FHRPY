"""Tests for the viewer save/export (recording + marker file)."""

import os

import numpy as np
import pytest

from fhrpy.io import read_fhr
from fhrpy.viewer import FHRViewer

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "sample.rcfm")


def test_save_markers_roundtrip(tmp_path):
    marks = [[10, "£Question"], [5216, "$ ACC 192"], [100, "hello"]]
    v = FHRViewer(SAMPLE, markers=marks)
    mp = v.save_markers(tmp_path / "rec.marks")
    # Re-loading via a fresh viewer parses the same marks (sorted by sample).
    text = mp.read_text()
    v2 = FHRViewer(SAMPLE, markers=text)
    got = {(s, t) for s, t in v2.markers}
    assert got == {(10, "£Question"), (100, "hello"), (5216, "$ ACC 192")}


def test_save_recording_roundtrip(tmp_path):
    v = FHRViewer(SAMPLE)
    out = v.save_recording(tmp_path / "out.rcfm")
    back = read_fhr(out)
    src = read_fhr(SAMPLE)
    assert len(back) == len(src)
    np.testing.assert_allclose(back.fhr1, src.fhr1)
    np.testing.assert_allclose(back.toco, src.toco)


def test_save_both(tmp_path):
    v = FHRViewer(SAMPLE, markers=[[42, "$ DEC 80"]])
    rec_path, marks_path = v.save(tmp_path / "session")
    assert rec_path.exists() and rec_path.suffix == ".rcfm"
    assert marks_path.exists() and marks_path.suffix == ".marks"
    assert "$ DEC 80" in marks_path.read_text()


def test_save_recording_requires_source(tmp_path):
    with pytest.raises(ValueError):
        FHRViewer(None).save_recording(tmp_path / "x.rcfm")
