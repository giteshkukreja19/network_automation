"""Unit tests for router_netmiko (Netmiko is mocked here; live behaviour is covered in test_integration.py)."""
import json
from unittest import mock

import pytest

import router_netmiko as r

SAMPLE = {"10.10.0.0/24": [{"protocol": "connected", "selected": True, "distance": 0, "metric": 0,
                            "nexthops": [{"interfaceName": "eth1", "directlyConnected": True}]}],
          "198.51.100.0/24": [{"protocol": "static", "selected": True, "distance": 1, "metric": 0,
                               "nexthops": [{"blackhole": True}]}]}


def test_flatten_routes():
    rows = r._flatten_routes(SAMPLE)
    assert [x["prefix"] for x in rows] == ["10.10.0.0/24", "198.51.100.0/24"]
    assert rows[0]["nexthops"] == ["directly connected"] and rows[1]["nexthops"] == ["blackhole"]


def test_routes_uses_netmiko_and_closes():
    conn = mock.MagicMock()
    conn.send_command.side_effect = [json.dumps(SAMPLE), "text table"]
    with mock.patch.object(r, "ConnectHandler", return_value=conn) as ch:
        out = r.routes()
    assert ch.call_args.kwargs["device_type"] == "linux"
    assert all(call.kwargs["read_timeout"] == r.config.REQUEST_TIMEOUT
               for call in conn.send_command.call_args_list)
    assert out["count"] == 2
    conn.disconnect.assert_called_once()


def test_command_read_timeout_is_reported():
    from netmiko.exceptions import NetmikoTimeoutException

    conn = mock.MagicMock()
    conn.send_command.side_effect = NetmikoTimeoutException("timed out")
    with mock.patch.object(r, "ConnectHandler", return_value=conn):
        with pytest.raises(r.RouterError, match="SSH timeout"):
            r.version()
    conn.disconnect.assert_called_once()


def test_auth_failure_is_reported():
    from netmiko.exceptions import NetmikoAuthenticationException
    with mock.patch.object(r, "ConnectHandler", side_effect=NetmikoAuthenticationException("bad")):
        with pytest.raises(r.RouterError, match="authentication failed"):
            r.connect()


def test_no_free_form_command_surface():
    assert not hasattr(r, "send_custom_command")
    assert all(c.startswith(("sudo -n vtysh", "ip -j", "hostname")) for c in r.READ_COMMANDS.values())
