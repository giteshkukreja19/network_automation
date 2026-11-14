"""Unit tests for the custom NAPALM driver using a fake `ip` backend (no network)."""
import json

import pytest
from napalm.base.exceptions import MergeConfigException

from linux_switch_driver import LinuxBridgeDriver


class FakeDriver(LinuxBridgeDriver):
    def __init__(self):
        super().__init__("x", "u", "p")
        self.alias = {"port1": "", "port2": "uplink"}
        self.cmds = []

    def _run(self, cmd):
        self.cmds.append(cmd)
        if cmd.startswith("/sbin/ip -j"):
            return json.dumps([{"ifname": n, "flags": ["UP", "LOWER_UP"], "operstate": "UP", "mtu": 1500,
                                "address": "aa:bb", "ifalias": a,
                                "stats64": {"rx": {"bytes": 10, "packets": 2, "errors": 0, "dropped": 0, "multicast": 1},
                                            "tx": {"bytes": 5, "packets": 1, "errors": 0, "dropped": 0}}}
                               for n, a in self.alias.items()])
        if cmd.startswith("sudo -n /sbin/ip link set dev"):
            parts = cmd.split()
            self.alias[parts[6]] = "" if parts[-1] == "''" else parts[-1].strip("'")
            return ""
        return {"hostname": "sw\n", "cat /proc/uptime": "12.5 1\n", "uname -r": "6.1\n"}[cmd]


def test_getters_follow_napalm_schema():
    d = FakeDriver()
    ifs = d.get_interfaces()
    assert set(ifs["port2"]) == {"is_up", "is_enabled", "description", "last_flapped", "mtu", "speed", "mac_address"}
    assert ifs["port2"]["description"] == "uplink"
    assert d.get_interfaces_counters()["port1"]["rx_octets"] == 10
    assert d.get_facts()["interface_list"] == ["port1", "port2"]


def test_candidate_workflow_compare_commit_rollback():
    d = FakeDriver()
    d.load_merge_candidate(config="interface port1\n description napalm-lab-test")
    assert "+ description napalm-lab-test" in d.compare_config()
    d.commit_config()
    assert d.alias["port1"] == "napalm-lab-test"
    d.rollback()
    assert d.alias["port1"] == ""


def test_discard_and_validation():
    d = FakeDriver()
    d.load_merge_candidate(config="interface port1\n description x")
    d.discard_config()
    assert d.compare_config() == ""
    for bad in ("interface port1\n description $(reboot)", "interface nope\n description x",
                "interface port1; reboot\n description x", "reload"):
        with pytest.raises(MergeConfigException):
            d.load_merge_candidate(config=bad)
