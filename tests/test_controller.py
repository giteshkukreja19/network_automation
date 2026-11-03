"""Unit tests for the FastAPI controller (in-process; device probes use real sockets against closed ports)."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_status_shape():
    j = client.get("/api/status").json()
    assert j["controller"] == "Network Automation Controller" and j["status"] == "running" and j["api_version"] == "v1"


def test_devices_report_down_when_unreachable(monkeypatch):
    monkeypatch.setattr(main, "INVENTORY", [{"name": "x", "role": "router", "platform": "t", "protocol": "ssh",
                                             "host": "127.0.0.1", "port": 1}])
    d = client.get("/api/devices").json()["devices"][0]
    assert d["status"] == "down" and d["reachable"] is False and d["error"]


def test_devices_report_up_for_listening_port(monkeypatch):
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    monkeypatch.setattr(main, "INVENTORY", [{"name": "x", "role": "router", "platform": "t", "protocol": "ssh",
                                             "host": "127.0.0.1", "port": s.getsockname()[1]}])
    try:
        assert client.get("/api/devices").json()["devices"][0]["status"] == "up"
    finally:
        s.close()


def test_operations_validation_and_log():
    assert client.post("/api/operations", json={"device": "bogus", "action": "x", "status": "ok"}).status_code == 422
    assert client.post("/api/operations", json={"device": "router", "action": "rm -rf /;", "status": "ok"}).status_code == 422
    ok = client.post("/api/operations", json={"device": "router", "action": "show_routes", "status": "ok"})
    assert ok.status_code == 201
    assert client.get("/api/logs?limit=1").json()["logs"][0]["action"] == "show_routes"
    assert client.get("/api/logs?limit=0").status_code == 422
