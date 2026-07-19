# BotCharter

**Architecture control and safety gates for AI-built bots.**

BotCharter provides the `botctl` command: an open-source control plane for teams that design, build, and maintain Telegram bots with AI coding agents.

It turns product intent into machine-readable flows, UI graphs, events, storage rules, dependencies, contracts, design approvals, and change plans. It can then compare those specifications with Python bot source code without importing or running the bot.

> Public alpha. Use it for architecture, review, drift detection, and guarded diagnostics. Runtime code generation, deployment, and production mutation are intentionally disabled.

[Russian documentation](README.ru.md)

## Why

AI agents can modify a bot faster than a human can reconstruct its architecture. That becomes dangerous when handlers, callbacks, databases, analytics, broadcasts, publishing, and external APIs evolve independently.

`botctl` makes the control surface explicit:

```text
Intent -> Specs -> Design review -> ChangePlan -> Implementation -> Audit
             \_______________________________________________/
                         machine-checked boundaries
```

## What it does

- adopts an existing project into a guarded `.botctl/` workspace;
- models product, roles, journeys, menus, responses, state, impact, and tests;
- requires reviewed design artifacts and an approved ChangePlan;
- detects callback, event, storage, dependency, and contract-test drift;
- generates agent-readable architecture context;
- performs explicit local PID/heartbeat, HTTP HEAD, and immutable SQLite checks;
- keeps `runtime_apply_allowed` permanently false in the public alpha.

## What it does not do

- generate or rewrite production bot code;
- read `.env`, tokens, personal logs, sessions, or user exports;
- import or execute the target bot during source audit;
- restart services or deploy releases;
- contact Telegram automatically;
- silently overwrite an existing `.botctl/` or `AGENTS.md`.

## Install

Python 3.11 or newer is required.

```bash
python -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/botctl --help
```

The package is not published to PyPI yet. The command above installs a local checkout of `botcharter`; the installed command remains `botctl`.

## Adopt an existing project

Preview the files that would be created:

```bash
botctl adopt --project /path/to/project
```

Create a new `.botctl/` control directory:

```bash
botctl adopt --project /path/to/project --confirm
```

Adoption creates project metadata, architecture graphs, six local specifications, draft design artifacts, generated agent context, and `.botctl/AGENT_INSTRUCTIONS.md`. Files outside `.botctl/` remain unchanged.

## Core workflow

```bash
botctl inspect --project /path/to/project --format agent
botctl verify --project /path/to/project
botctl design status --project /path/to/project --format json
botctl design gate --project /path/to/project --format json
botctl audit-runtime \
  --project /path/to/project \
  --specs /path/to/project/.botctl/specs \
  --format json
```

## Guarded diagnostics

Every probe requires an explicit target. Network and database access require an additional confirmation flag.

```bash
botctl probe-runtime --pid 12345
botctl probe-runtime --heartbeat-file /path/to/heartbeat --max-heartbeat-age 300
botctl probe-http --url https://bot.example/health --confirm-network
botctl probe-sqlite --database /path/to/bot.sqlite3 --confirm-database-read
```

See [Security](SECURITY.md) for exact boundaries.

## Reproducible demo

The demo copies a tiny existing service into a temporary directory, adopts it, verifies the result, and proves that source files outside `.botctl/` did not change.

```bash
python tools/demo_public_alpha.py
```

No network, Telegram token, runtime database, or private repository is required.

## Project status

The current public-alpha candidate includes:

- installable `botctl` CLI;
- 30+ JSON Schemas;
- specs-first architecture model;
- design review and approval gates;
- read-only Python source audit;
- portable audit profiles;
- guarded runtime probes;
- CI smoke tests and a reproducible public demo.

It is not yet a proven industry standard. The next validation milestone is a public benchmark across independent Telegram bot repositories with injected drift cases and measured precision/recall.

Human-readable validation messages, generated titles, and parts of the CLI are currently Russian-first. Machine-readable JSON, schemas, and identifiers are language-neutral. Full English localization is a post-alpha milestone.

## Documentation

- [Public alpha guide](docs/PUBLIC_ALPHA.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Architecture decisions](docs/adr/)
- [Detailed CLI notes](docs/BOTCTL_V0.md)
- [Changelog](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE).
