# ADR 0002: Specs-first workflow for bot changes

## Status

Accepted

## Context

Telegram bot behavior is often distributed across message handlers, callback handlers, storage methods, keyboard builders, and service helpers. Small changes can silently affect publishing, broadcasts, analytics, channel access, or admin tools.

Ad-hoc edits are fast initially but make future work unsafe.

## Decision

Use a specs-first workflow for meaningful bot changes.

Before changing runtime code, define or update:

- the flow in `FLOWS.yaml`;
- the UI screen/button transition in `UI_GRAPH.yaml`;
- analytics events in `EVENTS.yaml`;
- storage ownership in `STORAGE.yaml`;
- external dependencies/guards in `DEPENDENCIES.yaml`;
- required checks in `CONTRACTS.yaml`.

## Consequences

Positive:

- every change has a visible product/technical contour;
- tests can be generated or validated from specs;
- agents do not need to rediscover architecture from grep every time;
- product events are less likely to be polluted with technical transport details.

Negative:

- small changes take more discipline;
- specs must be kept concise or they become noise;
- validators are required to prevent drift.

## Practical rule

A change is allowed to skip spec updates only if it is a trivial text typo or a purely local refactor with no behavior, storage, UI, or dependency impact.
