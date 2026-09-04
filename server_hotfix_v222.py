#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.22 / profile 1.8.6.

Adds a focused, read-only log capture for identifying the command/message and
payload associated with Y1 suction and water setting changes made in the
Ecovacs app. No commands are sent to the robot and profile 1.8.6 is unchanged.
"""
import re

import server_hotfix_v221 as h

w = h.w
VERSION = "2.0.22"

# Terms known from Y1 telemetry/capability discovery. We deliberately return
# only short redacted log fragments around these terms rather than whole logs.
TERMS = (
    "fanMode", "waterMode", "setSpeed", "setWaterInfo", "setWashInfo",
    "speed", "water", "10000", "10001",
)


def _focused_fragment(line: str) -> str:
    line = w.s.redact(line).strip()
    # Keep enough context to see command/type/body/data while limiting exposure.
    if len(line) > 1400:
        positions = [line.lower().find(t.lower()) for t in TERMS]
        positions = [p for p in positions if p >= 0]
        p = min(positions) if positions else 0
        start = max(0, p - 350)
        line = line[start:start + 1400]
    return line


def capture_setting_commands():
    _, _, lines = w.s.get_logs("5m")
    matches = []
    seen = set()
    command_names = set()
    for raw in lines:
        low = raw.lower()
        if not ("ecovacs" in low or "deebot" in low or "cqyi87" in low):
            continue
        if not any(term.lower() in low for term in TERMS):
            continue
        fragment = _focused_fragment(raw)
        if fragment in seen:
            continue
        seen.add(fragment)
        for pattern in (
            r'"(?:name|type|command|cmd)"\s*:\s*"([^"\\]{1,80})"',
            r"'(?:name|type|command|cmd)'\s*:\s*'([^'\\]{1,80})'",
        ):
            for m in re.finditer(pattern, fragment, re.I):
                command_names.add(m.group(1))
        matches.append(fragment)
        if len(matches) >= 80:
            break
    return {
        "ok": True,
        "version": VERSION,
        "window": "5m",
        "candidate_command_names": sorted(command_names),
        "matching_log_fragments": matches,
        "notes": [
            "Read-only: this capture does not send any robot commands.",
            "Change exactly one suction or water setting in the Ecovacs app, then capture immediately.",
            "Fragments are redacted and limited to lines containing Y1 setting/command terms.",
            "The goal is to prove the command name and payload before changing the working profile.",
        ],
    }


w.s.capture_setting_commands = capture_setting_commands
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.21", "v2.0.22")

# Add a dedicated button next to field capture when the known button markup is present.
w.s.HTML = w.s.HTML.replace(
    "<button class=good onclick=fieldValues()>Capture field values</button>",
    "<button class=good onclick=fieldValues()>Capture field values</button><button class=good onclick=settingCommands()>Capture setting command</button>",
    1,
)
w.s.HTML = w.s.HTML.replace(
    "async function fieldValues()",
    "async function settingCommands(){out(await post('./api/setting-command'))}async function fieldValues()",
    1,
)

_BaseHandler = w.s.Handler
class Handler222(_BaseHandler):
    def do_POST(self):
        p = self.path.split("?", 1)[0].rstrip("/")
        if p.endswith("/api/setting-command"):
            return self.sendj(capture_setting_commands())
        return super().do_POST()

w.s.Handler = Handler222

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; profile remains 1.8.6",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
