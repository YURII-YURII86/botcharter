#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml
import jsonschema

from botctl.discover import discover_ux_evidence
from botctl.validate import validate_graph


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if item.is_file():
            h.update(str(item.relative_to(path)).encode("utf-8"))
            h.update(item.read_bytes())
    return h.hexdigest()


def run(cmd: list[str], cwd: Path, *, expect_ok: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if expect_ok and result.returncode != 0:
        print("COMMAND FAILED:", " ".join(cmd), file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def copy_reference_fixture(reference_bot: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    (target / ".botctl" / "change_plans").mkdir(parents=True)
    shutil.copytree(reference_bot / ".botctl", target / ".botctl", dirs_exist_ok=True)
    for rel in [
        "src/telegram_adapter.py",
        "src/app.py",
        "src/vk_client.py",
        "src/media_pipeline.py",
        "src/store.py",
        "compose.yml",
        "Makefile",
    ]:
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# smoke fixture\n", encoding="utf-8")


def assert_negative_case(control_root: Path, botctl: list[str], reference_bot: Path, tmp_root: Path, case_name: str, expected_code: str, mutate) -> None:
    case_dir = tmp_root / case_name
    copy_reference_fixture(reference_bot, case_dir)
    mutate(case_dir)
    result = run(botctl + ["verify", "--project", str(case_dir), "--format", "json"], cwd=control_root, expect_ok=False)
    ok = result.returncode != 0 and expected_code in result.stdout
    print(f"{case_name}_caught={ok}")
    if not ok:
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Повторяемый smoke test для botctl v0")
    parser.add_argument("--project", required=True, help="Путь к reference bot")
    args = parser.parse_args()

    control_root = Path(__file__).resolve().parents[1]
    reference_bot = Path(args.project).expanduser().resolve()
    botctl = [sys.executable, str(control_root / "tools" / "botctl.py")]
    tmp_root = control_root / ".tmp" / "botctl_v0_smoke"
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)

    print("== syntax ==")
    run([sys.executable, "-m", "py_compile", "tools/botctl.py", *[str(p) for p in sorted((control_root / "tools" / "botctl").glob("*.py"))]], cwd=control_root)

    print("== inspect read-only ==")
    before = tree_hash(reference_bot / ".botctl")
    inspect = run(botctl + ["inspect", "--project", str(reference_bot), "--format", "json"], cwd=control_root)
    after = tree_hash(reference_bot / ".botctl")
    inspect_payload = json.loads(inspect.stdout)
    print("inspect_returncode=0")
    print(f"inspect_read_only_hash_equal={before == after}")
    if before != after or inspect_payload.get("read_only") is not True:
        raise SystemExit(1)

    print("== main commands ==")
    run(botctl + ["snapshot", "--project", str(reference_bot)], cwd=control_root)
    verify = run(botctl + ["verify", "--project", str(reference_bot), "--format", "json"], cwd=control_root)
    diff = run(botctl + ["diff", "--project", str(reference_bot), "--format", "json"], cwd=control_root)
    run(botctl + ["plan", "validate", "--project", str(reference_bot), "--format", "json"], cwd=control_root)
    verify_payload = json.loads(verify.stdout)
    diff_payload = json.loads(diff.stdout)
    print(f"verify_errors={verify_payload['summary']['errors']}")
    print(f"verify_warnings={verify_payload['summary']['warnings']}")
    print(f"diff_in_sync={diff_payload['summary']['in_sync']}")
    print(f"diff_missing_local={diff_payload['summary']['missing_local']}")
    context_path = reference_bot / ".botctl" / "agent_context.json"
    context_payload = json.loads(context_path.read_text(encoding="utf-8"))
    ux = context_payload.get("ux_structure", {})
    print(f"ux_checks_observed={ux.get('checks_observed')}")
    print(f"ux_checks_missing={ux.get('checks_missing')}")
    if verify_payload["summary"]["errors"] != 0 or diff_payload["summary"]["missing_local"] != 0:
        raise SystemExit(1)
    if int(ux.get("checks_observed") or 0) < 8 or int(ux.get("checks_missing") or 0) != 0:
        raise SystemExit(1)
    observed_evidence = ux.get("observed_ux_evidence", {})
    signals = observed_evidence.get("signals", {}) if isinstance(observed_evidence, dict) else {}
    fingerprints = observed_evidence.get("source_fingerprints", {}) if isinstance(observed_evidence, dict) else {}
    structured_ok = bool(fingerprints)
    for signal in signals.values():
        matches = signal.get("matches", []) if isinstance(signal, dict) else []
        if not matches:
            structured_ok = False
            break
        first = matches[0]
        if not all(key in first for key in ["path", "line", "symbol", "snippet", "pattern"]):
            structured_ok = False
            break
        if not signal.get("confidence") or not signal.get("validity") or not signal.get("source_fingerprints"):
            structured_ok = False
            break
    print(f"ux_structured_evidence_ok={structured_ok}")
    if not structured_ok:
        raise SystemExit(1)

    print("== bootstrap hints ==")
    bootstrap_dir = tmp_root / "bootstrap_hints_no_graph"
    if bootstrap_dir.exists():
        shutil.rmtree(bootstrap_dir)
    (bootstrap_dir / "app").mkdir(parents=True)
    (bootstrap_dir / "app" / "main.py").write_text(
        "import logging\n"
        "import os\n"
        "from telegram import InlineKeyboardButton, InlineKeyboardMarkup\n"
        "from telegram.ext import Application, CommandHandler\n"
        "\n"
        "logging.basicConfig(level=logging.INFO)\n"
        "\n"
        "def start_keyboard():\n"
        "    return InlineKeyboardMarkup([[InlineKeyboardButton('Очередь', callback_data='main:queue')]])\n"
        "\n"
        "async def start(update, context):\n"
        "    await update.message.reply_text('Привет. /start готов.', reply_markup=start_keyboard())\n"
        "\n"
        "def build_app():\n"
        "    token = os.getenv('TELEGRAM_BOT_TOKEN')\n"
        "    app = Application.builder().token(token).build()\n"
        "    app.add_handler(CommandHandler('start', start))\n"
        "    return app\n",
        encoding="utf-8",
    )
    bootstrap_inspect = run(botctl + ["inspect", "--project", str(bootstrap_dir), "--format", "agent"], cwd=control_root, expect_ok=False)
    bootstrap_payload = json.loads(bootstrap_inspect.stdout)
    bootstrap_hints = bootstrap_payload.get("bootstrap_hints", {})
    bootstrap_signal_ids = set(bootstrap_hints.get("observed_ux_signal_ids", []))
    bootstrap_modules = bootstrap_hints.get("python_modules", [])
    bootstrap_hints_ok = (
        bootstrap_hints.get("needed") is True
        and any(module.get("path") == "app/main.py" for module in bootstrap_modules)
        and {"command_design", "start_onboarding", "token_env_safety", "webhook_or_polling_model"}.issubset(bootstrap_signal_ids)
    )
    print(f"bootstrap_hints_ok={bootstrap_hints_ok}")
    if not bootstrap_hints_ok:
        print(json.dumps(bootstrap_hints, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)

    bootstrap_preview = run(botctl + ["bootstrap-preview", "--project", str(bootstrap_dir), "--format", "json"], cwd=control_root)
    bootstrap_draft = json.loads(bootstrap_preview.stdout)
    draft_check_ids = {check.get("id") for check in bootstrap_draft.get("ux_structure", {}).get("checks", [])}
    draft_status_by_id = {check.get("id"): check.get("status") for check in bootstrap_draft.get("ux_structure", {}).get("checks", [])}
    draft_paths = {
        evidence.get("path")
        for node in bootstrap_draft.get("nodes", [])
        for evidence in node.get("evidence", []) or []
        if isinstance(evidence, dict)
    }
    draft_issues = validate_graph(bootstrap_draft, bootstrap_dir / ".botctl" / "graph.desired.yaml")
    preview_output = tmp_root / "preview-output" / "bootstrap.graph.desired.yaml"
    run(botctl + ["bootstrap-preview", "--project", str(bootstrap_dir), "--output", str(preview_output)], cwd=control_root)
    output_draft = load_yaml(preview_output)
    output_issues = validate_graph(output_draft, preview_output)
    overwrite_block = run(botctl + ["bootstrap-preview", "--project", str(bootstrap_dir), "--output", str(preview_output)], cwd=control_root, expect_ok=False)
    force_overwrite = run(botctl + ["bootstrap-preview", "--project", str(bootstrap_dir), "--output", str(preview_output), "--force"], cwd=control_root)
    dotbotctl_output = run(
        botctl + ["bootstrap-preview", "--project", str(bootstrap_dir), "--output", str(bootstrap_dir / ".botctl" / "graph.desired.yaml")],
        cwd=control_root,
        expect_ok=False,
    )
    bootstrap_preview_ok = (
        bootstrap_draft.get("kind") == "BotArchitectureGraph"
        and "app/main.py" in draft_paths
        and {"command_design", "start_onboarding", "token_env_safety", "webhook_or_polling_model"}.issubset(draft_check_ids)
        and draft_status_by_id.get("command_design") == "covered"
        and not any(issue.level == "error" for issue in draft_issues)
        and not any(issue.level == "error" for issue in output_issues)
        and preview_output.exists()
        and overwrite_block.returncode != 0
        and force_overwrite.returncode == 0
        and dotbotctl_output.returncode != 0
        and not (bootstrap_dir / ".botctl").exists()
    )
    print(f"bootstrap_preview_ok={bootstrap_preview_ok}")
    print(f"bootstrap_preview_output_ok={preview_output.exists() and not any(issue.level == 'error' for issue in output_issues)}")
    print(f"bootstrap_preview_overwrite_guard_ok={overwrite_block.returncode != 0 and force_overwrite.returncode == 0}")
    print(f"bootstrap_preview_dotbotctl_guard_ok={dotbotctl_output.returncode != 0 and not (bootstrap_dir / '.botctl').exists()}")
    if not bootstrap_preview_ok:
        print(json.dumps(bootstrap_draft, ensure_ascii=False, indent=2), file=sys.stderr)
        print("overwrite_block", overwrite_block.returncode, overwrite_block.stderr, file=sys.stderr)
        print("force_overwrite", force_overwrite.returncode, force_overwrite.stderr, file=sys.stderr)
        print("dotbotctl_output", dotbotctl_output.returncode, dotbotctl_output.stderr, file=sys.stderr)
        for issue in [*draft_issues, *output_issues]:
            print(issue.to_dict(), file=sys.stderr)
        raise SystemExit(1)

    design_menu = run(botctl + ["design", "extract-menu", "--project", str(bootstrap_dir), "--format", "json"], cwd=control_root)
    menu_map = json.loads(design_menu.stdout)
    menu_roles = {role.get("id") for role in menu_map.get("roles", [])}
    menu_commands = {command.get("command") for command in menu_map.get("commands", [])}
    menu_namespaces = {namespace.get("namespace") for namespace in menu_map.get("callback_contract", [])}
    design_output = tmp_root / "design-output" / "menu.map.json"
    run(botctl + ["design", "extract-menu", "--project", str(bootstrap_dir), "--output", str(design_output)], cwd=control_root)
    design_output_payload = json.loads(design_output.read_text(encoding="utf-8"))
    design_dotbotctl_output = run(
        botctl + ["design", "extract-menu", "--project", str(bootstrap_dir), "--output", str(bootstrap_dir / ".botctl" / "menu.map.json")],
        cwd=control_root,
        expect_ok=False,
    )
    design_extract_menu_ok = (
        menu_map.get("kind") == "BotMenuMap"
        and "start" in menu_commands
        and "user" in menu_roles
        and "main" in menu_namespaces
        and menu_map.get("menus")
        and menu_map.get("read_only") is True
        and all(gate.get("status") in {"covered", "weak"} for gate in menu_map.get("quality_gates", []))
        and design_output.exists()
        and design_output_payload.get("kind") == "BotMenuMap"
        and design_dotbotctl_output.returncode != 0
        and not (bootstrap_dir / ".botctl").exists()
    )
    print(f"design_extract_menu_ok={design_extract_menu_ok}")
    print(f"design_extract_menu_output_ok={design_output.exists() and design_output_payload.get('kind') == 'BotMenuMap'}")
    print(f"design_extract_menu_dotbotctl_guard_ok={design_dotbotctl_output.returncode != 0 and not (bootstrap_dir / '.botctl').exists()}")
    if not design_extract_menu_ok:
        print(json.dumps(menu_map, ensure_ascii=False, indent=2), file=sys.stderr)
        print("namespaces", sorted(menu_namespaces), file=sys.stderr)
        print("dotbotctl", design_dotbotctl_output.returncode, design_dotbotctl_output.stderr, file=sys.stderr)
        raise SystemExit(1)

    design_critique = run(botctl + ["design", "critique", "--project", str(bootstrap_dir), "--format", "json"], cwd=control_root)
    critique_payload = json.loads(design_critique.stdout)
    critique_output = tmp_root / "design-output" / "menu.critique.json"
    run(botctl + ["design", "critique", "--project", str(bootstrap_dir), "--input", str(design_output), "--output", str(critique_output)], cwd=control_root)
    critique_output_payload = json.loads(critique_output.read_text(encoding="utf-8"))
    critique_dotbotctl_output = run(
        botctl + ["design", "critique", "--project", str(bootstrap_dir), "--output", str(bootstrap_dir / ".botctl" / "menu.critique.json")],
        cwd=control_root,
        expect_ok=False,
    )
    critique_issue_ids = {issue.get("id") for issue in critique_payload.get("issues", [])}
    rulepack_eval = critique_payload.get("rulepack_evaluation", {})
    rulepack_result_ids = {result.get("id") for result in rulepack_eval.get("results", [])}
    design_critique_ok = (
        critique_payload.get("kind") == "BotMenuDesignCritique"
        and critique_payload.get("read_only") is True
        and critique_payload.get("summary", {}).get("issues", 0) >= 1
        and rulepack_eval.get("rulepack_id") == "telegram_bot_builder_ux"
        and rulepack_eval.get("summary", {}).get("rules", 0) >= 10
        and {"tbb.start_onboarding", "tbb.help_command", "tbb.inline_keyboard_layout", "tbb.navigation_escape_paths", "tbb.rate_limiting"}.issubset(rulepack_result_ids)
        and "commands.help_missing" in critique_issue_ids
        and "navigation.back_missing" in critique_issue_ids
        and critique_output.exists()
        and critique_output_payload.get("kind") == "BotMenuDesignCritique"
        and critique_dotbotctl_output.returncode != 0
        and not (bootstrap_dir / ".botctl").exists()
        and "roles.not_explicit" not in critique_issue_ids
        and "menus.no_inline_buttons" not in critique_issue_ids
    )
    print(f"design_critique_ok={design_critique_ok}")
    print(f"design_critique_rulepack_ok={rulepack_eval.get('rulepack_id') == 'telegram_bot_builder_ux' and rulepack_eval.get('summary', {}).get('rules', 0) >= 10}")
    print(f"design_critique_output_ok={critique_output.exists() and critique_output_payload.get('kind') == 'BotMenuDesignCritique'}")
    print(f"design_critique_dotbotctl_guard_ok={critique_dotbotctl_output.returncode != 0 and not (bootstrap_dir / '.botctl').exists()}")
    if not design_critique_ok:
        print(json.dumps(critique_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        print("dotbotctl", critique_dotbotctl_output.returncode, critique_dotbotctl_output.stderr, file=sys.stderr)
        raise SystemExit(1)

    brief_path = tmp_root / "design-brief.yaml"
    brief_path.write_text(
        "name: creator-task-bot\n"
        "roles:\n"
        "  - id: guest\n"
        "    title: Гость\n"
        "  - id: creator\n"
        "    title: Креатор\n"
        "  - id: lead\n"
        "    title: Лид\n"
        "  - id: admin\n"
        "    title: Администратор\n"
        "  - id: owner\n"
        "    title: Владелец\n"
        "flows:\n"
        "  - id: task_board\n"
        "    title: Задания\n"
        "    command: tasks\n"
        "    roles: [creator, lead, admin, owner]\n"
        "  - id: submit_work\n"
        "    title: Сдать работу\n"
        "    command: submit\n"
        "    roles: [creator]\n"
        "  - id: moderation_queue\n"
        "    title: Модерация\n"
        "    command: moderate\n"
        "    roles: [lead, admin, owner]\n"
        "  - id: payments\n"
        "    title: Выплаты\n"
        "    command: payments\n"
        "    roles: [creator, admin, owner]\n",
        encoding="utf-8",
    )
    brief_validation = run(
        botctl + ["design", "validate-brief", "--project", str(tmp_root / "creator-task-bot"), "--input", str(brief_path), "--format", "json"],
        cwd=control_root,
    )
    brief_validation_payload = json.loads(brief_validation.stdout)
    invalid_brief_path = tmp_root / "invalid-design-brief.yaml"
    invalid_brief_path.write_text(
        "name: bad-bot\n"
        "roles:\n"
        "  - id: admin\n"
        "  - id: admin\n"
        "  - id: token\n"
        "flows:\n"
        "  - id: admin\n"
        "    command: start\n"
        "    roles: [ghost]\n"
        "  - id: task_board\n"
        "    command: tasks\n"
        "    roles: [admin]\n"
        "  - id: task_board\n"
        "    command: tasks\n"
        "    roles: [admin]\n",
        encoding="utf-8",
    )
    invalid_brief_validation = run(
        botctl + ["design", "validate-brief", "--project", str(tmp_root / "bad-bot"), "--input", str(invalid_brief_path), "--format", "json"],
        cwd=control_root,
        expect_ok=False,
    )
    invalid_brief_payload = json.loads(invalid_brief_validation.stdout)
    invalid_from_brief = run(
        botctl + ["design", "from-brief", "--project", str(tmp_root / "bad-bot"), "--input", str(invalid_brief_path), "--format", "json"],
        cwd=control_root,
        expect_ok=False,
    )
    invalid_allowed_from_brief = run(
        botctl + ["design", "from-brief", "--project", str(tmp_root / "bad-bot"), "--input", str(invalid_brief_path), "--allow-invalid", "--format", "json"],
        cwd=control_root,
    )
    invalid_allowed_payload = json.loads(invalid_allowed_from_brief.stdout)
    invalid_issue_ids = {issue.get("id") for issue in invalid_brief_payload.get("issues", [])}
    brief_validation_ok = (
        brief_validation_payload.get("kind") == "BotDesignBriefValidation"
        and brief_validation_payload.get("valid") is True
        and brief_validation_payload.get("summary", {}).get("errors") == 0
        and invalid_brief_validation.returncode != 0
        and invalid_brief_payload.get("valid") is False
        and {"brief.role_duplicate", "brief.role_id_reserved", "brief.flow_role_unknown", "brief.command_reserved", "brief.flow_duplicate", "brief.command_duplicate"}.issubset(invalid_issue_ids)
        and invalid_from_brief.returncode != 0
        and invalid_allowed_payload.get("kind") == "BotMenuDesignProposal"
        and invalid_allowed_payload.get("brief_validation", {}).get("valid") is False
    )
    print(f"design_validate_brief_ok={brief_validation_ok}")
    print(f"design_validate_brief_invalid_guard_ok={invalid_brief_validation.returncode != 0 and invalid_from_brief.returncode != 0}")
    if not brief_validation_ok:
        print(json.dumps({"valid": brief_validation_payload, "invalid": invalid_brief_payload, "allowed": invalid_allowed_payload}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)

    design_from_brief = run(
        botctl + ["design", "from-brief", "--project", str(tmp_root / "creator-task-bot"), "--input", str(brief_path), "--format", "json"],
        cwd=control_root,
    )
    from_brief_payload = json.loads(design_from_brief.stdout)
    from_brief_output = tmp_root / "design-output" / "from-brief.proposal.yaml"
    run(
        botctl + ["design", "from-brief", "--project", str(tmp_root / "creator-task-bot"), "--input", str(brief_path), "--format", "yaml", "--output", str(from_brief_output)],
        cwd=control_root,
    )
    from_brief_output_payload = load_yaml(from_brief_output)
    from_brief_dotbotctl_output = run(
        botctl + ["design", "from-brief", "--project", str(tmp_root / "creator-task-bot"), "--input", str(brief_path), "--output", str((tmp_root / "creator-task-bot" / ".botctl" / "menu.proposal.yaml"))],
        cwd=control_root,
        expect_ok=False,
    )
    from_brief_roles = {role.get("id") for role in from_brief_payload.get("roles", [])}
    from_brief_commands = {command.get("command") for command in from_brief_payload.get("command_contract", [])}
    from_brief_callbacks = {item.get("namespace") for item in from_brief_payload.get("callback_contract", [])}
    design_from_brief_ok = (
        from_brief_payload.get("kind") == "BotMenuDesignProposal"
        and from_brief_payload.get("source_kind") == "BotDesignBrief"
        and {"creator", "lead", "admin", "owner"}.issubset(from_brief_roles)
        and {"/start", "/help", "/tasks", "/submit", "/moderate", "/payments"}.issubset(from_brief_commands)
        and {"nav", "admin", "task", "submit", "moderation", "payments"}.issubset(from_brief_callbacks)
        and from_brief_payload.get("implementation_policy", {}).get("mode") == "proposal_only"
        and from_brief_output.exists()
        and from_brief_output_payload.get("kind") == "BotMenuDesignProposal"
        and from_brief_dotbotctl_output.returncode != 0
        and not (tmp_root / "creator-task-bot" / ".botctl").exists()
    )
    print(f"design_from_brief_ok={design_from_brief_ok}")
    print(f"design_from_brief_output_ok={from_brief_output.exists() and from_brief_output_payload.get('kind') == 'BotMenuDesignProposal'}")
    print(f"design_from_brief_dotbotctl_guard_ok={from_brief_dotbotctl_output.returncode != 0 and not (tmp_root / 'creator-task-bot' / '.botctl').exists()}")
    if not design_from_brief_ok:
        print(json.dumps(from_brief_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        print("dotbotctl", from_brief_dotbotctl_output.returncode, from_brief_dotbotctl_output.stderr, file=sys.stderr)
        raise SystemExit(1)

    design_normalize = run(botctl + ["design", "normalize", "--project", str(bootstrap_dir), "--format", "json"], cwd=control_root)
    proposal_payload = json.loads(design_normalize.stdout)
    proposal_output = tmp_root / "design-output" / "menu.proposal.yaml"
    run(botctl + ["design", "normalize", "--project", str(bootstrap_dir), "--input", str(design_output), "--format", "yaml", "--output", str(proposal_output)], cwd=control_root)
    proposal_output_payload = load_yaml(proposal_output)
    proposal_dotbotctl_output = run(
        botctl + ["design", "normalize", "--project", str(bootstrap_dir), "--output", str(bootstrap_dir / ".botctl" / "menu.proposal.json")],
        cwd=control_root,
        expect_ok=False,
    )
    proposal_callback_namespaces = {item.get("namespace") for item in proposal_payload.get("callback_contract", [])}
    design_normalize_ok = (
        proposal_payload.get("kind") == "BotMenuDesignProposal"
        and proposal_payload.get("read_only") is True
        and proposal_payload.get("implementation_policy", {}).get("mode") == "proposal_only"
        and "main" in proposal_callback_namespaces
        and proposal_payload.get("menus")
        and proposal_payload.get("command_contract")
        and proposal_payload.get("global_navigation_requirements", {}).get("missing_from_extracted_design")
        and proposal_output.exists()
        and proposal_output_payload.get("kind") == "BotMenuDesignProposal"
        and proposal_dotbotctl_output.returncode != 0
        and not (bootstrap_dir / ".botctl").exists()
    )
    print(f"design_normalize_ok={design_normalize_ok}")
    print(f"design_normalize_output_ok={proposal_output.exists() and proposal_output_payload.get('kind') == 'BotMenuDesignProposal'}")
    print(f"design_normalize_dotbotctl_guard_ok={proposal_dotbotctl_output.returncode != 0 and not (bootstrap_dir / '.botctl').exists()}")
    if not design_normalize_ok:
        print(json.dumps(proposal_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        print("dotbotctl", proposal_dotbotctl_output.returncode, proposal_dotbotctl_output.stderr, file=sys.stderr)
        raise SystemExit(1)

    design_plan = run(botctl + ["design", "plan", "--project", str(bootstrap_dir), "--input", str(proposal_output), "--format", "json"], cwd=control_root)
    plan_payload = json.loads(design_plan.stdout)
    plan_output = tmp_root / "design-output" / "menu.implementation-plan.yaml"
    run(botctl + ["design", "plan", "--project", str(bootstrap_dir), "--input", str(proposal_output), "--format", "yaml", "--output", str(plan_output)], cwd=control_root)
    plan_output_payload = load_yaml(plan_output)
    plan_dotbotctl_output = run(
        botctl + ["design", "plan", "--project", str(bootstrap_dir), "--input", str(proposal_output), "--output", str(bootstrap_dir / ".botctl" / "menu.implementation-plan.yaml")],
        cwd=control_root,
        expect_ok=False,
    )
    design_plan_ok = (
        plan_payload.get("kind") == "BotMenuImplementationPlan"
        and plan_payload.get("read_only") is True
        and plan_payload.get("summary", {}).get("mode") == "plan_only"
        and len(plan_payload.get("phases", [])) >= 4
        and len(plan_payload.get("test_matrix", [])) >= 6
        and "restart bot service" in plan_payload.get("blocked_actions", [])
        and plan_output.exists()
        and plan_output_payload.get("kind") == "BotMenuImplementationPlan"
        and plan_dotbotctl_output.returncode != 0
        and not (bootstrap_dir / ".botctl").exists()
    )
    print(f"design_plan_ok={design_plan_ok}")
    print(f"design_plan_output_ok={plan_output.exists() and plan_output_payload.get('kind') == 'BotMenuImplementationPlan'}")
    print(f"design_plan_dotbotctl_guard_ok={plan_dotbotctl_output.returncode != 0 and not (bootstrap_dir / '.botctl').exists()}")
    if not design_plan_ok:
        print(json.dumps(plan_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        print("dotbotctl", plan_dotbotctl_output.returncode, plan_dotbotctl_output.stderr, file=sys.stderr)
        raise SystemExit(1)

    minimal_actual_map = tmp_root / "design-output" / "minimal.actual-menu-map.json"
    minimal_actual_map.write_text(
        json.dumps(
            {
                "apiVersion": "botctl.dev/v0",
                "kind": "BotMenuMap",
                "project_path": str(tmp_root / "creator-task-bot"),
                "read_only": True,
                "roles": [{"id": "user", "title": "User"}],
                "commands": [{"command": "start", "role_hint": "user"}],
                "menus": [],
                "callback_contract": [],
                "handlers_hint": [],
                "quality_gates": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    design_compare = run(
        botctl + ["design", "compare", "--project", str(tmp_root / "creator-task-bot"), "--input", str(from_brief_output), "--actual", str(minimal_actual_map), "--format", "json"],
        cwd=control_root,
    )
    compare_payload = json.loads(design_compare.stdout)
    compare_output = tmp_root / "design-output" / "menu.diff.yaml"
    run(
        botctl + ["design", "compare", "--project", str(tmp_root / "creator-task-bot"), "--input", str(from_brief_output), "--actual", str(minimal_actual_map), "--format", "yaml", "--output", str(compare_output)],
        cwd=control_root,
    )
    compare_output_payload = load_yaml(compare_output)
    compare_dotbotctl_output = run(
        botctl + ["design", "compare", "--project", str(tmp_root / "creator-task-bot"), "--input", str(from_brief_output), "--actual", str(minimal_actual_map), "--output", str((tmp_root / "creator-task-bot" / ".botctl" / "menu.diff.yaml"))],
        cwd=control_root,
        expect_ok=False,
    )
    compare_issue_ids = {issue.get("id") for issue in compare_payload.get("issues", [])}
    design_compare_ok = (
        compare_payload.get("kind") == "BotMenuDesignDiff"
        and compare_payload.get("read_only") is True
        and compare_payload.get("summary", {}).get("status") in {"partial", "diverged"}
        and compare_payload.get("summary", {}).get("missing_commands", 0) >= 1
        and compare_payload.get("summary", {}).get("missing_callback_namespaces", 0) >= 1
        and {"compare.commands_missing", "compare.callback_namespaces_missing", "compare.navigation_missing"}.issubset(compare_issue_ids)
        and compare_output.exists()
        and compare_output_payload.get("kind") == "BotMenuDesignDiff"
        and compare_dotbotctl_output.returncode != 0
        and not (tmp_root / "creator-task-bot" / ".botctl").exists()
    )
    print(f"design_compare_ok={design_compare_ok}")
    print(f"design_compare_output_ok={compare_output.exists() and compare_output_payload.get('kind') == 'BotMenuDesignDiff'}")
    print(f"design_compare_dotbotctl_guard_ok={compare_dotbotctl_output.returncode != 0 and not (tmp_root / 'creator-task-bot' / '.botctl').exists()}")
    if not design_compare_ok:
        print(json.dumps(compare_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        print("dotbotctl", compare_dotbotctl_output.returncode, compare_dotbotctl_output.stderr, file=sys.stderr)
        raise SystemExit(1)

    print("== design schemas ==")
    schema_checks = [
        (control_root / "schemas" / "ux-rulepack.schema.json", control_root / "tools" / "botctl" / "rulepacks" / "telegram_bot_builder_ux.yaml"),
        (control_root / "schemas" / "menu-map.schema.json", design_output),
        (control_root / "schemas" / "menu-design-proposal.schema.json", proposal_output),
        (control_root / "schemas" / "menu-implementation-plan.schema.json", plan_output),
        (control_root / "schemas" / "menu-design-diff.schema.json", compare_output),
    ]
    schema_results: list[str] = []
    for schema_path, data_path in schema_checks:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        data = load_yaml(data_path) if data_path.suffix in {".yaml", ".yml"} else json.loads(data_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(data)
        schema_results.append(schema_path.name)
    design_brief_schema = json.loads((control_root / "schemas" / "design-brief.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(design_brief_schema).validate(load_yaml(brief_path))
    schema_results.append("design-brief.schema.json")
    negative_schema = json.loads((control_root / "schemas" / "menu-design-proposal.schema.json").read_text(encoding="utf-8"))
    negative_ok = False
    try:
        jsonschema.Draft202012Validator(negative_schema).validate({"apiVersion": "botctl.dev/v0", "kind": "BotMenuDesignProposal", "read_only": False})
    except jsonschema.ValidationError:
        negative_ok = True
    design_schemas_ok = len(schema_results) == 6 and negative_ok
    print(f"design_schemas_ok={design_schemas_ok}")
    print(f"design_schema_negative_ok={negative_ok}")
    if not design_schemas_ok:
        print(schema_results, file=sys.stderr)
        raise SystemExit(1)

    print("== design init-system ==")
    init_dir = tmp_root / "design_init_fixture"
    (init_dir / "src").mkdir(parents=True)
    (init_dir / "src" / "bot.py").write_text(
        "import os\n"
        "from telegram import InlineKeyboardButton, InlineKeyboardMarkup\n"
        "from telegram.ext import Application, CommandHandler, CallbackQueryHandler\n"
        "BOT_TOKEN = os.environ['BOT_TOKEN']\n"
        "ADMIN_IDS = {1}\n"
        "def is_admin(user_id):\n"
        "    return user_id in ADMIN_IDS\n"
        "def main_keyboard():\n"
        "    return InlineKeyboardMarkup([[InlineKeyboardButton('Задания', callback_data='task:open:list')], [InlineKeyboardButton('Админка', callback_data='admin:open')], [InlineKeyboardButton('Назад', callback_data='nav:back')], [InlineKeyboardButton('Отмена', callback_data='nav:cancel')], [InlineKeyboardButton('Помощь', callback_data='nav:help')]])\n"
        "async def start(update, context):\n"
        "    await update.message.reply_text('Привет', reply_markup=main_keyboard())\n"
        "async def help(update, context):\n"
        "    await update.message.reply_text('Помощь')\n"
        "async def handle_callback(update, context):\n"
        "    query = update.callback_query\n"
        "    if query.data.startswith('admin:') and not is_admin(query.from_user.id):\n"
        "        await query.answer('Нет доступа')\n"
        "        return\n"
        "    if query.data == 'nav:cancel':\n"
        "        await query.answer('Отменено')\n"
        "        return\n"
        "    await query.answer('Готово')\n"
        "def main():\n"
        "    app = Application.builder().token(BOT_TOKEN).build()\n"
        "    app.add_handler(CommandHandler('start', start))\n"
        "    app.add_handler(CommandHandler('help', help))\n"
        "    app.add_handler(CallbackQueryHandler(handle_callback))\n"
        "    app.run_polling()\n",
        encoding="utf-8",
    )
    init_result = run(botctl + ["design", "init-system", "--project", str(init_dir), "--format", "json"], cwd=control_root)
    init_payload = json.loads(init_result.stdout)
    design_dir = init_dir / ".botctl" / "design"
    required_design_files = [
        "manifest.yaml",
        "product.model.yaml",
        "roles.model.yaml",
        "journeys.map.yaml",
        "menu.proposal.yaml",
        "responses.system.yaml",
        "state.model.yaml",
        "impact.graph.yaml",
        "test.matrix.yaml",
        "README.md",
    ]
    manifest_payload = load_yaml(design_dir / "manifest.yaml")
    product_payload = load_yaml(design_dir / "product.model.yaml")
    menu_proposal_payload = load_yaml(design_dir / "menu.proposal.yaml")
    init_second = run(botctl + ["design", "init-system", "--project", str(init_dir), "--format", "json"], cwd=control_root, expect_ok=False)
    preview_dir = tmp_root / "design_init_preview"
    preview_result = run(botctl + ["design", "init-system", "--project", str(init_dir), "--preview", "--output", str(preview_dir), "--format", "json"], cwd=control_root)
    preview_payload = json.loads(preview_result.stdout)
    init_system_ok = (
        init_payload.get("kind") == "BotDesignInitResult"
        and init_payload.get("preview") is False
        and init_payload.get("production_design_allowed") is False
        and all((design_dir / name).exists() for name in required_design_files)
        and (design_dir / "changeplans").is_dir()
        and manifest_payload.get("kind") == "BotDesignManifest"
        and manifest_payload.get("knowledge_status") == "draft"
        and manifest_payload.get("production_design_allowed") is False
        and product_payload.get("kind") == "BotProductModel"
        and product_payload.get("source") == "placeholder"
        and menu_proposal_payload.get("source") == "observed_code"
        and init_second.returncode != 0
        and preview_payload.get("preview") is True
        and (preview_dir / "manifest.yaml").exists()
        and (preview_dir / "README.md").exists()
    )
    print(f"design_init_system_ok={init_system_ok}")
    print(f"design_init_system_no_overwrite_ok={init_second.returncode != 0}")
    print(f"design_init_system_preview_ok={preview_payload.get('preview') is True and (preview_dir / 'manifest.yaml').exists()}")
    if not init_system_ok:
        print(json.dumps(init_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        print(init_second.stderr, file=sys.stderr)
        raise SystemExit(1)

    new_schema_checks = [
        (control_root / "schemas" / "design-manifest.schema.json", design_dir / "manifest.yaml"),
        (control_root / "schemas" / "product-model.schema.json", design_dir / "product.model.yaml"),
        (control_root / "schemas" / "role-model.schema.json", design_dir / "roles.model.yaml"),
        (control_root / "schemas" / "journey-map.schema.json", design_dir / "journeys.map.yaml"),
        (control_root / "schemas" / "response-system.schema.json", design_dir / "responses.system.yaml"),
        (control_root / "schemas" / "state-model.schema.json", design_dir / "state.model.yaml"),
        (control_root / "schemas" / "impact-graph.schema.json", design_dir / "impact.graph.yaml"),
        (control_root / "schemas" / "test-matrix.schema.json", design_dir / "test.matrix.yaml"),
    ]
    new_schema_ok = True
    for schema_path, data_path in new_schema_checks:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        data = load_yaml(data_path)
        jsonschema.Draft202012Validator(schema).validate(data)
    print(f"design_init_system_schemas_ok={new_schema_ok}")

    design_status = run(botctl + ["design", "status", "--project", str(init_dir), "--format", "json"], cwd=control_root)
    status_payload = json.loads(design_status.stdout)
    no_design_status = run(botctl + ["design", "status", "--project", str(tmp_root / "no_design_fixture"), "--format", "json"], cwd=control_root, expect_ok=False)
    no_design_payload = json.loads(no_design_status.stdout)
    readiness_schema = json.loads((control_root / "schemas" / "design-readiness.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(readiness_schema).validate(status_payload)
    jsonschema.Draft202012Validator(readiness_schema).validate(no_design_payload)
    design_status_ok = (
        status_payload.get("kind") == "BotDesignReadiness"
        and status_payload.get("design_exists") is True
        and status_payload.get("readiness_status") == "blocked"
        and status_payload.get("production_design_allowed") is False
        and status_payload.get("summary", {}).get("blockers", 0) >= 1
        and status_payload.get("summary", {}).get("errors", 0) == 0
        and len([item for item in status_payload.get("schema_validation", []) if item.get("valid")]) >= 8
        and no_design_status.returncode != 0
        and no_design_payload.get("readiness_status") == "missing_design_layer"
    )
    print(f"design_status_ok={design_status_ok}")
    print(f"design_status_missing_guard_ok={no_design_status.returncode != 0 and no_design_payload.get('readiness_status') == 'missing_design_layer'}")
    if not design_status_ok:
        print(json.dumps({"status": status_payload, "missing": no_design_payload}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)

    print("== design review/confirm ==")
    review_product = run(
        botctl + ["design", "review", "--project", str(init_dir), "--artifact", "product_model", "--actor", "smoke-reviewer", "--format", "json"],
        cwd=control_root,
    )
    review_product_payload = json.loads(review_product.stdout)
    confirm_without_flag = run(
        botctl + ["design", "confirm", "--project", str(init_dir), "--artifact", "product_model", "--actor", "smoke-reviewer"],
        cwd=control_root,
        expect_ok=False,
    )
    confirm_with_open_questions = run(
        botctl + ["design", "confirm", "--project", str(init_dir), "--artifact", "product_model", "--actor", "smoke-reviewer", "--confirm"],
        cwd=control_root,
        expect_ok=False,
    )
    required_confirmations = ["product_model", "role_model", "journey_map", "menu_proposal", "response_system", "impact_graph", "test_matrix"]
    artifact_files = {
        "product_model": "product.model.yaml",
        "role_model": "roles.model.yaml",
        "journey_map": "journeys.map.yaml",
        "menu_proposal": "menu.proposal.yaml",
        "response_system": "responses.system.yaml",
        "impact_graph": "impact.graph.yaml",
        "test_matrix": "test.matrix.yaml",
    }
    product_semantic_fixture = load_yaml(design_dir / "product.model.yaml")
    product_semantic_fixture["open_questions"] = []
    dump_yaml(design_dir / "product.model.yaml", product_semantic_fixture)
    semantic_validation = run(
        botctl + ["design", "validate-artifact", "--project", str(init_dir), "--artifact", "product_model", "--format", "json"],
        cwd=control_root,
        expect_ok=False,
    )
    semantic_validation_payload = json.loads(semantic_validation.stdout)
    confirm_placeholder = run(
        botctl + ["design", "confirm", "--project", str(init_dir), "--artifact", "product_model", "--actor", "smoke-reviewer", "--confirm"],
        cwd=control_root,
        expect_ok=False,
    )
    for artifact_key in required_confirmations:
        artifact_path = design_dir / artifact_files[artifact_key]
        artifact_payload = load_yaml(artifact_path)
        artifact_payload["open_questions"] = []
        artifact_payload["assumptions_required_confirmation"] = False
        if artifact_key == "product_model":
            artifact_payload.update({
                "source": "human_review",
                "purpose": "Помогать пользователю управлять задачами через Telegram.",
                "target_users": ["Авторизованные пользователи"],
                "primary_jobs": ["Создать и проверить задачу"],
                "non_goals": ["Не заменяет runtime service"],
                "business_rules": ["Админские действия требуют прав"],
                "success_metrics": ["Основной journey проходит без тупиков"],
                "risk_constraints": ["Секреты не хранятся в design artifacts"],
            })
        elif artifact_key == "role_model":
            for role in artifact_payload.get("roles", []):
                role["title"] = role.get("title") or role["id"]
                role["goals"] = role.get("goals") or ["Выполнить доступный сценарий"]
                role["permission_boundaries"] = role.get("permission_boundaries") or ["Не выполнять действия чужой роли"]
        elif artifact_key == "journey_map":
            artifact_payload.update({"source": "human_review", "journeys": [{"id": "journey.main", "role_id": "user", "goal": "Открыть главное меню", "steps": ["/запуск", "Выбрать действие"]}]})
        elif artifact_key == "response_system":
            artifact_payload.update({"source": "human_review", "responses": [{"id": "response.start", "intent": "onboarding", "template": "Выберите действие"}], "tone_rules": ["Писать просто и ясно"]})
        dump_yaml(artifact_path, artifact_payload)
        if artifact_key != "product_model":
            run(
                botctl + ["design", "review", "--project", str(init_dir), "--artifact", artifact_key, "--actor", "smoke-reviewer"],
                cwd=control_root,
            )
        run(
            botctl + ["design", "confirm", "--project", str(init_dir), "--artifact", artifact_key, "--actor", "smoke-reviewer", "--confirm"],
            cwd=control_root,
        )
    ready_status = run(botctl + ["design", "status", "--project", str(init_dir), "--format", "json"], cwd=control_root)
    ready_payload = json.loads(ready_status.stdout)
    review_confirm_ok = (
        review_product_payload.get("new_status") == "reviewed"
        and confirm_without_flag.returncode != 0
        and confirm_with_open_questions.returncode != 0
        and semantic_validation.returncode != 0
        and semantic_validation_payload.get("valid") is False
        and confirm_placeholder.returncode != 0
        and ready_payload.get("readiness_status") == "ready"
        and ready_payload.get("production_design_allowed") is True
        and ready_payload.get("readiness_score") == 100
    )
    print(f"design_review_confirm_ok={review_confirm_ok}")
    print(f"design_confirm_explicit_guard_ok={confirm_without_flag.returncode != 0}")
    print(f"design_confirm_open_questions_guard_ok={confirm_with_open_questions.returncode != 0}")
    print(f"design_semantic_validation_guard_ok={semantic_validation.returncode != 0 and confirm_placeholder.returncode != 0}")
    if not review_confirm_ok:
        print(json.dumps(ready_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)

    print("== design ChangePlan approval ==")
    change_id = "smoke.menu-change"
    gate_without_plan = run(
        botctl + ["design", "gate", "--project", str(init_dir), "--format", "json"],
        cwd=control_root,
        expect_ok=False,
    )
    gate_without_plan_payload = json.loads(gate_without_plan.stdout)
    create_change_plan = run(
        botctl + ["design", "change-plan-new", "--project", str(init_dir), "--id", change_id, "--intent", "Уточнить главное меню для роли user", "--risk-level", "medium", "--format", "json"],
        cwd=control_root,
    )
    create_change_plan_payload = json.loads(create_change_plan.stdout)
    incomplete_change_plan = run(
        botctl + ["design", "change-plan-validate", "--project", str(init_dir), "--id", change_id, "--format", "json"],
        cwd=control_root,
        expect_ok=False,
    )
    direct_approval = run(
        botctl + ["design", "change-plan-approve", "--project", str(init_dir), "--id", change_id, "--actor", "smoke-approver", "--confirm"],
        cwd=control_root,
        expect_ok=False,
    )
    change_plan_path = design_dir / "changeplans" / f"{change_id}.yaml"
    change_plan_payload = load_yaml(change_plan_path)
    change_plan_payload["affected_roles"] = ["user"]
    change_plan_payload["affected_menus"] = ["menu.main"]
    change_plan_payload["verification_plan"] = ["Проверить видимость меню для user"]
    change_plan_payload["rollback_plan"] = ["Откатить изменения menu proposal по git patch"]
    dump_yaml(change_plan_path, change_plan_payload)
    unknown_reference_validation = run(
        botctl + ["design", "change-plan-validate", "--project", str(init_dir), "--id", change_id, "--format", "json"],
        cwd=control_root,
        expect_ok=False,
    )
    unknown_reference_payload = json.loads(unknown_reference_validation.stdout)
    change_plan_payload["affected_menus"] = []
    dump_yaml(change_plan_path, change_plan_payload)
    valid_change_plan = run(
        botctl + ["design", "change-plan-validate", "--project", str(init_dir), "--id", change_id, "--format", "json"],
        cwd=control_root,
    )
    review_change_plan = run(
        botctl + ["design", "change-plan-review", "--project", str(init_dir), "--id", change_id, "--actor", "smoke-reviewer", "--format", "json"],
        cwd=control_root,
    )
    approve_without_flag = run(
        botctl + ["design", "change-plan-approve", "--project", str(init_dir), "--id", change_id, "--actor", "smoke-approver"],
        cwd=control_root,
        expect_ok=False,
    )
    approve_change_plan = run(
        botctl + ["design", "change-plan-approve", "--project", str(init_dir), "--id", change_id, "--actor", "smoke-approver", "--confirm", "--format", "json"],
        cwd=control_root,
    )
    approved_payload = json.loads(approve_change_plan.stdout)
    saved_approved_plan = load_yaml(change_plan_path)
    ready_gate = run(
        botctl + ["design", "gate", "--project", str(init_dir), "--id", change_id, "--format", "json"],
        cwd=control_root,
    )
    ready_gate_payload = json.loads(ready_gate.stdout)
    design_gate_schema = json.loads((control_root / "schemas" / "design-gate.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(design_gate_schema).validate(gate_without_plan_payload)
    jsonschema.Draft202012Validator(design_gate_schema).validate(ready_gate_payload)
    change_plan_approval_ok = (
        create_change_plan_payload.get("knowledge_status") == "draft"
        and incomplete_change_plan.returncode != 0
        and direct_approval.returncode != 0
        and unknown_reference_validation.returncode != 0
        and any(issue.get("code") == "change_plan.affected_menus.unknown_id" for issue in unknown_reference_payload.get("issues", []))
        and json.loads(valid_change_plan.stdout).get("valid") is True
        and json.loads(review_change_plan.stdout).get("knowledge_status") == "reviewed"
        and approve_without_flag.returncode != 0
        and approved_payload.get("approval_status") == "approved"
        and approved_payload.get("knowledge_status") == "confirmed"
        and saved_approved_plan.get("approved_by") == "smoke-approver"
        and saved_approved_plan.get("runtime_apply_allowed") is False
    )
    design_gate_ok = (
        gate_without_plan.returncode != 0
        and gate_without_plan_payload.get("gate_status") == "missing_change_plan"
        and gate_without_plan_payload.get("implementation_planning_allowed") is False
        and ready_gate_payload.get("gate_status") == "ready_for_implementation_planning"
        and ready_gate_payload.get("implementation_planning_allowed") is True
        and ready_gate_payload.get("runtime_apply_allowed") is False
        and ready_gate_payload.get("summary", {}).get("approved_change_plans") == 1
    )
    print(f"design_change_plan_approval_ok={change_plan_approval_ok}")
    print(f"design_change_plan_incomplete_guard_ok={incomplete_change_plan.returncode != 0}")
    print(f"design_change_plan_review_guard_ok={direct_approval.returncode != 0}")
    print(f"design_change_plan_explicit_approval_guard_ok={approve_without_flag.returncode != 0}")
    print(f"design_change_plan_unknown_reference_guard_ok={unknown_reference_validation.returncode != 0}")
    print(f"design_gate_ok={design_gate_ok}")
    print(f"design_gate_missing_plan_guard_ok={gate_without_plan.returncode != 0}")
    if not change_plan_approval_ok or not design_gate_ok:
        print(json.dumps(saved_approved_plan, ensure_ascii=False, indent=2), file=sys.stderr)
        print(json.dumps(ready_gate_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)

    no_confirm_save = run(botctl + ["bootstrap-save", "--project", str(bootstrap_dir)], cwd=control_root, expect_ok=False)
    dirty_guard_save = run(botctl + ["bootstrap-save", "--project", str(bootstrap_dir), "--confirm"], cwd=control_root, expect_ok=False)
    bootstrap_save = run(
        botctl + ["bootstrap-save", "--project", str(bootstrap_dir), "--confirm", "--allow-dirty", "--format", "json"],
        cwd=control_root,
    )
    bootstrap_save_payload = json.loads(bootstrap_save.stdout)
    save_artifacts = bootstrap_save_payload.get("generated_artifacts", {})
    saved_graph = bootstrap_dir / ".botctl" / "graph.desired.yaml"
    saved_project = bootstrap_dir / ".botctl" / "project.yaml"
    saved_context = bootstrap_dir / ".botctl" / "agent_context.json"
    saved_verify = run(botctl + ["verify", "--project", str(bootstrap_dir), "--format", "json"], cwd=control_root)
    saved_verify_payload = json.loads(saved_verify.stdout)
    existing_graph_guard = run(
        botctl + ["bootstrap-save", "--project", str(bootstrap_dir), "--confirm", "--allow-dirty"],
        cwd=control_root,
        expect_ok=False,
    )
    force_save = run(
        botctl + ["bootstrap-save", "--project", str(bootstrap_dir), "--confirm", "--allow-dirty", "--force", "--format", "json"],
        cwd=control_root,
    )
    force_payload = json.loads(force_save.stdout)
    backup_paths = [force_payload.get("saved", {}).get("backup_path"), force_payload.get("saved", {}).get("project_backup_path")]
    bootstrap_save_ok = (
        no_confirm_save.returncode != 0
        and dirty_guard_save.returncode != 0
        and bootstrap_save_payload.get("verify_summary", {}).get("errors") == 0
        and saved_verify_payload.get("summary", {}).get("errors") == 0
        and saved_graph.exists()
        and saved_project.exists()
        and saved_context.exists()
        and all(info.get("exists") for info in save_artifacts.values())
        and existing_graph_guard.returncode != 0
        and force_payload.get("verify_summary", {}).get("errors") == 0
        and all(path and Path(path).exists() for path in backup_paths)
    )
    print(f"bootstrap_save_ok={bootstrap_save_ok}")
    print(f"bootstrap_save_no_confirm_guard_ok={no_confirm_save.returncode != 0}")
    print(f"bootstrap_save_dirty_guard_ok={dirty_guard_save.returncode != 0}")
    print(f"bootstrap_save_existing_graph_guard_ok={existing_graph_guard.returncode != 0}")
    print(f"bootstrap_save_force_backup_ok={all(path and Path(path).exists() for path in backup_paths)}")
    if not bootstrap_save_ok:
        print("no_confirm", no_confirm_save.returncode, no_confirm_save.stderr, file=sys.stderr)
        print("dirty_guard", dirty_guard_save.returncode, dirty_guard_save.stderr, file=sys.stderr)
        print("bootstrap_save", bootstrap_save.stdout, bootstrap_save.stderr, file=sys.stderr)
        print("existing_graph_guard", existing_graph_guard.returncode, existing_graph_guard.stderr, file=sys.stderr)
        print("force_save", force_save.stdout, force_save.stderr, file=sys.stderr)
        raise SystemExit(1)

    print("== remediation hints ==")
    remediation_dir = tmp_root / "remediation_hints_missing_check"
    copy_reference_fixture(reference_bot, remediation_dir)
    remediation_graph_path = remediation_dir / ".botctl" / "graph.desired.yaml"
    remediation_graph = load_yaml(remediation_graph_path)
    for check in remediation_graph["ux_structure"]["checks"]:
        if check.get("id") == "global_error_handler":
            check["status"] = "missing"
            check["evidence_nodes"] = []
            break
    dump_yaml(remediation_graph_path, remediation_graph)
    run(botctl + ["snapshot", "--project", str(remediation_dir)], cwd=control_root)
    remediation_context_path = remediation_dir / ".botctl" / "agent_context.json"
    remediation_context = json.loads(remediation_context_path.read_text(encoding="utf-8"))
    remediation_hints = remediation_context.get("remediation_hints", [])
    global_error_hint = next((h for h in remediation_hints if h.get("check_id") == "global_error_handler"), None)
    remediation_markdown = (remediation_dir / ".botctl" / "agent_context.md").read_text(encoding="utf-8")
    remediation_hints_ok = bool(global_error_hint) and "Application.add_error_handler" in " ".join(global_error_hint.get("suggested_evidence", []))
    remediation_markdown_ok = "Что добавить для пропущенных UX-проверок" in remediation_markdown
    inspect_agent = run(botctl + ["inspect", "--project", str(remediation_dir), "--format", "agent"], cwd=control_root, expect_ok=False)
    inspect_agent_payload = json.loads(inspect_agent.stdout)
    inspect_agent_hints = inspect_agent_payload.get("remediation_hints", [])
    inspect_agent_global_error_hint = next((h for h in inspect_agent_hints if h.get("check_id") == "global_error_handler"), None)
    inspect_agent_hints_ok = bool(inspect_agent_payload.get("generated_agent_context", {}).get("exists")) and bool(inspect_agent_global_error_hint)
    print(f"remediation_hints_ok={remediation_hints_ok}")
    print(f"remediation_markdown_ok={remediation_markdown_ok}")
    print(f"inspect_agent_remediation_hints_ok={inspect_agent_hints_ok}")
    if not remediation_hints_ok or not remediation_markdown_ok or not inspect_agent_hints_ok:
        print(json.dumps({"snapshot_hints": remediation_hints, "inspect_agent_hints": inspect_agent_hints}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1)

    print("== negative checks ==")
    def bad_edge(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data["edges"][0]["to"] = "missing.node"
        dump_yaml(graph_path, data)

    def bad_title(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data["nodes"][0]["title"] = "product.tg_vk_reposter"
        dump_yaml(graph_path, data)

    def missing_affected_node(case_dir: Path) -> None:
        plan_path = case_dir / ".botctl" / "change_plans" / "example.yaml"
        data = load_yaml(plan_path)
        data["affected_nodes"][0] = "missing.node"
        dump_yaml(plan_path, data)

    def missing_rollback(case_dir: Path) -> None:
        plan_path = case_dir / ".botctl" / "change_plans" / "example.yaml"
        data = load_yaml(plan_path)
        data.pop("rollback", None)
        dump_yaml(plan_path, data)

    def missing_artifact_policy(case_dir: Path) -> None:
        project_path = case_dir / ".botctl" / "project.yaml"
        data = load_yaml(project_path)
        data.pop("artifact_policy", None)
        dump_yaml(project_path, data)

    def bad_generated_ux(case_dir: Path) -> None:
        context_path = case_dir / ".botctl" / "agent_context.json"
        data = json.loads(context_path.read_text(encoding="utf-8"))
        data["allowed_next_actions"][0]["title"] = "action.inspect"
        context_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def missing_ux_structure(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data.pop("ux_structure", None)
        dump_yaml(graph_path, data)

    def bad_ux_section_node(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data["ux_structure"]["sections"][0]["nodes"][0] = "missing.node"
        dump_yaml(graph_path, data)

    def missing_ux_checks(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data["ux_structure"].pop("checks", None)
        dump_yaml(graph_path, data)

    def bad_ux_check_source(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data["ux_structure"]["checks"][0]["source"] = "fantasy"
        dump_yaml(graph_path, data)

    def missing_required_ux_check(case_dir: Path) -> None:
        graph_path = case_dir / ".botctl" / "graph.desired.yaml"
        data = load_yaml(graph_path)
        data["ux_structure"]["checks"] = [c for c in data["ux_structure"]["checks"] if c.get("id") != "global_error_handler"]
        dump_yaml(graph_path, data)

    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "bad_edge_endpoint", "bad_edge_endpoint", bad_edge)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "bad_russian_title", "bad_russian_title", bad_title)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "missing_affected_node", "missing_affected_node", missing_affected_node)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "missing_rollback", "missing_rollback", missing_rollback)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "missing_artifact_policy", "artifact_policy_missing_authored", missing_artifact_policy)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "bad_generated_ux", "bad_action_title", bad_generated_ux)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "missing_ux_structure", "missing_ux_sections", missing_ux_structure)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "bad_ux_section_node", "bad_ux_section_node", bad_ux_section_node)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "missing_ux_checks", "missing_ux_checks", missing_ux_checks)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "bad_ux_check_source", "bad_ux_check_source", bad_ux_check_source)
    assert_negative_case(control_root, botctl, reference_bot, tmp_root, "missing_required_ux_check", "missing_required_ux_check", missing_required_ux_check)

    print("== aiogram evidence checks ==")
    aiogram_dir = tmp_root / "aiogram_positive"
    if aiogram_dir.exists():
        shutil.rmtree(aiogram_dir)
    (aiogram_dir / "app").mkdir(parents=True)
    (aiogram_dir / "app" / "main.py").write_text(
        "import os\n"
        "import logging\n"
        "from aiogram import Bot, Dispatcher\n"
        "from aiogram.types import BotCommand\n"
        "from app.handlers import BotApp\n"
        "logging.basicConfig(level=logging.INFO)\n"
        "async def run():\n"
        "    token = os.getenv('TELEGRAM_BOT_TOKEN')\n"
        "    bot = Bot(token=token)\n"
        "    dispatcher = Dispatcher()\n"
        "    app = BotApp()\n"
        "    app.setup(dispatcher)\n"
        "    await bot.set_my_commands([BotCommand(command='start', description='start')])\n"
        "    await dispatcher.start_polling(bot)\n",
        encoding="utf-8",
    )
    (aiogram_dir / "app" / "handlers.py").write_text(
        "import asyncio\n"
        "import logging\n"
        "from aiogram import F, Router, Dispatcher\n"
        "from aiogram.filters import Command\n"
        "from aiogram.types import Message, CallbackQuery, ErrorEvent\n"
        "from app.keyboards import start_keyboard\n"
        "logger = logging.getLogger(__name__)\n"
        "class Storage: pass\n"
        "class DraftStore: pass\n"
        "class RuntimePreferences: pass\n"
        "class StatusMessage: pass\n"
        "class BotApp:\n"
        "    def __init__(self):\n"
        "        self.router = Router(name='demo')\n"
        "        self._processing_audio = False\n"
        "        self._active_drafts = set()\n"
        "        self.storage = Storage()\n"
        "        self.drafts = DraftStore()\n"
        "        self.preferences = RuntimePreferences()\n"
        "        self._register_handlers()\n"
        "    def setup(self, dispatcher: Dispatcher):\n"
        "        dispatcher.include_router(self.router)\n"
        "    def _register_handlers(self):\n"
        "        self.router.errors.register(self.global_error)\n"
        "        self.router.message(Command('start'))(self.start)\n"
        "        self.router.message(Command('help'))(self.help)\n"
        "        self.router.message(F.voice | F.audio)(self.handle_audio)\n"
        "        self.router.callback_query(F.data.startswith('publish:'))(self.publish)\n"
        "        self.router.message()(self.fallback)\n"
        "    async def global_error(self, event: ErrorEvent):\n"
        "        logger.error('Unhandled', exc_info=True)\n"
        "        return True\n"
        "    async def fallback(self, message: Message):\n"
        "        await message.answer('unknown input fallback', reply_markup=start_keyboard())\n"
        "    async def start(self, message: Message):\n"
        "        await message.answer('/start ok', reply_markup=start_keyboard())\n"
        "    async def help(self, message: Message):\n"
        "        await message.answer('help')\n"
        "    async def handle_audio(self, message: Message):\n"
        "        if self._processing_audio:\n"
        "            await message.answer('уже обрабатываю, дождись')\n"
        "            return\n"
        "        self._processing_audio = True\n"
        "        status = StatusMessage()\n"
        "        await asyncio.wait_for(asyncio.sleep(0), timeout=30)\n"
        "        self.storage.save_result('draft', 'text')\n"
        "        self._processing_audio = False\n"
        "    async def publish(self, query: CallbackQuery):\n"
        "        draft = self.storage.load_result('draft')\n"
        "        if draft is None:\n"
        "            await query.answer('Черновик не найден')\n"
        "        await query.answer('ok')\n",
        encoding="utf-8",
    )
    (aiogram_dir / "app" / "keyboards.py").write_text(
        "from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup\n"
        "def start_keyboard():\n"
        "    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Go', callback_data='menu:start')]])\n",
        encoding="utf-8",
    )
    aiogram_signals = discover_ux_evidence(aiogram_dir).get("signals", {})
    required_aiogram_signals = {
        "command_design", "start_onboarding", "inline_keyboard_layout", "unknown_input_fallback",
        "progress_status", "human_readable_errors", "empty_states", "rate_limiting",
        "persistent_user_state", "global_error_handler", "token_env_safety",
        "analytics_or_observability", "webhook_or_polling_model",
    }
    aiogram_positive_ok = required_aiogram_signals.issubset(set(aiogram_signals))
    print(f"aiogram_positive_ok={aiogram_positive_ok}")
    if not aiogram_positive_ok:
        print(sorted(aiogram_signals), file=sys.stderr)
        raise SystemExit(1)

    aiogram_false_dir = tmp_root / "aiogram_false_positive_local_names"
    if aiogram_false_dir.exists():
        shutil.rmtree(aiogram_false_dir)
    (aiogram_false_dir / "app").mkdir(parents=True)
    (aiogram_false_dir / "app" / "main.py").write_text(
        "class Dispatcher:\n"
        "    def start_polling(self):\n"
        "        return None\n"
        "class Router:\n"
        "    def message(self, value=None):\n"
        "        return lambda handler: handler\n"
        "    def callback_query(self, value=None):\n"
        "        return lambda handler: handler\n"
        "class Command:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "class BotCommand:\n"
        "    def __init__(self, command, description):\n"
        "        self.command = command\n"
        "def configure():\n"
        "    router = Router()\n"
        "    router.message(Command('start'))(lambda: None)\n"
        "    router.callback_query('x')(lambda: None)\n"
        "    dispatcher = Dispatcher()\n"
        "    dispatcher.start_polling()\n"
        "    BotCommand(command='start', description='local')\n",
        encoding="utf-8",
    )
    aiogram_false_signals = discover_ux_evidence(aiogram_false_dir).get("signals", {})
    aiogram_false_positive_ok = not ({"command_design", "start_onboarding", "webhook_or_polling_model"} & set(aiogram_false_signals))
    print(f"aiogram_false_positive_local_names_ok={aiogram_false_positive_ok}")
    if not aiogram_false_positive_ok:
        print(aiogram_false_signals, file=sys.stderr)
        raise SystemExit(1)

    print("== AST false-positive checks ==")
    false_positive_dir = tmp_root / "ast_false_positive_comments"
    if false_positive_dir.exists():
        shutil.rmtree(false_positive_dir)
    (false_positive_dir / "src").mkdir(parents=True)
    (false_positive_dir / "src" / "app.py").write_text(
        "# add_error_handler should not count from a comment\n"
        "# CommandHandler should not count from a comment\n"
        "# run_polling should not count from a comment\n"
        "def unrelated():\n"
        "    text = 'InlineKeyboardMarkup in a string is also not a Telegram UX implementation'\n"
        "    return text\n",
        encoding="utf-8",
    )
    false_evidence = discover_ux_evidence(false_positive_dir)
    false_signals = false_evidence.get("signals", {})
    false_positive_ok = not ({"global_error_handler", "command_design", "webhook_or_polling_model", "inline_keyboard_layout"} & set(false_signals))
    print(f"ast_false_positive_comments_ok={false_positive_ok}")
    if not false_positive_ok:
        print(false_signals, file=sys.stderr)
        raise SystemExit(1)

    custom_method_dir = tmp_root / "ast_false_positive_custom_methods"
    if custom_method_dir.exists():
        shutil.rmtree(custom_method_dir)
    (custom_method_dir / "src").mkdir(parents=True)
    (custom_method_dir / "src" / "app.py").write_text(
        "class LocalRegistry:\n"
        "    def add_handler(self, value):\n"
        "        return value\n"
        "    def add_error_handler(self, value):\n"
        "        return value\n"
        "\n"
        "def configure():\n"
        "    '''Docstring mentions app.add_handler and app.add_error_handler.'''\n"
        "    registry = LocalRegistry()\n"
        "    registry.add_handler('not telegram')\n"
        "    registry.add_error_handler('not telegram')\n"
        "    return registry\n",
        encoding="utf-8",
    )
    custom_method_evidence = discover_ux_evidence(custom_method_dir)
    custom_method_signals = custom_method_evidence.get("signals", {})
    custom_methods_ok = not ({"command_design", "global_error_handler"} & set(custom_method_signals))
    print(f"ast_false_positive_custom_methods_ok={custom_methods_ok}")
    if not custom_methods_ok:
        print(custom_method_signals, file=sys.stderr)
        raise SystemExit(1)

    ambiguous_short_names_dir = tmp_root / "ast_false_positive_ambiguous_short_names"
    if ambiguous_short_names_dir.exists():
        shutil.rmtree(ambiguous_short_names_dir)
    (ambiguous_short_names_dir / "src").mkdir(parents=True)
    (ambiguous_short_names_dir / "src" / "app.py").write_text(
        "class LocalClock:\n"
        "    def sleep(self):\n"
        "        return None\n"
        "\n"
        "class os:\n"
        "    @staticmethod\n"
        "    def getenv(name):\n"
        "        return 'not process env'\n"
        "\n"
        "class logging:\n"
        "    @staticmethod\n"
        "    def getLogger(name):\n"
        "        return logging()\n"
        "    def error(self, message):\n"
        "        return message\n"
        "    def exception(self, message):\n"
        "        return message\n"
        "\n"
        "class Application:\n"
        "    @staticmethod\n"
        "    def builder():\n"
        "        return Application()\n"
        "    def run_polling(self):\n"
        "        return None\n"
        "\n"
        "def configure():\n"
        "    clock = LocalClock()\n"
        "    clock.sleep()\n"
        "    os.getenv('LOCAL_VALUE')\n"
        "    log = logging.getLogger('local')\n"
        "    log.error('local error')\n"
        "    log.exception('local exception')\n"
        "    Application.builder().run_polling()\n",
        encoding="utf-8",
    )
    ambiguous_evidence = discover_ux_evidence(ambiguous_short_names_dir)
    ambiguous_signals = ambiguous_evidence.get("signals", {})
    ambiguous_short_names_ok = not (
        {"rate_limiting", "token_env_safety", "human_readable_errors", "analytics_or_observability", "webhook_or_polling_model"}
        & set(ambiguous_signals)
    )
    print(f"ast_false_positive_ambiguous_short_names_ok={ambiguous_short_names_ok}")
    if not ambiguous_short_names_ok:
        print(ambiguous_signals, file=sys.stderr)
        raise SystemExit(1)

    lower_risk_short_names_dir = tmp_root / "ast_false_positive_lower_risk_short_names"
    if lower_risk_short_names_dir.exists():
        shutil.rmtree(lower_risk_short_names_dir)
    (lower_risk_short_names_dir / "src").mkdir(parents=True)
    (lower_risk_short_names_dir / "src" / "app.py").write_text(
        "class MessageHandler:\n"
        "    pass\n"
        "class CommandHandler:\n"
        "    pass\n"
        "class CallbackQueryHandler:\n"
        "    pass\n"
        "class InlineKeyboardMarkup:\n"
        "    pass\n"
        "class InlineKeyboardButton:\n"
        "    def __init__(self, text, callback_data=None):\n"
        "        self.callback_data = callback_data\n"
        "\n"
        "class Worker:\n"
        "    def write_heartbeat(self):\n"
        "        return None\n"
        "    def send_chat_action(self):\n"
        "        return None\n"
        "\n"
        "def configure():\n"
        "    MessageHandler()\n"
        "    CommandHandler('start')\n"
        "    CallbackQueryHandler()\n"
        "    InlineKeyboardMarkup()\n"
        "    InlineKeyboardButton('x', callback_data='local')\n"
        "    worker = Worker()\n"
        "    worker.write_heartbeat()\n"
        "    worker.send_chat_action()\n",
        encoding="utf-8",
    )
    lower_risk_evidence = discover_ux_evidence(lower_risk_short_names_dir)
    lower_risk_signals = lower_risk_evidence.get("signals", {})
    lower_risk_short_names_ok = not ({"command_design", "inline_keyboard_layout", "progress_status"} & set(lower_risk_signals))
    print(f"ast_false_positive_lower_risk_short_names_ok={lower_risk_short_names_ok}")
    if not lower_risk_short_names_ok:
        print(lower_risk_signals, file=sys.stderr)
        raise SystemExit(1)

    shutil.rmtree(tmp_root)
    print("botctl_v0_smoke=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
