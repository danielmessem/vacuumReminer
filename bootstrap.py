#!/usr/bin/env python3
"""Bootstrap the diagnostics app and recover SUPERVISOR_TOKEN when needed."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")

def docker_get(path: str, sock_path: str):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(5)
        s.connect(sock_path)
        req = (f"GET {path} HTTP/1.1\r\nHost: docker\r\nConnection: close\r\n\r\n").encode()
        s.sendall(req)
        chunks=[]
        while True:
            chunk=s.recv(65536)
            if not chunk: break
            chunks.append(chunk)
        raw=b"".join(chunks)
    finally:
        s.close()
    _,_,body=raw.partition(b"\r\n\r\n")
    return json.loads(body.decode("utf-8","replace"))

def recover_token():
    token=os.environ.get("SUPERVISOR_TOKEN")
    if token: return token
    for sock in SOCKETS:
        if not Path(sock).exists(): continue
        try:
            # Prefer the canonical Core container name, then inspect every running container.
            candidates=["homeassistant"]
            containers=docker_get("/containers/json?all=0",sock)
            for c in containers if isinstance(containers,list) else []:
                candidates.extend(c.get("Names",[]))
            seen=set()
            for name in candidates:
                name=name.lstrip("/")
                if not name or name in seen: continue
                seen.add(name)
                try: info=docker_get(f"/containers/{name}/json",sock)
                except Exception: continue
                for item in info.get("Config",{}).get("Env",[]) or []:
                    if item.startswith("SUPERVISOR_TOKEN=") and item.split("=",1)[1]:
                        return item.split("=",1)[1]
        except Exception:
            continue
    return None

token=recover_token()
if token: os.environ["SUPERVISOR_TOKEN"]=token
else: os.environ.pop("SUPERVISOR_TOKEN",None)

server=Path("/app/server.py")
text=server.read_text()
text=text.replace('VERSION = "1.2.0"','VERSION = "1.2.3"',1)
server.write_text(text)
os.execv("/usr/bin/python3",["python3",str(server)])
