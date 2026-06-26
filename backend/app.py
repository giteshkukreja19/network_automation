"""Flask dashboard + JSON API. Every route calls exactly one automation module and reports the real result."""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template

import config
import controller_client as ctl
import router_netmiko as router
import switch_napalm as switch

logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))

ERRORS = {ctl.ControllerError: ("controller", 502), router.RouterError: ("router", 502),
          switch.SwitchError: ("switch", 502)}


def run(device: str, action: str, fn, log_to_controller: bool = True):
    """Execute fn, wrap in a uniform envelope, and write an audit entry to the controller."""
    t0, ts = time.time(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        data, ok, code, err = fn(), True, 200, None
    except tuple(ERRORS) as exc:
        data, ok, code, err = None, False, ERRORS[type(exc)][1], str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("unexpected error in %s/%s", device, action)
        data, ok, code, err = None, False, 500, f"unexpected {type(exc).__name__}: {exc}"
    log.info("%s %s ok=%s", device, action, ok)
    if log_to_controller and device != "controller":
        ctl.record_operation(device, action, ok, err or "")
    return jsonify({"ok": ok, "device": device, "action": action, "timestamp": ts,
                    "duration_ms": round((time.time() - t0) * 1000), "data": data, "error": err}), code


@app.get("/")
def index():
    return render_template("index.html", switch_info=switch.driver_info(),
                           router_host=config.ROUTER_HOST, switch_host=config.SWITCH_HOST)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ---- Branch A: REST controller -------------------------------------------------
@app.get("/api/controller/health")
def c_health():
    return run("controller", "health", ctl.health)


@app.get("/api/controller/status")
def c_status():
    return run("controller", "status", ctl.status)


@app.get("/api/controller/devices")
def c_devices():
    return run("controller", "devices", ctl.devices)


@app.get("/api/controller/topology")
def c_topology():
    return run("controller", "topology", ctl.topology)


@app.get("/api/controller/logs")
def c_logs():
    return run("controller", "logs", ctl.logs)


# ---- Branch B: Netmiko -> FRRouting -------------------------------------------
ROUTER_ROUTES = {
    "connect": router.connect, "routes": router.routes, "interfaces": router.interfaces,
    "version": router.version, "loopback/configure": router.configure_loopback,
    "loopback/verify": router.verify_loopback, "loopback/restore": router.restore_loopback,
}
for path, fn in ROUTER_ROUTES.items():
    method = "POST" if path.endswith(("configure", "restore")) else "GET"
    app.add_url_rule(f"/api/router/{path}", endpoint=f"router_{path.replace('/', '_')}", methods=[method],
                     view_func=(lambda p=path, f=fn: run("router", p.replace("/", "_"), f)))

# ---- Branch C: NAPALM -> switch ------------------------------------------------
SWITCH_ROUTES = {
    "connect": switch.connect, "facts": switch.facts, "interfaces": switch.interfaces,
    "counters": switch.counters, "description/configure": switch.configure_description,
    "description/verify": switch.verify_description, "description/restore": switch.restore_description,
}
for path, fn in SWITCH_ROUTES.items():
    method = "POST" if path.endswith(("configure", "restore")) else "GET"
    app.add_url_rule(f"/api/switch/{path}", endpoint=f"switch_{path.replace('/', '_')}", methods=[method],
                     view_func=(lambda p=path, f=fn: run("switch", p.replace("/", "_"), f)))


if __name__ == "__main__":
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False)
