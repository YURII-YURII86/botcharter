# ADR 0003: Represent bot structure as machine-readable graphs

## Status

Accepted

## Context

A Telegram bot is a graph:

- users move between screens;
- buttons map to callbacks;
- callbacks trigger handlers;
- handlers call services;
- services read/write tables;
- external APIs can fail;
- events are emitted for analytics.

Plain prose documentation helps humans but cannot reliably detect missing handlers, dead buttons, unregistered events, or unsafe dependency changes.

## Decision

Represent key bot structure as machine-readable specs:

- `UI_GRAPH.yaml` for screens, buttons, and transitions;
- `FLOWS.yaml` for end-to-end scenarios;
- `EVENTS.yaml` for analytics events;
- `STORAGE.yaml` for tables and data ownership;
- `DEPENDENCIES.yaml` for external APIs and risk guards;
- `CONTRACTS.yaml` for required checks.

## Consequences

Positive:

- automated validators can compare specs with code;
- dead UI paths can be detected;
- event drift can be detected;
- risk review becomes repeatable;
- generated reports can visualize the system.

Negative:

- specs need schemas and linting;
- incomplete specs can give false confidence;
- runtime introspection may still be required for dynamic handlers.

## Future validator checks

- every callback in keyboards has a handler;
- every handler callback is represented in UI graph or explicitly internal;
- every emitted event exists in `EVENTS.yaml`;
- every table used by services exists in `STORAGE.yaml`;
- every external API call maps to a dependency and failure guard;
- every flow lists contract tests.
