#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.37 / profile 1.8.14.

Fixes profile generation for the Y1 room-palette renderer. Uses a regex anchor
against the generated 1.8.10 profile rather than an escaped literal block.
"""
from pathlib import Path
import re

import server_hotfix_v233 as release
import server_hotfix_v231 as base
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.37"
PROFILE_VERSION = "1.8.14"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1814() -> Path:
    src = base.build_profile_1810()
    dst = Path("/app/cqyi87_profile_1814.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.10"',
        'Y1PRO_PATCH_VERSION = "1.8.14"',
        "1.8.10 profile marker",
    )

    pattern = re.compile(
        r"def _pixel_index\(value: int\) -> int:\n"
        r"(?:    .*\n)+?"
        r"\n(?=def _clean_y1_raster|def _emit_y1_raster)",
        re.MULTILINE,
    )
    replacement = (
        "def _pixel_index(value: int) -> int:\n"
        "    # Y1 positive raster values represent room/segment labels. Keep 0\n"
        "    # transparent and map each positive label into the six pastel room\n"
        "    # palette indices understood by deebot-client.\n"
        "    if value <= 0:\n"
        "        return 0\n"
        "    return 6 + ((value - 1) % 6)\n\n"
    )
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        # More tolerant fallback: replace from function start to next top-level def.
        start = text.find("def _pixel_index(value: int) -> int:\n")
        if start < 0:
            raise RuntimeError("Could not locate Y1 raster palette mapping")
        next_def = text.find("\ndef ", start + 1)
        if next_def < 0:
            raise RuntimeError("Could not locate end of Y1 raster palette mapping")
        text = text[:start] + replacement + text[next_def + 1:]

    patch = r'''

# Y1 PRO display-only SVG treatment. Expand the native viewBox around its centre
# and paint the canvas white. Map geometry and position coordinates stay intact.
try:
    import re as _y1_re
    from deebot_client import map as _y1_map_module

    if not getattr(_y1_map_module.MapData, "_y1pro_svg_padding_patch_1814", False):
        _y1_orig_generate_svg_1814 = _y1_map_module.MapData.generate_svg

        def _y1_generate_svg_1814(self):
            svg = _y1_orig_generate_svg_1814(self)
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

        _y1_map_module.MapData.generate_svg = _y1_generate_svg_1814
        _y1_map_module.MapData._y1pro_svg_padding_patch_1814 = True
except Exception:
    pass
'''
    text += patch
    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1814()
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

def diagnose_237():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_map_presentation"] = {
        "room_label_palette": True,
        "positive_pixels_as_room_segments": True,
        "white_svg_background": True,
        "svg_viewbox_factor": 1.75,
        "approx_map_fill_percent": 57,
        "generator_anchor": "regex+fallback",
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Fix 1.8.13 generator anchor; apply Y1 room-label palette reliably"
    return result

w.s.diagnose = diagnose_237
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.33", "v2.0.37")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
