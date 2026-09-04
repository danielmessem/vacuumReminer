#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.39 / profile 1.8.16.

Makes Y1 raster value 1 transparent so the large pale-blue outside/background
area renders as white, while preserving the working pastel room colours.
"""
from pathlib import Path

import server_hotfix_v238 as release
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.39"
PROFILE_VERSION = "1.8.16"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1816() -> Path:
    src = release.build_profile_1815()
    dst = Path("/app/cqyi87_profile_1816.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.15"',
        'Y1PRO_PATCH_VERSION = "1.8.16"',
        "1.8.15 profile marker",
    )

    old_pixel = (
        "def _pixel_index(value: int) -> int:\n"
        "    # Y1 positive raster values represent room/segment labels. Keep 0\n"
        "    # transparent and map each positive label into the six pastel room\n"
        "    # palette indices understood by deebot-client.\n"
        "    if value <= 0:\n"
        "        return 0\n"
        "    return 6 + ((value - 1) % 6)\n\n"
    )
    new_pixel = (
        "def _pixel_index(value: int) -> int:\n"
        "    # Y1 raster value 1 is the outside/unmapped background. Keep it\n"
        "    # transparent so Home Assistant's SVG canvas shows white behind the\n"
        "    # floor plan. Other positive values are room/segment labels mapped\n"
        "    # into deebot-client's six pastel room colours.\n"
        "    if value <= 1:\n"
        "        return 0\n"
        "    return 6 + ((value - 2) % 6)\n\n"
    )
    text = _replace_once(text, old_pixel, new_pixel, "Y1 room/background palette mapping")

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1816()
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

def diagnose_239():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_background"] = {
        "raw_background_value": 1,
        "renderer_palette_index": 0,
        "transparent": True,
        "svg_canvas": "white",
        "room_colours_preserved": True,
        "geometry_changed": False,
        "position_transform_changed": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Render Y1 outside/background as transparent white while preserving pastel room colours"
    return result

w.s.diagnose = diagnose_239
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.38", "v2.0.39").replace("v2.0.37", "v2.0.39").replace("v2.0.33", "v2.0.39")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}; expected profile {PROFILE_VERSION}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
