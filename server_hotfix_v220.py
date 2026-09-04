#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.20 / profile 1.8.6.

Adds read-only capture of actual values for useful Y1 state/settings fields that
have already appeared in Home Assistant Core logs. This is for protocol mapping:
it does not send commands or change the working cqyi87 profile.
"""
import re

import server_hotfix_v219 as h

w = h.w
VERSION = "2.0.20"

# Only low-risk scalar settings/state values are returned. Map/resource/device
# identifiers and arbitrary payloads are intentionally excluded.
SAFE_FIELDS = (
    "mopState", "autoBoost", "breakCleanSwitch", "childLock", "cleanCount",
    "collectDust", "disturbSwitch", "fanMode", "waterMode", "chargeStatus",
    "status", "pauseSwitch", "dormant", "cleanArea", "cleanTime", "battery",
)


def _scalar_value(line, field):
    """Extract a JSON-ish scalar without exposing surrounding telemetry."""
    q = re.escape(field)
    m = re.search(
        r'[\"\']' + q + r'[\"\']\s*:\s*('
        r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|'
        r'true|false|null|-?\d+(?:\.\d+)?)',
        line,
        re.I,
    )
    if not m:
        return None
    raw = m.group(1)
    low = raw.lower()
    if low == "true": return True
    if low == "false": return False
    if low == "null": return None
    if raw[:1] in ("\"", "'"):
        value = raw[1:-1]
        return value[:80]
    try:
        return float(raw) if "." in raw else int(raw)
    except Exception:
        return raw[:80]


def capture_field_values():
    _, _, lines = w.s.get_logs("60m")
    values = {name: [] for name in SAFE_FIELDS}
    for raw in lines:
        if not re.search(r"ecovacs|deebot|cqyi87", raw, re.I):
            continue
        line = w.s.redact(raw)
        for name in SAFE_FIELDS:
            if not re.search(r'[\"\']' + re.escape(name) + r'[\"\']\s*:', line):
                continue
            value = _scalar_value(line, name)
            if value is not None and value not in values[name]:
                values[name].append(value)
                values[name] = values[name][-20:]
    found = {k: v for k, v in values.items() if v}
    return {
        "ok": True,
        "version": VERSION,
        "window": "60m",
        "values": found,
        "not_seen": [k for k in SAFE_FIELDS if k not in found],
        "notes": [
            "Read-only: no commands were sent to the robot.",
            "Values are distinct scalar values observed in recent Ecovacs/Y1 log traffic.",
            "Use changes observed while deliberately changing one setting at a time to map numeric/boolean meanings safely.",
        ],
    }


# Enrich the existing discovery result with values as well.
_base_discover = w.s.discover_capabilities


def discover_with_values():
    result = _base_discover()
    result["version"] = VERSION
    result["observed_values"] = capture_field_values()
    return result


w.s.capture_field_values = capture_field_values
w.s.discover_capabilities = discover_with_values

# v218's diagnose wrapper captured its original discovery function directly,
# so wrap diagnosis once more to ensure the 2.0.20 value report is included.
_base_diagnose = w.s.diagnose


def diagnose_220():
    result = _base_diagnose()
    result["field_value_capture"] = capture_field_values()
    return result


w.s.diagnose = diagnose_220
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.19", "v2.0.20")
w.s.HTML = w.s.HTML.replace(
    "<button class=good onclick=discoverCaps()>Discover capabilities</button>",
    "<button class=good onclick=discoverCaps()>Discover capabilities</button><button class=good onclick=fieldValues()>Capture field values</button>",
    1,
)
w.s.HTML = w.s.HTML.replace(
    "async function discoverCaps()",
    "async function fieldValues(){out(await post('./api/field-values'))}async function discoverCaps()",
    1,
)

_BaseHandler = w.s.Handler


class Handler220(_BaseHandler):
    def do_POST(self):
        p = self.path.split("?", 1)[0].rstrip("/")
        if p.endswith("/api/field-values"):
            return self.sendj(capture_field_values())
        if p.endswith("/api/discover"):
            return self.sendj(discover_with_values())
        return super().do_POST()


w.s.Handler = Handler220

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; profile remains 1.8.6",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
