# ADR 0006: Audit runtime bot source without mutating the target project

## Status

Accepted

## Context

The original project milestone requires comparing bot runtime code with FLOWS, UI, EVENTS, STORAGE, DEPENDENCIES, and CONTRACTS specs. Running or importing a production bot can initialize databases, contact Telegram, read secrets, or start background work.

## Decision

Implement `botctl audit-runtime` as static source inspection only. It reads allowlisted source and test files, skips unsafe paths and runtime data, does not import target modules, does not execute target code, does not contact networks, and does not write into the target project.

The command reports seven drift classes: callback coverage, UI handler coverage, event registry drift, storage registry drift, dependency drift, flow contract-test drift, and technical transport events mixed into product analytics.

The smoke contract hashes the safe target tree before and after the audit and fails if it changes.

## Consequences

Positive:

- production bots can be audited without service or data risk;
- reports are deterministic and suitable for CI;
- missing architecture declarations become explicit.

Negative:

- dynamic registrations and generated SQL may require explicit exceptions;
- static heuristics can produce warnings that need human review;
- live runtime truth remains outside this milestone.

## Alternatives considered

- Import target Python modules: rejected because imports may have side effects.
- Connect to the production database or Telegram API: rejected because this audit is source-only.
- Automatically repair specs or runtime code: rejected because audit and apply must remain separate.

## Applies to

- specs:
  - `specs/FLOWS.yaml`
  - `specs/EVENTS.yaml`
  - `specs/UI_GRAPH.yaml`
  - `specs/STORAGE.yaml`
  - `specs/DEPENDENCIES.yaml`
  - `specs/CONTRACTS.yaml`
- tools:
  - `tools/botctl/audit.py`
  - `tools/botctl/cli.py`
  - `tools/smoke_runtime_audit.py`
- runtime/reference projects:
  - read-only source inspection only

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
