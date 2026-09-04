#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.18 / profile 1.8.6.

Adds a read-only capability discovery report. It inspects the installed cqyi87
profile, Home Assistant Ecovacs entities, recent Y1 telemetry field names, and
known command/event registrations so we can identify useful sensors/features
without sending speculative robot commands.
"""
import json
import re
from collections import Counter

import server_hotfix_v217 as h

w = h.w
VERSION = "2.0.18"


def discover_capabilities():
    """Return a sanitized, read-only inventory of what cqyi87 may expose."""
    result = {
        "ok": True,
        "version": VERSION,
        "profile_expected": h.h.PROFILE_VERSION,
        "profile": w.s.patch_status(),
        "ha_entities": [],
        "profile_capabilities": {},
        "registered_events": [],
        "registered_commands": [],
        "observed_fields": [],
        "observed_message_types": [],
        "cleaning_fields": {},
        "notes": [
            "Discovery is read-only: it does not send unknown commands to the robot.",
            "Observed fields are evidence from recent robot traffic, not a promise that Home Assistant currently exposes each one as an entity.",
            "Local total-cleaning stats start from the patch installation period because cqyi87 has not returned usable historical totals through getTotalStats/getCleanInfo_V2.",
        ],
    }

    # Home Assistant entities that are plausibly owned by Ecovacs / the Y1.
    states = w.s.ha_request("/api/states")
    if states.get("ok"):
        for item in states.get("data") or []:
            eid = str(item.get("entity_id", ""))
            attrs = item.get("attributes") or {}
            name = str(attrs.get("friendly_name", ""))
            hay = (eid + " " + name).lower()
            if any(x in hay for x in ("beepbop", "deebot", "ecovacs", "y1 pro")):
                safe = {}
                for key in (
                    "friendly_name", "device_class", "unit_of_measurement",
                    "state_class", "battery_level", "fan_speed",
                    "supported_features", "icon"
                ):
                    if key in attrs:
                        safe[key] = attrs.get(key)
                result["ha_entities"].append({
                    "entity_id": eid,
                    "state": item.get("state"),
                    "attributes": safe,
                })

    # Introspect the installed profile inside HA Core. This imports only local
    # Python metadata and does not contact the robot/cloud.
    code = r'''
import json
import deebot_client.hardware.cqyi87 as m
info=m.get_device_info(); c=info.capabilities
out={"profile_version":getattr(m,"Y1PRO_PATCH_VERSION",None),"capabilities":{},"events":[],"commands":[]}
for name in dir(c):
    if name.startswith("_"): continue
    try: value=getattr(c,name)
    except Exception: continue
    if value is None or callable(value): continue
    out["capabilities"][name]=type(value).__name__
try:
    from deebot_client.commands import COMMANDS_WITH_MQTT_P2P_HANDLING
    for dtype, commands in COMMANDS_WITH_MQTT_P2P_HANDLING.items():
        for name in commands.keys(): out["commands"].append(str(name))
except Exception: pass
try:
    from deebot_client import events
    out["events"]=[x for x in dir(events) if x.endswith("Event")]
except Exception: pass
print(json.dumps(out))
'''
    meta = w.s.core_exec(["python", "-c", code])
    if meta.get("ok"):
        try:
            parsed = json.loads(meta.get("stdout", "{}").strip().splitlines()[-1])
            result["profile_capabilities"] = parsed.get("capabilities", {})
            result["registered_events"] = sorted(set(parsed.get("events", [])))
            # Do not dump every library command; retain useful Y1/stat/status candidates.
            useful = re.compile(r"clean|stat|battery|charge|speed|life|map|pos|network|info|water|mop|dust|error|work|voice", re.I)
            result["registered_commands"] = sorted({x for x in parsed.get("commands", []) if useful.search(x)})
            result["installed_profile_version"] = parsed.get("profile_version")
        except Exception as exc:
            result["profile_introspection_error"] = w.s.redact(exc)
    else:
        result["profile_introspection_error"] = meta

    # Mine recent already-received telemetry. Extract JSON object keys only;
    # values/identifiers/resources are deliberately not returned.
    _, _, lines = w.s.get_logs("60m")
    fields = Counter()
    msg_types = Counter()
    interesting = re.compile(r"cqyi87|deebot_client|ecovacs", re.I)
    key_re = re.compile(r'[\"\']([A-Za-z][A-Za-z0-9_]{1,48})[\"\']\s*:')
    type_re = re.compile(r"(?:iot/(?:atr|p2p)/|command[= ])([A-Za-z0-9_\-]+)", re.I)
    for raw in lines:
        if not interesting.search(raw):
            continue
        line = w.s.redact(raw)
        for key in key_re.findall(line):
            if key not in {"header", "body", "data", "payload", "params", "json"}:
                fields[key] += 1
        for mt in type_re.findall(line):
            msg_types[mt] += 1
    result["observed_fields"] = [{"field": k, "hits": n} for k, n in fields.most_common(120)]
    result["observed_message_types"] = [{"type": k, "hits": n} for k, n in msg_types.most_common(60)]

    clean_names = ("cleanArea", "cleanTime", "cleanCount", "cleanLogReport", "battery", "chargeStatus", "pauseSwitch", "status")
    result["cleaning_fields"] = {name: fields.get(name, 0) for name in clean_names}
    result["candidate_groups"] = {
        "cleaning_stats": [x for x in ("cleanArea", "cleanTime", "cleanCount", "cleanLogReport") if fields.get(x)],
        "state_power": [x for x in ("battery", "chargeStatus", "pauseSwitch", "status") if fields.get(x)],
        "maintenance": [x for x in fields if re.search(r"brush|filter|heap|dust|mop|care|solution|life", x, re.I)][:30],
        "other_sensor_candidates": [x for x in fields if re.search(r"error|wifi|signal|water|volume|speed|mode|dnd|continuous|carpet", x, re.I)][:40],
    }
    return result


_base_diagnose = w.s.diagnose


def diagnose_with_discovery():
    result = _base_diagnose()
    result["capability_discovery"] = discover_capabilities()
    return result


w.s.discover_capabilities = discover_capabilities
w.s.diagnose = diagnose_with_discovery
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.17", "v2.0.18")

# Add a dedicated button without rewriting the older UI/server implementation.
w.s.HTML = w.s.HTML.replace(
    "<button onclick=captureTelemetry()>Capture telemetry</button>",
    "<button onclick=captureTelemetry()>Capture telemetry</button><button class=good onclick=discoverCaps()>Discover capabilities</button>",
    1,
)
w.s.HTML = w.s.HTML.replace(
    "async function captureTelemetry()",
    "async function discoverCaps(){out(await post('./api/discover'))}async function captureTelemetry()",
    1,
)

_BaseHandler = w.s.Handler


class Handler218(_BaseHandler):
    def do_POST(self):
        p = self.path.split("?", 1)[0].rstrip("/")
        if p.endswith("/api/discover"):
            return self.sendj(discover_capabilities())
        return super().do_POST()


w.s.Handler = Handler218

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {h.h.PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
