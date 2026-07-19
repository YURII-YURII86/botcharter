# Public alpha guide

This guide demonstrates the intended use of `botctl` without a private bot, production token, network request, or runtime database.

## Scenario

A team has an existing Python service and wants an AI coding agent to turn part of it into a Telegram bot. The team wants architecture and safety controls before the agent creates handlers or storage.

## 1. Install the local checkout

```bash
python -m venv .venv
.venv/bin/python -m pip install .
```

## 2. Preview adoption

```bash
.venv/bin/botctl adopt --project /path/to/existing-service
```

This command is read-only. It lists the planned `.botctl/` files.

## 3. Confirm adoption

```bash
.venv/bin/botctl adopt --project /path/to/existing-service --confirm
```

Only a new `.botctl/` directory is created. Existing source and agent instruction files remain unchanged.

## 4. Define intent before code

Complete the six local specs:

```text
.botctl/specs/FLOWS.yaml
.botctl/specs/UI_GRAPH.yaml
.botctl/specs/EVENTS.yaml
.botctl/specs/STORAGE.yaml
.botctl/specs/DEPENDENCIES.yaml
.botctl/specs/CONTRACTS.yaml
```

Review the draft artifacts under `.botctl/design/`. Drafts are evidence and questions, not production approval.

## 5. Verify the control layer

```bash
botctl verify --project /path/to/existing-service
botctl design status --project /path/to/existing-service --format json
botctl design gate --project /path/to/existing-service --format json
```

The design gate remains blocked until required artifacts are reviewed and a ChangePlan is approved. Even then, public-alpha `runtime_apply_allowed` remains false.

## 6. Implement with an AI coding agent

Point the agent to `.botctl/AGENT_INSTRUCTIONS.md`. The agent should update specs and ChangePlan before runtime code. Code generation and review happen in the target project, not in this control-layer repository.

## 7. Audit implementation drift

```bash
botctl audit-runtime \
  --project /path/to/existing-service \
  --specs /path/to/existing-service/.botctl/specs \
  --format json
```

The audit parses allowlisted Python source and tests. It does not import target modules, read runtime databases, or contact Telegram.

## Run the included demo

```bash
python tools/demo_public_alpha.py
```

The script copies `examples/existing-service` into a temporary directory and verifies:

- preview writes nothing;
- confirmed adoption changes only `.botctl/`;
- all six specs and draft design artifacts exist;
- verification passes;
- repeat adoption is idempotent;
- source audit completes without private infrastructure.

## Alpha limitations

- Python source audit uses static heuristics and can miss dynamic registrations.
- The included profiles are examples, not universal adapters.
- There is no production code generation, deployment, rollback executor, Telegram API probe, or service manager integration.
- Independent benchmark results are not available yet.
- Human-readable validation and generated design text are currently Russian-first; use JSON output for language-neutral automation.
