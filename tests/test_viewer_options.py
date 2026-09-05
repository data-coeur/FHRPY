"""Viewer wrapper options added with the OpenCTG port (issues #16, #17, #18, #19, #22)."""

import json
import os

from fhrpy.viewer import FHRViewer

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "sample.rcfm")


def _opts(v):
    return json.loads(v._options_json())


def test_timezone_accepts_hours_or_an_iana_name():
    assert _opts(FHRViewer(SAMPLE, timezone=2))["tzOffset"] == 7200
    o = _opts(FHRViewer(SAMPLE, timezone="Europe/Paris"))
    assert o["timeZone"] == "Europe/Paris"
    assert "tzOffset" not in o


def test_extra_options_are_forwarded_to_the_js_viewer():
    delays = {"doppler": 1, "scalp": 0, "mecg": 0, "mhrToco": 6, "mhrOximeter": 12.5, "toco": None}
    v = FHRViewer(SAMPLE, labels={"mhr.text": "RCM"}, delays=delays, follow=True, bytesPerSample=8)
    o = _opts(v)
    assert o["labels"] == {"mhr.text": "RCM"}
    assert o["delays"] == delays
    assert o["follow"] is True
    assert o["bytesPerSample"] == 8


def test_control_methods_post_the_matching_js_calls(monkeypatch):
    v = FHRViewer(SAMPLE)
    posted = []
    monkeypatch.setattr(v, "_post", lambda method, *args: posted.append((method, args)) or True)
    v.set_timezone("Asia/Tokyo")
    v.set_timezone(-5)
    v.set_delays({"doppler": 1})
    v.set_follow(True)
    v.print(cm_per_min=3, paper="letter", header=["Bed 3"])
    v.print()
    assert posted == [
        ("setTimezone", ("Asia/Tokyo",)),
        ("setTimezone", (-18000,)),
        ("setDelays", ({"doppler": 1},)),
        ("setFollow", (True,)),
        ("print", ({"cmPerMin": 3, "paper": "letter", "header": ["Bed 3"]},)),
        ("print", ({"cmPerMin": 1},)),
    ]
    assert v.timezone == -5.0
    # the state given to a later page reflects the last calls
    assert _opts(v)["delays"] == {"doppler": 1} and _opts(v)["follow"] is True


def test_standalone_html_inlines_the_module_without_export_statements():
    html = FHRViewer(SAMPLE)._build_html()
    assert "\nexport " not in html
    assert "export {" not in html
    assert "class Signals" in html and "setFollow(" in html and "btn-follow" in html


def test_protected_alert_and_metadata_markers_round_trip(tmp_path):
    marks = [
        [0, "§monitor model=M1350A serial=X"],
        [40, "£!Monitor failure 503"],
        [80, "£Red=Doppler"],
        [120, "Labour starts"],
    ]
    v = FHRViewer(SAMPLE, markers=marks)
    text = v.save_markers(tmp_path / "rec.marks").read_text(encoding="utf-8")
    assert FHRViewer(SAMPLE, markers=text).markers == marks
