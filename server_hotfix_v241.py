#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.41 / profile 1.8.18.

Vertically flips the decoded Y1 map raster for Home Assistant presentation while
preserving the working background cleanup and room palette from 1.8.17.
"""
from pathlib import Path

import server_hotfix_v240 as release
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.41"
PROFILE_VERSION = "1.8.18"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1818() -> Path:
    src = release.build_profile_1817()
    dst = Path("/app/cqyi87_profile_1818.py")
    text = src.read_text()
    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.17"',
        'Y1PRO_PATCH_VERSION = "1.8.18"',
        "1.8.17 profile marker",
    )

    helper = r'''


def _flip_y1_raster_vertical(raw, width, height):
    """Flip raster top-to-bottom without changing horizontal orientation."""
    if width <= 0 or height <= 1 or len(raw) < width * height:
        return raw
    data = bytes(raw)
    return b"".join(
        data[y * width:(y + 1) * width]
        for y in range(height - 1, -1, -1)
    )
'''
    anchor = "\ndef _emit_y1_raster(event_bus, map_data: dict[str, Any]) -> bool:\n"
    if anchor not in text:
        raise RuntimeError("Could not locate Y1 raster emitter for vertical flip")
    text = text.replace(anchor, helper + anchor, 1)

    old = "raw = _clean_y1_raster(raw_without_outside, width, height)"
    new = "raw = _flip_y1_raster_vertical(_clean_y1_raster(raw_without_outside, width, height), width, height)"
    text = _replace_once(text, old, new, "Y1 cleaned raster for vertical flip")

    # Robot/dock coordinates are emitted in the same renderer coordinate system.
    # Mirror their Y coordinate about the decoded raster's physical vertical span
    # so overlays remain aligned with the vertically flipped floor plan.
    old_y = "y = float(y_max) - (float(py) * float(resolution))"
    new_y = "y = float(y_max) - ((float(height - 1) - float(py)) * float(resolution))"
    if old_y in text:
        text = text.replace(old_y, new_y)

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1818()
    installer.PROFILE_VERSION = PROFILE_VERSION
    installer._PROFILE_BUILD_ERROR = None
except Exception as exc:
    _PROFILE_BUILD_ERROR = str(exc)
    installer.PROFILE_VERSION = PROFILE_VERSION
    installer._PROFILE_BUILD_ERROR = _PROFILE_BUILD_ERROR
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.s.patch_status = installer.patch_status_strict
w.s.install_patch = installer.install_patch_strict

_base_diagnose = w.s.diagnose

def diagnose_241():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_orientation"] = {
        "vertical_flip": True,
        "horizontal_flip": False,
        "background_cleanup_preserved": True,
        "room_colours_preserved": True,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Flip Y1 map vertically in Home Assistant"
    return result

w.s.diagnose = diagnose_241
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.40", "v2.0.41").replace("v2.0.39", "v2.0.41").replace("v2.0.33", "v2.0.41")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}; expected profile {PROFILE_VERSION}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
