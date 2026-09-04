#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.31 / profile 1.8.10.

Cleans the Y1 map raster before it is converted to Home Assistant map pieces.
Builds from the exact generated 1.8.9 profile and patches only stable anchors.
"""
from pathlib import Path

import server_hotfix_v230 as h
import server_hotfix_v216 as installer

w = h.w
VERSION = "2.0.31"
PROFILE_VERSION = "1.8.10"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1810() -> Path:
    src = h.build_profile_189()
    dst = Path("/app/cqyi87_profile_1810.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.9"',
        'Y1PRO_PATCH_VERSION = "1.8.10"',
        "1.8.9 profile marker",
    )

    helper_anchor = '\n\ndef _emit_y1_raster(event_bus, map_data: dict[str, Any]) -> bool:\n'
    helper = '''\n\ndef _clean_y1_raster(raw: bytes, width: int, height: int) -> bytes:
    """Conservatively remove isolated Y1 raster noise and tiny islands."""
    size = width * height
    src = bytearray(raw[:size])

    def occupied_neighbours(buf: bytearray, x: int, y: int) -> list[int]:
        values = []
        for yy in range(max(0, y - 1), min(height, y + 2)):
            base = yy * width
            for xx in range(max(0, x - 1), min(width, x + 2)):
                if xx == x and yy == y:
                    continue
                value = buf[base + xx]
                if value:
                    values.append(value)
        return values

    previous = src[:]
    for y in range(height):
        base = y * width
        for x in range(width):
            idx = base + x
            nearby = occupied_neighbours(previous, x, y)
            if previous[idx]:
                if len(nearby) <= 1:
                    src[idx] = 0
            elif len(nearby) == 8:
                counts = {}
                for value in nearby:
                    counts[value] = counts.get(value, 0) + 1
                src[idx] = max(counts, key=counts.get)

    seen = bytearray(size)
    for start in range(size):
        if not src[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        component = []
        while stack:
            idx = stack.pop()
            component.append(idx)
            y, x = divmod(idx, width)
            for yy in range(max(0, y - 1), min(height, y + 2)):
                for xx in range(max(0, x - 1), min(width, x + 2)):
                    nidx = yy * width + xx
                    if nidx != idx and src[nidx] and not seen[nidx]:
                        seen[nidx] = 1
                        stack.append(nidx)
        if len(component) < 8:
            for idx in component:
                src[idx] = 0

    return bytes(src)
'''
    text = _replace_once(text, helper_anchor, helper + helper_anchor, "Y1 raster renderer")

    # Patch the most stable decode line rather than matching surrounding whitespace
    # or later length-normalisation code, which changed between generated profiles.
    decode_anchor = '        raw = _lz4_decode(packed)\n'
    decode_replacement = '        raw = _clean_y1_raster(_lz4_decode(packed), width, height)\n'
    text = _replace_once(text, decode_anchor, decode_replacement, "Y1 raster decode")

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1810()
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

def diagnose_231():
    result = _base_diagnose()
    result["version"] = VERSION
    result["y1pro_map_cleanup"] = {
        "profile": PROFILE_VERSION,
        "smoothing_passes": 1,
        "minimum_island_pixels": 8,
        "palette_mapping_changed": False,
        "map_transform_changed": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    return result

w.s.diagnose = diagnose_231
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.30", "v2.0.31")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
