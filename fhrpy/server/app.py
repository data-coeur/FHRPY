"""Standard-library HTTP inference server for FHRPY.

Endpoints
---------
``GET  /health``
    Liveness probe -> ``{"status": "ok", "workers": N}``.
``POST /analyze``
    Body = a raw recording file (``.fhr`` / ``.rcfm`` ...). The extension is
    taken from the ``X-Filename`` header or the ``?ext=`` query (default
    ``rcfm``). Returns JSON with the WMFB baseline (decimated for transport),
    accelerations, decelerations and — when ``?fs=1`` — false-signal segments.

The heavy work runs in a :class:`ProcessPoolExecutor`, so concurrent requests
are processed in parallel up to ``workers`` (default ``min(4, cpu)``) — matching
the 2-4 core real-time target (12 recordings of ~3 h in ~1 min).

Run: ``python -m fhrpy.server`` (see ``__main__``).
"""

from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _analyze_bytes(data: bytes, ext: str, with_fs: bool) -> dict:
    """Worker: decode a recording and return its analysis as JSON-able dict."""
    import numpy as np

    from fhrpy.baseline import analyze
    from fhrpy.falsesignal import detect_false_signals
    from fhrpy.io import read_fhr

    with tempfile.NamedTemporaryFile(suffix="." + ext.lstrip("."), delete=False) as fh:
        fh.write(data)
        tmp = fh.name
    try:
        rec = read_fhr(tmp)
        res = analyze(rec)
        baseline = np.asarray(res["baseline"], float)
        # Decimate the baseline to ~1 Hz for a compact response.
        step = max(1, int(round(rec.fs)))
        out = {
            "n_samples": int(len(rec)),
            "fs": rec.fs,
            "duration_s": round(len(rec) / rec.fs, 1),
            "baseline_1hz": [round(float(x), 2) for x in baseline[::step]],
            "accelerations": [[round(a, 1), round(b, 1)] for a, b in res["accelerations"]],
            "decelerations": [[round(a, 1), round(b, 1)] for a, b in res["decelerations"]],
        }
        if with_fs:
            fs = detect_false_signals(rec, kind="doppler")
            out["false_signals"] = [[round(a, 1), round(b, 1)] for a, b in fs["segments"]]
        return out
    finally:
        os.unlink(tmp)


class _Handler(BaseHTTPRequestHandler):
    pool: ProcessPoolExecutor = None  # set by build_server
    workers: int = 1

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        if urlparse(self.path).path == "/health":
            self._send(200, {"status": "ok", "workers": self.workers})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/analyze":
            self._send(404, {"error": "not found"})
            return
        q = parse_qs(parsed.query)
        ext = (self.headers.get("X-Filename", "").rsplit(".", 1)[-1]
               or q.get("ext", ["rcfm"])[0])
        with_fs = q.get("fs", ["0"])[0] not in ("0", "false", "")
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        if not data:
            self._send(400, {"error": "empty body"})
            return
        try:
            fut = self.pool.submit(_analyze_bytes, data, ext, with_fs)
            self._send(200, fut.result())
        except Exception as exc:  # pragma: no cover - defensive
            self._send(500, {"error": str(exc)})


def build_server(host: str = "0.0.0.0", port: int = 8000, workers: int | None = None):
    """Create a configured (but not yet serving) HTTP server + its process pool."""
    workers = workers or min(4, os.cpu_count() or 1)
    pool = ProcessPoolExecutor(max_workers=workers)
    handler = type("Handler", (_Handler,), {"pool": pool, "workers": workers})
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd._fhr_pool = pool  # keep a reference for shutdown
    return httpd


def run(host: str = "0.0.0.0", port: int = 8000, workers: int | None = None) -> None:
    httpd = build_server(host, port, workers)
    print(f"FHRPY inference server on http://{host}:{port}  (workers={httpd._fhr_pool._max_workers})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd._fhr_pool.shutdown()
