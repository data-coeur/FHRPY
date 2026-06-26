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
    false_signals:
        When ``True``, run the false-signal detector
        (:func:`fhrpy.falsesignal.detect_false_signals`) and inject the detected
        false-signal episodes as grey ``$ URS`` ("unreliable signal") shaded
        zones. ``false_signals_kind`` selects the model (``"doppler"`` default or
        ``"scalp"``); ``stage2_start`` is the optional 4 Hz second-stage sample
        index. Requires NumPy/SciPy.
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
        false_signals: bool = False,
        false_signals_kind: str = "doppler",
        stage2_start: int | None = None,
        timezone: float = 0.0,
        rcf_min: float | None = None,
        rcf_max: float | None = None,
        safe_min: float | None = None,
        safe_max: float | None = None,
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

        self.false_signals = bool(false_signals)
        self.false_signals_kind = false_signals_kind
        self.stage2_start = stage2_start
        # Time-axis timezone, in hours east of UTC. Default 0 (UTC) so an
        # anonymised epoch-0 start reads 00:00 on the time axis.
        self.timezone = float(timezone)

        # Top FHR grid bounds (bpm) and the central safe/normal band. ``None``
        # keeps the JS defaults (50..210 grid, 110..160 safe band).
        self.rcf_min = rcf_min
        self.rcf_max = rcf_max
        self.safe_min = safe_min
        self.safe_max = safe_max

        self.markers = self._normalize_markers(markers)
        if markers is None and self.path is not None:
            self._load_companion_markers()
        self._do_analyze = bool(analyze)

        if (analyze or self.false_signals) and self.path is not None:
            self._apply_pipeline()

        self._iframe_id = "fhr_" + uuid.uuid4().hex[:12]
        self._server = None
        self._server_thread = None
        self._event_callbacks: dict[str, list] = {}

    @classmethod
    def from_record(cls, record, markers=None, **opts):
        """Build a viewer directly from an in-memory :class:`fhrpy.io.FHRRecord`.

        Useful to display a hand-built or label-injected recording (e.g. an
        expert baseline) without writing a file first. The record is encoded to
        the analysed ``.rcfa`` layout when it carries a baseline, else
        ``.rcfm`` / ``.rcf``.
        """
        import numpy as np

        from ..io import encode_fhr

        def _has(a):
            return a is not None and np.asarray(a).size > 0

        with_analysis = _has(getattr(record, "baseline", None))
        with_mhr = _has(getattr(record, "mhr", None)) or with_analysis
        if with_analysis and not _has(getattr(record, "fhri", None)):
            record.fhri = np.asarray(record.fhr1, dtype=float)
        data = encode_fhr(record, with_mhr=with_mhr, with_analysis=with_analysis,
                          header_bytes=8)
        v = cls(path=None, markers=markers, **opts)
        v.data = data
        v.ext = "rcfa" if with_analysis else ("rcfm" if with_mhr else "rcf")
        return v

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

    def _load_companion_markers(self) -> None:
        """Load the companion marker file sitting next to the recording, if any.

        Looks for ``<name>.fhrh`` (the FHRPY/FHRMA marker convention), then
        ``<name>.marks``, then the legacy append-'h' name (e.g. ``x.rcfm`` ->
        ``x.rcfmh``).
        """
        if self.path is None:
            return
        for cand in (
            self.path.with_suffix(".fhrh"),
            self.path.with_suffix(".marks"),
            self.path.parent / (self.path.name + "h"),
        ):
            if cand.exists():
                self.markers = self._normalize_markers(cand.read_text(encoding="utf-8"))
                return

    def _apply_pipeline(self) -> None:
        """Run the analysis pipeline in the correct order and build the payload.

        Order matters: **false-signal detection & removal happens BEFORE the WMFB
        baseline**, so maternal/artefact samples don't distort the baseline. When
        both are requested, the detected false-signal samples are removed from the
        FHR before the baseline is computed. Detected episodes are shown as grey
        ``$ URS`` zones; the baseline + accel/decel as ``$ ACC`` / ``$ DEC`` zones.
        """
        import numpy as np  # local import: keep the viewer importable without NumPy

        from ..io import read_fhr

        rec = read_fhr(self.path)
        fs = float(getattr(rec, "fs", 4.0) or 4.0)
        n = len(rec)
        urs_marks, zone_marks = [], []

        # 1) False-signal detection & removal (upstream of the baseline).
        fs_mask = None
        if self.false_signals:
            from ..falsesignal import detect_false_signals

            res = detect_false_signals(
                rec, kind=self.false_signals_kind, stage2_start=self.stage2_start
            )
            fs_mask = np.asarray(res["mask"], dtype=bool)
            for start_s, end_s in res["segments"]:
                samp = int(round(start_s * fs))
                dur = int(round((end_s - start_s) * fs))
                if dur > 0:
                    urs_marks.append([samp, f"$ URS {dur}"])

        # 2) WMFB baseline + morphology, on the FS-cleaned signal.
        if self._do_analyze:
            from ..baseline import analyze as _analyze
            from ..io import encode_fhr

            if fs_mask is not None and fs_mask.any():
                m = fs_mask[:n]
                rec.fhr1 = rec.fhr1.copy()
                rec.fhr2 = rec.fhr2.copy()
                rec.fhr1[m] = 0  # 0 = lost signal -> treated as a gap by preprocess
                rec.fhr2[m] = 0
            ma = _analyze(rec)
            rec.fhri = np.asarray(ma["fhri"], dtype=float)
            rec.baseline = np.asarray(ma["baseline"], dtype=float)
            # The JS reads ``.rcfa`` as a fixed 12 bytes/sample layout (MHR present).
            self.data = encode_fhr(rec, with_mhr=True, with_analysis=True, header_bytes=8)
            self.ext = "rcfa"
            for typ, key in (("ACC", "accelerations"), ("DEC", "decelerations")):
                for seg in ma.get(key) or []:
                    samp = int(round(float(seg[0]) * fs))
                    dur = int(round((float(seg[1]) - float(seg[0])) * fs))
                    if dur > 0:
                        zone_marks.append([samp, f"$ {typ} {dur}"])
            self.analyzed = True

        # URS first, then ACC/DEC, then any user marks (drawn order is sample-sorted).
        self.markers = urs_marks + zone_marks + self.markers

    # ------------------------------------------------------------------ #
    # saving (recording + marker file)
    # ------------------------------------------------------------------ #
    def save_markers(self, path: str | Path) -> Path:
        """Write the current markers to a companion marker file.

        Format matches the viewer's loader: one line per mark, a 7-digit
        zero-padded 4 Hz sample index, a space, then the marker text (e.g.
        ``"0005216 $ ACC 192"`` or ``"0001234 £Question"``).
        """
        path = Path(path)
        lines = [f"{int(s):07d} {t}" for s, t in sorted(self.markers, key=lambda m: m[0])]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def save_recording(self, path: str | Path) -> Path:
        """Write the recording to a ``.rcf`` / ``.rcfm`` / ``.fhr`` file.

        The signal payload is taken from the source file (re-encoded via
        :func:`fhrpy.io.write_fhr` to the format implied by ``path``'s
        extension). Markers are *not* embedded in the recording — use
        :meth:`save_markers` for the companion marker file, or :meth:`save`
        to write both at once.
        """
        if self.path is None:
            raise ValueError("no source recording to save")
        path = Path(path)
        from ..io import read_fhr, write_fhr

        rec = read_fhr(self.path)
        ext = path.suffix.lower().lstrip(".")
        with_mhr = ext in ("rcfm", "fhrm")
        header = 8 if ext in ("rcf", "rcfm") else 4
        write_fhr(path, rec, with_mhr=with_mhr, header_bytes=header)
        return path

    def save(self, basepath: str | Path) -> tuple[Path, Path]:
        """Save both the recording and the companion marker file.

        ``basepath`` may include an extension (defaults to ``.rcfm``); the marker
        file is written next to it with a ``.marks`` suffix. Returns
        ``(recording_path, markers_path)``.
        """
        basepath = Path(basepath)
        if basepath.suffix == "":
            basepath = basepath.with_suffix(".rcfm")
        rec_path = self.save_recording(basepath)
        marks_path = self.save_markers(basepath.with_suffix(".marks"))
        return rec_path, marks_path

    def _options_json(self) -> str:
        opts = {
            "height": self.height,
            "scale": self.scale,
            "interpolate": self.interpolate,
            "zones": self.zones,
            "tzOffset": int(round(self.timezone * 3600)),
        }
        if self.channels:
            opts["channels"] = self.channels
        if self.signals_per_graph is not None:
            opts["signalsPerGraph"] = self.signals_per_graph
        if self.rcf_min is not None and self.rcf_max is not None:
            opts["range"] = [float(self.rcf_min), float(self.rcf_max)]
        if self.safe_min is not None and self.safe_max is not None:
            opts["safeZone"] = [float(self.safe_min), float(self.safe_max)]
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
            f'style="width:100%;height:{self.height + 10}px;border:none;background:#fff;" '
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

    def set_timezone(self, hours: float):
        """Set the time-axis timezone, in hours east of UTC (0 = UTC)."""
        self.timezone = float(hours)
        return self._post("setTimezone", int(round(self.timezone * 3600)))

    def set_channel_visible(self, name: str, visible: bool):
        return self._post("setChannelVisible", name, bool(visible))

    def set_zones_visible(self, on: bool):
        self.zones = bool(on)
        return self._post("setZonesVisible", bool(on))

    def set_interpolate(self, on: bool):
        self.interpolate = bool(on)
        return self._post("setInterpolate", bool(on))

    def set_contractions_visible(self, on: bool):
        """Show/hide the detected contraction (TOCO) zones."""
        return self._post("setContractionsVisible", bool(on))

    def set_false_signals_visible(self, on: bool):
        """Show/hide the false-signal (maternal/artefact) zones."""
        return self._post("setFalseSignalsVisible", bool(on))

    def set_range(self, min_bpm: float, max_bpm: float):
        """Set the top FHR grid bounds (bpm)."""
        self.rcf_min, self.rcf_max = float(min_bpm), float(max_bpm)
        return self._post("setRange", float(min_bpm), float(max_bpm))

    def set_safe_zone(self, min_bpm: float, max_bpm: float):
        """Set the central safe/normal FHR band (bpm), default 110–160."""
        self.safe_min, self.safe_max = float(min_bpm), float(max_bpm)
        return self._post("setSafeZone", float(min_bpm), float(max_bpm))

    def print(self):
        """Open the printable, multi-page A4-landscape layout (Save as PDF)."""
        return self._post("print")

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


def link_scroll(*viewers) -> bool:
    """Keep several already-displayed viewers scroll-synchronised (notebook).

    After displaying two (or more) :class:`FHRViewer` iframes, call this to lock
    their time windows together: scrolling, paging or wheel-scrolling one moves
    the others to the **same instant**. Handy to compare expert labels vs the
    method's predictions side by side. Implemented by relaying each viewer's
    ``scroll`` ``postMessage`` in the notebook frontend (best effort across
    VSCode / Colab); the in-page ``viewer.on('scroll', cb)`` API is the fallback.
    """
    try:
        from IPython.display import Javascript, display  # type: ignore
    except Exception:
        return False
    ids = [v._iframe_id for v in viewers]
    js = (
        "(function(){var ids=" + json.dumps(ids) + ";"
        "function frames(){return ids.map(function(id){return document.getElementById(id);});}"
        "var busy=false;"
        "window.addEventListener('message',function(e){"
        "var m=e.data; if(!m||m.source!=='fhrviewer'||m.event!=='scroll'||busy) return;"
        "var t=m.detail&&m.detail.time; if(t==null) return; busy=true;"
        "frames().forEach(function(f){ if(f&&f.contentWindow&&f.contentWindow!==e.source){"
        "f.contentWindow.postMessage({target:'fhrviewer',method:'scrollTo',args:[t]},'*');}});"
        "setTimeout(function(){busy=false;},40);});})();"
    )
    display(Javascript(js))
    return True
