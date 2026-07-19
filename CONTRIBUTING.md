# Contributing

Contributions are welcome during the public alpha, especially:

- sanitized audit profiles for independent open-source Telegram bots;
- false-positive and false-negative fixtures;
- JSON Schema tightening;
- Linux, macOS, and Windows compatibility fixes;
- English documentation improvements;
- benchmark cases with a clearly documented expected result.

## Development setup

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tools/smoke_runtime_audit.py
.venv/bin/python tools/smoke_runtime_probe.py
.venv/bin/python tools/smoke_http_probe.py
.venv/bin/python tools/smoke_sqlite_probe.py
.venv/bin/python tools/smoke_adopt.py
.venv/bin/python tools/demo_public_alpha.py
```

## Pull requests

1. Keep runtime bot code and secrets out of this repository.
2. Update a machine-readable spec before changing a long-term behavior.
3. Add or update an ADR for structural decisions.
4. Add a fixture that fails before the change and passes after it.
5. Run `git diff --check` and the relevant smoke tests.
6. Explain safety impact, verification, and rollback in the pull request.

Do not submit production databases, `.env` files, raw logs, user exports, tokens, credentials, or proprietary bot source.
