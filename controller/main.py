"""FastAPI REST controller: health, live device inventory, topology and an operations log."""
import logging
import os
import socket
import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s controller %(message)s")
log = logging.getLogger("controller")

API_VERSION = "v1"
STARTED = time.time()
CHECK_TIMEOUT = float(os.getenv("CHECK_TIMEOUT", "2"))

INVENTORY = [
    {"name": "router", "role": "router", "platform": "FRRouting (Linux)", "protocol": "ssh/netmiko",
     "host": os.getenv("ROUTER_HOST", "router"), "port": int(os.getenv("ROUTER_CHECK_PORT", "22"))},
    {"name": "switch", "role": "switch", "platform": os.getenv("SWITCH_PLATFORM", "Linux bridge / cEOS"),
     "protocol": "napalm",
     "host": os.getenv("SWITCH_HOST", "switch"), "port": int(os.getenv("SWITCH_CHECK_PORT", "22"))},
]

OPS: deque = deque(maxlen=500)
app = FastAPI(title="Network Automation Controller", version=API_VERSION)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def probe(host: str, port: int) -> dict:
    """Real TCP connect test - never a static value."""
    t0 = time.time()
    try:
        ip = socket.gethostbyname(host)
        with socket.create_connection((ip, port), timeout=CHECK_TIMEOUT):
            pass
        return {"reachable": True, "ip": ip, "latency_ms": round((time.time() - t0) * 1000, 1), "error": None}
    except Exception as exc:  # noqa: BLE001 - we report any failure verbatim
        return {"reachable": False, "ip": None, "latency_ms": None, "error": f"{type(exc).__name__}: {exc}"}


class Operation(BaseModel):
    device: Literal["router", "switch", "controller", "dashboard"]
    action: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.\- ]+$")
    status: Literal["ok", "error"]
    detail: str = Field(default="", max_length=500)


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": now()}


@app.get("/api/status")
def status():
    return {"controller": "Network Automation Controller", "status": "running", "api_version": API_VERSION,
            "uptime_seconds": round(time.time() - STARTED), "operations_logged": len(OPS), "timestamp": now()}


@app.get("/api/devices")
def devices():
    out = []
    for d in INVENTORY:
        r = probe(d["host"], d["port"])
        out.append({**d, **r, "status": "up" if r["reachable"] else "down"})
    return {"devices": out, "timestamp": now()}


@app.get("/api/topology")
def topology():
    reach = {d["name"]: probe(d["host"], d["port"])["reachable"] for d in INVENTORY}
    return {
        "networks": [{"name": "management", "purpose": "automation access (DNS names)"},
                     {"name": "data", "purpose": "router <-> switch data plane"}],
        "nodes": [{"name": "controller", "type": "fastapi"}] +
                 [{"name": d["name"], "type": d["role"], "platform": d["platform"], "reachable": reach[d["name"]]}
                  for d in INVENTORY],
        "links": [{"a": "router", "b": "switch", "network": "data"}],
    }


@app.get("/api/logs")
def logs(limit: int = Query(50, ge=1, le=500)):
    return {"count": min(limit, len(OPS)), "logs": list(OPS)[-limit:][::-1]}


@app.post("/api/operations", status_code=201)
def record_operation(op: Operation):
    entry = {"id": len(OPS) + 1, "timestamp": now(), **op.model_dump()}
    OPS.append(entry)
    log.info("operation %s", entry)
    return entry
