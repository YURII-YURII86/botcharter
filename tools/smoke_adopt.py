#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema


def hash_tree(project: Path, *, exclude_control: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if exclude_control and ".botctl" in path.parts:
            continue
        if path.is_file():
            digest.update(str(path.relative_to(project)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=root, text=True, capture_output=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    fixture = root / ".tmp" / "adopt_smoke" / "existing_project"
    shutil.rmtree(fixture.parent, ignore_errors=True)
    (fixture / "src").mkdir(parents=True)
    (fixture / "src" / "service.py").write_text("def existing_service():\n    return 'keep-me'\n", encoding="utf-8")
    (fixture / "AGENTS.md").write_text("EXISTING AGENT RULES MUST STAY UNCHANGED\n", encoding="utf-8")
    command = [sys.executable, str(root / "tools" / "botctl.py"), "adopt", "--project", str(fixture), "--format", "json"]
    before = hash_tree(fixture)
    preview = run(command, root)
    preview_payload = json.loads(preview.stdout)
    preview_ok = preview.returncode == 0 and before == hash_tree(fixture) and preview_payload["status"] == "ready_to_adopt" and preview_payload["read_only"] is True
    outside_before = hash_tree(fixture, exclude_control=True)
    confirmed = run(command + ["--confirm"], root)
    confirmed_payload = json.loads(confirmed.stdout)
    schema = json.loads((root / "schemas" / "adoption-result.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(confirmed_payload)
    six_specs = len(list((fixture / ".botctl" / "specs").glob("*.yaml"))) == 6
    adopted_ok = (
        confirmed.returncode == 0
        and confirmed_payload["status"] == "adopted"
        and confirmed_payload["verify_summary"]["errors"] == 0
        and six_specs
        and (fixture / ".botctl" / "design" / "manifest.yaml").is_file()
        and (fixture / ".botctl" / "AGENT_INSTRUCTIONS.md").is_file()
        and outside_before == hash_tree(fixture, exclude_control=True)
    )
    adopted_hash = hash_tree(fixture)
    repeated = run(command + ["--confirm"], root)
    repeated_payload = json.loads(repeated.stdout)
    repeat_ok = repeated.returncode == 0 and repeated_payload["status"] == "already_adopted" and adopted_hash == hash_tree(fixture)
    partial = fixture.parent / "partial_project"
    (partial / ".botctl").mkdir(parents=True)
    marker = partial / ".botctl" / "user-file.txt"
    marker.write_text("never overwrite", encoding="utf-8")
    blocked = run([sys.executable, str(root / "tools" / "botctl.py"), "adopt", "--project", str(partial), "--confirm", "--format", "json"], root)
    blocked_ok = blocked.returncode != 0 and marker.read_text(encoding="utf-8") == "never overwrite"
    print(f"adopt_preview_read_only_ok={preview_ok}")
    print(f"adopt_confirmed_scaffold_ok={adopted_ok}")
    print(f"adopt_repeat_idempotent_ok={repeat_ok}")
    print(f"adopt_existing_control_guard_ok={blocked_ok}")
    passed = preview_ok and adopted_ok and repeat_ok and blocked_ok
    print("adopt_smoke=passed" if passed else "adopt_smoke=failed")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
