#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.40 / profile 1.8.17.

Removes only the border-connected outside/background region from the Y1 raster.
This avoids treating an entire raw value as background, because the same value can
also occur inside the real floor plan. Interior room colours and geometry remain.
"""
from pathlib import Path

import server_hotfix_v239 as release
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.40"
PROFILE_VERSION = "1.8.17"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1817() -> Path:
    src = release.build_profile_1816()
    dst = Path("/app/cqyi87_profile_1817.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.16"',
        'Y1PRO_PATCH_VERSION = "1.8.17"',
        "1.8.16 profile marker",
    )

    helper = r'''


def _clear_y1_border_background(raw, width, height):
    """Clear only the outside region connected to the raster border.

    Y1 can reuse a raster value both outside the mapped floor plan and inside a
    genuine room. Therefore value-based global replacement is unsafe. Detect the
    dominant non-zero value on the outer border, then flood-fill only that value
    from the border inward. Enclosed occurrences of the same value are preserved.
    """
    try:
        if width <= 0 or height <= 0 or len(raw) < width * height:
            return raw
        from collections import Counter, deque

        border_values = []
        border_values.extend(int(v) for v in raw[:width])
        border_values.extend(int(v) for v in raw[(height - 1) * width:height * width])
        for y in range(1, height - 1):
            border_values.append(int(raw[y * width]))
            if width > 1:
                border_values.append(int(raw[y * width + width - 1]))

        nonzero = Counter(v for v in border_values if v != 0)
        if not nonzero:
            return raw
        background_value, _ = nonzero.most_common(1)[0]

        out = bytearray(raw)
        seen = bytearray(width * height)
        q = deque()

        def seed(x, y):
            i = y * width + x
            if not seen[i] and int(out[i]) == background_value:
                seen[i] = 1
                q.append(i)

        for x in range(width):
            seed(x, 0)
            if height > 1:
                seed(x, height - 1)
        for y in range(1, height - 1):
            seed(0, y)
            if width > 1:
                seed(width - 1, y)

        cleared = 0
        while q:
            i = q.popleft()
            out[i] = 0
            cleared += 1
            x = i % width
            y = i // width
            if x > 0:
                j = i - 1
                if not seen[j] and int(out[j]) == background_value:
                    seen[j] = 1
                    q.append(j)
            if x + 1 < width:
                j = i + 1
                if not seen[j] and int(out[j]) == background_value:
                    seen[j] = 1
                    q.append(j)
            if y > 0:
                j = i - width
                if not seen[j] and int(out[j]) == background_value:
                    seen[j] = 1
                    q.append(j)
            if y + 1 < height:
                j = i + width
                if not seen[j] and int(out[j]) == background_value:
                    seen[j] = 1
                    q.append(j)

        print(
            f"Y1_BORDER_BACKGROUND value={background_value} cleared={cleared} pixels",
            flush=True,
        )
        return bytes(out)
    except Exception as exc:
        print(f"Y1 border background cleanup failed: {exc}", flush=True)
        return raw
'''

    anchor = "\ndef _emit_y1_raster(event_bus, map_data: dict[str, Any]) -> bool:\n"
    if anchor not in text:
        raise RuntimeError("Could not locate Y1 raster emitter for border cleanup")
    text = text.replace(anchor, helper + anchor, 1)

    old = (
        "raw_unfiltered = _lz4_decode(packed)\n"
        "        _record_y1_raw_raster(raw_unfiltered, width, height, map_data)\n"
        "        raw = _clean_y1_raster(raw_unfiltered, width, height)"
    )
    new = (
        "raw_unfiltered = _lz4_decode(packed)\n"
        "        _record_y1_raw_raster(raw_unfiltered, width, height, map_data)\n"
        "        raw_without_outside = _clear_y1_border_background(raw_unfiltered, width, height)\n"
        "        raw = _clean_y1_raster(raw_without_outside, width, height)"
    )
    text = _replace_once(text, old, new, "Y1 decoded raster cleanup path")

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1817()
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

def diagnose_240():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_background"] = {
        "strategy": "border-connected flood fill",
        "background_detection": "dominant non-zero border value",
        "outside_to_transparent": True,
        "interior_same_value_preserved": True,
        "svg_canvas": "white",
        "room_colours_preserved": True,
        "geometry_changed": False,
        "position_transform_changed": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Remove only border-connected Y1 outside area; preserve same-colour interior rooms"
    return result

w.s.diagnose = diagnose_240
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.39", "v2.0.40").replace("v2.0.38", "v2.0.40").replace("v2.0.33", "v2.0.40")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}; expected profile {PROFILE_VERSION}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
