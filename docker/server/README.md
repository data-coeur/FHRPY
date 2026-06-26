# FHRPY inference server (Étape 5)

A dependency-light HTTP service (Python stdlib only — no FastAPI/uvicorn, no GPU,
no TensorFlow) that runs the WMFB baseline + false-signal detection on uploaded
recordings, using a process pool so several recordings are analysed in parallel.

## Run

Locally:
```bash
python -m fhrpy.server --port 8000 --workers 4
```

In Docker:
```bash
docker-compose -f docker/server/docker-compose.yml up --build
```

## API

```bash
curl http://localhost:8000/health
# {"status":"ok","workers":4}

curl -X POST --data-binary @examples/example_recording.fhr \
     -H "X-Filename: example_recording.fhr" \
     "http://localhost:8000/analyze?fs=1"
# {"n_samples":..., "baseline_1hz":[...], "accelerations":[[s,e],...],
#  "decelerations":[...], "false_signals":[...]}
```

## Performance

The detection path is pure NumPy with near-zero cold start. Measured on a 4-core
budget (see `examples/benchmark.py`): **12 recordings of ~3 h processed in ~40 s
wall-clock**, meeting the real-time target (≤ 60 s) without a GPU.

Optional future work: a Rust extension for the WMFB weighted-median hot loop, and
a request queue for backpressure under load.
