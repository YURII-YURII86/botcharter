from __future__ import annotations

import argparse
import json
import jsonschema
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .audit import audit_runtime_source
from .runtime_probe import probe_local_runtime
from .http_probe import probe_http_health
from .sqlite_probe import probe_sqlite_integrity
from .adopt import planned_adoption_paths, write_adoption_support
from . import __version__
from .design import compare_menu_design, create_design_change_plan, critique_menu_map, design_from_brief, design_gate_status, design_status_readiness, extract_menu_map, implementation_plan_from_proposal, normalize_menu_design, update_design_artifact_status, update_design_change_plan_status, validate_design_artifact_semantics, validate_design_brief, validate_design_change_plan, write_design_init_system
from .discover import discover_local, discover_ux_evidence, load_desired
from .model import (
    API_VERSION,
    STATUS_LABELS,
    dump_json,
    load_json,
    load_yaml,
    now_iso,
    project_control,
    relative,
)
from .validate import validate_graph, verify_project
from .schema import control_layer_root, validate_against_schema

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def _project_path(raw: str | None) -> Path:
    return Path(raw or ".").expanduser().resolve()


def _control_artifacts(project: Path) -> dict[str, Any]:
    control = project_control(project)
    names = [
        "project.yaml",
        "graph.desired.yaml",
        "architecture.brief.json",
        "graph.observed.json",
        "drift.report.json",
        "agent_context.json",
        "agent_context.md",
    ]
    return {
        name: {
            "path": str(control / name),
            "exists": (control / name).exists(),
        }
        for name in names
    }


def _load_project_metadata(project: Path) -> dict[str, Any]:
    path = project_control(project) / "project.yaml"
    if not path.exists():
        return {}
    try:
        data = load_yaml(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_generated_agent_context(project: Path) -> dict[str, Any]:
    path = project_control(project) / "agent_context.json"
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _bootstrap_hints(project: Path) -> dict[str, Any]:
    observed = discover_local(project)
    ux_evidence = _extract_observed_ux_evidence(project, observed)
    python_modules = [finding for finding in observed.get("findings", []) if isinstance(finding, dict) and finding.get("type") == "python_module"]
    project_files = [finding for finding in observed.get("findings", []) if isinstance(finding, dict) and finding.get("type") == "project_file"]
    signals = ux_evidence.get("signals", {}) if isinstance(ux_evidence, dict) else {}
    return {
        "needed": not (project_control(project) / "graph.desired.yaml").exists(),
        "read_only": True,
        "suggested_next_step": "Создать .botctl/graph.desired.yaml по найденным modules/signals, затем выполнить snapshot/verify.",
        "project_files": project_files,
        "python_modules": python_modules[:40],
        "observed_ux_signal_ids": sorted(signals.keys()) if isinstance(signals, dict) else [],
        "observed_ux_evidence": ux_evidence,
    }


def _inspect_payload(project: Path, agent_mode: bool = False) -> dict[str, Any]:
    issues, summary = verify_project(project)
    project_meta = _load_project_metadata(project)
    artifacts = _control_artifacts(project)
    errors = [i.to_dict() for i in issues if i.level == "error"]
    warnings = [i.to_dict() for i in issues if i.level == "warning"]
    safe_next_actions = [
        {
            "id": "action.create_snapshot",
            "title": "Обновить снимок архитектуры",
            "command": f"python tools/botctl.py snapshot --project {project}",
            "risk_level": "low",
            "approval_level": "agent_self_check",
        },
        {
            "id": "action.verify_project",
            "title": "Проверить архитектурный контракт",
            "command": f"python tools/botctl.py verify --project {project}",
            "risk_level": "low",
            "approval_level": "none",
        },
    ]
    blocked_actions = [
        {
            "id": "action.apply_runtime_change",
            "title": "Изменить runtime",
            "reason": "v0 не поддерживает apply и runtime-probe; нужен утверждённый ChangePlan будущей версии.",
            "required_before": ["Создать ChangePlan", "Получить human_approval", "Добавить read-only runtime-probe"],
        }
    ]
    bootstrap = _bootstrap_hints(project) if not artifacts.get("graph.desired.yaml", {}).get("exists") else None
    payload: dict[str, Any] = {
        "apiVersion": API_VERSION,
        "command": "inspect",
        "read_only": True,
        "generated_at": now_iso(),
        "project_path": str(project),
        "project": {
            "id": project_meta.get("id"),
            "title": project_meta.get("title") or project.name,
            "language": project_meta.get("language"),
            "primary_user": project_meta.get("primary_user"),
            "human_user": project_meta.get("human_user"),
        },
        "artifacts": artifacts,
        "status": {
            "valid": summary.get("errors", 0) == 0,
            "errors": summary.get("errors", 0),
            "warnings": summary.get("warnings", 0),
            "checked_change_plans": summary.get("checked_change_plans", 0),
        },
        "issues": {"errors": errors, "warnings": warnings},
        "safe_next_actions": safe_next_actions,
        "blocked_actions": blocked_actions,
    }
    if bootstrap is not None:
        payload["bootstrap_hints"] = bootstrap
    if agent_mode:
        generated_context = _load_generated_agent_context(project)
        payload["mode"] = "brief"
        payload["generated_agent_context"] = {
            "path": str(project_control(project) / "agent_context.json"),
            "exists": bool(generated_context),
            "kind": generated_context.get("kind"),
            "generated_at": generated_context.get("generated_at"),
        }
        if generated_context:
            payload["summary"] = generated_context.get("summary", {})
            payload["ux_structure"] = generated_context.get("ux_structure", {})
            payload["remediation_hints"] = generated_context.get("remediation_hints", [])
            payload["full_artifacts"] = generated_context.get("full_artifacts", {})
        else:
            payload["remediation_hints"] = []
        if bootstrap is not None:
            payload["bootstrap_hints"] = bootstrap
        payload["rules"] = [
            "inspect всегда read-only и не пишет файлы",
            "runtime нельзя менять без ChangePlan и human_approval",
            "реальные .env, токены и credentials нельзя читать или раскрывать",
            "inferred/candidate не являются основанием для apply",
        ]
    return payload


def _slug(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or fallback


def _yaml_text(data: Any) -> str:
    if yaml is None:
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _best_module_title(path: str) -> str:
    stem = Path(path).stem.replace("_", " ").replace("-", " ").strip()
    return f"Модуль {stem or path}"


def build_bootstrap_graph_draft(project: Path) -> dict[str, Any]:
    bootstrap = _bootstrap_hints(project)
    signal_ids = set(bootstrap.get("observed_ux_signal_ids", []) or [])
    project_slug = _slug(project.name, "telegram_bot")
    product_id = f"product.{project_slug}"
    capability_id = "capability.telegram_bot_core"
    flow_id = "flow.main_user_interaction"
    nodes: list[dict[str, Any]] = [
        {
            "id": product_id,
            "kind": "Product",
            "layer": "L0",
            "title": f"Telegram-бот {project.name}",
            "description": "Черновик паспорта проекта, сгенерированный по безопасному локальному осмотру кода.",
            "lifecycle_status": "active",
            "knowledge_status": "inferred",
            "confidence": "medium",
            "source": {"type": "bootstrap-preview"},
            "risk_level": "medium",
            "change_control": {"approval_level": "human_review"},
        },
        {
            "id": capability_id,
            "kind": "Capability",
            "layer": "L1",
            "title": "Основная способность Telegram-бота",
            "description": "Черновая способность, которую нужно уточнить человеком после просмотра найденных обработчиков и сценариев.",
            "lifecycle_status": "active",
            "knowledge_status": "inferred",
            "confidence": "medium",
            "source": {"type": "bootstrap-preview"},
            "risk_level": "medium",
        },
        {
            "id": flow_id,
            "kind": "Flow",
            "layer": "L2",
            "title": "Основной пользовательский сценарий",
            "description": "Черновой сценарий взаимодействия пользователя с ботом, выведенный из локальных признаков handlers и UX evidence.",
            "lifecycle_status": "active",
            "knowledge_status": "inferred",
            "confidence": "medium",
            "source": {"type": "bootstrap-preview"},
            "risk_level": "medium",
        },
    ]
    handler_ids: list[str] = []
    for module in bootstrap.get("python_modules", [])[:12]:
        if not isinstance(module, dict) or not module.get("path"):
            continue
        rel = str(module["path"])
        handler_id = f"handler.{_slug(Path(rel).with_suffix('').as_posix(), 'module')}"
        handler_ids.append(handler_id)
        nodes.append(
            {
                "id": handler_id,
                "kind": "Handler",
                "layer": "L3",
                "title": _best_module_title(rel),
                "description": "Python-модуль, найденный безопасным bootstrap-осмотром. Роль нужно подтвердить при ручном оформлении паспорта.",
                "lifecycle_status": "active",
                "knowledge_status": "inferred",
                "confidence": "medium",
                "source": {"type": "bootstrap-preview"},
                "risk_level": "medium",
                "evidence": [{"type": "code", "path": rel}],
            }
        )
    config_id = "config.telegram_token"
    nodes.append(
        {
            "id": config_id,
            "kind": "ConfigRef",
            "layer": "L4",
            "title": "Ссылка на токен Telegram",
            "description": "Секретный токен должен храниться вне графа и проекта как env/secret reference; сам токен не читается и не выводится.",
            "lifecycle_status": "active",
            "knowledge_status": "inferred" if "token_env_safety" in signal_ids else "candidate",
            "confidence": "medium" if "token_env_safety" in signal_ids else "low",
            "source": {"type": "bootstrap-preview"},
            "risk_level": "critical",
        }
    )
    trace_id = "trace.local_logs"
    nodes.append(
        {
            "id": trace_id,
            "kind": "TraceSink",
            "layer": "L6",
            "title": "Локальные логи и наблюдаемость",
            "description": "Черновой узел наблюдаемости по найденным logging/health/heartbeat признакам.",
            "lifecycle_status": "active",
            "knowledge_status": "inferred" if "analytics_or_observability" in signal_ids else "candidate",
            "confidence": "medium" if "analytics_or_observability" in signal_ids else "low",
            "source": {"type": "bootstrap-preview"},
            "risk_level": "low",
        }
    )
    policy_id = "policy.no_secret_leak"
    nodes.append(
        {
            "id": policy_id,
            "kind": "Policy",
            "layer": "L6",
            "title": "Запрет раскрытия секретов",
            "description": "Агент не читает и не выводит реальные токены, ключи, session-файлы и runtime-секреты.",
            "lifecycle_status": "active",
            "knowledge_status": "confirmed",
            "confidence": "high",
            "source": {"type": "bootstrap-preview"},
            "risk_level": "critical",
        }
    )
    project_file_paths = [str(item.get("path")) for item in bootstrap.get("project_files", []) if isinstance(item, dict)]
    deploy_id = "deploy.local_runtime"
    if any(path in {"Dockerfile", "compose.yml", "docker-compose.yml", "Makefile"} for path in project_file_paths):
        nodes.append(
            {
                "id": deploy_id,
                "kind": "DeployTarget",
                "layer": "L4",
                "title": "Локальная модель запуска",
                "description": "Черновой узел запуска по найденным Docker/Compose/Makefile признакам; runtime не проверялся.",
                "lifecycle_status": "active",
                "knowledge_status": "candidate",
                "confidence": "medium",
                "source": {"type": "bootstrap-preview"},
                "risk_level": "high",
            }
        )
    edges: list[dict[str, Any]] = [
        {"id": "edge.product_contains_core", "from": product_id, "to": capability_id, "type": "contains", "title": "Продукт содержит основную способность", "confidence": "medium", "source": {"type": "bootstrap-preview"}},
        {"id": "edge.core_implemented_by_flow", "from": capability_id, "to": flow_id, "type": "implements", "title": "Способность реализуется основным сценарием", "confidence": "medium", "source": {"type": "bootstrap-preview"}},
        {"id": "edge.flow_requires_token", "from": flow_id, "to": config_id, "type": "requires", "title": "Сценарий требует ссылку на Telegram token", "confidence": "medium", "source": {"type": "bootstrap-preview"}},
        {"id": "edge.secrets_guarded_by_policy", "from": config_id, "to": policy_id, "type": "guards", "title": "Секреты защищены политикой нераскрытия", "confidence": "high", "source": {"type": "bootstrap-preview"}},
        {"id": "edge.flow_traced_by_logs", "from": flow_id, "to": trace_id, "type": "traced_by", "title": "Сценарий наблюдается через логи", "confidence": "medium", "source": {"type": "bootstrap-preview"}},
    ]
    for index, handler_id in enumerate(handler_ids[:12], start=1):
        edges.append(
            {
                "id": f"edge.flow_uses_handler_{index}",
                "from": flow_id,
                "to": handler_id,
                "type": "uses",
                "title": "Сценарий использует найденный модуль",
                "confidence": "medium",
                "source": {"type": "bootstrap-preview"},
            }
        )
    if any(node.get("id") == deploy_id for node in nodes):
        edges.append({"id": "edge.product_deployed_to_local_runtime", "from": product_id, "to": deploy_id, "type": "deployed_to", "title": "Бот связан с локальной моделью запуска", "confidence": "medium", "source": {"type": "bootstrap-preview"}})
    check_evidence_by_signal = {
        "command_design": [flow_id] + handler_ids[:2],
        "start_onboarding": [flow_id] + handler_ids[:1],
        "inline_keyboard_layout": [flow_id] + handler_ids[:1],
        "unknown_input_fallback": [flow_id] + handler_ids[:1],
        "progress_status": [flow_id, trace_id],
        "human_readable_errors": [trace_id, policy_id],
        "empty_states": [flow_id],
        "rate_limiting": [flow_id],
        "persistent_user_state": [flow_id],
        "global_error_handler": [flow_id, trace_id],
        "token_env_safety": [config_id, policy_id],
        "analytics_or_observability": [trace_id],
        "webhook_or_polling_model": [deploy_id if any(node.get("id") == deploy_id for node in nodes) else flow_id],
    }
    ux_checks: list[dict[str, Any]] = []
    for check_id, base in UX_REMEDIATION_HINTS.items():
        evidence_nodes = [node_id for node_id in check_evidence_by_signal.get(check_id, [flow_id]) if any(node.get("id") == node_id for node in nodes)]
        covered = check_id in signal_ids and bool(evidence_nodes)
        ux_checks.append(
            {
                "id": check_id,
                "title": base["title"],
                "status": "covered" if covered else "planned",
                "source": "telegram-video-jobs-case" if check_id in {"progress_status", "human_readable_errors"} else "telegram-bot-builder",
                "why": base["why"],
                "evidence_nodes": evidence_nodes if covered else [],
            }
        )
    ux_sections = [
        {
            "id": "ux.section.main_flow",
            "title": "Основной сценарий бота",
            "purpose": "Показывает человеку и агенту главный путь: пользовательское событие обрабатывается Telegram-ботом.",
            "nodes": [product_id, capability_id, flow_id] + handler_ids[:5],
            "primary_actions": [
                {"id": "ux.action.review_main_flow", "title": "Проверить основной сценарий", "node": flow_id, "expected_result": "Понятно, какие найденные модули участвуют в работе бота."}
            ],
        },
        {
            "id": "ux.section.safety_and_runtime",
            "title": "Безопасность и границы запуска",
            "purpose": "Фиксирует секреты, наблюдаемость и границу read-only осмотра, чтобы агент не трогал runtime вслепую.",
            "nodes": [config_id, trace_id, policy_id] + ([deploy_id] if any(node.get("id") == deploy_id for node in nodes) else []),
            "primary_actions": [
                {"id": "ux.action.protect_secrets", "title": "Проверить защиту секретов", "node": policy_id, "expected_result": "Понятно, какие секреты нельзя читать, выводить или коммитить."}
            ],
        },
    ]
    return {
        "apiVersion": API_VERSION,
        "kind": "BotArchitectureGraph",
        "id": f"{project_slug}_graph_draft",
        "title": f"Черновой паспорт Telegram-бота {project.name}",
        "draft_notice": "Сгенерировано командой bootstrap-preview read-only. Перед сохранением в .botctl/graph.desired.yaml человек или агент должен уточнить названия, сценарии и риски.",
        "nodes": nodes,
        "ux_structure": {"sections": ux_sections, "checks": ux_checks},
        "edges": edges,
    }


def _print_human_inspect(payload: dict[str, Any]) -> None:
    project = payload.get("project", {})
    status = payload.get("status", {})
    print("Botctl inspect — read-only проверка проекта")
    print(f"Проект: {project.get('title') or 'Неизвестный проект'}")
    print(f"Путь: {payload.get('project_path')}")
    print(f"Статус: {'валиден' if status.get('valid') else 'есть ошибки'}")
    print(f"Ошибки: {status.get('errors', 0)}, предупреждения: {status.get('warnings', 0)}")
    print("\nАртефакты:")
    for name, info in payload.get("artifacts", {}).items():
        marker = "✓" if info.get("exists") else "–"
        print(f"  {marker} {name}")
    if payload.get("issues", {}).get("errors"):
        print("\nОшибки:")
        for issue in payload["issues"]["errors"][:20]:
            print(f"  - {issue['code']}: {issue['message']}")
    print("\nБезопасные следующие действия:")
    for action in payload.get("safe_next_actions", []):
        print(f"  - {action['title']}: {action['command']}")
    print("\nЗаблокированные действия:")
    for action in payload.get("blocked_actions", []):
        print(f"  - {action['title']}: {action['reason']}")


def command_inspect(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    payload = _inspect_payload(project, agent_mode=args.format == "agent")
    if args.format == "human":
        _print_human_inspect(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"]["errors"] == 0 else 2


def _binding_statuses_for_node(project: Path, node: dict[str, Any]) -> list[dict[str, Any]]:
    bindings = node.get("bindings") or {}
    binding_items: list[dict[str, Any]] = []
    for binding in [
        node.get("code_binding"),
        bindings.get("code"),
        bindings.get("test"),
        bindings.get("config"),
    ]:
        if isinstance(binding, dict) and binding.get("path"):
            binding_items.append(binding)
    for evidence in node.get("evidence", []) or []:
        if not isinstance(evidence, dict):
            continue
        if evidence.get("path"):
            binding_items.append(evidence)
        elif evidence.get("command"):
            binding_items.append({"command": evidence.get("command")})
    statuses: list[dict[str, Any]] = []
    for binding in binding_items:
        command_value = binding.get("command")
        if command_value and not binding.get("path"):
            exists = str(command_value).startswith("make") and (project / "Makefile").exists()
            statuses.append({
                "path": str(command_value),
                "exists": exists,
                "status": "in_sync" if exists else "missing_local",
                "status_label": STATUS_LABELS["in_sync"] if exists else STATUS_LABELS["missing_local"],
            })
            continue
        path_value = str(binding.get("path"))
        path = project / path_value
        statuses.append({
            "path": path_value,
            "exists": path.exists(),
            "status": "in_sync" if path.exists() else "missing_local",
            "status_label": STATUS_LABELS["in_sync"] if path.exists() else STATUS_LABELS["missing_local"],
        })
    return statuses

def build_drift(project: Path, observed: dict[str, Any]) -> dict[str, Any]:
    desired = load_desired(project)
    items: list[dict[str, Any]] = []
    for node in desired.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        for binding in _binding_statuses_for_node(project, node):
            items.append(
                {
                    "node_id": node.get("id"),
                    "title": node.get("title"),
                    "status": binding["status"],
                    "status_label": binding["status_label"],
                    "path": binding["path"],
                }
            )
    summary = {
        "in_sync": sum(1 for item in items if item["status"] == "in_sync"),
        "missing_local": sum(1 for item in items if item["status"] == "missing_local"),
        "missing_runtime": 0,
        "conflict": 0,
        "unknown": 0,
    }
    return {
        "apiVersion": API_VERSION,
        "kind": "DriftReport",
        "generated_at": now_iso(),
        "scope": "desired_vs_observed_local",
        "runtime_probe": {"enabled": False, "reason": "v0 не обращается к production/runtime"},
        "summary": summary,
        "items": items,
    }


def build_architecture_brief(project: Path, drift: dict[str, Any], observed: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = _load_project_metadata(project)
    ux_summary = build_ux_summary(project, observed)
    return {
        "apiVersion": API_VERSION,
        "kind": "ArchitectureBrief",
        "generated_at": now_iso(),
        "project": {
            "id": meta.get("id"),
            "title": meta.get("title") or project.name,
            "language": meta.get("language", "ru"),
        },
        "current_state": {
            "desired_graph": "present" if (project_control(project) / "graph.desired.yaml").exists() else "missing",
            "observed_local": "generated",
            "observed_runtime": "not_probed_v0",
            "drift_status": "has_missing_local" if drift.get("summary", {}).get("missing_local") else "in_sync",
            "ux_status": ux_summary.get("status"),
            "ux_status_label": ux_summary.get("status_label"),
        },
        "ux_structure": ux_summary,
        "rules": [
            "Локальная папка проекта — основной источник правды для входа агента",
            "inspect read-only и не обновляет артефакты",
            "snapshot обновляет generated artifacts",
            "runtime не трогать без отдельного read-only probe и ChangePlan",
            "Не читать и не раскрывать реальные секреты",
            "Человеко-видимые разделы, действия и статусы должны быть понятными и на русском языке",
        ],
    }




def _extract_observed_ux_evidence(project: Path, observed: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(observed, dict):
        for finding in observed.get("findings", []) or []:
            if isinstance(finding, dict) and finding.get("type") == "observed_ux_evidence":
                return finding
    return discover_ux_evidence(project)


UX_REMEDIATION_HINTS: dict[str, dict[str, Any]] = {
    "command_design": {
        "title": "Добавить явные Telegram handlers для команд",
        "why": "Агент не видит, какие команды доступны пользователю.",
        "look_in": ["src/app.py", "src/*telegram*.py", "src/*handler*.py"],
        "suggested_evidence": ["Application.add_handler(...)", "telegram.ext.CommandHandler", "telegram.ext.MessageHandler"],
    },
    "start_onboarding": {
        "title": "Описать и реализовать /start onboarding",
        "why": "Первый пользовательский сценарий не подтверждён локальным кодом.",
        "look_in": ["src/app.py", "src/*handler*.py"],
        "suggested_evidence": ["CommandHandler('start', ...)", "текст приветствия и следующий понятный шаг"],
    },
    "inline_keyboard_layout": {
        "title": "Добавить или подтвердить inline-клавиатуры",
        "why": "Нет локального признака меню/кнопок для управляемых действий.",
        "look_in": ["src/*telegram*.py", "src/*ui*.py", "src/*handler*.py"],
        "suggested_evidence": ["telegram.InlineKeyboardMarkup", "telegram.InlineKeyboardButton(..., callback_data=...)"],
    },
    "unknown_input_fallback": {
        "title": "Добавить fallback на непонятный ввод",
        "why": "Пользователь может написать неожиданный текст, а агент не видит безопасный ответ.",
        "look_in": ["src/*handler*.py", "src/app.py"],
        "suggested_evidence": ["fallback/default branch", "сообщение с подсказкой доступных действий"],
    },
    "progress_status": {
        "title": "Добавить статус долгих операций",
        "why": "Для долгих задач пользователь должен видеть прогресс или typing/status.",
        "look_in": ["src/*telegram*.py", "src/*worker*.py", "src/*queue*.py"],
        "suggested_evidence": ["context.bot.send_chat_action(...)", "write_heartbeat(...)", "queue/progress update"],
    },
    "human_readable_errors": {
        "title": "Добавить понятные ошибки для пользователя",
        "why": "Ошибки не должны выглядеть как stack trace или молчаливый сбой.",
        "look_in": ["src/*handler*.py", "src/*telegram*.py"],
        "suggested_evidence": ["try/except с пользовательским сообщением", "logging.exception(...) + безопасный reply"],
    },
    "empty_states": {
        "title": "Описать пустые состояния",
        "why": "Пустая очередь/нет данных/нет доступных элементов должны иметь понятный ответ.",
        "look_in": ["src/*store*.py", "src/*queue*.py", "src/*handler*.py"],
        "suggested_evidence": ["empty/no items branch", "skip/DLQ state handling"],
    },
    "rate_limiting": {
        "title": "Добавить защиту от rate limits",
        "why": "Telegram и внешние API могут ограничивать частоту запросов.",
        "look_in": ["src/*queue*.py", "src/*worker*.py", "src/*client*.py"],
        "suggested_evidence": ["asyncio.sleep/time.sleep", "retry/attempts", "batch/lease logic"],
    },
    "persistent_user_state": {
        "title": "Подтвердить сохранение состояния пользователя",
        "why": "Агенту нужно видеть, что состояние не теряется между сообщениями.",
        "look_in": ["src/*store*.py", "src/*state*.py", "src/*db*.py"],
        "suggested_evidence": ["SQLite/store/state DB", "user state repository"],
    },
    "global_error_handler": {
        "title": "Добавить глобальный обработчик ошибок Telegram app",
        "why": "Без global handler неожиданные ошибки могут теряться или ломать UX.",
        "look_in": ["src/app.py", "src/*telegram*.py"],
        "suggested_evidence": ["Application.add_error_handler(...)"],
    },
    "token_env_safety": {
        "title": "Подтвердить безопасное чтение токенов из env",
        "why": "Токены не должны быть зашиты в код или раскрыты в артефактах.",
        "look_in": ["src/config.py", "src/*settings*.py"],
        "suggested_evidence": ["os.getenv('...TOKEN...')", "валидация обязательных env-переменных"],
    },
    "analytics_or_observability": {
        "title": "Добавить наблюдаемость",
        "why": "Агенту и человеку нужны признаки health/logging/heartbeat.",
        "look_in": ["src/*worker*.py", "src/*health*.py", "src/app.py"],
        "suggested_evidence": ["logging.getLogger/basicConfig", "health check", "heartbeat"],
    },
    "webhook_or_polling_model": {
        "title": "Явно подтвердить polling или webhook модель",
        "why": "Способ запуска Telegram bot должен быть понятен перед deploy/debug.",
        "look_in": ["src/app.py", "compose.yml", "Dockerfile", "Makefile"],
        "suggested_evidence": ["Application.run_polling()", "Application.run_webhook()", "deploy command"],
    },
}


def _ux_remediation_hint(check_id: str, check: dict[str, Any]) -> dict[str, Any]:
    base = UX_REMEDIATION_HINTS.get(check_id, {})
    return {
        "check_id": check_id,
        "title": base.get("title") or f"Уточнить UX-check {check_id}",
        "why": base.get("why") or "Локальный скан не нашёл подтверждение для обязательного UX-check.",
        "status": check.get("status"),
        "look_in": base.get("look_in", ["src/"]),
        "suggested_evidence": base.get("suggested_evidence", []),
        "graph_source": check.get("source"),
        "evidence_nodes": check.get("evidence_nodes", []),
    }


def build_ux_summary(project: Path, observed: dict[str, Any] | None = None) -> dict[str, Any]:
    desired = load_desired(project)
    ux = desired.get("ux_structure") or {}
    observed_ux = _extract_observed_ux_evidence(project, observed)
    observed_signals = observed_ux.get("signals", {}) if isinstance(observed_ux, dict) else {}
    sections = ux.get("sections") or []
    important_nodes = {
        str(node.get("id"))
        for node in desired.get("nodes", []) or []
        if isinstance(node, dict) and node.get("kind") in {"Product", "Capability", "Flow"} and node.get("lifecycle_status") == "active"
    }
    covered_nodes: set[str] = set()
    action_count = 0
    checks = ux.get("checks") or []
    check_summaries: list[dict[str, Any]] = []
    covered_checks = 0
    missing_checks = 0
    observed_covered_checks = 0
    remediation_hints: list[dict[str, Any]] = []
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            status = check.get("status")
            observed_signal = observed_signals.get(str(check.get("id"))) if isinstance(observed_signals, dict) else None
            if observed_signal:
                observed_covered_checks += 1
            if status in {"covered", "not_applicable"} or observed_signal:
                covered_checks += 1
            if status == "missing" and not observed_signal:
                missing_checks += 1
            observed_signal = observed_signals.get(str(check.get("id"))) if isinstance(observed_signals, dict) else None
            observed_status = "observed" if observed_signal else "not_observed"
            effective_status = "observed_covered" if observed_signal else status
            summary_item = {
                "id": check.get("id"),
                "title": check.get("title"),
                "status": status,
                "effective_status": effective_status,
                "observed_status": observed_status,
                "source": check.get("source"),
                "evidence_nodes": check.get("evidence_nodes", []),
                "observed_evidence": observed_signal,
            }
            if status == "missing" and not observed_signal:
                hint = _ux_remediation_hint(str(check.get("id")), check)
                summary_item["remediation_hint"] = hint
                remediation_hints.append(hint)
            check_summaries.append(summary_item)
    section_summaries: list[dict[str, Any]] = []
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict):
            continue
        nodes = [str(node_id) for node_id in section.get("nodes", []) or []]
        covered_nodes.update(nodes)
        actions = section.get("primary_actions", []) or []
        action_count += len(actions) if isinstance(actions, list) else 0
        section_summaries.append(
            {
                "id": section.get("id"),
                "title": section.get("title"),
                "purpose": section.get("purpose"),
                "nodes": nodes,
                "primary_actions": actions,
            }
        )
    missing = sorted(important_nodes - covered_nodes)
    score = 100
    if not section_summaries:
        score -= 50
    if len(section_summaries) < 2:
        score -= 15
    score -= min(40, len(missing) * 10)
    if action_count < max(2, len(section_summaries)):
        score -= 15
    if not check_summaries:
        score -= 30
    score -= min(50, missing_checks * 10)
    if check_summaries and covered_checks < max(3, len(check_summaries) // 2):
        score -= 20
    score = max(0, score)
    if score >= 90:
        status = "strong"
        status_label = "UX-структура понятная и пригодна для управления"
    elif score >= 70:
        status = "usable"
        status_label = "UX-структура пригодна, но требует улучшений"
    else:
        status = "weak"
        status_label = "UX-структура слабая и может путать агента или человека"
    return {
        "score": score,
        "status": status,
        "status_label": status_label,
        "sections": section_summaries,
        "checks": check_summaries,
        "checks_covered": covered_checks,
        "checks_observed": observed_covered_checks,
        "checks_missing": missing_checks,
        "observed_ux_evidence": observed_ux,
        "important_nodes_covered": sorted(important_nodes & covered_nodes),
        "important_nodes_missing": missing,
        "remediation_hints": remediation_hints,
        "recommendations": [
            "Добавить русские смысловые разделы для всех Product/Capability/Flow",
            "Добавить primary_actions с понятными названиями и привязкой к узлам",
        ] if missing or score < 90 else [],
    }

def build_agent_context(project: Path, brief: dict[str, Any], drift: dict[str, Any]) -> dict[str, Any]:
    allowed_actions = [
        {
            "id": "action.inspect",
            "title": "Понять проект без изменений",
            "command": f"python tools/botctl.py inspect --project {project} --format agent",
            "risk_level": "low",
            "approval_level": "none",
        },
        {
            "id": "action.verify",
            "title": "Проверить архитектурный контракт",
            "command": f"python tools/botctl.py verify --project {project}",
            "risk_level": "low",
            "approval_level": "none",
        },
        {
            "id": "action.diff",
            "title": "Посмотреть расхождения desired и observed_local",
            "command": f"python tools/botctl.py diff --project {project}",
            "risk_level": "low",
            "approval_level": "none",
        },
    ]
    blocked_actions = [
        {
            "id": "action.runtime_apply",
            "title": "Изменить runtime или production",
            "reason": "v0 не поддерживает apply/runtime mutation; нужен утверждённый ChangePlan будущей версии.",
            "required_before": ["read-only runtime probe", "ConflictResolutionPlan при конфликте", "human_approval"],
        }
    ]
    return {
        "apiVersion": API_VERSION,
        "kind": "AgentContext",
        "mode": "brief",
        "generated_at": now_iso(),
        "project": brief.get("project", {}),
        "summary": {
            "title": "Краткий контекст для AI-агента",
            "drift": drift.get("summary", {}),
            "runtime": "не проверяется в v0",
            "ux": brief.get("ux_structure", {}),
        },
        "ux_structure": brief.get("ux_structure", {}),
        "remediation_hints": (brief.get("ux_structure", {}) or {}).get("remediation_hints", []),
        "rules": brief.get("rules", []),
        "next_actions": {"allowed": allowed_actions, "blocked": blocked_actions},
        "allowed_next_actions": allowed_actions,
        "blocked_actions": blocked_actions,
        "full_artifacts": {
            "desired_graph": ".botctl/graph.desired.yaml",
            "observed_graph": ".botctl/graph.observed.json",
            "drift_report": ".botctl/drift.report.json",
            "architecture_brief": ".botctl/architecture.brief.json",
        },
    }


def write_agent_markdown(project: Path, context: dict[str, Any], drift: dict[str, Any]) -> None:
    lines = [
        "# Контекст для AI-агента",
        "",
        f"Проект: {context.get('project', {}).get('title')}",
        "",
        "## Статус",
        f"- Runtime: {context.get('summary', {}).get('runtime')}",
        f"- Совпадает локально: {drift.get('summary', {}).get('in_sync', 0)}",
        f"- Описано, но не найдено в проекте: {drift.get('summary', {}).get('missing_local', 0)}",
        f"- UX-структура: {context.get('ux_structure', {}).get('status_label', 'не оценена')} ({context.get('ux_structure', {}).get('score', 0)}/100)",
        f"- UX-проверки подтверждены локальным сканом: {context.get('ux_structure', {}).get('checks_observed', 0)}",
        "",
        "## UX-разделы",
    ]
    for section in context.get("ux_structure", {}).get("sections", []):
        lines.append(f"- {section.get('title')}: {section.get('purpose')}")
    lines.extend([
        "",
        "## Правила",
    ])
    for rule in context.get("rules", []):
        lines.append(f"- {rule}")
    lines.extend(["", "## UX-проверки"])
    for check in context.get("ux_structure", {}).get("checks", []):
        lines.append(f"- {check.get('title')}: {check.get('effective_status', check.get('status'))}")
    hints = context.get("remediation_hints", []) or []
    if hints:
        lines.extend(["", "## Что добавить для пропущенных UX-проверок"])
        for hint in hints:
            look_in = ", ".join(hint.get("look_in", []) or [])
            evidence = ", ".join(hint.get("suggested_evidence", []) or [])
            lines.append(f"- {hint.get('title')}: {hint.get('why')} Смотреть: {look_in}. Признаки: {evidence}")
    lines.extend(["", "## Разрешённые следующие действия"])
    for action in context.get("allowed_next_actions", []):
        lines.append(f"- {action['title']}: `{action['command']}`")
    lines.extend(["", "## Заблокированные действия"])
    for action in context.get("blocked_actions", []):
        lines.append(f"- {action['title']}: {action['reason']}")
    (project_control(project) / "agent_context.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_snapshot_artifacts(project: Path) -> Path:
    control = project_control(project)
    control.mkdir(parents=True, exist_ok=True)
    observed = discover_local(project)
    drift = build_drift(project, observed)
    brief = build_architecture_brief(project, drift, observed)
    context = build_agent_context(project, brief, drift)
    dump_json(control / "graph.observed.json", observed)
    dump_json(control / "drift.report.json", drift)
    dump_json(control / "architecture.brief.json", brief)
    dump_json(control / "agent_context.json", context)
    write_agent_markdown(project, context, drift)
    return control


def command_snapshot(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    control = write_snapshot_artifacts(project)
    print(f"Снимок архитектуры обновлён: {control}")
    return 0


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _write_bootstrap_preview_output(project: Path, output: Path, text: str, *, force: bool) -> None:
    resolved = output.expanduser().resolve()
    control = project_control(project).resolve()
    if _is_relative_to(resolved, control):
        raise ValueError("bootstrap-preview --output не пишет внутрь .botctl; используйте внешний preview-файл")
    if resolved.exists() and not force:
        raise FileExistsError(f"output уже существует: {resolved}; используйте --force для перезаписи")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")


def command_bootstrap_preview(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    draft = build_bootstrap_graph_draft(project)
    issues = validate_graph(draft, project_control(project) / "graph.desired.yaml")
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        print("bootstrap-preview produced invalid draft:", file=sys.stderr)
        for issue in errors[:20]:
            print(f"- {issue.code}: {issue.message}", file=sys.stderr)
        return 2
    text = json.dumps(draft, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else _yaml_text(draft)
    if args.output:
        try:
            _write_bootstrap_preview_output(project, Path(args.output), text, force=bool(args.force))
        except (OSError, ValueError) as exc:
            print(f"Не удалось записать bootstrap preview: {exc}", file=sys.stderr)
            return 2
        print(f"Bootstrap preview записан: {Path(args.output).expanduser().resolve()}", file=sys.stderr)
    else:
        print(text, end="")
    return 0


def _git_status_porcelain(project: Path) -> str | None:
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if status.returncode != 0:
            return None
        return status.stdout
    except OSError:
        return None


def build_bootstrap_project_metadata(project: Path) -> dict[str, Any]:
    project_slug = _slug(project.name, "telegram_bot")
    return {
        "apiVersion": API_VERSION,
        "kind": "Project",
        "id": project_slug,
        "title": f"Telegram-бот {project.name}",
        "language": "ru",
        "primary_user": "AI-агент-разработчик",
        "human_user": "Владелец проекта",
        "entry_policy": {
            "first_command": "botctl inspect",
            "inspect_is_read_only": True,
            "runtime_access_requires_local_understanding": True,
        },
        "paths": {
            "desired_graph": ".botctl/graph.desired.yaml",
            "observed_graph": ".botctl/graph.observed.json",
            "drift_report": ".botctl/drift.report.json",
            "architecture_brief": ".botctl/architecture.brief.json",
            "agent_context_json": ".botctl/agent_context.json",
            "agent_context_md": ".botctl/agent_context.md",
        },
        "naming_policy": {"human_visible_language": "ru", "require_russian_titles": True},
        "artifact_policy": {
            "authored_versioned": [
                ".botctl/project.yaml",
                ".botctl/graph.desired.yaml",
                ".botctl/change_plans/*.yaml",
            ],
            "generated_ignored": [
                ".botctl/architecture.brief.json",
                ".botctl/graph.observed.json",
                ".botctl/drift.report.json",
                ".botctl/agent_context.json",
                ".botctl/agent_context.md",
            ],
            "audit_snapshots": {
                "enabled": False,
                "reason": "Generated artifacts воспроизводимы через botctl snapshot; audit snapshots включаются отдельным решением.",
            },
        },
        "ux_policy": {
            "require_clear_russian_human_labels": True,
            "forbid_raw_enums_in_human_titles": True,
            "generated_reports_must_include_next_actions": True,
            "generated_reports_must_include_blocked_actions": True,
            "default_human_language": "ru",
        },
        "safety_policy": {
            "forbidden_without_approval": [
                "Читать или выводить реальные токены и секреты",
                "Менять .env или production-настройки",
                "Перезапускать runtime-сервис",
                "Удалять runtime-базу или очередь повторов",
            ]
        },
    }


def _write_bootstrap_graph_to_project(project: Path, graph_text: str, project_text: str, *, force: bool, allow_dirty: bool) -> dict[str, Any]:
    control = project_control(project)
    graph_path = control / "graph.desired.yaml"
    project_path = control / "project.yaml"
    backup_path: Path | None = None
    project_backup_path: Path | None = None
    project_yaml_created = False
    if graph_path.exists() and not force:
        raise FileExistsError(f"graph уже существует: {graph_path}; используйте --force для замены")
    git_status = _git_status_porcelain(project)
    if git_status and not allow_dirty:
        raise RuntimeError("git рабочее дерево проекта не чистое; используйте --allow-dirty только если это осознанно")
    control.mkdir(parents=True, exist_ok=True)
    if project_path.exists() and force:
        project_backup_path = project_path.with_suffix(f".yaml.bak.{now_iso().replace(':', '').replace('-', '').replace('.', '')}")
        project_backup_path.write_text(project_path.read_text(encoding="utf-8"), encoding="utf-8")
    if graph_path.exists() and force:
        backup_path = graph_path.with_suffix(f".yaml.bak.{now_iso().replace(':', '').replace('-', '').replace('.', '')}")
        backup_path.write_text(graph_path.read_text(encoding="utf-8"), encoding="utf-8")
    if not project_path.exists():
        project_path.write_text(project_text, encoding="utf-8")
        project_yaml_created = True
    elif force and project_backup_path:
        project_path.write_text(project_text, encoding="utf-8")
    graph_path.write_text(graph_text, encoding="utf-8")
    created = [str(graph_path)] + ([str(project_path)] if project_yaml_created else [])
    rollback_parts = []
    if backup_path:
        rollback_parts.append(f"восстановить {backup_path} в {graph_path}")
    else:
        rollback_parts.append(f"удалить {graph_path}")
    if project_backup_path:
        rollback_parts.append(f"восстановить {project_backup_path} в {project_path}")
    elif project_yaml_created:
        rollback_parts.append(f"удалить {project_path}")
    return {
        "graph_path": str(graph_path),
        "project_path": str(project_path),
        "backup_path": str(backup_path) if backup_path else None,
        "project_backup_path": str(project_backup_path) if project_backup_path else None,
        "project_yaml_created": project_yaml_created,
        "created_paths": created,
        "git_dirty_before_save": bool(git_status),
        "rollback": "; ".join(rollback_parts),
    }


def command_bootstrap_save(args: argparse.Namespace) -> int:
    if not args.confirm:
        print("bootstrap-save требует явный --confirm; без него используйте bootstrap-preview", file=sys.stderr)
        return 2
    project = _project_path(args.project)
    draft = build_bootstrap_graph_draft(project)
    issues = validate_graph(draft, project_control(project) / "graph.desired.yaml")
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        print("bootstrap-save produced invalid draft:", file=sys.stderr)
        for issue in errors[:20]:
            print(f"- {issue.code}: {issue.message}", file=sys.stderr)
        return 2
    text = _yaml_text(draft)
    project_text = _yaml_text(build_bootstrap_project_metadata(project))
    try:
        save_info = _write_bootstrap_graph_to_project(project, text, project_text, force=bool(args.force), allow_dirty=bool(args.allow_dirty))
    except (OSError, RuntimeError, FileExistsError) as exc:
        print(f"Не удалось сохранить bootstrap graph: {exc}", file=sys.stderr)
        return 2
    verify_issues, verify_summary = verify_project(project)
    verify_errors = [issue for issue in verify_issues if issue.level == "error"]
    if verify_errors:
        graph_path = Path(save_info["graph_path"])
        backup_value = save_info.get("backup_path")
        if backup_value:
            backup_path = Path(str(backup_value))
            graph_path.write_text(backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        elif graph_path.exists():
            graph_path.unlink()
        project_path = Path(str(save_info.get("project_path")))
        project_backup_value = save_info.get("project_backup_path")
        if project_backup_value:
            project_backup_path = Path(str(project_backup_value))
            project_path.write_text(project_backup_path.read_text(encoding="utf-8"), encoding="utf-8")
        elif save_info.get("project_yaml_created") and project_path.exists():
            project_path.unlink()
        print("bootstrap-save verify failed; graph write rolled back", file=sys.stderr)
        for issue in verify_errors[:20]:
            print(f"- {issue.code}: {issue.message}", file=sys.stderr)
        return 2
    write_snapshot_artifacts(project)
    payload = {
        "apiVersion": API_VERSION,
        "command": "bootstrap-save",
        "project_path": str(project),
        "saved": save_info,
        "verify_summary": verify_summary,
        "generated_artifacts": _control_artifacts(project),
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Bootstrap project сохранён: {save_info['project_path']}")
        print(f"Bootstrap graph сохранён: {save_info['graph_path']}")
        if save_info.get("project_backup_path"):
            print(f"Backup предыдущего project.yaml: {save_info['project_backup_path']}")
        if save_info.get("backup_path"):
            print(f"Backup предыдущего graph: {save_info['backup_path']}")
        print(f"Verify: ошибок={verify_summary['errors']}, предупреждений={verify_summary['warnings']}")
        print(f"Snapshot artifacts: {project_control(project)}")
        print(f"Rollback: {save_info['rollback']}")
    return 0


def _emit_design_payload(project: Path, payload: dict[str, Any], args: argparse.Namespace, label: str) -> int:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else _yaml_text(payload)
    if args.output:
        try:
            _write_bootstrap_preview_output(project, Path(args.output), text, force=bool(args.force))
        except (OSError, ValueError) as exc:
            print(f"Не удалось записать {label}: {exc}", file=sys.stderr)
            return 2
        print(f"{label} записан: {Path(args.output).expanduser().resolve()}", file=sys.stderr)
    else:
        print(text, end="")
    return 0


def command_design(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    if args.design_command == "extract-menu":
        menu_map = extract_menu_map(project)
        return _emit_design_payload(project, menu_map, args, "Menu map")
    if args.design_command == "status":
        readiness = design_status_readiness(project)
        rc = _emit_design_payload(project, readiness, args, "Design readiness")
        if rc != 0:
            return rc
        return 0 if readiness.get("design_exists") else 2
    if args.design_command == "gate":
        gate = design_gate_status(project, change_id=args.id)
        rc = _emit_design_payload(project, gate, args, "Design gate")
        return rc if rc != 0 else (0 if gate["implementation_planning_allowed"] else 2)
    if args.design_command == "validate-artifact":
        if not args.artifact:
            print("design validate-artifact требует --artifact <artifact_key>", file=sys.stderr)
            return 2
        try:
            result = validate_design_artifact_semantics(project, args.artifact)
        except (OSError, ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            print(f"Не удалось проверить design artifact: {exc}", file=sys.stderr)
            return 2
        rc = _emit_design_payload(project, result, args, "Design artifact validation")
        return rc if rc != 0 else (0 if result["valid"] else 2)
    if args.design_command == "change-plan-new":
        if args.output:
            print("design change-plan-new пишет в .botctl/design/changeplans; --output запрещён", file=sys.stderr)
            return 2
        if not args.id or not args.intent:
            print("design change-plan-new требует --id <change_id> и --intent <text>", file=sys.stderr)
            return 2
        try:
            result = create_design_change_plan(project, args.id, args.intent, args.risk_level)
        except (OSError, ValueError, FileExistsError, jsonschema.ValidationError) as exc:
            print(f"Не удалось создать design ChangePlan: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else _yaml_text(result), end="")
        return 0
    if args.design_command == "change-plan-validate":
        if not args.id:
            print("design change-plan-validate требует --id <change_id>", file=sys.stderr)
            return 2
        try:
            result = validate_design_change_plan(project, args.id)
        except (OSError, ValueError, jsonschema.ValidationError) as exc:
            print(f"Не удалось проверить design ChangePlan: {exc}", file=sys.stderr)
            return 2
        rc = _emit_design_payload(project, result, args, "Design ChangePlan validation")
        return rc if rc != 0 else (0 if result["valid"] else 2)
    if args.design_command in {"change-plan-review", "change-plan-approve"}:
        if args.output:
            print(f"design {args.design_command} меняет ChangePlan; --output запрещён", file=sys.stderr)
            return 2
        if not args.id or not args.actor:
            print(f"design {args.design_command} требует --id <change_id> и --actor <name>", file=sys.stderr)
            return 2
        if args.design_command == "change-plan-approve" and not args.confirm:
            print("design change-plan-approve требует явный --confirm", file=sys.stderr)
            return 2
        try:
            result = update_design_change_plan_status(project, args.id, "approved" if args.design_command.endswith("approve") else "reviewed", actor=args.actor, note=args.note)
        except (OSError, ValueError, jsonschema.ValidationError) as exc:
            print(f"Не удалось обновить design ChangePlan: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else _yaml_text(result), end="")
        return 0
    if args.design_command in {"review", "confirm"}:
        if args.output:
            print(f"design {args.design_command} меняет artifact в проекте; --output запрещён", file=sys.stderr)
            return 2
        if not args.artifact:
            print(f"design {args.design_command} требует --artifact <artifact_key>", file=sys.stderr)
            return 2
        if args.design_command == "confirm" and not args.confirm:
            print("design confirm требует явный флаг --confirm", file=sys.stderr)
            return 2
        if args.design_command == "confirm" and not args.actor:
            print("design confirm требует --actor <name>", file=sys.stderr)
            return 2
        status = "confirmed" if args.design_command == "confirm" else "reviewed"
        try:
            result = update_design_artifact_status(
                project,
                args.artifact,
                status,
                actor=args.actor,
                note=args.note,
            )
        except (OSError, ValueError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            print(f"Не удалось обновить статус design artifact: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else _yaml_text(result), end="")
        return 0
    if args.design_command == "init-system":
        design_dir = project_control(project) / "design"
        if args.preview:
            if not args.output:
                print("design init-system --preview требует --output <external-dir>", file=sys.stderr)
                return 2
            target_dir = Path(args.output).expanduser().resolve()
            try:
                result = write_design_init_system(project, target_dir, preview=True, force=bool(args.force))
            except (OSError, ValueError, FileExistsError) as exc:
                print(f"Не удалось создать preview design system: {exc}", file=sys.stderr)
                return 2
        else:
            if args.output:
                print("design init-system без --preview пишет только в .botctl/design/; --output запрещён", file=sys.stderr)
                return 2
            try:
                result = write_design_init_system(project, design_dir, preview=False, force=False)
            except FileExistsError as exc:
                print(f"Design layer уже существует: {exc}. Используйте --preview --output <external-dir> для безопасного preview.", file=sys.stderr)
                return 2
            except (OSError, ValueError) as exc:
                print(f"Не удалось создать design system: {exc}", file=sys.stderr)
                return 2
        print(json.dumps(result, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else _yaml_text(result), end="")
        return 0
    if args.design_command in {"validate-brief", "from-brief"}:
        if not args.input:
            print(f"design {args.design_command} требует --input brief.yaml|brief.json", file=sys.stderr)
            return 2
        try:
            brief = load_json(Path(args.input)) if str(args.input).endswith(".json") else load_yaml(Path(args.input))
        except Exception as exc:
            print(f"Не удалось прочитать brief: {exc}", file=sys.stderr)
            return 2
        if not isinstance(brief, dict):
            print("Brief должен быть JSON/YAML object", file=sys.stderr)
            return 2
        validation = validate_design_brief(brief)
        if args.design_command == "validate-brief":
            rc = _emit_design_payload(project, validation, args, "Brief validation")
            return 2 if rc == 0 and not validation.get("valid") else rc
        if not validation.get("valid") and not args.allow_invalid:
            _emit_design_payload(project, validation, argparse.Namespace(format=args.format, output=None, force=False), "Brief validation")
            return 2
        proposal = design_from_brief(brief, allow_invalid=bool(args.allow_invalid))
        return _emit_design_payload(project, proposal, args, "Menu design proposal")
    if args.design_command == "compare":
        if not args.input or not args.actual:
            print("design compare требует --input proposal.yaml|json и --actual menu-map.yaml|json", file=sys.stderr)
            return 2
        try:
            proposal = load_json(Path(args.input)) if str(args.input).endswith(".json") else load_yaml(Path(args.input))
            actual = load_json(Path(args.actual)) if str(args.actual).endswith(".json") else load_yaml(Path(args.actual))
        except Exception as exc:
            print(f"Не удалось прочитать proposal/actual: {exc}", file=sys.stderr)
            return 2
        if not isinstance(proposal, dict) or proposal.get("kind") != "BotMenuDesignProposal":
            print("--input должен быть BotMenuDesignProposal", file=sys.stderr)
            return 2
        if not isinstance(actual, dict) or actual.get("kind") != "BotMenuMap":
            print("--actual должен быть BotMenuMap", file=sys.stderr)
            return 2
        diff = compare_menu_design(proposal, actual)
        return _emit_design_payload(project, diff, args, "Menu design diff")
    if args.design_command == "plan":
        if args.input:
            try:
                source = load_json(Path(args.input)) if str(args.input).endswith(".json") else load_yaml(Path(args.input))
            except Exception as exc:
                print(f"Не удалось прочитать input proposal/menu map: {exc}", file=sys.stderr)
                return 2
            if not isinstance(source, dict):
                print("Input должен быть JSON/YAML object", file=sys.stderr)
                return 2
            if source.get("kind") == "BotMenuDesignProposal":
                proposal = source
            elif source.get("kind") == "BotMenuMap":
                proposal = normalize_menu_design(source, critique_menu_map(source))
            else:
                print("design plan принимает BotMenuDesignProposal или BotMenuMap", file=sys.stderr)
                return 2
        else:
            menu_map = extract_menu_map(project)
            proposal = normalize_menu_design(menu_map, critique_menu_map(menu_map))
        plan = implementation_plan_from_proposal(proposal)
        return _emit_design_payload(project, plan, args, "Menu implementation plan")
    if args.design_command in {"critique", "normalize"}:
        if args.input:
            try:
                source = load_json(Path(args.input)) if str(args.input).endswith(".json") else load_yaml(Path(args.input))
            except Exception as exc:
                print(f"Не удалось прочитать input menu map: {exc}", file=sys.stderr)
                return 2
            if not isinstance(source, dict):
                print("Input menu map должен быть JSON/YAML object", file=sys.stderr)
                return 2
            menu_map = source
        else:
            menu_map = extract_menu_map(project)
        critique = critique_menu_map(menu_map)
        if args.design_command == "critique":
            return _emit_design_payload(project, critique, args, "Menu critique")
        proposal = normalize_menu_design(menu_map, critique)
        return _emit_design_payload(project, proposal, args, "Menu design proposal")
    print("Укажите design-команду: extract-menu, critique или normalize", file=sys.stderr)
    return 2


def command_verify(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    issues, summary = verify_project(project)
    payload = {"apiVersion": API_VERSION, "command": "verify", "project_path": str(project), "summary": summary, "issues": [i.to_dict() for i in issues]}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Проверка botctl v0: ошибок={summary['errors']}, предупреждений={summary['warnings']}, ChangePlan={summary['checked_change_plans']}")
        for issue in issues[:50]:
            print(f"- {issue.level} {issue.code}: {issue.message}")
    return 0 if summary["errors"] == 0 else 2


def command_diff(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    drift_path = project_control(project) / "drift.report.json"
    if drift_path.exists():
        drift = load_json(drift_path)
    else:
        observed = discover_local(project)
        drift = build_drift(project, observed)
    if args.format == "json":
        print(json.dumps(drift, ensure_ascii=False, indent=2))
    else:
        summary = drift.get("summary", {})
        print("Расхождения desired ↔ observed_local")
        print(f"Согласовано: {summary.get('in_sync', 0)}")
        print(f"Описано, но не найдено: {summary.get('missing_local', 0)}")
        for item in drift.get("items", [])[:50]:
            print(f"- {item['status_label']}: {item['title']} ({item.get('path')})")
    return 0 if drift.get("summary", {}).get("conflict", 0) == 0 else 2


def command_audit_runtime(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    control_root = control_layer_root()
    if args.profile and args.specs:
        print("audit-runtime: используйте либо --profile, либо --specs", file=sys.stderr)
        return 2
    if args.profile:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,79}", args.profile):
            print("audit-runtime: неверный profile id", file=sys.stderr)
            return 2
        profile_dir = control_root / "profiles" / args.profile
        specs_dir = profile_dir / "specs"
        profile_path = profile_dir / "profile.yaml"
        if not profile_path.is_file() or not specs_dir.is_dir():
            print(f"audit-runtime: профиль не найден: {args.profile}", file=sys.stderr)
            return 2
        try:
            profile_data = load_yaml(profile_path)
        except (OSError, ValueError) as exc:
            print(f"audit-runtime: не удалось прчитать профиль: {exc}", file=sys.stderr)
            return 2
        profile_issues = validate_against_schema(profile_data, "audit-profile.schema.json", profile_path)
        if profile_issues or profile_data.get("id") != args.profile:
            details = "; ".join(issue.message for issue in profile_issues) or "id профиля не совпадает с именем папки"
            print(f"audit-runtime: неверный профиль: {details}", file=sys.stderr)
            return 2
    else:
        specs_dir = Path(args.specs).expanduser().resolve() if args.specs else control_root / "specs"
    try:
        payload = audit_runtime_source(project, specs_dir)
    except (OSError, ValueError) as exc:
        print(f"Не удалось выполнить read-only runtime audit: {exc}", file=sys.stderr)
        return 2
    payload["profile"] = args.profile or "default"
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload["summary"]
        print(f"Read-only runtime audit: {summary['status']}")
        print(f"Ошибок: {summary['errors']}; предупреждений: {summary['warnings']}")
        for issue in payload["issues"][:100]:
            print(f"- [{issue['severity']}] {issue['code']}: {issue['title']}")
    return 0 if payload["summary"]["errors"] == 0 else 2


def command_probe_runtime(args: argparse.Namespace) -> int:
    try:
        payload = probe_local_runtime(
            pid=args.pid,
            heartbeat_file=Path(args.heartbeat_file) if args.heartbeat_file else None,
            max_heartbeat_age=args.max_heartbeat_age,
        )
    except (OSError, ValueError) as exc:
        print(f"probe-runtime: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload["summary"]
        print(f"Local read-only runtime probe: {summary['status']}")
        for check in payload["checks"]:
            print(f"- {check['kind']}: {check['state']} ({check['status']})")
    return 2 if payload["summary"]["status"] == "failed" else 0


def command_probe_http(args: argparse.Namespace) -> int:
    try:
        payload = probe_http_health(
            url=args.url,
            confirm_network=args.confirm_network,
            allow_insecure_localhost=args.allow_insecure_localhost,
            timeout=args.timeout,
        )
    except (OSError, ValueError) as exc:
        print(f"probe-http: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else f"HTTP HEAD probe: {payload['summary']['status']} ({payload['check']['state']})")
    return 0 if payload["summary"]["status"] == "passed" else 2


def command_probe_sqlite(args: argparse.Namespace) -> int:
    try:
        payload = probe_sqlite_integrity(database=Path(args.database), confirm_database_read=args.confirm_database_read)
    except (OSError, ValueError) as exc:
        print(f"probe-sqlite: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else f"SQLite immutable quick-check: {payload['summary']['status']} ({payload['check']['state']})")
    return 0 if payload["summary"]["status"] == "passed" else 2


def _emit_adoption(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"Project adoption: {payload['status']} ({payload['mode']})")
    for path in payload.get("created_paths", payload.get("planned_paths", [])):
        print(f"- {path}")
    for step in payload.get("next_steps", []):
        print(f"→ {step}")


def command_adopt(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    if not project.is_dir():
        print(f"adopt: project directory not found: {project}", file=sys.stderr)
        return 2
    control = project_control(project)
    planned = planned_adoption_paths()
    next_steps = [
        "Добавить ссылку на .botctl/AGENT_INSTRUCTIONS.md в инструкции вашего AI-агента.",
        "Заполнить .botctl/specs/ до изменения runtime-кода.",
        "Проверить draft design: botctl design status --project .",
    ]
    if control.exists():
        complete = (control / "project.yaml").is_file() and (control / "graph.desired.yaml").is_file()
        payload = {
            "apiVersion": API_VERSION, "kind": "BotProjectAdoptionResult", "project_path": str(project),
            "mode": "confirmed" if args.confirm else "preview", "status": "already_adopted" if complete else "blocked",
            "read_only": True, "planned_paths": planned, "created_paths": [], "next_steps": next_steps,
        }
        _emit_adoption(payload, args.format)
        return 0 if complete else 2
    preview = {
        "apiVersion": API_VERSION, "kind": "BotProjectAdoptionResult", "project_path": str(project),
        "mode": "preview", "status": "ready_to_adopt", "read_only": True,
        "planned_paths": planned, "created_paths": [], "next_steps": ["Повторить команду с --confirm для создания только новой папки .botctl/."] + next_steps,
    }
    if not args.confirm:
        _emit_adoption(preview, args.format)
        return 0
    try:
        draft = build_bootstrap_graph_draft(project)
        graph_issues = validate_graph(draft, control / "graph.desired.yaml")
        graph_errors = [issue for issue in graph_issues if issue.level == "error"]
        if graph_errors:
            raise ValueError("bootstrap graph failed validation: " + "; ".join(issue.message for issue in graph_errors[:3]))
        metadata = build_bootstrap_project_metadata(project)
        metadata["paths"]["architecture_specs"] = ".botctl/specs"
        metadata["paths"]["agent_instructions"] = ".botctl/AGENT_INSTRUCTIONS.md"
        metadata["artifact_policy"]["authored_versioned"].extend([".botctl/specs/*.yaml", ".botctl/AGENT_INSTRUCTIONS.md", ".botctl/design/**"])
        _write_bootstrap_graph_to_project(project, _yaml_text(draft), _yaml_text(metadata), force=False, allow_dirty=True)
        write_adoption_support(control)
        write_design_init_system(project, control / "design", preview=False, force=False)
        write_snapshot_artifacts(project)
        verify_issues, verify_summary = verify_project(project)
        errors = [issue for issue in verify_issues if issue.level == "error"]
        if errors:
            raise ValueError("post-adoption verify failed: " + "; ".join(issue.message for issue in errors[:3]))
    except Exception as exc:
        if control.exists():
            shutil.rmtree(control)
        print(f"adopt failed; new .botctl rolled back: {exc}", file=sys.stderr)
        return 2
    created = [str(path.relative_to(project)) + ("/" if path.is_dir() else "") for path in sorted(control.rglob("*"))]
    payload = {
        "apiVersion": API_VERSION, "kind": "BotProjectAdoptionResult", "project_path": str(project),
        "mode": "confirmed", "status": "adopted", "read_only": False,
        "planned_paths": planned, "created_paths": created, "next_steps": next_steps, "verify_summary": verify_summary,
    }
    _emit_adoption(payload, args.format)
    return 0


def _load_graph_nodes(project: Path) -> set[str]:
    desired = load_desired(project)
    return {str(node.get("id")) for node in desired.get("nodes", []) or [] if isinstance(node, dict) and node.get("id")}


def command_plan(args: argparse.Namespace) -> int:
    project = _project_path(args.project)
    if args.plan_command == "new":
        plan_id = args.id or "change.example"
        title = args.title or "Новый план изменения"
        path = project_control(project) / "change_plans" / f"{plan_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.force:
            print(f"ChangePlan уже существует: {path}", file=sys.stderr)
            return 2
        content = f"""apiVersion: {API_VERSION}
kind: ChangePlan
id: {plan_id}
title: \"{title}\"
status: draft
goal: \"Кратко опишите цель изменения.\"
affected_nodes: []
risk:
  level: low
  reason: \"Объясните риск изменения.\"
approval:
  level: none
  reason: \"Объясните, почему достаточно этого уровня подтверждения.\"
steps: []
verification: []
rollback: []
"""
        path.write_text(content, encoding="utf-8")
        print(f"Создан ChangePlan: {path}")
        return 0
    if args.plan_command == "validate":
        return command_verify(args)
    print("Укажите plan-команду: new или validate", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="botctl", description="BotCharter public alpha — architecture control for AI-built bots")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Read-only вход в проект")
    inspect.add_argument("--project", default=".")
    inspect.add_argument("--format", choices=["human", "json", "agent"], default="human")
    inspect.set_defaults(func=command_inspect)

    adopt = sub.add_parser("adopt", help="Подключить существующий проект к specs-first AI-agent workflow")
    adopt.add_argument("--project", default=".")
    adopt.add_argument("--confirm", action="store_true", help="Создать новую .botctl/; без флага только preview")
    adopt.add_argument("--format", choices=["human", "json"], default="human")
    adopt.set_defaults(func=command_adopt)

    snapshot = sub.add_parser("snapshot", help="Создать generated artifacts")
    snapshot.add_argument("--project", default=".")
    snapshot.set_defaults(func=command_snapshot)

    bootstrap_preview = sub.add_parser("bootstrap-preview", help="Read-only черновик graph.desired.yaml для проекта без паспорта")
    bootstrap_preview.add_argument("--project", default=".")
    bootstrap_preview.add_argument("--format", choices=["yaml", "json"], default="yaml")
    bootstrap_preview.add_argument("--output", help="Записать preview во внешний файл вместо stdout; .botctl запрещён")
    bootstrap_preview.add_argument("--force", action="store_true", help="Перезаписать существующий output-файл")
    bootstrap_preview.set_defaults(func=command_bootstrap_preview)

    bootstrap_save = sub.add_parser("bootstrap-save", help="Сохранить draft graph.desired.yaml в .botctl с явным подтверждением")
    bootstrap_save.add_argument("--project", default=".")
    bootstrap_save.add_argument("--confirm", action="store_true", help="Обязательное явное подтверждение записи graph.desired.yaml")
    bootstrap_save.add_argument("--force", action="store_true", help="Заменить существующий graph.desired.yaml с backup")
    bootstrap_save.add_argument("--allow-dirty", action="store_true", help="Разрешить запись при dirty git worktree проекта")
    bootstrap_save.add_argument("--format", choices=["human", "json"], default="human")
    bootstrap_save.set_defaults(func=command_bootstrap_save)

    design = sub.add_parser("design", help="Read-only проектирование/извлечение UX-структуры бота")
    design.add_argument("design_command", choices=["extract-menu", "critique", "normalize", "from-brief", "validate-brief", "validate-artifact", "plan", "compare", "init-system", "status", "gate", "review", "confirm", "change-plan-new", "change-plan-validate", "change-plan-review", "change-plan-approve"])
    design.add_argument("--project", default=".")
    design.add_argument("--format", choices=["yaml", "json"], default="json")
    design.add_argument("--input", help="Для critique/normalize: BotMenuMap; from-brief: BotDesignBrief; plan: Proposal/Map; compare: BotMenuDesignProposal")
    design.add_argument("--actual", help="Для compare: фактический BotMenuMap JSON/YAML")
    design.add_argument("--output", help="Записать результат во внешний файл; .botctl запрещён")
    design.add_argument("--allow-invalid", action="store_true", help="Для from-brief: всё равно сгенерировать proposal при validation errors")
    design.add_argument("--preview", action="store_true", help="Для init-system: писать preview во внешний --output, не в проект")
    design.add_argument("--force", action="store_true", help="Перезаписать существующий output-файл или непустой preview-output")
    design.add_argument("--artifact", help="Для review/confirm: ключ artifact, например product_model или menu_proposal")
    design.add_argument("--actor", help="Для review/confirm: кто подтверждает artifact")
    design.add_argument("--note", help="Для review/confirm: короткая заметка в review_history")
    design.add_argument("--confirm", action="store_true", help="Явное подтверждение команды design confirm")
    design.add_argument("--id", help="ChangePlan id")
    design.add_argument("--intent", help="Цель design ChangePlan")
    design.add_argument("--risk-level", choices=["low", "medium", "high", "critical"], default="low", help="Уровень риска design ChangePlan")
    design.set_defaults(func=command_design)

    verify = sub.add_parser("verify", help="Проверить .botctl контракт")
    verify.add_argument("--project", default=".")
    verify.add_argument("--format", choices=["human", "json"], default="human")
    verify.set_defaults(func=command_verify)

    diff = sub.add_parser("diff", help="Показать drift desired ↔ observed_local")
    diff.add_argument("--project", default=".")
    diff.add_argument("--format", choices=["human", "json"], default="human")
    diff.set_defaults(func=command_diff)

    audit_runtime = sub.add_parser("audit-runtime", help="Read-only сверка runtime source с architecture specs")
    audit_runtime.add_argument("--project", required=True, help="Папка target bot project")
    audit_runtime.add_argument("--specs", help="Папка specs; по умолчанию specs/ control-layer project")
    audit_runtime.add_argument("--profile", help="Profile id из profiles/<id>/profile.yaml")
    audit_runtime.add_argument("--format", choices=["human", "json"], default="human")
    audit_runtime.set_defaults(func=command_audit_runtime)

    probe_runtime = sub.add_parser("probe-runtime", help="Read-only проверка локального процесса и heartbeat metadata")
    probe_runtime.add_argument("--pid", type=int, help="PID локального процесса")
    probe_runtime.add_argument("--heartbeat-file", help="Явный путь к heartbeat-файлу; содержимое не читается")
    probe_runtime.add_argument("--max-heartbeat-age", type=int, default=300, help="Допустимый возраст heartbeat в секундах")
    probe_runtime.add_argument("--format", choices=["human", "json"], default="human")
    probe_runtime.set_defaults(func=command_probe_runtime)

    probe_http = sub.add_parser("probe-http", help="Явно подтверждённый HEAD health-check без body, auth и redirects")
    probe_http.add_argument("--url", required=True, help="Явный health URL без credentials/query/fragment")
    probe_http.add_argument("--confirm-network", action="store_true", help="Обязательное подтверждение одного сетевого HEAD-запроса")
    probe_http.add_argument("--allow-insecure-localhost", action="store_true", help="Разрешить HTTP только для localhost-теста")
    probe_http.add_argument("--timeout", type=float, default=5.0, help="Timeout 1..30 секунд")
    probe_http.add_argument("--format", choices=["human", "json"], default="human")
    probe_http.set_defaults(func=command_probe_http)

    probe_sqlite = sub.add_parser("probe-sqlite", help="Явно подтверждённый immutable read-only SQLite quick-check")
    probe_sqlite.add_argument("--database", required=True, help="Явный путь к .db/.sqlite/.sqlite3")
    probe_sqlite.add_argument("--confirm-database-read", action="store_true", help="Обязательное подтверждение открытия базы только для чтения")
    probe_sqlite.add_argument("--format", choices=["human", "json"], default="human")
    probe_sqlite.set_defaults(func=command_probe_sqlite)

    plan = sub.add_parser("plan", help="Работа с ChangePlan")
    plan.add_argument("plan_command", choices=["new", "validate"])
    plan.add_argument("--project", default=".")
    plan.add_argument("--format", choices=["human", "json"], default="human")
    plan.add_argument("--id")
    plan.add_argument("--title")
    plan.add_argument("--force", action="store_true")
    plan.set_defaults(func=command_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
