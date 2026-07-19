# ADR 0007: Portable runtime audit profiles

## Status

Accepted

## Context

Different Telegram bots register callbacks and use storage or external tools in different ways. One shared reference spec cannot accurately describe every bot.

## Decision

Keep reusable, read-only audit profiles under `profiles/<id>/`. Each profile has validated metadata and its own six architecture specs. Dependency specs may map static source signals through `audit_categories`.

Ship `botctl` as an installable Python command. CI runs the synthetic safety audit without requiring access to private runtime repositories.

## Consequences

Positive:

- one tool can audit structurally different bots;
- bot-specific declarations stay outside runtime repositories;
- profiles are schema-checked before use;
- installation and CI do not require running the script from this repository.

Negative:

- a new bot pattern may require a new static adapter category;
- profiles must be maintained when a bot architecture changes;
- static inspection still cannot prove live production behavior.

## Applies to

- `profiles/`
- `schemas/audit-profile.schema.json`
- `tools/botctl/audit.py`
- `tools/botctl/cli.py`
- `pyproject.toml`
- `.github/workflows/ci.yml`

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
