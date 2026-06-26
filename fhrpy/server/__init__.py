"""FHRPY inference server (Étape 5).

A dependency-light HTTP inference service (Python standard library only — no
FastAPI/uvicorn required) that runs the WMFB baseline analysis and the
false-signal detector on uploaded recordings, using a process pool so several
recordings are analysed in parallel on a small CPU server.
"""

from .app import build_server, run

__all__ = ["build_server", "run"]
