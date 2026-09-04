#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.36 / profile 1.8.13.

Treats positive Y1 raster values as room/segment labels instead of native
Deebot floor/wall semantic indices, which caused large blue/beige blocks in HA.
Also increases display padding so the map is smaller in the HA viewer.
"""
from pathlib import Path

import server_hotfix_v233 as release
import server_hotfix_v231 as base
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.36"
PROFILE_VERSION = "1.8.13"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1813() -> Path:
    src = base.build_profile_1810()
    dst = Path("/app/cqyi87_profile_1813.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.10"',
        'Y1PRO_PATCH_VERSION = "1.8.13"',
        "1.8.10 profile marker",
    )

    old_pixel = '''def _pixel_index(value: int) -> int:\n    if value <= 0:\n        return 0\n    if value <= 5:\n        return value\n    return 6 + ((value - 6) % 6)\n'''
    new_pixel = '''def _pixel_index(value: int) -> int:\n    # Y1 raster values are segment/room labels, not deebot-client's native\n    # floor/wall/carpet palette indices. Preserve 0 as transparent and map\n    # every positive segment label into the six native pastel room colours.\n    if value <= 0:\n        return 0\n    return 6 + ((value - 1) % 6)\n'''
    text = _replace_once(text, old_pixel, new_pixel, "Y1 raster palette mapping")

    patch = r'''

# Y1 PRO display-only SVG treatment. Expand the native viewBox around its centre
# and paint the canvas white. Map geometry and position coordinates stay intact.
try:
    import re as _y1_re
    from deebot_client import map as _y1_map_module

    if not getattr(_y1_map_module.MapData, "_y1pro_svg_padding_patch_1813", False):
        _y1_orig_generate_svg_1813 = _y1_map_module.MapData.generate_svg

        def _y1_generate_svg_1813(self):
            svg = _y1_orig_generate_svg_1813(self)
            if not svg or "viewBox=" not in svg:
                return svg
            try:
                match = _y1_re.search(r'viewBox="([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)"', svg)
                if not match:
                    return svg
                x, y, width, height = (float(v) for v in match.groups())
                if width <= 0 or height <= 0:
                    return svg
                factor = 1.75
                new_width = width * factor
                new_height = height * factor
                new_x = x - ((new_width - width) / 2.0)
                new_y = y - ((new_height - height) / 2.0)
                new_viewbox = f'viewBox="{new_x:.3f} {new_y:.3f} {new_width:.3f} {new_height:.3f}"'
                svg = svg[:match.start()] + new_viewbox + svg[match.end():]
                open_end = svg.find(">")
                if open_end != -1:
                    background = (
                        f'<rect x="{new_x:.3f}" y="{new_y:.3f}" '
                        f'width="{new_width:.3f}" height="{new_height:.3f}" fill="#ffffff"/>'
                    )
                    svg = svg[:open_end + 1] + background + svg[open_end + 1:]
                return svg
            except Exception:
                return svg

        _y1_map_module.MapData.generate_svg = _y1_generate_svg_1813
        _y1_map_module.MapData._y1pro_svg_padding_patch_1813 = True
except Exception:
    pass
'''
    text += patch
    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1813()
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

def diagnose_236():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_presentation"] = {
        "room_label_palette": True,
        "positive_pixels_as_room_segments": True,
        "white_svg_background": True,
        "svg_viewbox_factor": 1.75,
        "approx_map_fill_percent": 57,
        "geometry_changed": False,
        "position_transform_changed": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Correct Y1 room-label palette and shrink HA map presentation"
    return result

w.s.diagnose = diagnose_236
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.33", "v2.0.36")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
