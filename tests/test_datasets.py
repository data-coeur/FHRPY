"""Tests for the bundled FHRMA example dataset + its loader."""
import numpy as np
import pytest

import fhrpy.datasets as ds
from fhrpy.viewer import FHRViewer


def test_registry_and_files_present():
    names = ds.example_names()
    assert len(names) > 1000, "expected the full bundled FHRMA datasets"
    # spot-check a spread (there are 1200+ examples)
    for e in ds.list_examples()[:40] + ds.list_examples("fs")[:5]:
        p = ds.example_path(e["name"])
        assert p.exists()
        if e["labelled"]:
            assert p.with_suffix(".fhrh").exists()


def test_categories_and_naming():
    names = set(ds.example_names())
    assert "morpho_train01" in names and "morpho_test01" in names
    assert "fs_dopmhr_train0001" in names and "fs_scalp_train0001" in names
    # test/val records are unlabelled, train records labelled
    assert not ds.example_markers("morpho_test01")
    assert ds.expert_baseline("morpho_train01") is not None


def test_morpho_has_expert_baseline_and_zones():
    name = "morpho_train21"
    bl = ds.expert_baseline(name)
    assert bl is not None and bl.ndim == 1 and bl.size > 1000
    marks = ds.example_markers(name)
    types = {m[1][2:5] for m in marks if m[1].startswith("$")}
    assert {"ACC", "DEC"} & types


def test_falsesig_has_urs_and_protected_expulsion():
    name = "fs_dopmhr_train0006"
    marks = ds.example_markers(name)
    assert any(m[1].startswith("$ URS") for m in marks), "no false-signal zones"
    # the expulsion mark is protected (the £ prefix marks a non-editable mark)
    assert any(m[1] == "£2nd stage" for m in marks)


@pytest.mark.parametrize("source", ["expert", "method", "raw"])
def test_load_example_builds_viewer(source):
    v = ds.load_example("morpho_train19", source=source, height=300)
    assert isinstance(v, FHRViewer)
    assert len(v.data) > 0
    html = v._build_html()
    assert "FHRViewer" in html and "{{DATA_B64}}" not in html  # placeholder substituted


def test_timestamp_is_zeroed():
    from fhrpy.io import read_fhr

    rec = read_fhr(ds.example_path("fs_dopmhr_train0006"))
    assert int(rec.timestamp) == 0


def test_from_record_roundtrip_baseline():
    from fhrpy.io import read_fhr

    rec = read_fhr(ds.example_path("morpho_train19"))
    rec.baseline = np.full(len(rec), 140.0)
    v = FHRViewer.from_record(rec, markers=[[10, "$ ACC 40"]])
    assert v.ext == "rcfa" and len(v.data) > 0
