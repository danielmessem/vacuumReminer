#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.25 / profile 1.8.8.

Adds read-only focused capture for the remaining Y1 settings/capabilities already
seen in telemetry. No robot commands are sent and profile 1.8.8 is unchanged.
"""
import re

import server_hotfix_v224 as h

w = h.w
VERSION = "2.0.25"
PROFILE_VERSION = "1.8.8"

FIELDS = (
    "autoBoost",
    "breakCleanSwitch",
    "childLock",
    "cleanCount",
    "collectDust",
    "disturbSwitch",
    "dormant",
    "workMode",
    "mopState",
    "relocateSwitch",
    "silentOtaSwitch",
)


def capture_other_capabilities():
    _, _, lines = w.s.get_logs("5m")
    hits = []
    seen = set()
    for raw in lines:
        low = raw.lower()
        if not ("ecovacs" in low or "deebot" in low or "cqyi87" in low):
            continue
        if not any(field.lower() in low for field in FIELDS):
            continue
        line = w.s.redact(raw).strip()
        if line in seen:
            continue
        seen.add(line)
        hits.append(line[:1800])
        if len(hits) >= 100:
            break

    command_candidates = []
    for line in hits:
        m = re.search(r"iot/p2p/(\d{4,6})/", line)
        if m and m.group(1) not in command_candidates:
            command_candidates.append(m.group(1))

    latest = {}
    for field in FIELDS:
        for line in reversed(hits):
            m = re.search(r'[\"\']' + re.escape(field) + r'[\"\']\s*:\s*(true|false|null|-?\d+(?:\.\d+)?|[\"\'][^\"\']*[\"\'])', line, re.I)
            if not m:
                continue
            raw_value = m.group(1)
            if raw_value.lower() == "true":
                value = True
            elif raw_value.lower() == "false":
                value = False
            elif raw_value.lower() == "null":
                value = None
            elif raw_value[:1] in ('"', "'"):
                value = raw_value[1:-1]
            else:
                try:
                    value = int(raw_value)
                except ValueError:
                    try:
                        value = float(raw_value)
                    except ValueError:
                        value = raw_value
            latest[field] = value
            break

    return {
        "ok": True,
        "version": VERSION,
        "profile": PROFILE_VERSION,
        "window": "5m",
        "fields": list(FIELDS),
        "latest": latest,
        "candidate_numeric_commands": command_candidates,
        "matching_log_fragments": hits,
        "notes": [
            "Read-only: no commands are sent to the robot.",
            "Change exactly one setting in the Ecovacs app, then capture immediately.",
            "This is intended to map remaining settings before adding them to Home Assistant.",
        ],
    }


w.s.capture_other_capabilities = capture_other_capabilities
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.24", "v2.0.25")

# Add a button without disturbing existing diagnostics buttons.
w.s.HTML = w.s.HTML.replace(
    "<button class=good onclick=settingCommands()>Capture setting command</button>",
    "<button class=good onclick=settingCommands()>Capture setting command</button><button class=good onclick=otherCaps()>Capture other capabilities</button>",
    1,
)
w.s.HTML = w.s.HTML.replace(
    "async function settingCommands()",
    "async function otherCaps(){out(await post('./api/other-capabilities'))}async function settingCommands()",
    1,
)

_BaseHandler = w.s.Handler
class Handler225(_BaseHandler):
    def do_POST(self):
        p = self.path.split("?", 1)[0].rstrip("/")
        if p.endswith("/api/other-capabilities"):
            return self.sendj(capture_other_capabilities())
        return super().do_POST()

w.s.Handler = Handler225

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; profile remains {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
