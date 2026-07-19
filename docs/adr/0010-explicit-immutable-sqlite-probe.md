# ADR 0010: Open SQLite only as explicit immutable read-only input

## Status

Accepted

## Context

Source audit can describe storage and a process probe can show liveness, but neither detects a structurally damaged SQLite file. Opening a production database carelessly can create journal sidecars, lock writers, or expose personal data.

## Decision

Add `botctl probe-sqlite` with an explicit database path and mandatory `--confirm-database-read`. Accept only regular, non-symlink `.db`, `.sqlite`, or `.sqlite3` files.

Open SQLite through a URI with `mode=ro&immutable=1`, enable `PRAGMA query_only=ON`, and execute only the built-in fixed `PRAGMA quick_check(1)`. Do not accept SQL from the caller. Do not read user rows or output schema and table names. Compare file metadata before and after and fail if it changes.

Tests use only a temporary generated database. No runtime bot database is opened by the control-layer test suite.

## Consequences

Positive:

- obvious SQLite corruption can be detected without writes or application imports;
- personal rows and schema details stay out of reports;
- explicit confirmation prevents accidental database access.

Negative:

- `quick_check(1)` is deliberately narrower than a full forensic audit;
- immutable mode assumes the supplied file is not changing during the probe;
- this does not validate business-level data correctness.

## Applies to

- `specs/FLOWS.yaml`
- `specs/CONTRACTS.yaml`
- `specs/DEPENDENCIES.yaml`
- `schemas/sqlite-probe.schema.json`
- `tools/botctl/sqlite_probe.py`
- `tools/smoke_sqlite_probe.py`

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
