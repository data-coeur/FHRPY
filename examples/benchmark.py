"""Throughput benchmark for the FHRPY CPU inference path (Étape 5).

Measures the wall-clock time of the WMFB baseline analysis and the false-signal
detector on a real recording, and extrapolates to the real-time target:
*12 recordings of ~3 h each processed in ~1 min on a 2-4 core CPU server*.

Run: ``python3 examples/benchmark.py``
"""

from __future__ import annotations

import os
import sys
import time

# Allow running from a source checkout without `pip install`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fhrpy.baseline import analyze
from fhrpy.falsesignal import detect_false_signals
from fhrpy.io import read_fhr

EXAMPLE = os.path.join(os.path.dirname(__file__), "example_recording.fhr")
TARGET_RECORDS = 12
TARGET_HOURS = 3.0
TARGET_SECONDS = 60.0


def _best_of(fn, repeats: int = 3) -> float:
    best = float("inf")
    for _ in range(repeats):
        t = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t)
    return best


def main() -> None:
    rec = read_fhr(EXAMPLE, header=4)
    n = len(rec)
    minutes = n / rec.fs / 60.0
    print(f"record: {n} samples = {minutes:.1f} min @ {rec.fs:g} Hz")

    t_wmfb = _best_of(lambda: analyze(rec))
    t_fs = _best_of(lambda: detect_false_signals(rec, kind="doppler"))
    per_record = t_wmfb + t_fs
    print(f"  WMFB baseline analyze : {t_wmfb * 1000:7.0f} ms")
    print(f"  false-signal (doppler): {t_fs * 1000:7.0f} ms")
    print(f"  total per record      : {per_record * 1000:7.0f} ms")

    # Records are independent -> embarrassingly parallel across records.
    samp_3h = TARGET_HOURS * 3600 * rec.fs
    per_3h = per_record * (samp_3h / n)  # ~linear in samples
    serial = TARGET_RECORDS * per_3h
    cores = min(4, os.cpu_count() or 1)
    print(f"\ntarget: {TARGET_RECORDS} records of {TARGET_HOURS:g} h in <= {TARGET_SECONDS:g} s")
    print(f"  per {TARGET_HOURS:g} h-record (1 core, extrapolated): {per_3h:.1f} s")
    print(f"  {TARGET_RECORDS} records serial (1 core)          : {serial:.1f} s")
    print(f"  {TARGET_RECORDS} records on {cores} cores (ideal)         : {serial / cores:.1f} s")
    verdict = "MET" if serial / cores <= TARGET_SECONDS else "NOT met (needs optimization)"
    print(f"  => target {verdict}")


if __name__ == "__main__":
    main()
