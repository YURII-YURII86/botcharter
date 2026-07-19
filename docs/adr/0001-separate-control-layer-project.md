# ADR 0001: Keep bot architecture control layer as a separate project

## Status

Accepted

## Context

Runtime bot projects contain handlers, services, storage, deployment scripts, bot tokens, production logs, and product-specific behavior. Mixing architectural standards and validators into a live bot repository makes it harder to tell what is product code and what is meta/tooling.

The current need is broader than one bot: we need a standardized way to understand, audit, and safely change many Telegram bots.

## Decision

Create `bot-architecture-control-layer` as a separate project outside runtime bot repositories.

This repository owns specs, templates, validators, ADRs, and examples. Runtime bots remain separate and can be inspected by tools from this project.

## Consequences

Positive:

- architecture tooling can evolve without touching production bot runtime;
- multiple bots can reuse the same standard;
- secrets and production data stay out of the control project;
- agents can reason from specs before editing bot code.

Negative:

- specs can drift from runtime if validators are not run;
- there is an extra repository/project to maintain;
- examples must avoid copying sensitive production data.

## Rules

- No bot tokens or production databases in this project.
- No concrete bot deployment scripts in this project unless they are generic templates.
- Runtime-specific facts should live in examples or imported snapshots, not in the standard itself.
