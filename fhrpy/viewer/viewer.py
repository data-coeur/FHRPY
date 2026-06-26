"""Python wrapper around the vanilla-JS FHR / CTG web viewer.

The wrapper bundles the JS + CSS + (base64) data into a single self-contained
HTML page so the viewer works:

* inline in a Jupyter notebook (VSCode and Colab) via an ``srcdoc`` iframe,
* as a standalone offline ``.html`` file (no server, no PHP),
* served from a background ``http.server`` thread (handy on Colab proxy).

The outbound control path (Python -> viewer) is implemented by posting messages
into the iframe. Inbound events (viewer -> Python) are best-effort: they are
forwarded via ``window.postMessage`` from the iframe; in a notebook they can be
captured with an IPython comm. If a full bidirectional comm is impractical in a
given frontend, the JS ``viewer.on(event, cb)`` API remains available in-page.
"""

from __future__ import annotations

import base64
import json
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:  # Python 3.9+: read packaged web assets after pip install
    from importlib import resources as _resources
except ImportError:  # pragma: no cover
    import importlib_resources as _resources  # type: ignore


_DEFAULT_CHANNELS = ["FHR1", "FHR2", "MHR"]


def _read_asset(name: str) -> str:
    """Read a file from the package ``web/`` directory."""
    pkg = "fhrpy.viewer.web"
    try:
        return _resources.files(pkg).joinpath(name).read_text(encoding="utf-8")
    except (AttributeError, FileNotFoundError):
        # Fallback for older importlib / source checkouts.
        here = Path(__file__).resolve().parent / "web" / name
        return here.read_text(encoding="utf-8")


class FHRViewer:
    """A Python-controllable handle to the web CTG viewer.

    Parameters
    ----------
    path:
        Path to a ``.rcf`` / ``.rcfm`` / ``.fhr`` / ``.rcfa`` recording.
    markers:
        Optional list of ``[sampleIndex, text]`` marks, or a marker-file string.
    height:
        Initial viewer height in pixels.
    scale:
        Paper speed in cm/min: ``1`` (default) or ``3``.
    channels:
        List of FHR channel names to display (e.g. ``["FHR1", "MHR"]``).
    interpolate:
        Linear-interpolate missing points when ``True``.
    zones:
        Show colored acc/dec/contraction zones when ``True`` (default).
    analyze:
        When ``True``, run the WMFB baseline + accel/decel analysis
        (:func:`fhrpy.baseline.analyze`) on the recording and feed the real
        baseline / preprocessed FHR / acceleration / deceleration zones to the
        viewer (re-encoded as an analysed ``.rcfa`` payload). Requires NumPy/SciPy.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        markers=None,
        height: int = 400,
        scale: int = 1,
        channels=None,
        interpolate: bool = False,
        zones: bool = True,
        signals_per_graph: int | None = None,
        analyze: bool = False,
        **opts,
    ):
        self.path = Path(path) if path is not None else None
        self.ext = self._infer_ext(self.path)
        self.data = self.path.read_bytes() if self.path else b""
        self.analyzed = False
        self.height = int(height)
        self.scale = 3 if int(scale) == 3 else 1
        self.channels = list(channels) if channels else None
        self.interpolate = bool(interpolate)
        self.zones = bool(zones)
        self.signals_per_graph = signals_per_graph
        self._extra_opts = opts

        self.markers = self._normalize_markers(markers)

        if analyze and self.path is not None:
            self._apply_analysis()

        self._iframe_id = "fhr_" + uuid.uuid4().hex[:12]
        self._server = None
        self._server_thread = None
        self._event_callbacks: dict[str, list] = {}

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _infer_ext(path):
        if path is None:
            return "rcfm"
        suffix = path.suffix.lower().lstrip(".")
        return suffix or "rcfm"

    @staticmethod
    def _normalize_markers(markers):
        if markers is None:
            return []
        if isinstance(markers, str):
            out = []
            for line in markers.splitlines():
                if len(line) > 5:
                    try:
                        out.append([int(line[:7]), line[8:]])
                    except ValueError:
                        continue
            return out
        # assume list of [sample, text]
        return [[int(m[0]), str(m[1])] for m in markers]

    def _apply_analysis(self) -> None:
        """Run the WMFB analysis and replace the payload with an analysed ``.rcfa``.

        Computes the real baseline + preprocessed FHR and the acceleration /
        deceleration segments, re-encodes the recording as a 12-byte ``.rcfa``
        (carrying ``FHRi`` + ``baseline``), and prepends ``$ ACC`` / ``$ DEC``
        period markers so the colored zones reflect the real analysis instead of
        the flat-140 placeholder.
        """
        import numpy as np  # local import: keep the viewer importable without NumPy

        from ..baseline import analyze as _analyze
        from ..io import encode_fhr, read_fhr

        rec = read_fhr(self.path)
        res = _analyze(rec)
        rec.fhri = np.asarray(res["fhri"], dtype=float)
        rec.baseline = np.asarray(res["baseline"], dtype=float)

        # The JS reads ``.rcfa`` as a fixed 12 bytes/sample layout (MHR present),
        # so always include the MHR channel (zeros when the source had none).
        self.data = encode_fhr(rec, with_mhr=True, with_analysis=True, header_bytes=8)
        self.ext = "rcfa"

        fs = float(getattr(rec, "fs", 4.0) or 4.0)
        zone_marks = []
        for typ, key in (("ACC", "accelerations"), ("DEC", "decelerations")):
            for seg in res.get(key) or []:
                start_s, end_s = float(seg[0]), float(seg[1])
                samp = int(round(start_s * fs))
                dur = int(round((end_s - start_s) * fs))
                if dur > 0:
                    zone_marks.append([samp, f"$ {typ} {dur}"])
        # Period marks first, then any user marks (drawn order is sample-sorted anyway).
        self.markers = zone_marks + self.markers
        self.analyzed = True

    def _options_json(self) -> str:
        opts = {
            "height": self.height,
            "scale": self.scale,
            "interpolate": self.interpolate,
            "zones": self.zones,
        }
        if self.channels:
            opts["channels"] = self.channels
        if self.signals_per_graph is not None:
            opts["signalsPerGraph"] = self.signals_per_graph
        opts.update(self._extra_opts)
        return json.dumps(opts)

    def _build_html(self) -> str:
        """Return a fully self-contained HTML page (JS + CSS + data inline)."""
        js = _read_asset("fhrviewer.js")
        css = _read_asset("fhrviewer.css")
        template = _read_asset("standalone.html")

        # Strip the `export` keywords so the module body can be inlined directly.
        js_inline = (
            js.replace("export class FHRViewer", "class FHRViewer")
            .replace("export function upgradeAll", "function upgradeAll")
            .replace("export default FHRViewer;", "")
        )

        data_b64 = base64.b64encode(self.data).decode("ascii") if self.data else ""
        html = (
            template.replace("/*__CSS__*/", css)
            .replace("/*__JS__*/", js_inline)
            .replace("{{DATA_B64}}", data_b64)
            .replace("{{EXT}}", self.ext)
            .replace("{{MARKERS}}", json.dumps(self.markers))
            .replace("{{OPTIONS_JSON}}", self._options_json())
        )
        return html

    # ------------------------------------------------------------------ #
    # rendering
    # ------------------------------------------------------------------ #
    def to_html(self, path: str | Path) -> Path:
        """Write a standalone offline HTML bundle (viewer + data) to ``path``."""
        path = Path(path)
        path.write_text(self._build_html(), encoding="utf-8")
        return path

    def _srcdoc_iframe(self) -> str:
        html = self._build_html()
        escaped = html.replace("&", "&amp;").replace('"', "&quot;")
        return (
            f'<iframe id="{self._iframe_id}" srcdoc="{escaped}" '
            f'style="width:100%;height:{self.height + 70}px;border:none;" '
            f'allow="fullscreen"></iframe>'
        )

    def _repr_html_(self) -> str:
        """Inline rendering for Jupyter (VSCode + Colab)."""
        return self._srcdoc_iframe()

    def show(self):
        """Display the viewer inline in a notebook, or open a browser otherwise."""
        try:
            from IPython.display import HTML, display  # type: ignore

            display(HTML(self._srcdoc_iframe()))
            return
        except Exception:
            pass
        # Not in a notebook: fall back to serving + opening a browser.
        self.serve()

    @staticmethod
    def _in_colab() -> bool:
        try:
            import google.colab  # noqa: F401  # type: ignore

            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # serving
    # ------------------------------------------------------------------ #
    def serve(self, port: int = 0, open_browser: bool = True):
        """Launch a background HTTP server thread and open the viewer.

        Returns the bound port. On Colab the served URL must be reached through
        the Colab output proxy (``google.colab.output.serve_kernel_port_as_window``).
        """
        html_bytes = self._build_html().encode("utf-8")

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)

            def log_message(self, *args):  # silence
                pass

        self._server = HTTPServer(("127.0.0.1", port), _Handler)
        bound_port = self._server.server_address[1]
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()
        url = f"http://127.0.0.1:{bound_port}/"

        if open_browser:
            if self._in_colab():
                try:
                    from google.colab import output  # type: ignore

                    output.serve_kernel_port_as_window(bound_port)
                except Exception:
                    pass
            else:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
        return bound_port

    def stop(self):
        """Stop the background HTTP server, if running."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    # ------------------------------------------------------------------ #
    # outbound control path (Python -> viewer, via the iframe)
    # ------------------------------------------------------------------ #
    def _post(self, method: str, *args):
        """Post a control message into the rendered iframe (notebook only)."""
        try:
            from IPython.display import Javascript, display  # type: ignore
        except Exception:
            return False
        payload = json.dumps({"target": "fhrviewer", "method": method, "args": list(args)})
        js = (
            f"(function(){{var f=document.getElementById('{self._iframe_id}');"
            f"if(f&&f.contentWindow){{f.contentWindow.postMessage({payload},'*');}}}})();"
        )
        display(Javascript(js))
        return True

    def set_markers(self, markers):
        self.markers = self._normalize_markers(markers)
        return self._post("setMarkers", self.markers)

    def scroll_to(self, epoch_or_fraction):
        return self._post("scrollTo", epoch_or_fraction)

    def set_height(self, px: int):
        self.height = int(px)
        return self._post("setHeight", int(px))

    def set_scale(self, cm_per_min: int):
        self.scale = 3 if int(cm_per_min) == 3 else 1
        return self._post("setScale", self.scale)

    def set_channel_visible(self, name: str, visible: bool):
        return self._post("setChannelVisible", name, bool(visible))

    def set_zones_visible(self, on: bool):
        self.zones = bool(on)
        return self._post("setZonesVisible", bool(on))

    def set_interpolate(self, on: bool):
        self.interpolate = bool(on)
        return self._post("setInterpolate", bool(on))

    # ------------------------------------------------------------------ #
    # inbound events (viewer -> Python) — best effort
    # ------------------------------------------------------------------ #
    def on(self, event: str, callback):
        """Register a Python callback for a viewer event.

        Inbound delivery relies on the notebook frontend forwarding the iframe's
        ``postMessage`` to the kernel. When that bridge is unavailable, the
        in-page JS ``viewer.on('<event>', cb)`` API remains the supported path.

        TODO: wire a robust bidirectional IPython comm so these callbacks fire
        from the running viewer in all frontends (VSCode/Colab differ).
        """
        self._event_callbacks.setdefault(event, []).append(callback)
        return self
