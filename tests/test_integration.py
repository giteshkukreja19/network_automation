"""LIVE integration tests - no mocks. They FAIL (never skip) if the stack is not running.
Run after `./scripts/start.sh`:   pytest -m integration -v
"""
import os

import pytest
import requests

DASH = os.getenv("DASHBOARD_URL", "http://127.0.0.1:5000")
CTRL = os.getenv("CONTROLLER_PUBLIC_URL", "http://127.0.0.1:8000")
T = 30
pytestmark = pytest.mark.integration


def get(path, **kw):
    return requests.get(f"{DASH}{path}", timeout=T, **kw)


def post(path):
    return requests.post(f"{DASH}{path}", timeout=T)


def ok(resp):
    j = resp.json()
    assert resp.status_code == 200 and j["ok"], j
    return j["data"]


def test_dashboard_http_200():
    r = get("/")
    assert r.status_code == 200 and "Network Automation and Orchestration Platform" in r.text


def test_controller_direct_http_200():
    assert requests.get(f"{CTRL}/health", timeout=T).status_code == 200


def test_controller_through_dashboard():
    assert ok(get("/api/controller/health"))["status"] == "healthy"
    names = {d["name"]: d for d in ok(get("/api/controller/devices"))["devices"]}
    assert names["router"]["status"] == "up" and names["switch"]["status"] == "up"


def test_router_netmiko_ssh_and_real_routes():
    assert ok(get("/api/router/connect"))["ssh_status"] == "authenticated"
    routes = ok(get("/api/router/routes"))
    prefixes = {r["prefix"] for r in routes["routes"]}
    assert "10.10.0.0/24" in prefixes and "198.51.100.0/24" in prefixes      # connected + static from frr.conf
    assert "Codes:" in routes["raw_text"] or "K>*" in routes["raw_text"]       # genuine vtysh output


def test_router_config_and_restore():
    after = ok(post("/api/router/loopback/configure"))["after"]
    assert after["address_configured"]
    assert ok(get("/api/router/loopback/verify"))["address_configured"]
    assert not ok(post("/api/router/loopback/restore"))["after"]["address_configured"]


def test_switch_napalm_session_facts_interfaces_counters():
    assert ok(get("/api/switch/connect"))["connected"]
    facts = ok(get("/api/switch/facts"))["facts"]
    assert facts["hostname"] and facts["interface_list"]
    ifs = ok(get("/api/switch/interfaces"))["interfaces"]
    assert ifs and all("is_up" in v and "description" in v for v in ifs.values())
    assert ok(get("/api/switch/counters"))["counters"]


def test_switch_config_verify_restore():
    d = ok(post("/api/switch/description/configure"))
    assert d["after"] == "napalm-lab-test"
    assert ok(get("/api/switch/description/verify"))["matches"]
    r = ok(post("/api/switch/description/restore"))
    assert r["after"] == d["before"]
    assert not ok(get("/api/switch/description/verify"))["matches"]


def test_operations_are_audited_in_controller():
    logs = ok(get("/api/controller/logs"))["logs"]
    assert any(l["device"] == "router" for l in logs) and any(l["device"] == "switch" for l in logs)


def test_errors_are_reported_not_hidden():
    # unknown endpoint must be a real 404, and the envelope must carry errors (not fake success) elsewhere
    assert get("/api/router/does-not-exist").status_code == 404
    assert post("/api/router/routes").status_code == 405
