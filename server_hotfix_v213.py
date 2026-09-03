#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.13 / profile 1.8.3.

Fixes the Y1 full-map coordinate transform. cqyi87 mapData xMin/yMax are
already 800x800 map-grid coordinates, while resolution describes each cell's
physical size. Earlier profiles treated xMin/yMax as millimetres, shrinking and
misplacing the raster in Home Assistant.
"""
from pathlib import Path

import server_hotfix_v212 as h

w = h.w
VERSION = "2.0.13"
PROFILE_VERSION = "1.8.3"


def build_profile_183():
    src = h.build_profile_182()
    dst = Path("/app/cqyi87_profile_183.py")
    text = src.read_text()

    text = text.replace('Y1PRO_PATCH_VERSION = "1.8.2"', 'Y1PRO_PATCH_VERSION = "1.8.3"', 1)

    # Profile 1.8.1 introduced unit_scale into the old millimetre transform.
    # Match that generated form here; matching the pre-1.8.1 source makes every
    # clean add-on build stop at profile 1.8.2.
    old = '''    for row in range(height):\n        y_mm = (y_max - (row * resolution)) * unit_scale\n        gy = int(round(400 - (y_mm / 50.0)))\n        if gy < 0 or gy >= 800:\n            continue\n        piece_row_from_top = gy // 100\n        piece_row_from_bottom = 7 - piece_row_from_top\n        oy = gy % 100\n        for col in range(width):\n            value = _pixel_index(raw[row * width + col])\n            if value == 0:\n                continue\n            x_mm = (x_min + (col * resolution)) * unit_scale\n            gx = int(round(400 + (x_mm / 50.0)))\n            if gx < 0 or gx >= 800:\n                continue\n            piece_col = gx // 100\n'''
    new = '''    # cqyi87 uses xMin/yMax in its native 800x800 cell grid. `resolution`\n    # is the physical size of one cell (5 cm on this Y1), not a multiplier for\n    # the offsets. Using the offsets as millimetres compressed a 227x270-cell\n    # house map into only a few dozen renderer pixels.\n    _LOGGER.warning(\n        "Y1PRO_MAP_GRID width=%s height=%s resolution=%s xMin=%s yMax=%s bounds=(%s,%s)-(%s,%s)",\n        width, height, resolution, x_min, y_max,\n        int(round(x_min)), int(round(y_max - (height - 1))),\n        int(round(x_min + (width - 1))), int(round(y_max)),\n    )\n    for row in range(height):\n        gy = int(round(y_max - row))\n        if gy < 0 or gy >= 800:\n            continue\n        piece_row_from_top = gy // 100\n        piece_row_from_bottom = 7 - piece_row_from_top\n        oy = gy % 100\n        for col in range(width):\n            value = _pixel_index(raw[row * width + col])\n            if value == 0:\n                continue\n            gx = int(round(x_min + col))\n            if gx < 0 or gx >= 800:\n                continue\n            piece_col = gx // 100\n'''
    if old not in text:
        raise RuntimeError("Could not locate Y1 raster coordinate transform")
    text = text.replace(old, new, 1)

    # mapMinorData is an incremental patch stream with no x/y anchor in the
    # observed payload. Do not attempt to paint it at an invented location; the
    # full mapData broadcasts remain the source of truth. Mark it handled so it
    # does not generate misleading parser warnings while we reverse its format.
    marker = '''    handled = False\n    mid = str(data.get("mapId", ""))\n'''
    replacement = '''    handled = False\n    mid = str(data.get("mapId", ""))\n    if isinstance(data.get("mapMinorData"), dict):\n        _LOGGER.debug("Y1PRO_MAP_MINOR received incremental patch; awaiting anchor format")\n        return HandlingResult.success()\n'''
    if marker not in text:
        raise RuntimeError("Could not locate Y1 map-data handler")
    text = text.replace(marker, replacement, 1)

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_183()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.12", "v2.0.13")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
