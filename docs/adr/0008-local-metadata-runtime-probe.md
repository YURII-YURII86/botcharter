# ADR 0008: Limit the first runtime probe to local metadata

## Status

Accepted

## Context

Static source audit cannot show whether a bot process is currently alive or whether its heartbeat is fresh. A network or database probe would require secrets, production access, and a wider safety review.

## Decision

Add `botctl probe-runtime` with a deliberately narrow scope. It accepts an explicit PID and/or heartbeat file path. It checks process existence using POSIX signal zero, which does not deliver a signal, and checks heartbeat freshness using file metadata only.

The probe does not discover processes automatically, read file contents, follow heartbeat symlinks, read databases or logs, contact Telegram or other networks, write runtime files, restart services, or send a mutating signal.

Network, database, service-manager, container, and remote-host probes require a separate ADR and explicit authorization.

## Consequences

Positive:

- operators can distinguish a dead process or stale heartbeat from source drift;
- the check works without tokens or database access;
- output is machine-readable and safe for local monitoring.

Negative:

- process existence does not prove that Telegram updates are handled correctly;
- the caller must know the PID or heartbeat path;
- a fresh heartbeat only proves that something updated the file.

## Applies to

- `specs/FLOWS.yaml`
- `specs/CONTRACTS.yaml`
- `specs/DEPENDENCIES.yaml`
- `schemas/runtime-probe.schema.json`
- `tools/botctl/runtime_probe.py`
- `tools/smoke_runtime_probe.py`

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
