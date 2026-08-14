#!/usr/bin/env python3
"""Best-effort DEEBOT client inspection.

An HA add-on runs in its own container, so it cannot directly read the Python
site-packages filesystem of the Home Assistant Core container. This module
therefore fingerprints everything that is legitimately visible and explicitly
reports that limitation rather than pretending the add-on inspected Core.
"""
import importlib.util, json, os, re, subprocess, sys
from pathlib import Path

TARGETS = ["deebot_client", "deebot-client", "ecovacs"]
PATTERNS = ["cqyi87", "Device class", "SUPPORTED_MODELS", "hardware", "cd45", "30000"]


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return {"returncode": p.returncode, "stdout": p.stdout[:100000], "stderr": p.stderr[:20000]}
    except Exception as e:
        return {"error": str(e)}


def package_info():
    out = {"python": sys.version, "packages_visible_to_addon": {}}
    try:
        import importlib.metadata as md
        for name in TARGETS:
            try:
                d = md.distribution(name)
                out["packages_visible_to_addon"][name] = {
                    "version": d.version,
                    "location": str(d.locate_file("")),
                    "files": [str(x) for x in (d.files or []) if "deebot" in str(x).lower() or "ecovacs" in str(x).lower()][:500],
                }
            except Exception as e:
                out["packages_visible_to_addon"][name] = {"installed": False, "error": str(e)}
    except Exception as e:
        out["metadata_error"] = str(e)
    return out


def local_source_search():
    roots = [Path("/usr/local/lib"), Path("/opt"), Path("/app")]
    hits = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*.py"):
                if len(hits) >= 2000:
                    break
                try:
                    text = p.read_text(errors="replace")
                    if any(re.search(re.escape(x), text, re.I) for x in PATTERNS):
                        hits.append({"path": str(p), "matches": {x: bool(re.search(re.escape(x), text, re.I)) for x in PATTERNS}})
                except Exception:
                    pass
        except Exception:
            pass
    return hits


def installed_client_fingerprint(core_logs=""):
    """Extract evidence about the *Core* client from logs without claiming filesystem access."""
    text = core_logs or ""
    evidence = []
    for line in text.splitlines():
        if re.search(r"deebot|ecovacs|cqyi87|device class|deebot-client|version", line, re.I):
            evidence.append(line[-2000:])
    versions = sorted(set(re.findall(r"deebot[-_ ]?client[^0-9]{0,20}([0-9]+(?:\.[0-9]+)+)", text, re.I)))
    return {
        "core_filesystem_direct_access": False,
        "reason": "Home Assistant add-ons run in a separate container; this add-on cannot read Core's /usr/local/lib/python*/site-packages without an explicit host/container mount or Core-side diagnostic endpoint.",
        "versions_seen_in_core_logs": versions,
        "core_log_evidence": evidence[-1000:],
        "next_exact_core_command": "python3 -c 'import deebot_client,inspect; print(deebot_client.__file__); print(getattr(deebot_client,\"__version__\",\"unknown\"))'",
        "next_package_listing_command": "python3 -m pip show deebot-client",
    }


def inspect(core_logs=""):
    return {
        "package_info_in_diagnostic_container": package_info(),
        "local_source_hits_in_diagnostic_container": local_source_search(),
        "core_runtime": installed_client_fingerprint(core_logs),
        "important": "Do not treat package_info_in_diagnostic_container as the Home Assistant Core package. The containers are separate.",
    }
