"""Bundled FHRMA example recordings with their **expert labels**.

A small, self-contained subset of the public FHRMA datasets is shipped with
FHRPY so the viewer and the methods can be tried without downloading anything:

* ``ctg`` — full Doppler recordings from the FHRMA *Examples* folder (the
  showcase "analyse a complete CTG" examples); the 2nd-stage / **expulsion**
  instant comes from the recording and is stored as a protected ``£Expulsion``
  marker. These are the notebook's default examples.
* ``morpho`` — morphological-analysis examples with the **expert** ground truth
  (expert **baseline** + **acceleration / deceleration** zones), used to compare
  expert labels vs the WMFB method.
* ``falsesig`` — false-signal examples with the **expert** false-signal episodes
  (shown as ``$ URS`` zones), used to compare expert labels vs the detector.

All bundled recordings have their start timestamp zeroed, so they open at 00:00
without needing a timezone. Expert labels live in companion ``.fhrh`` marker
files (7-digit 4 Hz sample + text); the morphological baseline is additionally
stored in a compact ``.labels.npz``.

Typical use::

    import fhrpy.datasets as ds
    ds.list_examples()                       # what's available
    ds.load_example("morpho_train21")        # viewer showing the EXPERT labels
    ds.load_example("morpho_train21", source="method")   # FHRPY's predictions
"""
from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_INDEX = json.loads((_DIR / "index.json").read_text(encoding="utf-8"))


def list_examples(kind: str | None = None) -> list[dict]:
    """Return the registry entries (optionally filtered by ``kind``)."""
    out = []
    for category, entries in _INDEX.items():
        if kind and category != kind:
            continue
        out += [dict(category=category, **e) for e in entries]
    return out


def example_names(kind: str | None = None) -> list[str]:
    """Just the example names."""
    return [e["name"] for e in list_examples(kind)]


def _entry(name: str):
    for category, entries in _INDEX.items():
        for e in entries:
            if e["name"] == name:
                return category, e
    raise KeyError(f"unknown example {name!r}; see fhrpy.datasets.list_examples()")


def example_path(name: str) -> Path:
    """Absolute path to a bundled recording."""
    return _DIR / _entry(name)[1]["file"]


def example_markers(name: str) -> list[list]:
    """Expert-label markers ``[[sample, text], ...]`` for an example.

    Marker texts use the viewer's zone syntax: ``$ ACC <dur>`` / ``$ DEC <dur>``
    / ``$ URS <dur>`` (durations in 4 Hz samples), plus a protected
    ``£Expulsion`` mark for false-signal examples.
    """
    p = _DIR / _entry(name)[1]["markers"]
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if len(line) > 8:
            out.append([int(line[:7]), line[8:]])
    return out


def expert_baseline(name: str):
    """Expert baseline (bpm at 4 Hz) for a morphology example, else ``None``."""
    e = _entry(name)[1]
    if not e.get("labels"):
        return None
    import numpy as np

    with np.load(_DIR / e["labels"]) as z:
        return z["baseline"].astype(float)


def load_example(name: str, source: str = "expert", **viewer_opts):
    """Build an :class:`fhrpy.viewer.FHRViewer` for a bundled example.

    ``source``:

    * ``"expert"`` (default) — show the **expert labels**: the ``.fhrh`` zones
      (acc/dec/false-signal) and, for morphology examples, the expert baseline
      injected so the zones sit on the real labelled baseline.
    * ``"method"`` — run the FHRPY pipeline (false-signal detection + WMFB
      baseline + accel/decel) and show **its predictions** instead.
    * ``"raw"`` — the signals only, no analysis, no markers.
    """
    from ..viewer import FHRViewer

    category, e = _entry(name)
    path = _DIR / e["file"]

    if source == "method":
        run_fs = e.get("false_signals", category == "falsesig")
        return FHRViewer(path, analyze=True, false_signals=run_fs,
                         false_signals_kind=e.get("kind", "doppler"), **viewer_opts)
    if source == "raw":
        return FHRViewer(path, **viewer_opts)
    if source != "expert":
        raise ValueError("source must be 'expert', 'method' or 'raw'")

    markers = example_markers(name)
    baseline = expert_baseline(name)
    if baseline is not None:
        import numpy as np

        from ..io import read_fhr

        rec = read_fhr(path)
        rec.baseline = np.asarray(baseline, dtype=float)
        if rec.fhri is None or np.asarray(rec.fhri).size == 0:
            rec.fhri = np.asarray(rec.fhr1, dtype=float)
        return FHRViewer.from_record(rec, markers=markers, **viewer_opts)
    return FHRViewer(path, markers=markers, **viewer_opts)
