"""CUSTOM NAPALM driver for a Linux-bridge virtual switch (Implementation B).

This is NOT part of upstream NAPALM. It subclasses napalm.base.NetworkDriver and implements the standard
getters and the candidate-config workflow (load_merge_candidate / compare_config / commit_config /
discard_config / rollback) by running real `ip` commands over SSH on the switch container.
Interface "description" == Linux interface alias (ifalias).

Supported candidate syntax (merge):
    interface port1
     description some text
    interface port2
     no description
"""
import json
import re
import shlex

import paramiko
from napalm.base import NetworkDriver
from napalm.base.exceptions import CommandErrorException, ConnectionException, MergeConfigException

IFACE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,15}$")
DESC_RE = re.compile(r"^[A-Za-z0-9 _.\-:/]{0,200}$")


class LinuxBridgeDriver(NetworkDriver):
    def __init__(self, hostname, username, password, timeout=60, optional_args=None):
        self.hostname, self.username, self.password, self.timeout = hostname, username, password, timeout
        self.optional_args = optional_args or {}
        self.port = int(self.optional_args.get("port", 22))
        self.client = None
        self._candidate = {}        # {iface: description}
        self._rollback = None       # {iface: previous description}

    # ---- connection -------------------------------------------------------------
    def open(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(self.hostname, port=self.port, username=self.username, password=self.password,
                                timeout=self.timeout, banner_timeout=self.timeout, auth_timeout=self.timeout,
                                look_for_keys=False, allow_agent=False)
        except Exception as exc:  # noqa: BLE001
            raise ConnectionException(f"cannot connect to {self.hostname}:{self.port}: {exc}") from exc

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def is_alive(self):
        t = self.client.get_transport() if self.client else None
        return {"is_alive": bool(t and t.is_active())}

    def _run(self, cmd: str) -> str:
        if not self.client:
            raise ConnectionException("connection not open")
        _, out, err = self.client.exec_command(cmd, timeout=self.timeout)
        text, etext = out.read().decode(), err.read().decode()
        if out.channel.recv_exit_status() != 0:
            raise CommandErrorException(f"`{cmd}` failed: {etext.strip() or text.strip()}")
        return text

    def _links(self, stats=False):
        return json.loads(self._run("/sbin/ip -j -s link show" if stats else "/sbin/ip -j link show"))

    # ---- getters ----------------------------------------------------------------
    def get_facts(self):
        hostname = self._run("hostname").strip()
        uptime = float(self._run("cat /proc/uptime").split()[0])
        links = self._links()
        return {"uptime": uptime, "vendor": "Linux", "model": "Linux bridge (br0) in container",
                "hostname": hostname, "fqdn": hostname, "os_version": self._run("uname -r").strip(),
                "serial_number": "N/A", "interface_list": sorted(l["ifname"] for l in links)}

    def get_interfaces(self):
        out = {}
        for l in self._links():
            flags = l.get("flags", [])
            out[l["ifname"]] = {"is_up": l.get("operstate") in ("UP", "UNKNOWN") and "LOWER_UP" in flags,
                                "is_enabled": "UP" in flags, "description": l.get("ifalias", ""),
                                "last_flapped": -1.0, "mtu": l.get("mtu", 0), "speed": 0,
                                "mac_address": l.get("address", "")}
        return out

    def get_interfaces_counters(self):
        out = {}
        for l in self._links(stats=True):
            rx, tx = l.get("stats64", {}).get("rx", {}), l.get("stats64", {}).get("tx", {})
            out[l["ifname"]] = {
                "tx_errors": tx.get("errors", 0), "rx_errors": rx.get("errors", 0),
                "tx_discards": tx.get("dropped", 0), "rx_discards": rx.get("dropped", 0),
                "tx_octets": tx.get("bytes", 0), "rx_octets": rx.get("bytes", 0),
                "tx_unicast_packets": tx.get("packets", 0), "rx_unicast_packets": rx.get("packets", 0) - rx.get("multicast", 0),
                "tx_multicast_packets": 0, "rx_multicast_packets": rx.get("multicast", 0),
                "tx_broadcast_packets": 0, "rx_broadcast_packets": 0}
        return out

    def _running(self):
        return {n: i["description"] for n, i in self.get_interfaces().items()}

    def get_config(self, retrieve="all", full=False, sanitized=False):
        text = "\n".join(f"interface {n}\n description {d}" if d else f"interface {n}"
                         for n, d in sorted(self._running().items()))
        return {"running": text, "candidate": self._render(self._candidate), "startup": ""}

    # ---- candidate configuration workflow ---------------------------------------
    @staticmethod
    def _render(cand):
        return "\n".join(f"interface {n}\n " + (f"description {d}" if d else "no description")
                         for n, d in sorted(cand.items()))

    def load_merge_candidate(self, filename=None, config=None):
        text = config if config is not None else open(filename).read()
        cand, iface = {}, None
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            if line.startswith("interface "):
                iface = line.split(None, 1)[1]
                if not IFACE_RE.match(iface):
                    raise MergeConfigException(f"invalid interface name: {iface!r}")
            elif iface and line.startswith("description "):
                desc = line.split(None, 1)[1]
                if not DESC_RE.match(desc):
                    raise MergeConfigException("description contains unsupported characters")
                cand[iface] = desc
            elif iface and line == "no description":
                cand[iface] = ""
            else:
                raise MergeConfigException(f"unsupported line: {line!r}")
        running = self._running()
        unknown = [i for i in cand if i not in running]
        if unknown:
            raise MergeConfigException(f"interface(s) not on device: {', '.join(unknown)}")
        self._candidate = cand

    def load_replace_candidate(self, filename=None, config=None):
        raise NotImplementedError("replace is not supported by the Linux bridge driver")

    def compare_config(self):
        running, diff = self._running(), []
        for n, d in sorted(self._candidate.items()):
            if running.get(n, "") != d:
                diff.append(f"interface {n}\n- description {running.get(n, '')}\n+ description {d}")
        return "\n".join(diff)

    def commit_config(self, message="", revert_in=None):
        running = self._running()
        self._rollback = {n: running[n] for n in self._candidate}
        for n, d in self._candidate.items():
            self._set_alias(n, d)
        self._candidate = {}

    def discard_config(self):
        self._candidate = {}

    def rollback(self):
        if self._rollback is None:
            raise CommandErrorException("nothing to roll back in this session")
        for n, d in self._rollback.items():
            self._set_alias(n, d)
        self._rollback = None

    def _set_alias(self, iface, desc):
        if not IFACE_RE.match(iface) or not DESC_RE.match(desc):
            raise MergeConfigException("refusing unsafe interface/description")
        if desc:
            self._run(f"sudo -n /sbin/ip link set dev {shlex.quote(iface)} alias {shlex.quote(desc)}")
        else:
            self._run(f"sudo -n /sbin/ip link set dev {shlex.quote(iface)} alias ''")
