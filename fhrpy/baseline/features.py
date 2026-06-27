"""CTG feature extraction — a NumPy port of the standard features from the amnio
MATLAB ``computeFeaturesAmnio.m``.

Only the *standard* clinical features are ported (groups A–D): basic / baseline /
time-in-band, acceleration & deceleration morphology, deceleration types,
contractions, and a standard short-/long-term variability. The experimental
features (spectral power, de Haan LTI/STI, Ayres, ssi/mev/bu) are intentionally
left out. All names are in English. See :func:`compute_features`.
"""
from __future__ import annotations

import numpy as np

from .wmfb import analyze, classify_decelerations

_FS = 4.0


def _event_metrics(events, fhri, baseline, kind):
    """Per-event metrics (port of extractAccDecDataAmnio): duration, amplitude,
    surface(s), nadir/peak, time-to-extremum. ``kind`` is 'acc' or 'dec'."""
    out = []
    n = min(len(fhri), len(baseline))
    for start_s, end_s in events:
        s = max(0, int(round(float(start_s) * _FS)))
        e = min(n, int(round(float(end_s) * _FS)))
        if not s < e:
            continue
        sig = (baseline[s:e] - fhri[s:e]) if kind == "dec" else (fhri[s:e] - baseline[s:e])
        amplitude = float(np.max(sig))
        surface = float(np.sum(sig)) / 240.0
        surface_da2 = float(np.sum(sig ** 2)) / 240.0
        surface_da15 = float(np.sum(np.maximum(sig, 0) ** 1.5)) / 240.0
        if kind == "dec":
            idx = int(np.argmin(fhri[s:e]))
            extreme = float(fhri[s:e][idx])
        else:
            idx = int(np.argmax(sig))
            extreme = float(np.max(fhri[s:e]))
        out.append({
            "duration": float(end_s) - float(start_s),
            "amplitude": amplitude, "surface": surface,
            "surface_da2": surface_da2, "surface_da15": surface_da15,
            "extreme": extreme, "time_to_extreme": idx / _FS,
        })
    return out


def _pct(mask, n):
    return 100.0 * float(np.sum(mask)) / n if n else float("nan")


def _safe_mean(a):
    a = np.asarray(a, dtype=float)
    return float(np.mean(a)) if a.size else float("nan")


def compute_features(source, start_s: float | None = None, end_s: float | None = None) -> dict:
    """Compute the standard CTG feature synthesis over an analysis window.

    Parameters
    ----------
    source:
        An :class:`fhrpy.io.FHRRecord` (analysed on the fly) or a dict returned by
        :func:`fhrpy.baseline.analyze`.
    start_s, end_s:
        Optional analysis window in seconds (defaults to the whole valid signal).

    Returns
    -------
    dict
        Ordered feature name -> value. Surfaces are in bpm·min; times in %.
    """
    ma = source if isinstance(source, dict) and "baseline" in source else analyze(source)
    fhri = np.asarray(ma["fhri"], dtype=float)
    baseline = np.asarray(ma["baseline"], dtype=float)
    n = min(len(fhri), len(baseline))
    fhri, baseline = fhri[:n], baseline[:n]

    d = int(ma.get("d") or 0)
    f = int(ma.get("f") if ma.get("f") is not None else n - 1)
    s0 = int(round(start_s * _FS)) if start_s is not None else d
    s1 = int(round(end_s * _FS)) if end_s is not None else f
    s0, s1 = max(0, s0), min(n, s1 + 1)
    sl = slice(s0, s1)
    win = s1 - s0
    fhr_w, bl_w = fhri[sl], baseline[sl]

    acc = list(ma.get("accelerations") or [])
    dec = list(ma.get("decelerations") or [])
    cons = list(ma.get("contractions") or [])
    dec_types = ma.get("deceleration_types") or classify_decelerations(dec, fhri, baseline, cons)

    def in_win(seg):
        return seg[1] * _FS > s0 and seg[0] * _FS < s1

    acc_w = [a for a in acc if in_win(a)]
    dec_w = [x for x in dec if in_win(x)]
    cons_w = [c for c in cons if in_win(c)]
    dt_w = [t for t in dec_types if t["end_s"] * _FS > s0 and t["start_s"] * _FS < s1]

    accD = _event_metrics(acc_w, fhri, baseline, "acc")
    decD = _event_metrics(dec_w, fhri, baseline, "dec")

    r: dict = {}
    # --- A. basic -----------------------------------------------------------
    r["analysis_duration_min"] = win / 240.0
    # signal loss = % of the window where the FHR is missing. The preprocessed
    # ``fhr`` marks gaps with NaN (amnio: FHR(FHR==0)=NaN; perte = %NaN).
    fhr_gap = ma.get("fhr")
    if fhr_gap is not None:
        r["signal_loss_percent"] = _pct(np.isnan(np.asarray(fhr_gap)[sl]), win)
    else:
        raw = np.asarray(getattr(source, "fhr1", []), dtype=float)
        r["signal_loss_percent"] = _pct(raw[sl] == 0, win) if raw.size else float("nan")
    r["fhr_mean"] = _safe_mean(fhr_w)
    r["fhr_total_delta"] = float(np.quantile(fhr_w, 0.98) - np.quantile(fhr_w, 0.02)) if win else float("nan")

    # --- B. baseline --------------------------------------------------------
    r["baseline_mean"] = _safe_mean(bl_w)
    r["baseline_minus_fhr_mean"] = r["baseline_mean"] - r["fhr_mean"]
    diff = fhr_w - bl_w
    nf = float(np.mean(np.sign(diff) * diff ** 2)) if win else float("nan")
    r["baseline_fhr_normdiff"] = float(np.sign(nf) * np.sqrt(abs(nf))) if win else float("nan")
    for thr in (90, 100, 110):
        r[f"baseline_time_below_{thr}_percent"] = _pct(bl_w < thr, win)
    for thr in (160, 180, 200):
        r[f"baseline_time_above_{thr}_percent"] = _pct(bl_w > thr, win)
    r["baseline_range"] = float(np.max(bl_w) - np.min(bl_w)) if win else float("nan")
    above = bl_w[bl_w > 160] - 160
    below = 110 - bl_w[bl_w < 110]
    r["baseline_above160_surface"] = float(np.sum(above)) / win if win else float("nan")
    r["baseline_above160_surface2"] = float(np.sum(above ** 2)) / win if win else float("nan")
    r["baseline_below110_surface"] = float(np.sum(below)) / win if win else float("nan")
    r["baseline_below110_surface2"] = float(np.sum(below ** 2)) / win if win else float("nan")

    # --- B. FHR time-in-band -----------------------------------------------
    for thr in (90, 100, 110):
        r[f"fhr_time_below_{thr}_percent"] = _pct(fhr_w < thr, win)
    for thr in (160, 180, 200):
        r[f"fhr_time_above_{thr}_percent"] = _pct(fhr_w > thr, win)

    # --- B. accelerations ---------------------------------------------------
    r["acc_count"] = len(accD)
    r["acc_slope_mean"] = _safe_mean([a["amplitude"] / max(a["time_to_extreme"], 0.25) for a in accD])
    r["acc_duration_mean"] = _safe_mean([a["duration"] for a in accD])
    r["acc_amplitude_mean"] = _safe_mean([a["amplitude"] for a in accD])
    r["acc_surface_mean"] = _safe_mean([a["surface"] for a in accD])
    r["acc_surface_total"] = float(np.sum([a["surface"] for a in accD]))

    # --- B. decelerations ---------------------------------------------------
    r["dec_count"] = len(decD)
    durs = [x["duration"] for x in decD]
    amps = [x["amplitude"] for x in decD]
    surfs = [x["surface"] for x in decD]
    nadirs = [x["extreme"] for x in decD]
    r["dec_duration_mean"] = _safe_mean(durs)
    r["dec_duration_max"] = float(np.max(durs)) if durs else float("nan")
    r["dec_amplitude_mean"] = _safe_mean(amps)
    r["dec_amplitude_median"] = float(np.median(amps)) if amps else float("nan")
    r["dec_amplitude_max"] = float(np.max(amps)) if amps else float("nan")
    r["dec_surface_mean"] = _safe_mean(surfs)
    r["dec_surface_total"] = float(np.sum(surfs))
    r["dec_surface_da2_total"] = float(np.sum([x["surface_da2"] for x in decD]))
    r["dec_surface_da15_total"] = float(np.sum([x["surface_da15"] for x in decD]))
    r["dec_nadir_mean"] = _safe_mean(nadirs)
    r["dec_nadir_min"] = float(np.min(nadirs)) if nadirs else float("nan")
    r["dec_slope_mean"] = _safe_mean([x["amplitude"] / max(x["time_to_extreme"], 0.25) for x in decD])
    r["dec_light_count"] = int(np.sum([dd < 120 for dd in durs]))
    r["dec_severe_count"] = int(np.sum([120 <= dd < 300 for dd in durs]))
    for thr in (120, 180, 300):
        r[f"dec_prolonged_over_{thr}_count"] = int(np.sum([dd > thr for dd in durs]))
        r[f"dec_prolonged_over_{thr}_surface_total"] = float(
            np.sum([x["surface"] for x in decD if x["duration"] > thr]))

    # --- C. deceleration types ---------------------------------------------
    def _typ_sum(pred):
        return float(np.sum([t["surface"] for t in dt_w if pred(t["type"])]))

    r["dec_early_count"] = sum(t["type"] == "early" for t in dt_w)
    r["dec_early_surface_total"] = _typ_sum(lambda x: x == "early")
    r["dec_late_count"] = sum(t["type"] == "late" for t in dt_w)
    r["dec_late_surface_total"] = _typ_sum(lambda x: x == "late")
    r["dec_variable_count"] = sum(t["type"].startswith("variable") for t in dt_w)
    r["dec_variable_surface_total"] = _typ_sum(lambda x: x.startswith("variable"))
    r["dec_prolonged_count"] = sum(t["type"] == "prolonged" for t in dt_w)

    # --- C. contractions ----------------------------------------------------
    r["contraction_count"] = len(cons_w)
    r["dec_to_contraction_ratio"] = r["dec_count"] / max(r["contraction_count"], 1)
    r["dec_repeated"] = int(r["dec_to_contraction_ratio"] > 0.5)

    # --- D. variability (standard STV/LTV) ---------------------------------
    # STV: mean absolute successive difference of FHRi (bpm).
    if win > 1:
        r["stv_msd"] = float(np.mean(np.abs(np.diff(fhr_w))))
    else:
        r["stv_msd"] = float("nan")
    # LTV: per-minute range of FHRi (bpm).
    ranges = []
    for i in range(s0, s1, int(60 * _FS)):
        seg = fhri[i:min(i + int(60 * _FS), s1)]
        if seg.size:
            ranges.append(float(np.max(seg) - np.min(seg)))
    ranges = np.asarray(ranges, dtype=float)
    r["ltv_delta_mean"] = _safe_mean(ranges)
    r["ltv_time_below_6bpm_percent"] = _pct(ranges < 6, ranges.size) if ranges.size else float("nan")
    r["ltv_time_above_25bpm_percent"] = _pct(ranges > 25, ranges.size) if ranges.size else float("nan")

    return r
