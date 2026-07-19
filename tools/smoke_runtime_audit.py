#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

from botctl.audit import safe_source_hash


def run(command: list[str], cwd: Path, *, ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if ok and result.returncode != 0:
        print(result.stdout, result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def git_status(project: Path) -> str:
    result = subprocess.run(["git", "status", "--porcelain=v1", "-uall"], cwd=project, text=True, capture_output=True)
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tmp = root / ".tmp" / "runtime_audit_smoke"
    shutil.rmtree(tmp, ignore_errors=True)
    bot = tmp / "bad_bot"
    specs = tmp / "specs"
    (bot / "src").mkdir(parents=True)
    (bot / "tests").mkdir()
    (bot / "src" / "bot.py").write_text(
        "from aiogram import Router, F\n"
        "from aiogram.types import InlineKeyboardButton\n"
        "import aiohttp\n"
        "router = Router()\n"
        "button_ok = InlineKeyboardButton(text='OK', callback_data='ok:run')\n"
        "button_bad = InlineKeyboardButton(text='BAD', callback_data='orphan:run')\n"
        "@router.callback_query(F.data.startswith('ok:'))\n"
        "async def handle_ok(query):\n    await query.answer('ok')\n"
        "async def work(store, user_id):\n"
        "    store.record_behavior_event(user_id, 'product_ok', {})\n"
        "    store.record_behavior_event(user_id, 'network_debug', {})\n"
        "    async with aiohttp.ClientSession() as session:\n        await session.get('https://example.invalid')\n"
        "SCHEMA = '''CREATE TABLE IF NOT EXISTS known_table(id INTEGER); CREATE TABLE secret_table(id INTEGER);'''\n",
        encoding="utf-8",
    )
    (bot / "tests" / "test_ok.py").write_text("def test_unrelated():\n    assert True\n", encoding="utf-8")
    dump(specs / "EVENTS.yaml", {"events": {"product_ok": {}}})
    dump(specs / "STORAGE.yaml", {"tables": {"known_table": {}}})
    dump(specs / "DEPENDENCIES.yaml", {"dependencies": {"telegram_bot_api": {}}})
    dump(specs / "UI_GRAPH.yaml", {"screens": {"main": {"buttons": [{"id": "other"}]}}})
    dump(specs / "FLOWS.yaml", {"flows": {"demo": {"contract_tests": ["expected_contract"]}}})
    dump(specs / "CONTRACTS.yaml", {"contracts": {}})

    before = safe_source_hash(bot)
    command = [sys.executable, str(root / "tools" / "botctl.py"), "audit-runtime", "--project", str(bot), "--specs", str(specs), "--format", "json"]
    result = run(command, root, ok=False)
    payload = json.loads(result.stdout)
    after = safe_source_hash(bot)
    schema = json.loads((root / "schemas" / "runtime-audit.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    codes = {item["code"] for item in payload["issues"]}
    required = {
        "callback.without_handler", "handler.missing_from_ui_graph", "event.unregistered",
        "table.unregistered", "dependency.unregistered", "flow.contract_test_not_found",
        "event.technical_in_product_analytics",
    }
    fixture_ok = result.returncode != 0 and before == after and required.issubset(codes)
    print(f"runtime_audit_fixture_ok={fixture_ok}")
    print(f"runtime_audit_fixture_read_only_ok={before == after}")
    if not fixture_ok:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    if not args.reference:
        print("runtime_audit_smoke=passed")
        return 0

    reference = Path(args.reference).expanduser().resolve()
    reference_before = safe_source_hash(reference)
    reference_git_before = git_status(reference)
    reference_result = run([sys.executable, str(root / "tools" / "botctl.py"), "audit-runtime", "--project", str(reference), "--format", "json"], root, ok=False)
    reference_payload = json.loads(reference_result.stdout)
    reference_after = safe_source_hash(reference)
    reference_git_after = git_status(reference)
    jsonschema.Draft202012Validator(schema).validate(reference_payload)
    reference_ok = (
        reference_before == reference_after
        and reference_git_before == reference_git_after
        and reference_payload.get("read_only") is True
        and reference_payload.get("summary", {}).get("status") == "passed"
        and reference_payload.get("summary", {}).get("errors") == 0
        and reference_payload.get("summary", {}).get("warnings") == 0
    )
    print(f"runtime_audit_reference_read_only_ok={reference_ok}")
    print(f"runtime_audit_reference_git_status_unchanged={reference_git_before == reference_git_after}")
    print(f"runtime_audit_reference_status={reference_payload['summary']['status']}")
    print(f"runtime_audit_reference_errors={reference_payload['summary']['errors']}")
    print(f"runtime_audit_reference_warnings={reference_payload['summary']['warnings']}")
    print("runtime_audit_smoke=passed" if reference_ok else "runtime_audit_smoke=failed")
    return 0 if reference_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
