# Network Automation and Orchestration Platform
**REST API | Netmiko | NAPALM | Virtual Network Infrastructure** - runs locally on Apple-Silicon macOS with Docker Desktop.

> **Honesty note.** The code was written and checked in a sandbox **without Docker**. What was actually executed there:
> 12 unit tests (pass), and a live smoke test of Flask + FastAPI with the router/switch deliberately down (all device
> calls returned accurate errors and the audit log recorded them). **The containers, FRRouting, SSH logins, the Linux-bridge
> switch and the 9 integration tests have NOT been run.** Run `./scripts/verify.sh` yourself; section 9 lists the first
> things to check if something differs. cEOS (Implementation A) is untested and needs an image you must obtain.

## 1. Architecture

```
 Browser ── http://localhost:5000 ──► dashboard container (Flask + Python backend)
                                         │  all three branches stay separate modules
        ┌────────────────────────────────┼─────────────────────────────────┐
        ▼ Requests/HTTP                  ▼ Netmiko (linux driver) / SSH    ▼ NAPALM
  controller:8000                    router:22                         switch:22 (linux) | :443 (eos)
  FastAPI                            Alpine + FRRouting                Linux bridge + custom NAPALM driver
  (health, devices, topology,        sudo -n vtysh -c '...'            (Impl. B)  or  Arista cEOS + native
   logs, operations)                                                    NAPALM EOS driver (Impl. A)
        └───────────── management network "mgmt" (Docker DNS names) ─────────────┘
                                   router ◄── data network 10.10.0.0/24 ──► switch
```

**How the Flask app reaches the devices.** Docker Desktop runs containers inside a Linux VM, so the Mac cannot route to
container IPs. Therefore Flask runs *inside* the `mgmt` network and uses Docker DNS names (`controller`, `router`, `switch`).
No IP is hardcoded; the dashboard shows the IP it resolved at runtime. Only the dashboard is needed from the Mac
(`127.0.0.1:5000`); `8000`, `2222`, `2223` are optional localhost-only ports for manual checks.

## 2. Image / ARM64 decisions

| Component | Choice | ARM64 status |
|---|---|---|
| Router | `alpine:3.20` + `apk add frr` | Alpine ships aarch64 packages, so native ARM64. (I avoided `frrouting/frr` because I could not verify its arm64 manifest.) Alpine's FRR binary paths are found by `entrypoint.sh`; unverified on your machine. |
| Controller / dashboard | `python:3.12-slim` | Multi-arch, native |
| Switch, **Implementation B (default)** | `alpine:3.20` + iproute2, real Linux bridge `br0` + veth ports | Native. **Uses a custom NAPALM driver, not upstream NAPALM.** |
| Switch, **Implementation A** | Arista cEOS-lab | **Not downloadable without an Arista account** (arista.com login). Arista's default cEOS-lab is x86_64 only, so on Apple Silicon it needs emulation (slow, often unreliable) *unless* you obtain an Arista ARM build. I could not verify an ARM build is available to you. Treat A as optional. |
| Containerlab | not needed for B | Containerlab is Linux-only. On macOS it is run **inside a privileged container** (section 7); that needs `--privileged` and the Docker socket. Not verified here. |

Privileges: no container is `privileged`. Router and switch get only `NET_ADMIN` (router also `NET_RAW`) because zebra writes kernel
routes/addresses and the switch creates a bridge/veth ports. Containerlab itself needs `--privileged` (it creates network namespaces).

## 3. Project layout

```
docker-compose.yml        Implementation B: controller, router, switch, dashboard, 2 networks
docker-compose.clab.yml   Implementation A: controller + dashboard on Containerlab's "clab" network
topology.clab.yml         Containerlab: FRR router + cEOS switch
Dockerfile                dashboard image (Flask + backend)
backend/                  app.py, controller_client.py, router_netmiko.py, switch_napalm.py,
                          linux_switch_driver.py (custom NAPALM driver), config.py
controller/               FastAPI service + Dockerfile
router/                   Dockerfile, daemons, frr.conf, sshd_config, entrypoint.sh
switch/                   Dockerfile, entrypoint.sh, sshd_config, configuration/ceos-startup.cfg
templates/ static/        dashboard HTML / CSS / JS
tests/                    unit tests + live integration tests
scripts/                  setup.sh start.sh verify.sh cleanup.sh
```

## 4. Install and run (macOS, Implementation B)

Run every command from the project root (`cd network-automation-lab`).

```bash
docker info --format '{{.ServerVersion}} {{.OSType}}/{{.Architecture}}'   # expect linux/aarch64
python3 --version                                                          # expect >= 3.11
./scripts/setup.sh      # creates .env, host venv for tests, builds all images
./scripts/start.sh      # docker compose up -d, waits until http://localhost:5000 answers
./scripts/verify.sh     # port checks + live integration tests; exit code 1 on any failure
open http://localhost:5000
```
Restart: `./scripts/cleanup.sh && ./scripts/start.sh`. Logs: `docker compose logs -f router`.

Manual checks from the Mac:
```bash
curl http://127.0.0.1:8000/health                                  # FastAPI
ssh -p 2222 admin@127.0.0.1                                        # password: labpassword; then: sudo vtysh -c 'show ip route'
ssh -p 2223 admin@127.0.0.1                                        # then: ip -j link show
```

## 5. What each part does

| Branch | Path | Notes |
|---|---|---|
| A | Dashboard → `controller_client.py` (Requests, timeout, error mapping) → FastAPI | `/api/devices` does a **real TCP probe** per device; down devices are reported `down`. Operations from branches B/C are audit-logged via `POST /api/operations`. |
| B | `router_netmiko.py` → Netmiko `device_type="linux"` → SSH → `sudo -n vtysh -c ...` | Routes come from `show ip route json` and are parsed. Sudo is limited to the `vtysh` binary. Commands are a fixed allow-list; no free-form command endpoint exists. |
| C | `switch_napalm.py` → NAPALM → switch | `SWITCH_MODE=linux`: **custom** `LinuxBridgeDriver` (SSH + `ip -j link`, descriptions = interface alias). `SWITCH_MODE=eos`: **native** `napalm.get_network_driver("eos")`. Same code path for both: `open`, `get_facts`, `get_interfaces`, `get_interfaces_counters`, `load_merge_candidate` → `compare_config` → `commit_config`, `rollback`. |

**Native vs custom NAPALM:** the default switch driver is *custom* NAPALM-compatible code (subclass of `napalm.base.NetworkDriver`,
getter output follows NAPALM's schema). It implements merge-candidate configuration for interface descriptions only; replace-config,
BGP, LLDP, etc. are not implemented. Only the cEOS path uses upstream NAPALM.

**Safe configuration (Workflow 4).** The browser can't choose values. Router: add/remove `10.255.255.1/32` on `lo`. Switch: set/clear
description `napalm-lab-test` on `SWITCH_TEST_INTERFACE`. Each configure call returns *before*, *after* (read back from the device),
and for the switch the NAPALM diff; a read-back mismatch is reported as an error. "Restore Original" reverts (the switch remembers the
original description in backend memory; after a dashboard restart it clears the description).

**Security:** credentials come from `.env` (git-ignored) and never reach the browser; Flask is published on `127.0.0.1` only; all
network calls have timeouts; custom driver validates interface names and descriptions with strict regexes and `shlex.quote`.
Lab credentials are weak by design - don't reuse this outside a laptop.

## 6. API (dashboard)

All responses: `{ok, device, action, timestamp, duration_ms, data, error}`; failures return HTTP 502 (device/controller) or 500.
`GET /api/controller/{health,status,devices,topology,logs}` · `GET /api/router/{connect,routes,interfaces,version,loopback/verify}` ·
`POST /api/router/loopback/{configure,restore}` · `GET /api/switch/{connect,facts,interfaces,counters,description/verify}` ·
`POST /api/switch/description/{configure,restore}`. Controller (port 8000): `/health`, `/api/status`, `/api/devices`, `/api/topology`,
`/api/logs`, `POST /api/operations`.

## 7. Implementation A: Arista cEOS (optional, unverified)

1. Download cEOS-lab from arista.com (free account) and import it: `docker import cEOS-lab-<ver>.tar.xz ceos:<ver>`.
   Check whether an ARM64 build exists for your account; with an x86_64 image expect emulation problems.
2. Put the tag into `topology.clab.yml`, then `docker build -t lab-router:latest ./router`.
3. Deploy Containerlab from a container (macOS has no native clab):
   ```bash
   docker run --rm -it --privileged --network host --pid=host \
     -v /var/run/docker.sock:/var/run/docker.sock -v /run/netns:/var/run/netns \
     -v /var/lib/docker/containers:/var/lib/docker/containers \
     -v "$PWD":"$PWD" -w "$PWD" ghcr.io/srl-labs/clab containerlab deploy -t topology.clab.yml
   ```
4. `./scripts/start.sh clab` (uses `docker-compose.clab.yml`; sets `SWITCH_MODE=eos`, host `clab-netlab-switch`, eAPI over HTTPS on 443).
5. Destroy with the same command using `destroy -t topology.clab.yml --cleanup`.
If cEOS does not boot within your time budget, stay on Implementation B.

## 8. Five-minute demo

1. `./scripts/start.sh`, open `localhost:5000` (30 s).
2. **Controller:** Check Controller Health → JSON `healthy`; List Network Devices → router/switch `up` with measured latency (45 s).
3. **Router:** Connect → hostname + resolved IP; Show IP Routes → table with connected `10.10.0.0/24`, static `198.51.100.0/24` (blackhole), `203.0.113.0/24` (60 s).
4. **Router config:** Configure Test Loopback → before/after in JSON; Verify; Restore Original (45 s).
5. **Switch:** Connect → Get Switch Facts → Get Interfaces (port1-4, br0) → Get Interface Counters (60 s).
6. **Switch config:** Configure Test Interface Description → diff + read-back; Verify; Restore Original (45 s).
7. **Failure honesty:** `docker compose stop router`, click Show IP Routes → red error; List Network Devices → router `down`; `docker compose start router` (45 s).
8. Show the audit trail: Get Controller Status → `operations_logged` increased; `curl localhost:8000/api/logs`.

## 9. Troubleshooting (things most likely to need a tweak)

| Symptom | Likely cause / fix |
|---|---|
| Router container restarts, log says `missing FRR binary` | Alpine's FRR path differs. `docker run --rm --entrypoint sh netlab-router -c 'apk info -L frr \| grep -E "zebra\|staticd"'`, then adjust `bin()` in `router/entrypoint.sh`. |
| Routes table is empty / `vtysh did not return JSON` | zebra not running: `docker compose logs router`; check `docker compose exec router sudo -n vtysh -c 'show ip route json'`. |
| `SSH authentication failed` | Password in `.env` changed after the image was built: `./scripts/cleanup.sh && docker compose up -d --build`. |
| Netmiko hangs at login | Prompt not detected: `docker compose exec router su - admin` and check the prompt ends with `$`. |
| `ip link add ... veth` fails in switch log | Rare Docker VM kernel limitation; ports will be missing. Check `docker compose logs switch`. |
| Switch interface description not applied | `sudo -n /sbin/ip` path: `docker compose exec switch sh -c 'command -v ip'`; update `switch/entrypoint.sh` sudoers line and `linux_switch_driver.py` paths. |
| `pip install` fails building lxml/cryptography | The Dockerfile installs build tools; re-run `docker compose build --no-cache dashboard`. |
| Port 5000 busy | macOS AirPlay Receiver uses 5000: turn it off in System Settings, or change the published port in `docker-compose.yml`. |
| Integration tests fail immediately | By design: they never skip. Start the stack first. |

Unit tests only (no containers): `.venv/bin/python -m pytest -m "not integration"`.
