# CLAUDE.md

This file gives Claude/agentic coding tools project-specific guidance.

## Identity

Project: `botcharter` (BotCharter; CLI: `botctl`)

Purpose: create a universal skeleton/control layer for Telegram bot structure management: specs, graphs, validators, templates, ADRs, and audit workflow.

This is not a runtime bot repository.

## Start here

Read in order:

1. `CONTEXT.md`
2. `README.md`
3. `docs/adr/0001-separate-control-layer-project.md`
4. `docs/adr/0002-specs-first-bot-management.md`
5. `docs/adr/0003-machine-readable-graphs.md`
6. `docs/adr/0004-runtime-bots-stay-independent.md`
7. `.ai_context/handoff.md`

## Working model

The project uses a specs-first model.

Runtime bot code should be changed only in runtime bot repositories. This repository defines how to understand, audit, and validate those bots.

## Main specs

- `specs/FLOWS.yaml`
- `specs/EVENTS.yaml`
- `specs/UI_GRAPH.yaml`
- `specs/STORAGE.yaml`
- `specs/DEPENDENCIES.yaml`
- `specs/CONTRACTS.yaml`

Keep specs concise and machine-readable.

## Reference bots

External runtime bots may be inspected only as explicitly approved read-only fixtures. Do not store machine-specific paths, copied proprietary source, secrets, databases, logs, or production data in this repository. Public examples must be synthetic or explicitly licensed and sanitized.

## Safety rules

Do not write tokens, `.env`, production DBs, raw user data, logs with PII, Chrome Web Store credentials, or concrete deployment files into this repository.

Do not mix product events with technical transport details. Technical implementation facts belong in logs/diagnostics, not product analytics specs, unless explicitly modeled as system events.

## Expected deliverables

Good contributions include:

- validator CLI prototype;
- YAML schema definitions;
- templates for new bot projects;
- sanitized examples imported from the reference bot;
- graph visualizer/exporter;
- ADRs for structural decisions;
- contract test templates.

## Validation ideas

A useful validator should check:

- button callback data has a handler;
- callback handlers appear in UI graph or are explicitly internal;
- emitted event names exist in `EVENTS.yaml`;
- DB tables used by code exist in `STORAGE.yaml`;
- external API calls map to `DEPENDENCIES.yaml`;
- each flow lists contract tests;
- runtime tests include the required contracts.

## Git

Keep git clean. Make small commits with direct messages. Do not touch unrelated repositories unless the task explicitly asks for cross-project audit.


## Documentation maintenance

Use `docs/DOCUMENTATION_RULES.md` before editing `CONTEXT.md`, ADRs or specs. Use `templates/CONTEXT.template.md` and `templates/ADR.template.md` for new documents.
