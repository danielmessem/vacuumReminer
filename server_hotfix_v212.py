#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.12 / profile 1.8.2.

Builds on 2.0.11. Adds a read-only getCleanInfo_V2 probe to discover the
Y1 PRO cleaning-history response shape. The probe is attached only to the
report-stats refresh path and does not alter cleaning, map, state or battery.
"""
from pathlib import Path

import server_hotfix_v211 as h

w = h.w
VERSION = "2.0.12"
PROFILE_VERSION = "1.8.2"


def build_profile_182():
    src = h.build_profile_181()
    dst = Path("/app/cqyi87_profile_182.py")
    text = src.read_text()

    text = text.replace('Y1PRO_PATCH_VERSION = "1.8.1"', 'Y1PRO_PATCH_VERSION = "1.8.2"', 1)

    # Insert the history probe immediately before get_device_info so the class
    # exists when the capabilities object is constructed. It uses the same
    # Android request envelope as the other Y1Pro* JSON commands.
    marker = '\n\ndef get_device_info() -> StaticDeviceInfo:\n'
    probe = r'''

class Y1ProCleanInfoV2Command(JsonCommandMqttP2P):
    """Read-only probe for the firmware-advertised getCleanInfo_V2 command."""
    NAME = "getCleanInfo_V2"

    def __init__(self) -> None:
        super().__init__()

    @classmethod
    def create_from_mqtt(cls, payload: str | bytes | bytearray):
        return cls()

    @staticmethod
    def _safe(value: Any, key: str = "") -> Any:
        sensitive = {"resource", "did", "deviceid", "serial", "token", "accesstoken", "refreshtoken", "authcode"}
        if key.lower() in sensitive:
            return "<redacted>"
        if isinstance(value, dict):
            return {str(k): Y1ProCleanInfoV2Command._safe(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [Y1ProCleanInfoV2Command._safe(v) for v in value]
        return value

    def _capture(self, response: Any) -> HandlingResult:
        try:
            safe = self._safe(response)
            _LOGGER.warning("Y1PRO_CLEANINFO_V2_RESPONSE %s", orjson.dumps(safe).decode())
        except Exception:
            _LOGGER.warning("Y1PRO_CLEANINFO_V2_RESPONSE <could not serialize>", exc_info=True)
        body = response.get("body", {}) if isinstance(response, dict) else {}
        if isinstance(body, dict) and body.get("code", 0) not in (0, None):
            return HandlingResult(HandlingState.FAILED)
        return HandlingResult.success()

    def _handle_response(self, event_bus, response: dict[str, Any]) -> HandlingResult:
        data: Any = response.get("resp", response) if isinstance(response, dict) else response
        return self._capture(data)

    def _handle_mqtt_p2p(self, event_bus, response: dict[str, Any]) -> None:
        self._capture(response)


COMMANDS_WITH_MQTT_P2P_HANDLING.setdefault(DataType.JSON, {})["getCleanInfo_V2"] = Y1ProCleanInfoV2Command
'''
    if marker not in text:
        raise RuntimeError("Could not locate get_device_info insertion point")
    text = text.replace(marker, probe + marker, 1)

    # Probe through report stats only. Existing live-clean stats remain on the
    # proven 10001 field query, and lifetime stats remain disabled.
    old_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime", "cleanCount", "cleanLogReport"])]), report=CapabilityEvent(ReportStatsEvent, []), total=CapabilityEvent(TotalStatsEvent, [])),\n'
    new_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime", "cleanCount", "cleanLogReport"])]), report=CapabilityEvent(ReportStatsEvent, [Y1ProCleanInfoV2Command()]), total=CapabilityEvent(TotalStatsEvent, [])),\n'
    if old_stats not in text:
        raise RuntimeError("Could not locate 1.8.1 stats capability")
    text = text.replace(old_stats, new_stats, 1)

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_182()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.11", "v2.0.12")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
