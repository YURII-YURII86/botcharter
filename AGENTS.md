# AGENTS.md

## Project identity

This repository is `botcharter` (product name: BotCharter; CLI: `botctl`).

It is a separate control/spec/tooling project for building a standardized, machine-readable management layer for Telegram bots.

It is **not** a runtime Telegram bot.

## Reference runtime bots

External runtime bots may be used only as read-only development fixtures. Never record machine-specific paths in tracked public files. Do not move runtime code, tokens, databases, logs, user data, or deployment config into this project.

## Required reading order

Before meaningful work, read:

1. `CONTEXT.md`
2. `README.md`
3. `docs/DOCUMENTATION_RULES.md`
4. `docs/adr/*.md`
5. relevant files in `specs/`
6. `.ai_context/handoff.md`

## Core workflow

Use a specs-first workflow:

1. Identify the bot concern: flow, UI, event, storage, dependency, or contract.
2. Update the relevant spec in `specs/`.
3. Add or update ADR if the decision changes structure or long-term rules.
4. Add tooling/templates/examples if needed.
5. Commit changes with a clear message.

Do not start by editing a runtime bot. Runtime bots are audited from this project, not mixed into it.

## Source of truth files

```text
CONTEXT.md                  why this project exists and how to compare with the reference bot
README.md                   project overview
specs/FLOWS.yaml            bot flows and entrypoints
specs/EVENTS.yaml           analytics event registry
specs/UI_GRAPH.yaml         screens, buttons, transitions
specs/STORAGE.yaml          tables, ownership, TTL, PII
specs/DEPENDENCIES.yaml     external dependencies, risks, guards
specs/CONTRACTS.yaml        required checks
.ai_context/handoff.md      current operational state
```

## Hard boundaries

Never store here:

- Telegram bot tokens;
- `.env` files;
- production SQLite databases;
- user exports;
- raw logs with personal data;
- Chrome Web Store credentials;
- runtime deployment scripts for a concrete bot unless explicitly templated and sanitized.

## What belongs here

Allowed:

- specs;
- ADRs;
- validators/checkers;
- generic templates;
- sanitized examples;
- graph definitions;
- documentation;
- machine-readable schemas.

## What does not belong here

Not allowed unless explicitly requested:

- concrete bot handlers copied from runtime projects;
- production DB files;
- bot-specific secrets;
- one-off fixes for a runtime bot;
- generated build artifacts from runtime bots.

## Reference bot comparison rules

When comparing this project to an external runtime bot:

- `specs/FLOWS.yaml` ↔ runtime handlers/services/tests;
- `specs/UI_GRAPH.yaml` ↔ inline/reply keyboards and callback handlers;
- `specs/EVENTS.yaml` ↔ `record_behavior_event` / behavior analytics;
- `specs/STORAGE.yaml` ↔ `CREATE TABLE`, `_ensure_columns`, writes and cleanup;
- `specs/DEPENDENCIES.yaml` ↔ Telegram API, media hosts, network/proxy dependencies;
- `specs/CONTRACTS.yaml` ↔ tests.

Production truth must come from the runtime project's explicitly approved source, never from copied local artifacts.

## Commit discipline

Use git for meaningful changes. Keep commits scoped:

- specs update;
- ADR update;
- tool implementation;
- example import;
- docs update.

Do not commit unrelated runtime bot changes from another repository.

## Current first milestone

Build a validator that can inspect a bot repository and report:

- callbacks without handlers;
- handlers missing from UI graph;
- emitted events missing from `EVENTS.yaml`;
- tables missing from `STORAGE.yaml`;
- external calls missing from `DEPENDENCIES.yaml`;
- flows missing contract tests;
- technical transport events mixed into product analytics.


## Documentation maintenance

Use `docs/DOCUMENTATION_RULES.md` before editing `CONTEXT.md`, ADRs or specs. Use `templates/CONTEXT.template.md` and `templates/ADR.template.md` for new documents.
