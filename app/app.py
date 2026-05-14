"""
vault-vso-demo-app — Flask UI showing three Vault Secrets Operator patterns
running side-by-side in a single pod that never restarts:

  1) Dynamic Secret — PostgreSQL credentials read via a sidecar that polls
     the K8s Secret and writes the values into a shared emptyDir volume.
     The webapp re-reads the file on every request.
  2) Static Secret  — KV v2 mounted as a Secret volume. kubelet propagates
     in-place updates; the webapp re-reads the files each request.
  3) PKI Secret     — Short-lived TLS cert mounted as a Secret volume.
     VSO renews ahead of expiry; kubelet remounts the files.

The pod's uptime counter increments forever to make it obvious that none
of the three rotation paths require a restart.
"""
import os
import hashlib
import socket
import json
from datetime import datetime, timezone

from flask import Flask, render_template_string, jsonify
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from pygments import highlight
from pygments.lexers import JsonLexer
from pygments.formatters import HtmlFormatter

app = Flask(__name__)
POD_START = datetime.now(timezone.utc)
POD_NAME = os.getenv("HOSTNAME", socket.gethostname())

# Paths populated by the sidecar / kubelet.
CREDS_FILE = "/shared/credentials.txt"   # written by the sidecar
STATIC_DIR = "/static-config"            # mounted from VaultStaticSecret
PKI_CRT = "/tls/tls.crt"                 # mounted from VaultPKISecret

counter = 0


def read_credentials():
    """Read DB credentials from the shared volume (refreshed by the sidecar)."""
    try:
        with open(CREDS_FILE, "r") as f:
            data = {}
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v
            return data
    except FileNotFoundError:
        return {}


def read_static_config():
    """Read the static config Secret directory (mounted by VSO Static)."""
    if not os.path.isdir(STATIC_DIR):
        return {"_status": "waiting for VSO to sync..."}
    result = {}
    try:
        for key in sorted(os.listdir(STATIC_DIR)):
            if key.startswith("."):
                continue
            path = os.path.join(STATIC_DIR, key)
            if os.path.isfile(path):
                with open(path) as f:
                    result[key] = f.read().strip()
        return result if result else {"_status": "secret is empty"}
    except Exception as e:
        return {"_error": str(e)}


def read_pki_cert():
    """Parse the PKI cert (renewed by VSO before expiry)."""
    if not os.path.isfile(PKI_CRT):
        return {"_status": "waiting for certificate issuance..."}
    try:
        with open(PKI_CRT, "rb") as f:
            pem = f.read()
        cert = x509.load_pem_x509_certificate(pem)
        fp = cert.fingerprint(hashes.SHA256()).hex()
        now = datetime.now(timezone.utc)
        remaining_s = int((cert.not_valid_after_utc - now).total_seconds())
        return {
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
            "serial_hex": format(cert.serial_number, "x"),
            "not_valid_before_utc": cert.not_valid_before_utc.isoformat(),
            "not_valid_after_utc": cert.not_valid_after_utc.isoformat(),
            "remaining_seconds": remaining_s,
            "signature_algorithm": cert.signature_algorithm_oid._name,
            "public_key_size_bits": cert.public_key().key_size,
            "fingerprint_sha256": ":".join(fp[i:i + 2] for i in range(0, len(fp), 2)),
        }
    except Exception as e:
        return {"_error": str(e)}


def hl_json(data):
    """Render a dict as jq-like syntax-highlighted JSON via Pygments."""
    js = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
    return highlight(js, JsonLexer(),
                     HtmlFormatter(style="monokai", noclasses=True, nobackground=True))


def pwd_hash(pwd):
    if not pwd:
        return "n/a"
    h = hashlib.sha256(pwd.encode()).hexdigest()
    return f"sha256:{h[:12]}"


PAGE = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><title>Vault Secrets Operator — three patterns, one pod</title>
<style>
body{font-family:-apple-system,Segoe UI,sans-serif;max-width:920px;margin:1.5em auto;padding:1.5em;background:#0f172a;color:#e2e8f0}
h1{color:#a855f7;margin:0 0 .3em 0;font-size:1.7em}
.sub{color:#94a3b8;margin-bottom:1.5em}
.box{background:#1e293b;padding:1.2em 1.5em;border-radius:10px;margin:.8em 0;border-left:4px solid #3b82f6}
.box.cred{border-color:#22c55e}
.box.timer{border-color:#fbbf24}
.box.flow{border-color:#a855f7;font-size:.95em}
.box.static{border-color:#0ea5e9}
.box.pki{border-color:#f43f5e}
.jq{font-family:'SF Mono',Consolas,monospace;font-size:.85em;line-height:1.5;background:#0b1220;padding:1em;border-radius:6px;overflow-x:auto;margin:.5em 0}
.jq pre{margin:0;color:#e2e8f0}
.hint{color:#94a3b8;font-size:.8em;margin-top:.4em;font-style:italic}
.label{color:#64748b;font-size:.78em;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4em}
.val{font-family:'SF Mono',Consolas,monospace;font-size:1em;line-height:1.6;word-break:break-all;color:#f1f5f9}
.big{font-size:1.3em;font-weight:600;color:#22c55e}
.timer-big{font-size:2em;font-weight:600;color:#fbbf24;font-family:'SF Mono',Consolas,monospace}
.step{margin:.3em 0;padding-left:1.5em;text-indent:-1.5em}
.step::before{content:"\\2192 ";color:#a855f7}
.pod{color:#7dd3fc;font-family:'SF Mono',Consolas,monospace}
.footer{margin-top:2em;color:#64748b;font-size:.75em;text-align:center}
.controls{position:sticky;top:0;background:#1e293b;padding:.8em 1em;border-radius:8px;margin:0 0 1.2em 0;display:flex;align-items:center;gap:1em;flex-wrap:wrap;border:1px solid #334155;z-index:10}
.controls button{background:#334155;color:#e2e8f0;border:1px solid #475569;padding:.5em 1em;border-radius:6px;font-size:.9em;cursor:pointer;font-family:inherit;transition:all .15s}
.controls button:hover{background:#475569}
.controls button.on{background:#22c55e;border-color:#16a34a;color:#0f172a;font-weight:600}
.controls button.off{background:#ef4444;border-color:#b91c1c;color:white;font-weight:600}
.controls .countdown{color:#fbbf24;font-family:'SF Mono',Consolas,monospace;font-size:.9em;margin-left:auto}
.controls select{background:#0b1220;color:#e2e8f0;border:1px solid #475569;padding:.45em .7em;border-radius:6px;font-size:.9em;font-family:inherit}
</style>
</head><body>
<h1>Vault Secrets Operator &mdash; three patterns, zero restarts</h1>
<p class="sub">One pod consumes secrets from Vault through three different VSO resources (Dynamic, Static, PKI). Each block below re-reads its source on every request. The pod uptime counter just keeps growing.</p>

<div class="controls">
  <button id="toggleBtn" onclick="toggleAuto()">Pause auto-refresh</button>
  <button onclick="window.location.reload()">Refresh now</button>
  <label>Interval:
    <select id="intervalSel" onchange="changeInterval()">
      <option value="3">3s (fast)</option>
      <option value="10" selected>10s (default)</option>
      <option value="30">30s</option>
      <option value="60">60s</option>
      <option value="0">manual</option>
    </select>
  </label>
  <span class="countdown" id="countdown">next: 10s</span>
</div>

<div class="box cred">
  <div class="label">Pattern 1 &mdash; Dynamic Secret (PostgreSQL via sidecar)</div>
  <div class="val">DB user: <span class="big">{{ db_user }}</span></div>
  <div class="val">Password (sha256, 12 chars): <span class="big">{{ pwd_fp }}</span></div>
  <div class="val">Last sidecar update: {{ updated }}</div>
  <div class="hint">Sidecar polls K8s Secret <code>db-creds</code> every 3s and writes <code>/shared/credentials.txt</code>. VSO renews the Vault lease near expiry; the new values land here without restarting the pod.</div>
</div>

<div class="box timer">
  <div class="label">Pod uptime</div>
  <div class="timer-big">{{ uptime }}</div>
  <div class="val">started at {{ pod_start }} &middot; pod: <span class="pod">{{ pod_name }}</span></div>
  <div class="val">If this number only grows, the pod has never restarted.</div>
</div>

<div class="box static">
  <div class="label">Pattern 2 &mdash; Static Secret (KV v2, refreshAfter 30s)</div>
  <div class="jq">{{ static_html|safe }}</div>
  <div class="hint">Edit the KV path in Vault and the UI picks it up within ~30s. No pod restart.</div>
</div>

<div class="box pki">
  <div class="label">Pattern 3 &mdash; PKI Secret (TTL 5m, expiryOffset 2m)</div>
  <div class="jq">{{ pki_html|safe }}</div>
  <div class="hint">Serial and validity window rotate every ~3 minutes. VSO renews the cert, kubelet remounts the files, the pod keeps running.</div>
</div>

<div class="box flow">
  <div class="label">Sidecar pattern (Pattern 1 only)</div>
  <div class="step">VaultDynamicSecret requests fresh DB credentials with a short TTL.</div>
  <div class="step">Sidecar (kubectl) reads Secret <code>db-creds</code> every 3s.</div>
  <div class="step">Sidecar writes <code>/shared/credentials.txt</code> on a shared <code>emptyDir</code>.</div>
  <div class="step">Webapp re-reads the file on each HTTP request.</div>
  <div class="step">VSO renews the lease at <code>renewalPercent</code> &rarr; Secret updated &rarr; sidecar picks it up within 3s.</div>
  <div class="step"><strong>Pod uptime keeps increasing. No restart. No request loss.</strong></div>
</div>

<div class="footer">request #{{ counter }} &middot; refresh controls at the top</div>
<script>
(function(){
  var STORAGE_KEY_ON = 'vsoDemoAutoRefresh';
  var STORAGE_KEY_INT = 'vsoDemoRefreshInterval';
  var on = localStorage.getItem(STORAGE_KEY_ON) !== 'off';
  var intervalSec = parseInt(localStorage.getItem(STORAGE_KEY_INT) || '10', 10);
  if (isNaN(intervalSec)) intervalSec = 10;
  var remaining = intervalSec;
  function render() {
    var btn = document.getElementById('toggleBtn');
    var cd = document.getElementById('countdown');
    var sel = document.getElementById('intervalSel');
    if (sel) sel.value = intervalSec === 0 ? '0' : String(intervalSec);
    if (intervalSec === 0) {
      btn.textContent = 'Manual mode';
      btn.className = 'off';
      cd.textContent = 'manual refresh only';
      return;
    }
    if (on) {
      btn.textContent = 'Pause auto-refresh';
      btn.className = 'on';
      cd.textContent = 'next: ' + remaining + 's';
    } else {
      btn.textContent = 'Resume auto-refresh';
      btn.className = 'off';
      cd.textContent = 'paused';
    }
  }
  function tick() {
    if (!on || intervalSec === 0) return;
    remaining--;
    if (remaining <= 0) { window.location.reload(); return; }
    render();
  }
  window.toggleAuto = function() {
    on = !on;
    localStorage.setItem(STORAGE_KEY_ON, on ? 'on' : 'off');
    remaining = intervalSec;
    render();
  };
  window.changeInterval = function() {
    var v = parseInt(document.getElementById('intervalSel').value, 10);
    intervalSec = v;
    localStorage.setItem(STORAGE_KEY_INT, String(v));
    remaining = v;
    render();
  };
  render();
  setInterval(tick, 1000);
})();
</script>
</body></html>"""


@app.route("/")
def index():
    global counter
    counter += 1
    creds = read_credentials()
    uptime_s = int((datetime.now(timezone.utc) - POD_START).total_seconds())
    uptime = f"{uptime_s // 60}m {uptime_s % 60:02d}s"
    return render_template_string(
        PAGE,
        db_user=creds.get("username", "(no creds yet)"),
        pwd_fp=pwd_hash(creds.get("password", "")),
        updated=creds.get("updated", "never"),
        uptime=uptime,
        pod_start=POD_START.strftime("%Y-%m-%d %H:%M:%S UTC"),
        pod_name=POD_NAME,
        counter=counter,
        static_html=hl_json(read_static_config()),
        pki_html=hl_json(read_pki_cert()),
    )


@app.route("/api/info")
def api_info():
    creds = read_credentials()
    uptime_s = int((datetime.now(timezone.utc) - POD_START).total_seconds())
    return jsonify({
        "pod_name": POD_NAME,
        "pod_uptime_seconds": uptime_s,
        "pod_started_at_utc": POD_START.isoformat(),
        "db_user": creds.get("username", ""),
        "db_password_hash": pwd_hash(creds.get("password", "")),
        "creds_last_updated": creds.get("updated", "never"),
        "static_config": read_static_config(),
        "pki_cert": read_pki_cert(),
        "pattern": "three VSO patterns, single pod, no restart",
    })


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
