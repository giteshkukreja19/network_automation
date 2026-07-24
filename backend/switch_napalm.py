"""Branch C: Flask backend -> NAPALM -> virtual switch.

SWITCH_MODE=eos   -> NATIVE napalm.get_network_driver("eos") against Arista cEOS (eAPI over HTTPS)
SWITCH_MODE=linux -> CUSTOM LinuxBridgeDriver (linux_switch_driver.py) against the Linux-bridge container
Both go through the same NAPALM calls: open/get_facts/get_interfaces/load_merge_candidate/compare/commit.
"""
import logging
import socket
from contextlib import contextmanager

from napalm import get_network_driver

import config
from linux_switch_driver import LinuxBridgeDriver

log = logging.getLogger("switch")
_original_description = {}   # remembers the description before our test change (per interface)


class SwitchError(Exception):
    pass


def driver_info() -> dict:
    if config.SWITCH_MODE == "eos":
        return {"mode": "eos", "driver": "napalm.eos (native, upstream NAPALM)"}
    return {"mode": "linux", "driver": "LinuxBridgeDriver (CUSTOM NAPALM driver, not upstream)"}


def _make_device():
    if config.SWITCH_MODE == "eos":
        cls = get_network_driver("eos")
        return cls(hostname=config.SWITCH_HOST, username=config.LAB_USER, password=config.LAB_PASSWORD,
                   timeout=int(config.REQUEST_TIMEOUT),
                   optional_args={"transport": "https", "port": config.SWITCH_PORT})
    return LinuxBridgeDriver(hostname=config.SWITCH_HOST, username=config.LAB_USER, password=config.LAB_PASSWORD,
                             timeout=int(config.REQUEST_TIMEOUT), optional_args={"port": config.SWITCH_PORT})


@contextmanager
def session():
    dev = _make_device()
    try:
        dev.open()
    except Exception as exc:  # noqa: BLE001 - NAPALM raises many types
        raise SwitchError(f"cannot open NAPALM session to {config.SWITCH_HOST}:{config.SWITCH_PORT}: {exc}") from exc
    try:
        yield dev
    except SwitchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SwitchError(f"NAPALM operation failed: {type(exc).__name__}: {exc}") from exc
    finally:
        try:
            dev.close()
        except Exception:  # noqa: BLE001
            log.debug("close failed", exc_info=True)


def _mgmt_ip() -> str:
    try:
        return socket.gethostbyname(config.SWITCH_HOST)
    except OSError:
        return "unresolved"


def connect() -> dict:
    with session() as dev:
        facts = dev.get_facts()
        return {"connected": True, "hostname": facts["hostname"], "management_ip": _mgmt_ip(),
                "alive": dev.is_alive(), **driver_info()}


def facts() -> dict:
    with session() as dev:
        return {**driver_info(), "management_ip": _mgmt_ip(), "facts": dev.get_facts()}


def interfaces() -> dict:
    with session() as dev:
        return {**driver_info(), "interfaces": dev.get_interfaces()}


def counters() -> dict:
    with session() as dev:
        return {**driver_info(), "counters": dev.get_interfaces_counters()}


def _apply(description: str) -> dict:
    iface = config.SWITCH_TEST_INTERFACE
    with session() as dev:
        ifs = dev.get_interfaces()
        if iface not in ifs:
            raise SwitchError(f"test interface {iface!r} not found on switch; available: {sorted(ifs)[:10]}")
        before = ifs[iface]["description"]
        cfg = f"interface {iface}\n description {description}" if description else f"interface {iface}\n no description"
        dev.load_merge_candidate(config=cfg)
        diff = dev.compare_config()
        if not diff.strip():
            dev.discard_config()
            return {"interface": iface, "before": before, "after": before, "diff": "", "committed": False,
                    "note": "already in desired state"}
        dev.commit_config()
        after = dev.get_interfaces()[iface]["description"]
        if after != description:
            raise SwitchError(f"read-back mismatch: wanted {description!r}, device reports {after!r}")
        return {"interface": iface, "before": before, "after": after, "diff": diff, "committed": True}


def configure_description() -> dict:
    iface = config.SWITCH_TEST_INTERFACE
    with session() as dev:
        _original_description.setdefault(iface, dev.get_interfaces().get(iface, {}).get("description", ""))
    return _apply(config.TEST_DESCRIPTION)


def verify_description() -> dict:
    iface = config.SWITCH_TEST_INTERFACE
    with session() as dev:
        current = dev.get_interfaces().get(iface, {}).get("description")
    return {"interface": iface, "current_description": current, "expected": config.TEST_DESCRIPTION,
            "matches": current == config.TEST_DESCRIPTION}


def restore_description() -> dict:
    iface = config.SWITCH_TEST_INTERFACE
    return _apply(_original_description.pop(iface, ""))
