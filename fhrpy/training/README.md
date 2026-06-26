# FS model training sources

TensorFlow/Keras training code for the FHRMA false-signal (FS) detectors,
preserved from the original FHRMA toolbox (`FS training python sources/`). These
are **not** required for inference — `fhrpy.falsesignal` runs the trained models
in pure NumPy from the bundled `FSDop.mat` / `FSScalp.mat`. They are kept here so
the models can be retrained.

> Requires **TensorFlow 2** (GPU or TPU strongly recommended — the original
> models were trained for tens of thousands of epochs on TPU v2/v3). Nothing here
> is imported by the `fhrpy` package; importing `fhrpy` or `fhrpy.training` does
> not pull in TensorFlow.

## Files

| File | Purpose |
|------|---------|
| `1_Prepare_packaged_data.ipynb` | Reads the raw per-recording binaries from `dataV8.zip` and bin-packs them into fixed-length, padded, pickled training tensors (`dataV8{MHR,dop,Int}{ntrain}-{nval}.pkl`). |
| `2_Training_FSMHR.ipynb` | Trains the **FSMHR** sub-model (`GRU1MHR` + `DensePmat`), the MHR false-signal detector. 6-feature input. |
| `3_Training_FSDop.ipynb` | Loads the **frozen** FSMHR weights and trains `GRU1/2/3` + `Dense1` on top → **FSDop** (Doppler FHR false-signal detector, using MHR as a helper). Exports `FSDop.mat` (cell "export to Matlab"). |
| `4_FSScalp.py` | Standalone (Google Cloud TPU) training of **FSScalp** (scalp-ECG FHR, 4-feature input, no MHR). Exports `FSScalp.mat`. |

The large training assets (`dataV8.zip`, `FSDop.h5`, `FSMHR.h5`, `FSScalp.h5`)
live in the original toolbox repo, not in this package.

## Pipeline overview

1. **Data packaging** (`1_…`). Raw per-recording binaries:
   - `dop###.dop` = `uint16/4` reshaped `(-1, 5)`: columns `FHR, MHR, labelF, labelM, isStage2`.
   - `int###.int` = `(-1, 3)`: `FHR, labelF, isStage2` (scalp/internal).
   - Labels: `isFalse = label < 1`, `docare = label != 1` (value `1` = "don't care").
   - `docare` reweighted by `sqrt(len / sum(docare))`.
   - `X` normalized exactly as at inference: `(hr - 120) / 60` plus present/absent masks.
   - Recordings bin-packed into fixed-length rows separated by a **reset** marker
     column (the last input column, index `m-1`), padded, and pickled.

2. **Model definition** (bidirectional, 3 stacked GRUs):
   - Standard Keras `layers.GRU` (`reset_after=True` default), gate order `z|r|h`,
     `return_sequences=True`, `stateful=False`.
   - Bidirectionality is hand-built: input `I` and its time-reverse are stacked on
     the **batch** axis (`axis=0`); a single GRU runs over both; each layer's
     output is recombined as `[forward, flip(reverse), <skip features>]`.
   - FSDop units: `GRU1=24, GRU2=24, GRU3=24` (+ frozen `GRU1MHR=12`);
     FSScalp units: `GRU1=24, GRU2=18, GRU3=12`.
   - Constraints (training only):
     - `Sparsity` — block-diagonal recurrent kernel.
     - `SparsityKernel` — input-kernel block sparsity **plus** a `-1e30` reset bias
       on the reset-input column (col `m-1`) so a reset sample forces the gates/
       state to 0 between bin-packed recordings.
     - `Reseter` — the reset-bias-only variant for the last GRU.
     - `Set0forReset` layer — zeroes a layer's outputs at reset samples.
     - `BiasConstraintCallback` — after each batch, ties
       `W_input_bias[-1][2L:3L] = -W_recurrent_bias[0][2L:3L]` so the candidate-gate
       input bias cancels the recurrent bias, keeping the model consistent with the
       `reset_after=True` two-bias-row convention.
   - Loss `weighted_binary_crossentropy` = per-sample BCE × `docare` weight,
     **summed** (not averaged). Metric `weighted_accuracy`. Optimizer Adam with a
     step/exponential LR schedule. `GaussianDropout` 0.2/0.3/0.4 between GRUs.

3. **On-the-fly augmentation** (`siglossgenerator`, a `tf.function`): the key to
   the method. Each training step randomly:
   - **cuts** the signal at a random sample (inserts a reset marker),
   - **drops** FHR/MHR segments at several scales (`pFHRn/pFHRd`, `pMHRn/pMHRd`)
     to simulate signal loss,
   - **synthesizes false signals** by overwriting random FHR windows with the
     **maternal** HR shifted by a sampled offset (`DiffFM`, from `DiffMF.dat`) —
     modeling the Doppler-grabs-maternal-HR confusion — and flags those samples
     `isFalse`. Also synthesizes doubling/halving artefacts (`*2`, `*0.5`).
   - randomly zeroes `isStage2` (`pNoStage2`) and applies a small global scale
     (`stdMult`).

4. **Export to `.mat`** (cell "export to Matlab" in `3_…`, equivalent in
   `4_FSScalp.py`): `get_weights()` for each layer, **strip the reset input
   column** (`GRU*[0] = GRU*[0][0:-1, :]`), then `scipy.io.savemat`. The resulting
   `.mat` cells are `[W (m,3n), U (n,3n), B (2,3n)]` per GRU and `[W, b]` per Dense
   — exactly what `fhrpy.falsesignal.model` consumes.

## Retraining checklist

1. Obtain `dataV8.zip` + `DiffMF.dat` from the FHRMA repo; run
   `1_Prepare_packaged_data.ipynb` to produce the `.pkl` tensors.
2. Run `2_Training_FSMHR.ipynb` → `FSMHR.h5`.
3. Run `3_Training_FSDop.ipynb` (loads frozen `FSMHR.h5`) → `FSDop.h5` + `FSDop.mat`.
4. Run `4_FSScalp.py` → `FSScalp.h5` + `FSScalp.mat`.
5. Copy the new `FSDop.mat` / `FSScalp.mat` into `fhrpy/falsesignal/weights/`.
   The NumPy inference picks them up unchanged.
