# Octave parity harness (FHRPY ⇄ FHRMA MATLAB)

This harness validates that FHRPY's NumPy ports are **numerically faithful** to
the original FHRMA MATLAB toolbox, by running the *original* MATLAB `.m` sources
under GNU Octave in Docker and comparing their outputs to FHRPY's.

It directly answers the question "does the Python port match MATLAB?" with
measured, reproducible numbers.

## What it does

1. Builds an Octave 9.2.0 image with the Forge `signal` package (Dockerfile).
2. Compiles the FHRMA `multisigfilter` C MEX (the zero-phase IIR filter that
   `butterfilt.m` uses) for Linux, so Octave runs the **original C filtering
   path**, not a fallback. Only Windows `.mexw32/.mexw64` binaries ship upstream,
   so we build a Linux-portable copy (`matlab_ref/multisigfilter_oct.c`, identical
   filter arithmetic, Windows threading replaced by a sequential loop) with
   `mex`.
3. Runs `fhropen` → `preprocess` → `aamwmfb` on a handful of `.fhr` recordings
   and dumps the reference outputs to `out/ref_<name>.mat` (MATLAB v7).
4. `tests/test_matlab_parity.py` loads those and compares against
   `fhrpy.io.read_fhr`, `fhrpy.preprocess.preprocess`,
   `fhrpy.preprocess.dsp.butterfilt`, and `fhrpy.baseline.wmfb`.

The MATLAB sources used are copied verbatim into `matlab_ref/` (provenance and
GPLv3 licensing in `matlab_ref/NOTICE`); the harness does **not** depend on any
path outside the repo at run time.

## How to run

Prerequisites: Docker + `docker-compose` (v1.29 works; the `docker compose`
plugin is **not** required).

```bash
# 1. Generate the Octave references (first run builds the image; minutes once).
bash docker/octave/run.sh

# 2. Compare FHRPY against them.
python3 -m pytest -q tests/test_matlab_parity.py -rA
```

`run.sh` always processes `examples/example_recording.fhr` (= train01, ~58 min)
and, if the FHRMA dataset is present at the default read-only path, also stages
and processes `train03.fhr` (~40 min) and `train19.fhr` (~29 min). Point it
elsewhere with `FHRPY_DATASET_DIR=…` or `FHRPY_EXTRA_FILES="/abs/a.fhr /abs/b.fhr"`.

Outputs land in `docker/octave/out/` (gitignored, regenerable).

## Expected runtime

* Image build (one-off): a few minutes (downloads the base image + installs the
  `control` and `signal` Forge packages).
* Per recording: `aamwmfb` runs in **~0.3–0.5 s** under Octave; the whole
  reference generation over the three recordings is a few seconds plus container
  startup. The Python comparison runs in ~4 s.

## Achieved parity (Octave 9.2.0)

`multisigfilter` compiled cleanly and matched `filtfilt` to **0.0** on the
order-1 smoke test, so Octave used the original C filter path throughout.

| Stage | example_recording | train03 | train19 |
|---|---|---|---|
| `read_fhr` vs `fhropen` (FHR1/FHR2/TOCO) | **0.0 (exact)** | **0.0** | **0.0** |
| `preprocess` FHRi | **0.0 (exact)** | **0.0** | **0.0** |
| order-1 `butterfilt` (1 cpm low-pass) | ~1e-12 | ~1e-12 | ~1e-12 |
| WMFB baseline — mean abs diff | 0.27 bpm | 0.49 bpm | 0.27 bpm |
| WMFB baseline — 95th pct | 0.53 bpm | 1.48 bpm | 0.42 bpm |
| WMFB baseline — 99th pct | 1.12 bpm | 10.5 bpm | 4.1 bpm |
| WMFB baseline — max | 87 bpm | 46 bpm | 42 bpm |
| accel events matched / ref | 3 / 3 | 7 / 7 (+1 extra) | 3 / 3 |
| decel events matched / ref | 28 / 28 | 9 / 10 | 4 / 5 |
| accel/decel event-time coverage | ≥ 0.98 | ≥ 0.98 | ≥ 0.97 |

**Reading these numbers.** File I/O, preprocessing and the Butterworth filtering
are essentially *bit-exact*. The WMFB **baseline** agrees to well under 1 bpm on
average (95th percentile ≤ ~1.5 bpm), but has **localized** discrepancies up to
~40–90 bpm. These concentrate in:

* the **signal tail** (last few samples) — the `interp`/`decimate` FIR
  upsampling/decimation in `medgliss` has different edge behaviour between
  MATLAB's `interp`/`decimate` and SciPy's `resample_poly`/`cheby1`+`filtfilt`;
* a **few interior blocks** — weighted-median **tie-breaking** and the
  `enveloppe` FFT-bin selection can pick a different point when weights are close,
  which then propagates through the 6 iterative passes.

These shift a handful of accel/decel boundaries and occasionally split one
event into two (e.g. train19 dec at 446–530 s). The parity test therefore
asserts on **robust statistics** (mean, percentiles, matched-event boundaries,
event-time coverage) rather than the raw max, and documents the achieved values
above.

## Known remaining discrepancies (WMFB port risks)

| Symptom | Likely cause |
|---|---|
| Baseline tail differs by tens of bpm | `interp`/`decimate` FIR edge behaviour (`resample_poly` vs MATLAB `interp`; `cheby1`+`filtfilt` vs MATLAB `decimate`) |
| Isolated interior baseline jumps | weighted-median tie-breaking when sorted cumulative weights cross `s/2` at near-equal points |
| A decel/accel split into two, ±1 event count | the above baseline jumps move a zero-crossing inside `adjustduration` |
| Sub-bpm ripple everywhere | `enveloppe` FFT band-bin rounding in the per-sample trust weight `P` |

## Files

* `Dockerfile`, `docker-compose.yml` — Octave image + signal package.
* `run.sh` — one-command build + reference generation.
* `run_reference.m` — the Octave driver (compiles `multisigfilter`, runs the
  pipeline, writes `out/ref_*.mat`).
* `matlab_ref/` — verbatim FHRMA MATLAB sources + Linux-portable
  `multisigfilter_oct.c` (+ `NOTICE` for provenance/licensing).
* `out/` — generated references (gitignored).
* `../../tests/test_matlab_parity.py` — the comparison test.
