# ADR 0012: Publish as a narrow public alpha, not an industry standard

## Status

Accepted

## Context

The control layer has a substantial implementation and synthetic safety coverage, but it has not yet been validated by independent users or benchmarked across a public corpus. Continuing to add features would not prove product value.

The repository also originated as a local project and contained machine-specific reference paths, Russian-only onboarding, and no open-source policy files.

## Decision

Prepare version `0.8.0a1` as a public-alpha candidate under the MIT License. Position it as an architecture control plane, drift auditor, and safety gate for Telegram bots maintained with AI coding agents.

English becomes the primary public README with a Russian entrypoint. Add Security, Contributing, Changelog, public-alpha guide, release checklist, a synthetic existing-service example, and a reproducible demo that uses no network or private repository.

Run CI on Python 3.11, 3.12, and 3.13. Add a release hygiene check for machine-specific paths and required public files. Building artifacts is allowed locally; creating a public repository, pushing, tagging, or publishing to TestPyPI/PyPI requires separate explicit owner approval.

Do not describe the alpha as a world standard. The next proof milestone is an independent public benchmark with injected drift cases and measured detection quality.

## Consequences

Positive:

- external users can understand and reproduce the value without private context;
- product claims match available evidence;
- security and contribution boundaries are explicit;
- the team can gather independent validation before expanding runtime capabilities.

Negative:

- local development documentation must stay sanitized;
- package URLs cannot be finalized until a public repository exists;
- alpha status may reduce adoption but prevents misleading stability claims.

## Applies to

- `README.md`
- `README.ru.md`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- `docs/PUBLIC_ALPHA.md`
- `docs/RELEASE_CHECKLIST.md`
- `examples/existing-service/`
- `tools/demo_public_alpha.py`
- `tools/release_check.py`
- `.github/workflows/ci.yml`
- `pyproject.toml`

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
