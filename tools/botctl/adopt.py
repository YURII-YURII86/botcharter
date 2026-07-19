from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import dump_yaml


LOCAL_SPEC_FILES: dict[str, dict[str, Any]] = {
    "FLOWS.yaml": {"version": "0.1.0", "purpose": "Project-local bot flows; replace drafts before runtime implementation.", "flows": {}},
    "EVENTS.yaml": {"version": "0.1.0", "events": {}},
    "UI_GRAPH.yaml": {"version": "0.1.0", "callback_namespaces": {}, "screens": {}},
    "STORAGE.yaml": {"version": "0.1.0", "tables": {}},
    "DEPENDENCIES.yaml": {"version": "0.1.0", "dependencies": {}},
    "CONTRACTS.yaml": {"version": "0.1.0", "contracts": {}},
}


def planned_adoption_paths() -> list[str]:
    paths = [
        ".botctl/project.yaml",
        ".botctl/graph.desired.yaml",
        ".botctl/AGENT_INSTRUCTIONS.md",
        ".botctl/design/",
        ".botctl/change_plans/",
    ]
    paths.extend(f".botctl/specs/{name}" for name in LOCAL_SPEC_FILES)
    paths.extend([
        ".botctl/graph.observed.json",
        ".botctl/drift.report.json",
        ".botctl/architecture.brief.json",
        ".botctl/agent_context.json",
        ".botctl/agent_context.md",
    ])
    return paths


def agent_instructions() -> str:
    return """# Botctl instructions for AI agents

This project uses a specs-first control layer in `.botctl/`.

Before creating or changing Telegram bot runtime code:

1. Read `.botctl/project.yaml` and `.botctl/agent_context.md`.
2. Update the relevant file in `.botctl/specs/`.
3. Review the draft artifacts in `.botctl/design/` with the human owner.
4. Create and approve a design ChangePlan.
5. Run `botctl verify`, `botctl design status`, and `botctl design gate`.
6. Do not treat `runtime_apply_allowed: false` as permission to modify production.

Never read or print tokens, `.env`, production databases, personal logs, or user exports. Never restart or deploy a bot without a separate explicit instruction and rollback plan.

Useful commands:

```bash
botctl inspect --project . --format agent
botctl verify --project .
botctl design status --project . --format json
botctl design gate --project . --format json
botctl audit-runtime --project . --specs .botctl/specs --format json
```
"""


def write_adoption_support(control: Path) -> list[Path]:
    specs = control / "specs"
    specs.mkdir()
    written: list[Path] = []
    for name, payload in LOCAL_SPEC_FILES.items():
        path = specs / name
        dump_yaml(path, payload)
        written.append(path)
    instructions = control / "AGENT_INSTRUCTIONS.md"
    instructions.write_text(agent_instructions(), encoding="utf-8")
    written.append(instructions)
    (control / "change_plans").mkdir()
    return written
