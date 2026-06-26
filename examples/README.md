# FHRPY examples

Bundled data and runnable demos.

| File | What it is |
|------|------------|
| `sample.rcfm` | A short (~5 min) `.rcfm` recording (anonymised header). |
| `example_recording.fhr` | A real 58-min FHRMA recording (`.fhr`, 4 Hz) used by the demos and tests. |
| `viewer_demo.ipynb` | Notebook demo — viewer with WMFB baseline + zones, false signals, the methods API, and save/export. Renders inline under VSCode and Colab. |
| `viewer_demo.html` | A self-contained **offline** demo page — double-click to open the analyzed CTG (baseline + colored zones) in a browser, no server/PHP. |
| `benchmark.py` | Throughput benchmark (Étape 5): single-record timing + a real 4-worker parallel run vs the 12×3h-in-≤60s target. |

## Quick run

```bash
pip install -e ..            # install fhrpy from the repo root
python benchmark.py          # throughput benchmark
jupyter notebook viewer_demo.ipynb   # interactive viewer demo
```

```python
from fhrpy.viewer import FHRViewer
FHRViewer("example_recording.fhr", analyze=True, false_signals=True)  # inline in a notebook
```

See [../docs/PROGRESS.md](../docs/PROGRESS.md) for screenshots and the project status.
