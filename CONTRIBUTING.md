# Contributing

Thanks for your interest in improving this demo.

## How to contribute

1. **Open an issue first** for anything beyond a typo or trivial fix — it's easier to align on direction before code review.
2. **Fork the repo** and create a topic branch (`feat/short-description`, `fix/short-description`).
3. **Keep changes focused**. One concern per PR makes review fast.
4. **Test on a real cluster** when touching manifests or the Vault setup script. The README's Quick Start is the smoke test.
5. **Open a PR** against `main` with a short description of what changed and why.

## Style

- Manifests: keep placeholders explicit (`# CHANGE: ...`). Don't hardcode environment-specific values.
- Shell scripts: `set -euo pipefail`, no silent failures.
- Python: keep `app/app.py` self-contained — it ships as a single ConfigMap.
- Comments and documentation: English.

## What's in scope

- Bug fixes for the three demonstrated patterns (Dynamic / Static / PKI).
- Improvements to the UI (auto-refresh, JSON rendering, accessibility).
- Helm chart, Kustomize overlays, or alternative deployment shapes.
- Additional documentation, diagrams, examples.

## What's out of scope

- Provider-specific integrations (cloud-specific load balancers, managed Vault offerings). Keep it portable.
- Replacing the demonstrated patterns with something else — fork the repo if you want a different demo.

## License

By contributing you agree your contribution is licensed under Apache 2.0 (same as the project).
