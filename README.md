# FHRPY

**Python toolbox for Fetal Heart Rate (FHR) / cardiotocography (CTG) analysis**, with
a clean web-based CTG viewer.

FHRPY is a focused Python port of the MATLAB
[FHRMA](https://github.com/utsb-fmm/FHRMA) toolbox. It provides:

- **Baseline estimation** — the **WMFB** method (Weighted Median Filter Bank) plus
  morphological analysis (accelerations, decelerations, uterine contractions).
- **False-signal detection** (`fhrma-fs`) — detection of Doppler MHR/FHR confusion,
  with the training code included.
- **File I/O** for `.fhr` / `.rcf` / `.rcfm` formats and the reference datasets.
- A **web CTG viewer** that runs locally (Python UI), inline in Jupyter notebooks
  (VSCode and Google Colab), and as standalone offline HTML — no PHP required.

> ⚠️ **Status: under active development (pre-release).** APIs and formats may change
> until the first validated release. See the [open issues](https://github.com/data-coeur/FHRPY/issues)
> for the roadmap (Étapes 0–5), and **[docs/PROGRESS.md](docs/PROGRESS.md)** for the
> current state with screenshots.

## Install (dev, from source)

```bash
git clone -b dev https://github.com/data-coeur/FHRPY.git
cd FHRPY
pip install -e .
```

## Quick start

```python
from fhrpy.viewer import FHRViewer

# Open a recording with the real WMFB baseline + accel/decel zones.
# Renders inline in a Jupyter notebook (VSCode / Colab):
FHRViewer("examples/example_recording.fhr", analyze=True)

# ...or export a standalone offline HTML page (no server, no PHP):
FHRViewer("examples/example_recording.fhr", analyze=True).to_html("demo.html")
```

```python
# Signal methods without the viewer:
from fhrpy.io import read_fhr
from fhrpy.baseline import analyze

res = analyze(read_fhr("examples/example_recording.fhr"))
res["baseline"], res["accelerations"], res["decelerations"]
```

## License

MIT — see [LICENSE](LICENSE).

## Citation

If you use FHRPY in academic work, please cite the original FHRMA toolbox (citation
block to be completed in Étape 4) and this repository.

---

*🧠 We are recruiting for the **AIM-CTG** project — details coming soon.*
