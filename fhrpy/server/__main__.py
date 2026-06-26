"""``python -m fhrpy.server`` entry point."""

import argparse

from .app import run

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="FHRPY inference server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=None)
    a = p.parse_args()
    run(host=a.host, port=a.port, workers=a.workers)
