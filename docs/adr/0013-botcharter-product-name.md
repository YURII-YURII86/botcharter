# ADR 0013: Use BotCharter as the public product name

## Status

Accepted

## Context

The original working name `bot-architecture-control-layer` accurately described the repository but was too long and generic for a public product. The CLI name `botctl` is short and already used throughout adopted projects and documentation.

## Decision

Use **BotCharter** as the public product name and `botcharter` as the Python distribution and GitHub repository name. Keep `botctl` as the installed CLI and `botctl` as the Python import package to preserve the existing command and internal API surface.

Use the primary tagline: **Architecture control and safety gates for AI-built bots.** The initial implementation remains specialized for Telegram bots; the brand does not promise support for every bot platform in the public alpha.

The public GitHub location is `YURII-YURII86/botcharter`. Do not include the maintainer's personal email in package metadata; GitHub provides the public contact surface and private vulnerability reporting should be configured there.

## Consequences

Positive:

- the product has a short, memorable, extensible name;
- CLI compatibility is preserved;
- distribution, repository, and documentation use one brand.

Negative:

- the distribution name differs from the import package and command;
- existing internal documents may retain the old name as historical context;
- trademark clearance is still required before a large commercial launch.

## Applies to

- `pyproject.toml`
- `README.md`
- `README.ru.md`
- `LICENSE`
- `CONTEXT.md`
- CLI help and release checks

## Supersedes / superseded by

- Supersedes the public naming portion of ADR 0001; architectural separation remains unchanged.
- Superseded by: none
