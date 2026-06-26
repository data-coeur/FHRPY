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
> for the roadmap (Étapes 0–5).

## Install (dev, from source)

```bash
git clone https://github.com/data-coeur/FHRPY.git
cd FHRPY
pip install -e .
```

## License

MIT — see [LICENSE](LICENSE).

## Citation

If you use FHRPY in academic work, please cite the original FHRMA toolbox (citation
block to be completed in Étape 4) and this repository.

---

*🧠 We are recruiting for the **AIM-CTG** project — details coming soon.*
