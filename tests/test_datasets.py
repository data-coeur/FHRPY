"""Tests for the bundled FHRMA example dataset + its loader."""
import numpy as np
import pytest

import fhrpy.datasets as ds
from fhrpy.viewer import FHRViewer


def test_registry_and_files_present():
    names = ds.example_names()
    assert names, "no bundled examples registered"
    for e in ds.list_examples():
        assert ds.example_path(e["name"]).exists()
        assert (ds._DIR / e["markers"]).exists()


def test_morpho_has_expert_baseline_and_zones():
    name = "morpho_train21"
    bl = ds.expert_baseline(name)
    assert bl is not None and bl.ndim == 1 and bl.size > 1000
    marks = ds.example_markers(name)
    types = {m[1][2:5] for m in marks if m[1].startswith("$")}
    assert {"ACC", "DEC"} & types


def test_falsesig_has_urs_and_protected_expulsion():
    name = "fs_dopmhr_01"
    marks = ds.example_markers(name)
    assert any(m[1].startswith("$ URS") for m in marks), "no false-signal zones"
    # the expulsion mark is protected (the £ prefix marks a non-editable mark)
    assert any(m[1] == "£Expulsion" for m in marks)


@pytest.mark.parametrize("source", ["expert", "method", "raw"])
def test_load_example_builds_viewer(source):
    v = ds.load_example("morpho_train19", source=source, height=300)
    assert isinstance(v, FHRViewer)
    assert len(v.data) > 0
    html = v._build_html()
    assert "FHRViewer" in html and "{{DATA_B64}}" not in html  # placeholder substituted


def test_timestamp_is_zeroed():
    from fhrpy.io import read_fhr

    rec = read_fhr(ds.example_path("fs_dopmhr_01"))
    assert int(rec.timestamp) == 0


def test_from_record_roundtrip_baseline():
    from fhrpy.io import read_fhr

    rec = read_fhr(ds.example_path("morpho_train19"))
    rec.baseline = np.full(len(rec), 140.0)
    v = FHRViewer.from_record(rec, markers=[[10, "$ ACC 40"]])
    assert v.ext == "rcfa" and len(v.data) > 0
