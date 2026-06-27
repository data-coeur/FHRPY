"""The bundled **FHRMA datasets** — full morphological + false-signal corpora.

Everything ships with FHRPY (start timestamp zeroed, so recordings open at 00:00):

* ``morpho/`` — the morphological-analysis dataset: ``morpho_train01`` …
  ``morpho_train66`` (with the **expert** baseline + accel/decel/URS labels) and
  ``morpho_test01`` … ``morpho_test90`` (held-out, unlabelled).
* ``fs/`` — the false-signal dataset, both sensors and all splits:
  ``fs_dopmhr_train0001`` …, ``fs_dopmhr_val…``, ``fs_dopmhr_testcp…``,
  ``fs_dopmhr_testdbs…``, ``fs_scalp_train…``, ``fs_scalp_val…``,
  ``fs_scalp_test…``. The **train** records carry the expert false-signal labels
  (``$ URS`` zones) + a protected ``£2nd stage`` marker; val/test are unlabelled.
* ``ctg/`` — ``ctg_example_01`` … ``ctg_example_11``, the FHRMA *Examples* full
  Doppler recordings (the notebook's showcase).

There is no manifest file: examples are discovered by **filename pattern**, so a
record's name *is* its handle (e.g. ``ds.load_example("morpho_train21")``).
``kind`` (doppler/scalp) and the presence of labels are inferred from the name
and the companion ``.fhrh`` / ``.labels.npz`` files.
"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent
_CATEGORIES = ("ctg", "morpho", "fs")


def _scan():
    """name -> (recording_path, category)."""
    out = {}
    for cat in _CATEGORIES:
        d = _DIR / cat
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.fhr")) + sorted(d.glob("*.fhrm")):
            out[p.stem] = (p, cat)
    return out


_INDEX = _scan()


def _kind(name: str) -> str:
    return "scalp" if "scalp" in name else "doppler"


def _category(name: str) -> str:
    return _entry(name)[1]


def _entry(name: str):
    e = _INDEX.get(name)
    if e is None:
        raise KeyError(f"unknown example {name!r}; see fhrpy.datasets.example_names()")
    return e


def example_names(kind: str | None = None) -> list[str]:
    """All bundled example names (optionally filtered by category: ctg/morpho/fs)."""
    return [n for n, (_p, cat) in _INDEX.items() if kind in (None, cat)]


def list_examples(kind: str | None = None) -> list[dict]:
    """Richer listing: name, category, detector kind, and label availability."""
    out = []
    for name, (path, cat) in _INDEX.items():
        if kind not in (None, cat):
            continue
        out.append({
            "name": name, "category": cat, "kind": _kind(name),
            "labelled": path.with_suffix(".fhrh").exists(),
            "has_baseline": path.with_suffix(".labels.npz").exists(),
        })
    return out


def example_path(name: str) -> Path:
    """Absolute path to a bundled recording."""
    return _entry(name)[0]


def example_markers(name: str) -> list[list]:
    """Expert-label markers ``[[sample, text], ...]`` for an example (``[]`` if none)."""
    p = _entry(name)[0].with_suffix(".fhrh")
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if len(line) > 8:
            out.append([int(line[:7]), line[8:]])
    return out


def expert_baseline(name: str):
    """Expert baseline (bpm at 4 Hz) for a morphology example, else ``None``."""
    p = _entry(name)[0].with_suffix(".labels.npz")
    if not p.exists():
        return None
    import numpy as np

    with np.load(p) as z:
        return z["baseline"].astype(float)


def load_and_process(name: str, source: str = "expert", **viewer_opts):
    """Build an :class:`fhrpy.viewer.FHRViewer` for a bundled example.

    ``source``:

    * ``"expert"`` (default) — show the **expert labels** (.fhrh zones, and the
      injected expert baseline for labelled morphology records). Unlabelled
      records fall back to the raw signals.
    * ``"method"`` — run the FHRPY pipeline (WMFB baseline + accel/decel, and
      false-signal detection for fs/ctg records) and show **its predictions**.
    * ``"fs"`` — false-signal detection only (no baseline / morphology).
    * ``"raw"`` — signals only.
    """
    from ..viewer import FHRViewer

    path, cat = _entry(name)
    kind = _kind(name)
    run_fs = cat in ("fs", "ctg")

    if source == "method":
        return FHRViewer(path, analyze=True, false_signals=run_fs,
                         false_signals_kind=kind, **viewer_opts)
    if source == "fs":
        return FHRViewer(path, analyze=False, false_signals=True,
                         false_signals_kind=kind, **viewer_opts)
    if source == "raw":
        return FHRViewer(path, **viewer_opts)
    if source != "expert":
        raise ValueError("source must be 'expert', 'method', 'fs' or 'raw'")

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
    return FHRViewer(path, markers=(markers or None), **viewer_opts)


# Backwards-compatible alias.
load_example = load_and_process
