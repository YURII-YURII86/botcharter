# Project context

## Identity

BotCharter is an independent control/spec/tooling project for Telegram bots built or maintained with AI coding agents. The installed CLI command is `botctl`.

It is not a runtime Telegram bot and must never contain production tokens, `.env` files, user exports, production databases, personal logs, or deployment credentials.

## Problem

Bot behavior is usually distributed across handlers, keyboards, state, storage, analytics, external APIs, and tests. AI agents can change those surfaces quickly, but without a machine-readable control layer they can also create silent drift and unsafe production changes.

## Product promise

The public alpha provides:

- specs-first architecture artifacts;
- design review and ChangePlan gates;
- static source/spec drift detection;
- one-command guarded adoption of an existing project;
- explicit, narrow runtime diagnostics;
- agent-readable context and safety rules.

Runtime code generation, deployment, service control, Telegram API access, and production mutation are outside the public alpha.

## Source of truth

```text
README.md                  public product entrypoint
specs/*.yaml               machine-readable control-layer behavior
schemas/*.json             artifact contracts
docs/adr/*.md              long-term decisions
tools/botctl/               CLI implementation
tools/smoke_*.py           safety and regression fixtures
.ai_context/handoff.md      current development handoff
```

## Reference projects

Development may use external runtime bots as read-only fixtures. Their source, secrets, databases, logs, deployment configuration, and absolute local paths must not be copied into this repository.

Public examples must be fictional from inception or based on explicitly licensed public sources. Renaming or lightly sanitizing a private-derived artifact is not sufficient. The reproducible public demo under `examples/` is the release-facing reference.

## Core workflow

1. Adopt or inspect a project.
2. Define flows, UI, events, storage, dependencies, and contracts.
3. Review and confirm design artifacts.
4. Approve a ChangePlan with verification and rollback.
5. Implement outside this control repository.
6. Audit source/spec drift.
7. Use explicit probes only with a named target and required confirmation.

## Release standard

A public release candidate must have:

- no secrets, personal data, or machine-specific paths;
- no private project names, architecture fingerprints, closed-audit results, or local-host commit metadata;
- a clean wheel build and installation;
- passing synthetic smoke tests without private repositories;
- English onboarding and a reproducible demo;
- documented safety boundaries, license, contributing rules, and changelog;
- runtime apply disabled unless a future ADR defines approval, isolation, verification, and rollback.
