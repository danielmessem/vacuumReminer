#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.16 / profile 1.8.6.

Installer reliability hotfix. Refuses to install an unexpected generated profile,
verifies the copied cqyi87.py byte-for-byte inside the running HA Core container,
and surfaces expected/installed profile versions in diagnostics.
No map/control/stat semantics are changed from profile 1.8.5.
"""
from pathlib import Path
import hashlib
import re

import server_hotfix_v215 as h

w = h.w
VERSION = "2.0.16"
PROFILE_VERSION = "1.8.6"
_PROFILE_BUILD_ERROR = None


def build_profile_186():
    src = h.build_profile_185()
    dst = Path("/app/cqyi87_profile_186.py")
    text = src.read_text()
    old = 'Y1PRO_PATCH_VERSION = "1.8.5"'
    new = 'Y1PRO_PATCH_VERSION = "1.8.6"'
    if old not in text:
        raise RuntimeError("Could not locate 1.8.5 profile marker")
    text = text.replace(old, new, 1)
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_186()
except Exception as exc:
    _PROFILE_BUILD_ERROR = str(exc)
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)


def _profile_version_from_text(text):
    m = re.search(r'Y1PRO_PATCH_VERSION\s*=\s*["\']([^"\']+)["\']', text or "")
    return m.group(1) if m else None


def _source_profile_status():
    path = Path(w.s.PROFILE_PATH)
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "path": str(path),
            "version": _profile_version_from_text(text),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": w.s.redact(exc)}


def patch_status_strict():
    p = w.s.client_paths()
    source = _source_profile_status()
    if not p.get("ok"):
        return {**p, "expected_version": PROFILE_VERSION, "source_profile": source}
    target = p.get("target")
    r = w.s.core_exec([
        "python", "-c",
        (
            "from pathlib import Path;import hashlib,re;"
            f"p=Path({target!r});b=p.read_bytes() if p.exists() else b'';"
            "t=b.decode('utf-8','replace');"
            "m=re.search(r'Y1PRO_PATCH_VERSION\\s*=\\s*[\\\"\\\']([^\\\"\\\']+)[\\\"\\\']',t);"
            "print('version='+(m.group(1) if m else 'MISSING'));"
            "print('sha256='+hashlib.sha256(b).hexdigest())"
        ),
    ])
    installed_version = None
    installed_sha = None
    for line in r.get("stdout", "").splitlines():
        if line.startswith("version="):
            installed_version = line.split("=", 1)[1]
        elif line.startswith("sha256="):
            installed_sha = line.split("=", 1)[1]
    exact = bool(
        r.get("ok")
        and source.get("ok")
        and source.get("version") == PROFILE_VERSION
        and installed_version == PROFILE_VERSION
        and installed_sha == source.get("sha256")
    )
    return {
        "ok": bool(r.get("ok")),
        "target": target,
        "installed": installed_version not in (None, "MISSING"),
        "expected_version": PROFILE_VERSION,
        "installed_version": installed_version,
        "exact_match": exact,
        "source_profile": source,
        "installed_sha256": installed_sha,
        "build_error": _PROFILE_BUILD_ERROR,
        "detail": r,
    }


def install_patch_strict():
    source = _source_profile_status()
    if _PROFILE_BUILD_ERROR:
        return {
            "ok": False,
            "message": "Profile generation failed; nothing was installed.",
            "expected_version": PROFILE_VERSION,
            "build_error": _PROFILE_BUILD_ERROR,
            "source_profile": source,
        }
    if not source.get("ok") or source.get("version") != PROFILE_VERSION:
        return {
            "ok": False,
            "message": "Refusing to install: generated profile version does not match this add-on.",
            "expected_version": PROFILE_VERSION,
            "source_profile": source,
        }

    p = w.s.client_paths()
    if not p.get("ok"):
        return {"ok": False, "message": "Could not locate deebot-client", "detail": p}
    cid, _ = w.s.core()
    target = p["target"]
    if not cid:
        return {"ok": False, "message": "Home Assistant Core container not found"}

    w.s.CLIENT_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    backup = w.s.CLIENT_BACKUP_ROOT / f"cqyi87-{w.s.datetime.now():%Y%m%d-%H%M%S-%f}.py"
    if w.s.core_exec(["sh", "-c", f"test -f '{target}'"]).get("ok"):
        w.s.docker(["cp", f"{cid}:{target}", str(backup)])

    rc, _, err = w.s.docker(["cp", str(w.s.PROFILE_PATH), f"{cid}:{target}"])
    if rc:
        return {"ok": False, "message": "Copy failed", "error": w.s.redact(err)}

    # Validate syntax first, then validate raw file version/hash. Do not rely on
    # Python import state or .pyc cache to decide whether the copy succeeded.
    compile_result = w.s.core_exec(["python", "-m", "py_compile", target])
    status = patch_status_strict()
    ok = bool(compile_result.get("ok") and status.get("exact_match"))
    return {
        "ok": ok,
        "message": (
            f"Y1 PRO profile {PROFILE_VERSION} installed and verified byte-for-byte. Restart Core next."
            if ok else
            "Profile copy did not verify exactly; Home Assistant was left running and no success is being reported."
        ),
        "target": target,
        "expected_version": PROFILE_VERSION,
        "verification": status,
        "compile": compile_result,
        "backup": str(backup),
    }


w.s.patch_status = patch_status_strict
w.s.install_patch = install_patch_strict

_base_diagnose = w.s.diagnose


def diagnose_profile_verified():
    result = _base_diagnose()
    status = patch_status_strict()
    result["y1pro_patch"] = status
    result["y1pro_profile_expected"] = PROFILE_VERSION
    result["y1pro_profile_match"] = bool(status.get("exact_match"))
    if not status.get("exact_match"):
        result.setdefault("recommendations", []).insert(
            0,
            f"Installed cqyi87 profile does not match {PROFILE_VERSION}. Use Install cqyi87 profile, then restart Home Assistant Core."
        )
    return result


w.s.diagnose = diagnose_profile_verified
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.15", "v2.0.16")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}; expected profile {PROFILE_VERSION}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
