# FHRPY

**Python toolbox for Fetal Heart Rate (FHR) / cardiotocography (CTG) analysis**, with
a clean, dependency-light web CTG viewer.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/data-coeur/FHRPY/blob/main/examples/viewer_demo.ipynb)

FHRPY is a focused Python port of the MATLAB
[FHRMA](https://github.com/utsb-fmm/FHRMA) toolbox. It provides:

- **False-signal detection** (`fhrma-fs`) — deep-learning detection of Doppler
  maternal/fetal heart-rate confusion, with NumPy inference (no TensorFlow needed)
  and the training code included.
- **Baseline estimation** — the **WMFB** method (Weighted Median Filter Bank) plus
  morphological analysis (accelerations, decelerations, and uterine
  **contractions** detected from the TOCO signal).
- **File I/O** for `.fhr` / `.rcf` / `.rcfm` / `.dat` formats and the reference datasets.
- A **web CTG viewer** that runs locally (Python UI), inline in Jupyter notebooks
  (VSCode and Google Colab), and as standalone offline HTML — no PHP required.

> The badges above: the **Colab** link opens the demo notebook (works once the
> repository is public). A **CI** badge will be added when the test workflow is
> enabled (see `docs/PROGRESS.md`).

## Processing pipeline (order matters)

The analysis stages run in this order — **false-signal detection comes first**, so
that maternal/artefact samples are removed *before* the baseline is computed:

```
read_fhr → preprocess → false-signal detection & removal → WMFB baseline → accel/decel
```

Running baseline estimation on un-cleaned signal would let false signals distort
the baseline, so `fhrma-fs` is applied (and its samples discarded) upstream.

> ⚠️ **Status: under active development (pre-release).** APIs and formats may change
> until the first validated release. See the [open issues](https://github.com/data-coeur/FHRPY/issues)
> for the roadmap (Étapes 0–5) and **[docs/PROGRESS.md](docs/PROGRESS.md)** for the
> current state with screenshots.

---

## Install

```bash
pip install -e .            # from a source checkout
# (PyPI release `pip install fhrpy` will follow the first validated release)
```

Requires Python ≥ 3.9, NumPy and SciPy. The viewer needs no JavaScript build step
and no extra system packages for its notebook / HTML / local-server modes.

## Quick start

### The web CTG viewer

```python
from fhrpy.viewer import FHRViewer

# Open a recording with the real WMFB baseline + accel/decel colored zones.
# Renders inline in a Jupyter notebook (VSCode / Colab):
FHRViewer("examples/example_recording.fhr", analyze=True)

# ...or detect false signals and shade them too:
FHRViewer("examples/example_recording.fhr", analyze=True, false_signals=True)

# Export a standalone offline HTML page (no server, no PHP):
FHRViewer("examples/example_recording.fhr", analyze=True).to_html("demo.html")

# Or serve it (handy on Colab / for a local UI):
FHRViewer("examples/example_recording.fhr", analyze=True).serve()
```

The viewer is a **Python-controllable object**: `set_markers()`, `scroll_to()`,
`set_height()`, `set_scale()` (1 or 3 cm/min), `set_channel_visible()`,
`set_zones_visible()`, `set_interpolate()`, and `on(event, callback)` to listen
for scroll / button / marker events. It is responsive, supports a configurable
number of signals per graph, FHR/MHR toggling with linear gap interpolation, and
colored acceleration / deceleration / contraction zones.

### The signal-processing methods (no viewer)

```python
from fhrpy.io import read_fhr
from fhrpy.baseline import analyze
from fhrpy.falsesignal import detect_false_signals

rec = read_fhr("examples/example_recording.fhr")

ma = analyze(rec)                      # WMFB baseline + morphology
ma["baseline"]                         # baseline (bpm) at 4 Hz
ma["accelerations"], ma["decelerations"]   # [(start_s, end_s), ...]

fs = detect_false_signals(rec, kind="doppler")
fs["prob"], fs["mask"], fs["segments"]      # per-sample P(false) + episodes
```

## What's inside

| Module | Purpose |
|--------|---------|
| `fhrpy.io` | Read/write `.fhr` `.rcf` `.rcfm` `.dat` (faithful to `fhropen.m`/`fhrsave.m`) |
| `fhrpy.preprocess` | Filtering, interpolation, resampling (NumPy ports of the DSP helpers) |
| `fhrpy.baseline` | WMFB baseline + acceleration/deceleration + TOCO contraction detection |
| `fhrpy.falsesignal` | False-signal (MHR/FHR confusion) detection — NumPy inference |
| `fhrpy.training` | The original false-signal model training sources (Keras) |
| `fhrpy.viewer` | The web CTG viewer + its Python wrapper |

## File format

Little-endian, 4 Hz. Header is a `uint32` timestamp (dataset files) or
`magic + timestamp` (recorder files). Per sample: `FHR1, FHR2` (`uint16`/4),
optional `MHR` (`uint16`/4), `TOCO` (`uint8`/2), a quality/sensor byte, and —
in analysed `.rcfa` files — preprocessed `FHRi` and `baseline`. Extensions:
`.fhr`/`.rcf` = 6 B/sample, `.fhrm`/`.rcfm` = 8 B/sample, `.dat` = 4 B/sample
(PhysioNet CTU-UHB), analysed variants add 4 B/sample.

## Datasets & examples

A real recording is bundled at `examples/example_recording.fhr` and a short
`.rcfm` at `examples/sample.rcfm`. The full FHRMA morphological-analysis dataset
and the false-signal datasets can be added on request — see issue #8.

## Docker

Docker is **optional** (the toolbox is pure Python). Two self-contained setups
are provided, each with its own README:

- **Inference server** — `docker/server/` ([README](docker/server/README.md)):
  `docker-compose -f docker/server/docker-compose.yml up --build`.
- **MATLAB-parity harness** (Octave) — `docker/octave/` ([README](docker/octave/README.md)):
  `bash docker/octave/run.sh`.

## License

**MIT** — see [LICENSE](LICENSE). FHRPY is an independent reimplementation; the
original MATLAB FHRMA toolbox is GPLv3 by the same author, who relicenses these
methods under MIT for FHRPY.

## Citation

FHRPY reimplements methods published by Boudet et al. **If you use FHRPY in
academic work, please cite the relevant original papers** (and this repository):

- **Toolbox (always cite):** Boudet, S., Houzé de l'Aulnoit, A., Demailly, R.,
  Delgranche, A., Peyrodie, L., Beuscart, R., Houzé de l'Aulnoit, D. *A fetal
  heart rate morphological analysis toolbox for MATLAB.* SoftwareX, 2020;11:100428.
  doi:10.1016/j.softx.2020.100428
- **Morphological analysis (baseline, accel/decel):** Houzé de l'Aulnoit, A.,
  Boudet, S., et al. *Automated fetal heart rate analysis for baseline
  determination and acceleration/deceleration detection: A comparison of 11
  methods versus expert consensus.* Biomed. Signal Process. Control,
  2019;49:113–123. doi:10.1016/j.bspc.2018.10.002
- **WMFB baseline method:** Boudet, S., et al. *Fetal heart rate baseline
  computation with a weighted median filter.* Comput. Biol. Med.,
  2019;114:103468. doi:10.1016/j.compbiomed.2019.103468
- **Morphological-analysis dataset:** Boudet, S., et al. *Fetal heart rate signal
  dataset for training morphological analysis methods and evaluating them against
  an expert consensus.* Data in Brief, 2019. doi:10.20944/preprints201907.0039.v1
- **False-signal detection (method, interface, dataset):** Boudet, S., et al.
  *Use of deep learning to detect the maternal heart rate and false signals on
  fetal heart rate recordings.* Biosensors, 2022;12(9):691.
  doi:10.3390/bios12090691

## We are recruiting — AIM-CTG

🧠 **We are recruiting for the AIM-CTG project** (AI for CTG analysis). Details and
how to apply will be added here soon. <!-- TODO: add AIM-CTG recruiting text/links (issue #5) -->

## Acknowledgements

Based on the [FHRMA](https://github.com/utsb-fmm/FHRMA) MATLAB toolbox by Samuel
Boudet and colleagues (Faculté de Médecine et Maïeutique de Lille).
