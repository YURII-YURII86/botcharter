# ADR 0004: Runtime bots stay independent and are audited from outside

## Status

Accepted

## Context

The control layer should help many bots, but each runtime bot may have its own stack, deployment, database, UI conventions, and product constraints.

Forcing all bots into one monorepo or shared runtime framework would create coupling and migration risk.

## Decision

Runtime bots stay independent. The control layer audits them from outside using specs, adapters, and validators.

A bot may optionally copy templates from this project, but the control layer must not become a required runtime dependency unless explicitly adopted.

## Consequences

Positive:

- existing bots can be audited without rewrites;
- each bot can keep its deployment model;
- validators can be introduced incrementally;
- failed experiments in one bot do not pollute the architecture standard.

Negative:

- validators need adapters for different project layouts;
- some checks may be approximate without runtime integration;
- each bot still needs local project memory and handoff files.

## Integration pattern

For a runtime bot repository:

1. generate or write local specs;
2. run validator from this project against that repo;
3. fix drift or explicitly document exceptions;
4. keep runtime code and control-layer specs in separate commits/projects.
