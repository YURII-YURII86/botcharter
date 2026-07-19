# ADR 0009: Require explicit confirmation for HTTP health probes

## Status

Accepted

## Context

A live process and fresh heartbeat do not prove that a bot's public health endpoint is reachable. Even a read-only network request can create access-log records or contact the wrong host, so it must not happen automatically.

## Decision

Add a separate `botctl probe-http` command. It performs one bounded HTTP `HEAD` request only after `--confirm-network` is supplied. Non-local targets must use HTTPS. Plain HTTP is permitted only for localhost tests with a second `--allow-insecure-localhost` flag.

Reject credentials, query strings, and fragments in URLs. Do not add authorization, cookies, tokens, or custom headers. Do not follow redirects and do not read the response body. Keep timeout between one and thirty seconds.

The control-layer test suite contacts only a temporary localhost server. It does not probe a real bot or production endpoint.

## Consequences

Positive:

- endpoint reachability can be checked with a narrow, visible network action;
- accidental network access is blocked by default;
- redirects and URL-carried secrets cannot silently widen scope.

Negative:

- some endpoints do not implement `HEAD` and will report failure;
- the request can still appear in the target access log;
- this does not validate Telegram delivery or business flows.

## Applies to

- `specs/FLOWS.yaml`
- `specs/CONTRACTS.yaml`
- `specs/DEPENDENCIES.yaml`
- `schemas/http-probe.schema.json`
- `tools/botctl/http_probe.py`
- `tools/smoke_http_probe.py`

## Supersedes / superseded by

- Supersedes: none
- Superseded by: none
