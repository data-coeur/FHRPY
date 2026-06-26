"""Test the viewer's analyze=True integration (no browser needed).

Verifies that the Python WMFB analysis is fed to the web viewer as a real
12-byte ``.rcfa`` payload (carrying FHRi + baseline) plus ``$ ACC`` / ``$ DEC``
period markers, so the colored zones reflect the real analysis.
"""

import os

import pytest

from fhrpy.viewer import FHRViewer

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples", "example_recording.fhr")


@pytest.mark.skipif(not os.path.exists(EXAMPLE), reason="example recording not present")
def test_analyze_produces_rcfa_and_zone_markers():
    v = FHRViewer(EXAMPLE, analyze=True, height=440, zones=True)
    assert v.analyzed is True
    assert v.ext == "rcfa"
    # 8-byte header + N samples * 12 bytes (FHR1,FHR2,MHR,TOCO,Q,FHRi,baseline).
    assert (len(v.data) - 8) % 12 == 0
    # At least some acceleration/deceleration period markers were injected.
    zone = [m for m in v.markers if str(m[1]).startswith("$ ")]
    assert zone, "expected $ ACC/DEC period markers"
    types = {str(m[1]).split()[1] for m in zone}
    assert types <= {"ACC", "DEC", "CON"}
    # Each marker encodes a positive sample index and duration in samples.
    for samp, text in zone:
        assert samp >= 0
        assert int(str(text).split()[2]) > 0

    # The self-contained HTML embeds the analysed payload.
    html = v._build_html()
    assert "background-canvas" in html
    assert '"rcfa"' in html or "rcfa" in html
