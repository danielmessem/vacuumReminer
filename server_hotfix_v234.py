#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.34 / profile 1.8.11.

Adds a light display canvas and padding around the Y1 raster so the Home
Assistant map is closer to the Ecovacs app presentation and is not oversized.
The underlying map geometry, room palette and robot coordinates are unchanged.
"""
from pathlib import Path

import server_hotfix_v233 as release
import server_hotfix_v231 as base
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.34"
PROFILE_VERSION = "1.8.11"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1811() -> Path:
    src = base.build_profile_1810()
    dst = Path("/app/cqyi87_profile_1811.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.10"',
        'Y1PRO_PATCH_VERSION = "1.8.11"',
        "1.8.10 profile marker",
    )

    helper_anchor = '\n\ndef _emit_y1_raster(event_bus, map_data: dict[str, Any]) -> bool:\n'
    helper = '''\n\ndef _add_y1_display_canvas(pieces: dict[int, bytearray]) -> None:
    """Add a subtle near-white canvas and margin around the occupied Y1 map.

    deebot-client renders index 0 as transparent. On dark Home Assistant themes
    that makes the outside of the map look black/dark and the tightly-cropped
    viewBox makes the floor plan look oversized. Index 5 is the lightest native
    palette entry (#edf3fb), so use it only as display background around the
    existing raster. Existing non-zero map pixels are never changed.
    """
    min_x = 800
    min_y = 800
    max_x = -1
    max_y = -1

    for index, pixels in pieces.items():
        piece_col = index // 8
        piece_row_from_bottom = index % 8
        piece_row_from_top = 7 - piece_row_from_bottom
        for j, value in enumerate(pixels):
            if not value:
                continue
            input_x = j % 100
            input_y = j // 100
            gx = piece_col * 100 + input_y
            gy = piece_row_from_top * 100 + (99 - input_x)
            min_x = min(min_x, gx)
            min_y = min(min_y, gy)
            max_x = max(max_x, gx)
            max_y = max(max_y, gy)

    if max_x < min_x or max_y < min_y:
        return

    map_width = max_x - min_x + 1
    map_height = max_y - min_y + 1
    padding = max(14, int(max(map_width, map_height) * 0.12))
    padding = min(padding, 36)
    left = max(0, min_x - padding)
    right = min(799, max_x + padding)
    top = max(0, min_y - padding)
    bottom = min(799, max_y + padding)

    for gy in range(top, bottom + 1):
        piece_row_from_top = gy // 100
        piece_row_from_bottom = 7 - piece_row_from_top
        oy = gy % 100
        input_x = 99 - oy
        for gx in range(left, right + 1):
            piece_col = gx // 100
            ox = gx % 100
            index = piece_col * 8 + piece_row_from_bottom
            piece = pieces.setdefault(index, bytearray(10000))
            j = ox * 100 + input_x
            if piece[j] == 0:
                piece[j] = 5
'''
    text = _replace_once(text, helper_anchor, helper + helper_anchor, "Y1 raster renderer")

    emit_anchor = '''    if not pieces:\n        return False\n    try:\n'''
    emit_replacement = '''    if not pieces:\n        return False\n    _add_y1_display_canvas(pieces)\n    try:\n'''
    text = _replace_once(text, emit_anchor, emit_replacement, "Y1 map piece emission")

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1811()
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

def diagnose_234():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_presentation"] = {
        "light_canvas": True,
        "canvas_palette_index": 5,
        "canvas_rgb": "#edf3fb",
        "padding_ratio": 0.12,
        "padding_min_pixels": 14,
        "padding_max_pixels": 36,
        "geometry_changed": False,
        "position_transform_changed": False,
        "room_palette_changed": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Lighter Ecovacs-style map canvas with extra margin for a smaller HA presentation"
    return result

w.s.diagnose = diagnose_234
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.33", "v2.0.34")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
