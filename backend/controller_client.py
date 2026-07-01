"""Branch A: Flask backend -> Python Requests -> FastAPI controller."""
import logging
import requests

import config

log = logging.getLogger("controller_client")


class ControllerError(Exception):
    pass


def _request(method: str, path: str, **kwargs) -> dict:
    url = f"{config.CONTROLLER_URL}{path}"
    try:
        resp = requests.request(method, url, timeout=config.REQUEST_TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout as exc:
        raise ControllerError(f"controller timed out after {config.REQUEST_TIMEOUT}s: {url}") from exc
    except requests.ConnectionError as exc:
        raise ControllerError(f"cannot connect to controller at {url}") from exc
    except requests.HTTPError as exc:
        raise ControllerError(f"controller returned HTTP {exc.response.status_code} for {url}") from exc
    except ValueError as exc:
        raise ControllerError(f"controller returned invalid JSON from {url}") from exc


def health() -> dict:
    return _request("GET", "/health")


def status() -> dict:
    return _request("GET", "/api/status")


def devices() -> dict:
    return _request("GET", "/api/devices")


def topology() -> dict:
    return _request("GET", "/api/topology")


def logs(limit: int = 20) -> dict:
    return _request("GET", "/api/logs", params={"limit": limit})


def record_operation(device: str, action: str, ok: bool, detail: str = "") -> None:
    """Best effort audit log; never lets a logging failure break an automation action."""
    try:
        _request("POST", "/api/operations",
                 json={"device": device, "action": action, "status": "ok" if ok else "error",
                       "detail": detail[:500]})
    except ControllerError as exc:
        log.warning("could not log operation: %s", exc)
