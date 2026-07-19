# ADR 0014: Public artifacts must be synthetic and history-clean

## Status

Accepted

## Context

A public-alpha snapshot passed path and secret checks but still exposed indirect metadata: private project names, architecture fingerprints, closed-audit counts, and a local computer name in superseded commit metadata. These details were not credentials, but they were not required for the public product and could reveal private development context.

## Decision

Public specifications, profiles, examples, benchmarks, documentation, Git history, tags, and distributions must be generated from fictional fixtures or explicitly licensed public sources. Renaming a private-derived artifact is not sufficient.

Release checks must cover sensitive filenames, common credential patterns, local-host email addresses, machine paths, and explicit fictional labeling of bundled profiles. Before publication, inspect the complete public Git history and every release archive. Public commits must use the maintainer's GitHub noreply address.

If indirect disclosure is discovered, make the repository private immediately. Reopening requires a new clean repository history and freshly built artifacts; rewriting the branch alone is insufficient because superseded commit objects may remain addressable.

## Consequences

Positive:

- public users receive reproducible examples without private context;
- product capabilities remain demonstrable without exposing internal project structure;
- release review covers metadata and history, not only current files.

Negative:

- private validation results cannot be copied into public documentation;
- synthetic fixtures require separate maintenance;
- an exposed repository may need to be replaced rather than merely force-pushed.

## Applies to

- `profiles/`
- `examples/`
- `specs/`
- `docs/`
- `tools/release_check.py`
- `tools/inspect_distribution.py`
- public Git repositories and release assets

## Supersedes / superseded by

- Tightens the sanitization requirements in ADR 0012.
- Superseded by: none
