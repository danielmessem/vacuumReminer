#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.38 / profile 1.8.15.

Adds raw decoded Y1 raster telemetry so we can identify the true outside/background
value before changing the renderer again. Keeps the working 1.8.14 presentation.
"""
from pathlib import Path

import server_hotfix_v237 as release
import server_hotfix_v231 as base
import server_hotfix_v216 as installer

w = release.w
VERSION = "2.0.38"
PROFILE_VERSION = "1.8.15"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_1815() -> Path:
    # Start from the already-working 1.8.14 generator, then add observation only.
    src = release.build_profile_1814()
    dst = Path("/app/cqyi87_profile_1815.py")
    text = src.read_text()
    text = _replace_once(text, 'Y1PRO_PATCH_VERSION = "1.8.14"', 'Y1PRO_PATCH_VERSION = "1.8.15"', "1.8.14 profile marker")

    helper = r'''

# Last raw raster summary, intentionally contains no Ecovacs account/device IDs.
_Y1_RAW_RASTER_DIAGNOSTICS = {}

def _record_y1_raw_raster(raw, width, height, map_data):
    try:
        from collections import Counter
        counts = Counter(int(v) for v in raw)
        total = max(1, len(raw))
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        top = [
            {"value": value, "count": count, "percent": round((count * 100.0) / total, 3)}
            for value, count in ordered[:32]
        ]
        nonzero = [(v, c) for v, c in counts.items() if v != 0]
        dominant_nonzero = max(nonzero, key=lambda item: item[1], default=(None, 0))
        border = []
        if width > 0 and height > 0 and len(raw) >= width * height:
            border.extend(raw[:width])
            border.extend(raw[(height - 1) * width:height * width])
            for row in range(1, max(1, height - 1)):
                border.append(raw[row * width])
                if width > 1:
                    border.append(raw[row * width + width - 1])
        border_counts = Counter(int(v) for v in border)
        border_ordered = sorted(border_counts.items(), key=lambda item: (-item[1], item[0]))
        _Y1_RAW_RASTER_DIAGNOSTICS.clear()
        _Y1_RAW_RASTER_DIAGNOSTICS.update({
            "width": int(width),
            "height": int(height),
            "pixels": int(len(raw)),
            "unique_values": int(len(counts)),
            "zero_percent": round((counts.get(0, 0) * 100.0) / total, 3),
            "dominant_nonzero_value": dominant_nonzero[0],
            "dominant_nonzero_percent": round((dominant_nonzero[1] * 100.0) / total, 3),
            "top_values": top,
            "border_top_values": [
                {"value": value, "count": count, "percent": round((count * 100.0) / max(1, len(border)), 3)}
                for value, count in border_ordered[:16]
            ],
            "resolution": map_data.get("resolution"),
            "lz4_len": map_data.get("lz4Len"),
        })
        print("Y1_RAW_RASTER_DIAGNOSTICS=" + repr(_Y1_RAW_RASTER_DIAGNOSTICS), flush=True)
    except Exception as exc:
        print(f"Y1 raw raster diagnostics failed: {exc}", flush=True)
'''

    anchor = "\ndef _emit_y1_raster(event_bus, map_data: dict[str, Any]) -> bool:\n"
    if anchor not in text:
        raise RuntimeError("Could not locate Y1 raster emitter for diagnostics")
    text = text.replace(anchor, helper + anchor, 1)

    # Record the decompressed bytes before cleanup/palette conversion. Match both
    # the 1.8.10 cleanup form and a plain decode form defensively.
    cleanup = "raw = _clean_y1_raster(_lz4_decode(packed), width, height)"
    if cleanup in text:
        text = text.replace(cleanup, "raw_unfiltered = _lz4_decode(packed)\n        _record_y1_raw_raster(raw_unfiltered, width, height, map_data)\n        raw = _clean_y1_raster(raw_unfiltered, width, height)", 1)
    else:
        plain = "raw = _lz4_decode(packed)"
        if plain not in text:
            raise RuntimeError("Could not locate Y1 LZ4 decode for diagnostics")
        text = text.replace(plain, "raw = _lz4_decode(packed)\n        _record_y1_raw_raster(raw, width, height, map_data)", 1)

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_1815()
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

def diagnose_238():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["y1pro_raster_diagnostics"] = {
        "enabled": True,
        "location": "Home Assistant Core log",
        "log_prefix": "Y1_RAW_RASTER_DIAGNOSTICS=",
        "captures": ["dimensions", "value_histogram", "border_histogram", "dominant_nonzero", "resolution", "lz4_len"],
        "raw_map_blob_logged": False,
        "account_or_device_ids_logged": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    result["release_note"] = "Add raw Y1 raster histogram diagnostics before any further background/palette changes"
    return result

w.s.diagnose = diagnose_238
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.37", "v2.0.38").replace("v2.0.33", "v2.0.38")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}; expected profile {PROFILE_VERSION}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
