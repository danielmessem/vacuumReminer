#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.29 / profile 1.8.8.

Adds read-only consumables capture and display. No robot commands are sent and
profile 1.8.8 is unchanged.
"""
import ast
import json
import re

import server_hotfix_v228 as h

w = h.w
VERSION = "2.0.29"
PROFILE_VERSION = "1.8.8"

LABELS = {
    "sideBrush": "Side brush",
    "rollBrush": "Main / roller brush",
    "filter": "Filter",
    "unitCare": "Unit care",
}


def _extract_consumables(raw):
    """Extract a consumables array from a redacted log line."""
    for pattern in (
        r'\\"consumables\\"\s*:\s*(\[[^]]*\])',
        r'"consumables"\s*:\s*(\[[^]]*\])',
        r"'consumables'\s*:\s*(\[[^]]*\])",
    ):
        m = re.search(pattern, raw)
        if not m:
            continue
        text = m.group(1).replace('\\"', '"')
        try:
            value = json.loads(text)
        except Exception:
            try:
                value = ast.literal_eval(text)
            except Exception:
                continue
        if isinstance(value, list):
            return value
    return None


def capture_consumables():
    _, _, lines = w.s.get_logs("5m")
    source = None
    items = None
    # Use the newest complete consumables report in the window.
    for raw in reversed(lines):
        low = raw.lower()
        if "consumables" not in low:
            continue
        found = _extract_consumables(raw)
        if found:
            items = found
            source = w.s.redact(raw).strip()[:1800]
            break

    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        left = item.get("left")
        total = item.get("total")
        try:
            percent = round(float(left) / float(total) * 100, 1) if float(total) > 0 else None
        except (TypeError, ValueError, ZeroDivisionError):
            percent = None
        result.append({
            "type": kind,
            "name": LABELS.get(kind, kind or "Unknown"),
            "remaining": left,
            "total": total,
            "remaining_percent": percent,
        })

    order = {name: i for i, name in enumerate(LABELS)}
    result.sort(key=lambda x: order.get(x.get("type"), 99))
    return {
        "ok": bool(result),
        "version": VERSION,
        "profile": PROFILE_VERSION,
        "window": "5m",
        "consumables": result,
        "source_log_fragment": source,
        "notes": [
            "Read-only: no commands are sent to the robot.",
            "Percent remaining is calculated as remaining / total x 100.",
            "Profile 1.8.8 is unchanged.",
        ] if result else [
            "No consumables report was found in the last 5 minutes.",
            "Open the Ecovacs app to trigger a fresh robot status query, then capture again.",
            "Read-only: no commands are sent to the robot.",
        ],
    }


w.s.capture_consumables = capture_consumables
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.28", "v2.0.29")

# Add the focused capture beside the existing capability capture.
w.s.HTML = w.s.HTML.replace(
    "<button class=good onclick=otherCaps()>Capture other capabilities</button>",
    "<button class=good onclick=otherCaps()>Capture other capabilities</button><button class=good onclick=consumables()>Capture consumables</button>",
    1,
)
w.s.HTML = w.s.HTML.replace(
    "async function otherCaps()",
    "async function consumables(){out(await post('./api/consumables'))}async function otherCaps()",
    1,
)

_BaseHandler = w.s.Handler
class Handler229(_BaseHandler):
    def do_POST(self):
        p = self.path.split("?", 1)[0].rstrip("/")
        if p.endswith("/api/consumables"):
            return self.sendj(capture_consumables())
        return super().do_POST()

w.s.Handler = Handler229

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; profile remains {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
