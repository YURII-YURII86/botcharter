# ADR 0011: Adopt an existing project through one guarded command

## Status

Accepted

## Context

The control layer is reusable, but a new user currently has to discover and run bootstrap, design initialization, snapshot, verification, and spec setup separately. This makes correct AI-agent onboarding easy to skip.

## Decision

Add `botctl adopt --project <path>`. Without `--confirm`, it produces a read-only adoption plan. With explicit confirmation, it creates a new `.botctl/` control directory containing the project passport, desired and observed graphs, six local bot specs, draft design artifacts, generated agent context, and a dedicated AI-agent instruction file.

Do not edit runtime source or an existing root `AGENTS.md`. Never overwrite a non-empty `.botctl/`. Verify the created control layer and remove the entire newly created directory if any adoption step fails. A second run reports that the project is already adopted and writes nothing.

Local specs live in `.botctl/specs/` so an existing project's unrelated root `specs/` directory is not repurposed.

## Consequences

Positive:

- one guarded command prepares a project for specs-first AI-agent work;
- runtime code and existing agent instructions remain untouched;
- every adopted project starts with the same machine-readable control surface;
- preview, verification, and rollback reduce adoption risk.

Negative:

- generated design artifacts are drafts and still require human review;
- users must link `.botctl/AGENT_INSTRUCTIONS.md` from their agent configuration if their tool does not discover it automatically;
- adoption describes the existing project but does not generate a runtime bot.

## Applies to

- `specs/FLOWS.yaml`
- `specs/CONTRACTS.yaml`
- `specs/DEPENDENCIES.yaml`
- `schemas/adoption-result.schema.json`
- `tools/botctl/adopt.py`
- `tools/botctl/cli.py`
- `tools/smoke_adopt.py`

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
