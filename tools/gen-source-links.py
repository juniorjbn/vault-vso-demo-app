#!/usr/bin/env python3
"""Resolve `vsolink` anchors into GitHub permalinks.

Reads the start/end anchor comments (`# vsolink:<pattern>:<kind>:start|end`) in
app/app.py (kind=code) and manifests/04-vault-secrets.yaml (kind=yaml), computes
the line range between each pair, and emits app/source_links.json with deep links
pinned to the current commit SHA. Then regenerates manifests/05-configmap-app.yaml
(app.py + sidecar.sh + source_links.json) so the deployed app stays in sync and
ships the links.

Run from the repo root after editing app/app.py or manifests/04-vault-secrets.yaml,
then commit. Links point to HEAD-at-generation; since only this script's outputs
change after, the anchored lines stay identical => links remain correct.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "app/app.py"
SECRETS = "manifests/04-vault-secrets.yaml"
PATTERNS = ["dynamic", "static", "pki",
            "transform-fpe", "transform-mask", "transform-token"]


def sh(*args):
    return subprocess.check_output(args, cwd=ROOT).decode().strip()


def repo_slug():
    url = sh("git", "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", url)
    if not m:
        sys.exit("nao consegui extrair owner/repo de: " + url)
    return m.group(1)


def anchor_ranges(path, kind):
    """{pattern: (first_content_line, last_content_line)} from start/end anchors."""
    lines = open(os.path.join(ROOT, path)).read().splitlines()
    starts, ends = {}, {}
    for i, ln in enumerate(lines, 1):
        m = re.search(r"vsolink:(\w+):" + re.escape(kind) + r":(start|end)\b", ln)
        if m:
            (starts if m.group(2) == "start" else ends)[m.group(1)] = i
    out = {}
    for p in PATTERNS:
        if p in starts and p in ends and ends[p] - 1 >= starts[p] + 1:
            out[p] = (starts[p] + 1, ends[p] - 1)
    return out


def indent4(text):
    return "\n".join(("    " + ln) if ln.strip() else "" for ln in text.splitlines())


def main():
    sha = sh("git", "rev-parse", "HEAD")
    repo = repo_slug()
    base = "https://github.com/%s/blob/%s" % (repo, sha)
    code = anchor_ranges(APP, "code")
    yml = anchor_ranges(SECRETS, "yaml")

    links = {"_meta": {"repo": repo, "sha": sha}}
    missing = []
    for p in PATTERNS:
        entry = {}
        if p in code:
            entry["code"] = "%s/%s#L%d-L%d" % (base, APP, code[p][0], code[p][1])
        else:
            missing.append("%s:code" % p)
        if p in yml:
            entry["yaml"] = "%s/%s#L%d-L%d" % (base, SECRETS, yml[p][0], yml[p][1])
        links[p] = entry

    with open(os.path.join(ROOT, "app/source_links.json"), "w") as f:
        json.dump(links, f, indent=2)
        f.write("\n")
    print("app/source_links.json escrito (sha %s)" % sha[:8])
    print(json.dumps(links, indent=2))
    if missing:
        print("AVISO: ancoras faltando: " + ", ".join(missing), file=sys.stderr)

    regen_configmap(links)


def regen_configmap(links):
    app_py = open(os.path.join(ROOT, APP)).read()
    sidecar = open(os.path.join(ROOT, "app/sidecar.sh")).read()
    sl = json.dumps(links, indent=2)
    cm = (
        "---\n"
        "# GERADO por tools/gen-source-links.py - NAO editar a mao.\n"
        "# Bundle: app.py (== app/app.py), sidecar.sh, source_links.json (deep links GitHub).\n"
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: vso-demo-app-code\n"
        "  namespace: vso-demo  # CHANGE: your namespace\n"
        "data:\n"
        "  app.py: |\n" + indent4(app_py) + "\n"
        "  sidecar.sh: |\n" + indent4(sidecar) + "\n"
        "  source_links.json: |\n" + indent4(sl) + "\n"
    )
    with open(os.path.join(ROOT, "manifests/05-configmap-app.yaml"), "w") as f:
        f.write(cm)
    print("manifests/05-configmap-app.yaml regenerado (app.py em sync + source_links.json)")


if __name__ == "__main__":
    main()
