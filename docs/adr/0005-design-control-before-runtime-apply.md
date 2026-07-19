# ADR 0005: Require a confirmed design package and approved ChangePlan before runtime work

## Status

Accepted

## Context

Schema-valid bot descriptions can still be incomplete, contradictory, or based on accidental legacy code. A menu proposal alone does not explain product purpose, roles, journeys, responses, state, impact, tests, or the exact scope and rollback of a change.

The control layer needs a machine-readable gate that future agents cannot bypass by changing one status field manually.

## Decision

Introduce `.botctl/design/` as a separate authored design-control package containing product, role, journey, menu, response, state, impact, test, manifest, and ChangePlan artifacts.

Each core artifact must pass schema and semantic validation, then move through `draft → reviewed → confirmed`. A design ChangePlan must move through `draft → reviewed → approved`, reference existing confirmed design ids, include verification and rollback, and record the approving actor.

`botctl design gate` is the consolidated decision surface. It may set `implementation_planning_allowed=true` only when the design package is ready and at least one selected ChangePlan is valid and approved. In this milestone `runtime_apply_allowed` is always `false`.

## Consequences

Positive:

- agents cannot treat extracted legacy code or placeholders as confirmed design;
- affected roles, journeys, menus, callbacks, handlers, responses, states, and tests are checked against source-of-truth artifacts;
- approval history, verification, rollback, and blockers are machine-readable;
- design work remains separated from runtime mutation.

Negative:

- production-grade changes require more authored artifacts and review steps;
- semantic checks enforce minimum completeness, not expert product quality;
- future runtime/build tooling needs a separate ADR and safety model.

## Alternatives considered

- One monolithic design YAML: rejected because review, ownership, and status would be too coarse.
- Treat working legacy code as confirmed design: rejected because existing behavior may encode accidental UX or hidden risk.
- Let approved ChangePlan enable runtime apply immediately: rejected because runtime probe, apply, verification, and rollback engines are not implemented.

## Applies to

- specs:
  - `schemas/design-*.schema.json`
  - `schemas/*-model.schema.json`
  - `schemas/change-plan-design.schema.json`
- tools:
  - `tools/botctl/design.py`
  - `tools/botctl/cli.py`
  - `tools/smoke_botctl_v0.py`
- runtime/reference projects:
  - optional local `.botctl/design/` package; no runtime dependency or mutation

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
