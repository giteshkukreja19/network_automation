"""All settings come from environment variables (see .env.example). Nothing secret is sent to the browser."""
import os


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


LAB_USER = _env("LAB_USER", "admin")
LAB_PASSWORD = _env("LAB_PASSWORD", "labpassword")
REQUEST_TIMEOUT = float(_env("REQUEST_TIMEOUT", "10"))
LOG_LEVEL = _env("LOG_LEVEL", "INFO")

CONTROLLER_URL = _env("CONTROLLER_URL", "http://controller:8000").rstrip("/")

ROUTER_HOST = _env("ROUTER_HOST", "router")
ROUTER_PORT = int(_env("ROUTER_PORT", "22"))

SWITCH_MODE = _env("SWITCH_MODE", "linux").lower()          # "linux" (custom driver) | "eos" (native NAPALM)
SWITCH_HOST = _env("SWITCH_HOST", "switch")
SWITCH_PORT = int(_env("SWITCH_PORT", "22" if SWITCH_MODE == "linux" else "443"))
SWITCH_TEST_INTERFACE = _env("SWITCH_TEST_INTERFACE", "port1" if SWITCH_MODE == "linux" else "Ethernet1")

# Fixed, allow-listed lab values: the browser can never choose what gets configured.
LOOPBACK_ADDRESS = "10.255.255.1/32"
TEST_DESCRIPTION = "napalm-lab-test"

FLASK_HOST = _env("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(_env("FLASK_PORT", "5000"))
