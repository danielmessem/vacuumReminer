#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.35 / profile 1.8.12.

Reverts the raster-canvas experiment from 1.8.11 and instead shrinks the Y1 map
by expanding the rendered SVG viewBox. This preserves the actual map pixels and
keeps outside space white without adding fake raster data.
"""
from pathlib import Path

import server_hotfix_v233 as release
import server_hotfix_v231 as base
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.35"
PROFILE_VERSION = "1.8.12"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1812() -> Path:
    # Build from 1.8.10 deliberately: 1.8.11 painted a large background rectangle
    # into the raster, which caused HA to crop/scale the map badly.
    src = base.build_profile_1810()
    dst = Path("/app/cqyi87_profile_1812.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.10"',
        'Y1PRO_PATCH_VERSION = "1.8.12"',
        "1.8.10 profile marker",
    )

    # The native deebot-client renderer crops tightly to the raster. Post-process
    # the generated SVG instead: expand its viewBox around the same centre so the
    # floor plan occupies ~68% of the card, and add a white SVG background.
    # This does not alter map geometry, room pixels, robot coordinates or dock.
    patch = r'''

# Y1 PRO display-only SVG treatment. The Y1 profile is loaded only for cqyi87.
# We patch the Python MapData wrapper so the actual native map rendering remains
# untouched; only the final SVG viewport/background are adjusted.
try:
    import re as _y1_re
    from deebot_client import map as _y1_map_module

    if not getattr(_y1_map_module.MapData, "_y1pro_svg_padding_patch", False):
        _y1_orig_generate_svg = _y1_map_module.MapData.generate_svg

        def _y1_generate_svg(self):
            svg = _y1_orig_generate_svg(self)
            if not svg or "viewBox=" not in svg:
                return svg
            try:
                match = _y1_re.search(r'viewBox="([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)"', svg)
                if not match:
                    return svg
                x, y, width, height = (float(v) for v in match.groups())
                if width <= 0 or height <= 0:
                    return svg

                # Scale floor plan to roughly 68% of the available view area.
                factor = 1.47
                new_width = width * factor
                new_height = height * factor
                new_x = x - ((new_width - width) / 2.0)
                new_y = y - ((new_height - height) / 2.0)
                new_viewbox = f'viewBox="{new_x:.3f} {new_y:.3f} {new_width:.3f} {new_height:.3f}"'
                svg = svg[:match.start()] + new_viewbox + svg[match.end():]

                # Force a clean white canvas independent of HA light/dark theme.
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

        _y1_map_module.MapData.generate_svg = _y1_generate_svg
        _y1_map_module.MapData._y1pro_svg_padding_patch = True
except Exception:
    pass
'''

    text += patch
    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1812()
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

def diagnose_235():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_presentation"] = {
        "white_svg_background": True,
        "svg_viewbox_factor": 1.47,
        "approx_map_fill_percent": 68,
        "fake_raster_canvas": False,
        "geometry_changed": False,
        "position_transform_changed": False,
        "room_palette_changed": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Revert fake raster canvas; use white SVG background and larger viewBox so the HA map is smaller"
    return result

w.s.diagnose = diagnose_235
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.33", "v2.0.35")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
