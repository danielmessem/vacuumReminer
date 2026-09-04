#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.21 / profile 1.8.6.

Improves read-only Y1 field capture by reporting the latest observed value and
recent change sequence for each useful scalar field. No robot commands are sent
and the working cqyi87 profile remains unchanged.
"""
import re

import server_hotfix_v220 as h

w = h.w
VERSION = "2.0.21"
SAFE_FIELDS = h.SAFE_FIELDS
_scalar_value = h._scalar_value


def capture_field_values():
    _, _, lines = w.s.get_logs("15m")
    sequences = {name: [] for name in SAFE_FIELDS}
    for raw in lines:
        if not re.search(r"ecovacs|deebot|cqyi87", raw, re.I):
            continue
        line = w.s.redact(raw)
        for name in SAFE_FIELDS:
            if not re.search(r'[\"\']' + re.escape(name) + r'[\"\']\s*:', line):
                continue
            value = _scalar_value(line, name)
            if value is None:
                continue
            seq = sequences[name]
            if not seq or seq[-1] != value:
                seq.append(value)
                if len(seq) > 12:
                    del seq[:-12]

    found = {k: v for k, v in sequences.items() if v}
    latest = {k: v[-1] for k, v in found.items()}
    return {
        "ok": True,
        "version": VERSION,
        "window": "15m",
        "latest": latest,
        "recent_changes": found,
        "not_seen": [k for k in SAFE_FIELDS if k not in found],
        "notes": [
            "Read-only: no commands were sent to the robot.",
            "latest is the last scalar value seen in the selected log window.",
            "recent_changes is chronological and suppresses consecutive duplicates.",
            "For mapping suction/water levels, change one setting at a time and capture immediately.",
        ],
    }


# Replace v220 value capture globally so both dedicated capture and discovery use it.
w.s.capture_field_values = capture_field_values

_base_discover = h.discover_with_values

def discover_with_latest_values():
    result = _base_discover()
    result["version"] = VERSION
    result["observed_values"] = capture_field_values()
    return result

w.s.discover_capabilities = discover_with_latest_values

_base_diagnose = w.s.diagnose

def diagnose_221():
    result = _base_diagnose()
    result["field_value_capture"] = capture_field_values()
    return result

w.s.diagnose = diagnose_221
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.20", "v2.0.21")

_BaseHandler = w.s.Handler
class Handler221(_BaseHandler):
    def do_POST(self):
        p = self.path.split("?", 1)[0].rstrip("/")
        if p.endswith("/api/field-values"):
            return self.sendj(capture_field_values())
        if p.endswith("/api/discover"):
            return self.sendj(discover_with_latest_values())
        return super().do_POST()

w.s.Handler = Handler221

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; profile remains 1.8.6",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
