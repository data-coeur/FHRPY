"""Smoke test for the FHRPY inference server (stdlib HTTP + process pool)."""

import json
import os
import threading
import urllib.request

import pytest

from fhrpy.server import build_server

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "example_recording.fhr")


@pytest.mark.skipif(not os.path.exists(EXAMPLE), reason="example recording not present")
def test_health_and_analyze():
    httpd = build_server(host="127.0.0.1", port=0, workers=2)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/health", timeout=10) as r:
            health = json.load(r)
        assert health["status"] == "ok"
        assert health["workers"] == 2

        data = open(EXAMPLE, "rb").read()
        req = urllib.request.Request(
            base + "/analyze?fs=1", data=data, method="POST",
            headers={"X-Filename": "example_recording.fhr"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.load(r)
        assert res["n_samples"] > 1000
        assert isinstance(res["baseline_1hz"], list) and res["baseline_1hz"]
        assert "decelerations" in res and "false_signals" in res
    finally:
        httpd.shutdown()
        httpd._fhr_pool.shutdown()
