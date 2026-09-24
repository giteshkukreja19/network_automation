"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const REQUEST_TIMEOUT_MS = 30_000;

function table(cols, rows) {
  if (!rows.length) return "<p>No rows returned.</p>";
  const head = cols.map((c) => `<th>${esc(c[0])}</th>`).join("");
  const body = rows.map((r) => "<tr>" + cols.map((c) => {
    const v = c[1](r); const cls = c[2] ? c[2](r) : "";
    return `<td class="${cls}">${esc(v)}</td>`;
  }).join("") + "</tr>").join("");
  return `<div class="tbl"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

const renderers = {
  "/api/controller/devices": (d) => table(
    [["Device", (r) => r.name], ["Platform", (r) => r.platform], ["Host", (r) => r.host], ["IP", (r) => r.ip || "–"],
     ["Status", (r) => r.status, (r) => r.status], ["Latency ms", (r) => r.latency_ms ?? "–"]], d.devices),
  "/api/router/routes": (d) => table(
    [["Prefix", (r) => r.prefix], ["Protocol", (r) => r.protocol], ["Next hop", (r) => r.nexthops.join(", ")],
     ["Interface", (r) => r.interfaces.join(", ")], ["Selected", (r) => r.selected ? "yes" : "no"]], d.routes),
  "/api/router/interfaces": (d) => table(
    [["Interface", (r) => r.name], ["State", (r) => r.state], ["Addresses", (r) => r.addresses.join(", ")],
     ["MTU", (r) => r.mtu]], d.interfaces),
  "/api/switch/interfaces": (d) => table(
    [["Interface", (r) => r[0]], ["Oper", (r) => r[1].is_up ? "up" : "down", (r) => r[1].is_up ? "up" : "down"],
     ["Admin", (r) => r[1].is_enabled ? "enabled" : "disabled"], ["Description", (r) => r[1].description],
     ["MAC", (r) => r[1].mac_address]], Object.entries(d.interfaces)),
};

function updateFacts(sec, api, d) {
  if (sec === "router" && d.hostname) { $("router-hostname").textContent = d.hostname; $("router-ip").textContent = d.management_ip; }
  if (sec === "switch") {
    const h = d.hostname || (d.facts && d.facts.hostname);
    if (h) $("switch-hostname").textContent = h;
    if (d.management_ip) $("switch-ip").textContent = d.management_ip;
  }
  if (sec === "controller" && api.endsWith("/health")) $("controller-health").textContent = d.status;
}

async function run(btn) {
  const sec = btn.dataset.sec, api = btn.dataset.api, method = btn.dataset.method || "GET";
  const msg = $(`${sec}-msg`), dot = $(`${sec}-dot`), out = $(`${sec}-out`);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  document.querySelectorAll(`#sec-${sec} button`).forEach((b) => (b.disabled = true));
  msg.className = "msg busy"; msg.textContent = "Running…"; if (dot) dot.className = "dot busy";
  try {
    const res = await fetch(api, {method, signal: controller.signal});
    let body;
    try {
      body = await res.json();
    } catch (err) {
      if (!(err instanceof SyntaxError)) throw err;
      throw new Error(`Backend returned invalid JSON (HTTP ${res.status})`);
    }
    if (!body || typeof body !== "object" || typeof body.ok !== "boolean") {
      throw new Error(`Backend returned an invalid response (HTTP ${res.status})`);
    }
    out.textContent = JSON.stringify(body, null, 2);
    $(`${sec}-time`).textContent = body.timestamp ? `${body.timestamp} (${body.duration_ms} ms)` : new Date().toISOString();
    if (body.ok) {
      msg.className = "msg ok"; msg.textContent = `Success: ${body.action} completed in ${body.duration_ms} ms`;
      if (dot) { dot.className = "dot ok"; }
      $(`${sec}-status`).textContent = sec === "controller" ? "connected" : (sec === "router" ? "SSH authenticated" : "NAPALM session OK");
      updateFacts(sec, api, body.data);
      $(`${sec}-table`).innerHTML = renderers[api] ? renderers[api](body.data) : "";
    } else {
      msg.className = "msg bad"; msg.textContent = `Failed: ${body.error || `HTTP ${res.status}`}`;
      if (dot) dot.className = "dot bad";
      $(`${sec}-status`).textContent = "unreachable / error";
      $(`${sec}-table`).innerHTML = "";
    }
  } catch (err) {
    const timedOut = err !== null && typeof err === "object" && err.name === "AbortError";
    const message = timedOut
      ? `Request timed out after ${REQUEST_TIMEOUT_MS / 1000} seconds`
      : `Request failed: ${err instanceof Error ? err.message : String(err)}`;
    msg.className = "msg bad"; msg.textContent = message;
    out.textContent = JSON.stringify({ok: false, error: message}, null, 2);
    if (dot) dot.className = "dot bad";
    $(`${sec}-status`).textContent = "unreachable / error";
    $(`${sec}-table`).innerHTML = "";
  } finally {
    clearTimeout(timeout);
    document.querySelectorAll(`#sec-${sec} button`).forEach((b) => (b.disabled = false));
  }
}

document.querySelectorAll("button[data-api]").forEach((b) => b.addEventListener("click", () => run(b)));
