"""Branch B: Flask backend -> Netmiko (linux driver) -> SSH -> FRRouting vtysh.

Only the commands in READ_COMMANDS / the loopback helpers can ever be executed.
"""
import json
import logging
import socket
from contextlib import contextmanager

from netmiko import ConnectHandler
from netmiko.exceptions import (NetmikoAuthenticationException, NetmikoBaseException,
                                NetmikoTimeoutException)

import config

log = logging.getLogger("router")


class RouterError(Exception):
    pass


VTYSH = "sudo -n vtysh"
READ_COMMANDS = {
    "routes_json": f"{VTYSH} -c 'show ip route json'",
    "routes_text": f"{VTYSH} -c 'show ip route'",
    "interfaces_ip": "ip -j addr show",
    "interfaces_frr": f"{VTYSH} -c 'show interface brief'",
    "version": f"{VTYSH} -c 'show version'",
    "running_config": f"{VTYSH} -c 'show running-config'",
    "hostname": "hostname",
}
LOOP_ADD = (f"{VTYSH} -c 'configure terminal' -c 'interface lo' "
            f"-c 'ip address {config.LOOPBACK_ADDRESS}' -c 'end'")
LOOP_DEL = (f"{VTYSH} -c 'configure terminal' -c 'interface lo' "
            f"-c 'no ip address {config.LOOPBACK_ADDRESS}' -c 'end'")


@contextmanager
def session():
    params = dict(device_type="linux", host=config.ROUTER_HOST, port=config.ROUTER_PORT,
                  username=config.LAB_USER, password=config.LAB_PASSWORD,
                  timeout=config.REQUEST_TIMEOUT, conn_timeout=config.REQUEST_TIMEOUT,
                  auth_timeout=config.REQUEST_TIMEOUT, banner_timeout=config.REQUEST_TIMEOUT)
    conn = None
    try:
        conn = ConnectHandler(**params)
        yield conn
    except NetmikoAuthenticationException as exc:
        raise RouterError(f"SSH authentication failed for {config.LAB_USER}@{config.ROUTER_HOST}") from exc
    except NetmikoTimeoutException as exc:
        raise RouterError(f"SSH timeout connecting to {config.ROUTER_HOST}:{config.ROUTER_PORT}") from exc
    except NetmikoBaseException as exc:
        raise RouterError(f"Netmiko error: {exc}") from exc
    except OSError as exc:
        raise RouterError(f"cannot reach router: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                log.debug("disconnect failed", exc_info=True)


def _run(conn, key_or_cmd: str) -> str:
    cmd = READ_COMMANDS.get(key_or_cmd, key_or_cmd)
    return conn.send_command(cmd, read_timeout=config.REQUEST_TIMEOUT).strip()


def _mgmt_ip() -> str:
    try:
        return socket.gethostbyname(config.ROUTER_HOST)
    except OSError:
        return "unresolved"


def connect() -> dict:
    with session() as conn:
        return {"connected": True, "hostname": _run(conn, "hostname"), "management_ip": _mgmt_ip(),
                "host": config.ROUTER_HOST, "port": config.ROUTER_PORT, "prompt": conn.find_prompt(),
                "ssh_status": "authenticated"}


def _flatten_routes(raw: dict) -> list:
    rows = []
    for prefix, entries in raw.items():
        for e in entries:
            hops = e.get("nexthops", [])
            rows.append({
                "prefix": prefix,
                "protocol": e.get("protocol"),
                "selected": e.get("selected", False),
                "distance": e.get("distance"),
                "metric": e.get("metric"),
                "nexthops": [h.get("ip") or ("blackhole" if h.get("blackhole") else "directly connected")
                             for h in hops],
                "interfaces": [h.get("interfaceName", "") for h in hops],
            })
    return sorted(rows, key=lambda r: r["prefix"])


def routes() -> dict:
    with session() as conn:
        out = _run(conn, "routes_json")
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as exc:
            raise RouterError(f"vtysh did not return JSON: {out[:200]}") from exc
        return {"command": "show ip route json", "count": len(parsed), "routes": _flatten_routes(parsed),
                "raw_text": _run(conn, "routes_text")}


def interfaces() -> dict:
    with session() as conn:
        raw = json.loads(_run(conn, "interfaces_ip"))
        rows = [{"name": i.get("ifname"), "state": i.get("operstate"), "mac": i.get("address"),
                 "mtu": i.get("mtu"),
                 "addresses": [f"{a['local']}/{a['prefixlen']}" for a in i.get("addr_info", [])]}
                for i in raw]
        return {"interfaces": rows, "frr_brief": _run(conn, "interfaces_frr")}


def version() -> dict:
    with session() as conn:
        return {"version": _run(conn, "version")}


def _loopback_state(conn) -> dict:
    cfg = _run(conn, "running_config")
    block, in_lo = [], False
    for line in cfg.splitlines():
        if line.startswith("interface lo"):
            in_lo = True
        elif in_lo and line.startswith("!"):
            break
        if in_lo:
            block.append(line)
    kernel = _run(conn, "ip -4 -br addr show dev lo")
    return {"frr_config": "\n".join(block) or "(no 'interface lo' block)", "kernel": kernel,
            "address_configured": config.LOOPBACK_ADDRESS in "\n".join(block) and
                                  config.LOOPBACK_ADDRESS.split("/")[0] in kernel}


def verify_loopback() -> dict:
    with session() as conn:
        return {"expected_address": config.LOOPBACK_ADDRESS, **_loopback_state(conn)}


def configure_loopback() -> dict:
    with session() as conn:
        before = _loopback_state(conn)
        _run(conn, LOOP_ADD)
        after = _loopback_state(conn)
    if not after["address_configured"]:
        raise RouterError("configuration was sent but read-back does not show the loopback address")
    return {"expected_address": config.LOOPBACK_ADDRESS, "before": before, "after": after, "applied": True}


def restore_loopback() -> dict:
    with session() as conn:
        before = _loopback_state(conn)
        _run(conn, LOOP_DEL)
        after = _loopback_state(conn)
    if after["address_configured"]:
        raise RouterError("restore was sent but loopback address is still present")
    return {"before": before, "after": after, "restored": True}
