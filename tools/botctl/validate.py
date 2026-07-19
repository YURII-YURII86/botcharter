from __future__ import annotations

from pathlib import Path
from typing import Any

from .schema import validate_against_schema
from .model import (
    API_VERSION,
    APPROVAL_LEVELS,
    APPROVAL_ORDER,
    CHANGE_STATUSES,
    Issue,
    KNOWLEDGE_STATUSES,
    LIFECYCLE_STATUSES,
    NODE_KINDS,
    RELATION_TYPES,
    RISK_LEVELS,
    RISK_MIN_APPROVAL,
    contains_cyrillic,
    list_change_plans,
    load_json,
    load_yaml,
    looks_like_raw_id,
    project_control,
)

# Compatibility alias for a simple import pattern.
def approval_level_ok(risk: str, approval: str) -> bool:
    minimum = RISK_MIN_APPROVAL.get(risk, "human_approval")
    return APPROVAL_ORDER.get(approval, -1) >= APPROVAL_ORDER.get(minimum, 99)


def validate_project_yaml(data: dict[str, Any], path: Path) -> list[Issue]:
    issues: list[Issue] = []
    if data.get("apiVersion") != API_VERSION:
        issues.append(Issue("error", "invalid_api_version", f"project.yaml должен иметь apiVersion={API_VERSION}", str(path)))
    if data.get("kind") != "Project":
        issues.append(Issue("error", "invalid_kind", "project.yaml должен иметь kind=Project", str(path)))
    for key in ["id", "title", "language", "entry_policy", "paths", "naming_policy"]:
        if key not in data:
            issues.append(Issue("error", "missing_field", f"project.yaml: отсутствует поле {key}", str(path)))
    title = str(data.get("title", ""))
    if looks_like_raw_id(title) or not contains_cyrillic(title):
        issues.append(Issue("error", "bad_russian_title", "project.yaml: title должен быть понятным русским названием", str(path)))
    if data.get("language") != "ru":
        issues.append(Issue("error", "language_not_ru", "project.yaml: language должен быть ru для v0", str(path)))
    entry = data.get("entry_policy", {}) or {}
    if entry.get("inspect_is_read_only") is not True:
        issues.append(Issue("error", "inspect_not_read_only", "entry_policy.inspect_is_read_only должен быть true", str(path)))
    artifact_policy = data.get("artifact_policy", {}) or {}
    authored = set(artifact_policy.get("authored_versioned", []) or [])
    generated = set(artifact_policy.get("generated_ignored", []) or [])
    required_authored = {".botctl/project.yaml", ".botctl/graph.desired.yaml"}
    required_generated = {
        ".botctl/architecture.brief.json",
        ".botctl/graph.observed.json",
        ".botctl/drift.report.json",
        ".botctl/agent_context.json",
        ".botctl/agent_context.md",
    }
    for item in sorted(required_authored - authored):
        issues.append(Issue("error", "artifact_policy_missing_authored", f"artifact_policy.authored_versioned должен включать {item}", str(path)))
    for item in sorted(required_generated - generated):
        issues.append(Issue("error", "artifact_policy_missing_generated", f"artifact_policy.generated_ignored должен включать {item}", str(path)))
    ux_policy = data.get("ux_policy", {}) or {}
    if ux_policy.get("require_clear_russian_human_labels") is not True:
        issues.append(Issue("error", "ux_policy_missing_russian_labels", "ux_policy.require_clear_russian_human_labels должен быть true", str(path)))
    if ux_policy.get("forbid_raw_enums_in_human_titles") is not True:
        issues.append(Issue("error", "ux_policy_missing_raw_enum_guard", "ux_policy.forbid_raw_enums_in_human_titles должен быть true", str(path)))
    return issues


def validate_graph(data: dict[str, Any], path: Path) -> list[Issue]:
    issues: list[Issue] = []
    if data.get("apiVersion") != API_VERSION:
        issues.append(Issue("error", "invalid_api_version", f"graph.desired.yaml должен иметь apiVersion={API_VERSION}", str(path)))
    if data.get("kind") != "BotArchitectureGraph":
        issues.append(Issue("error", "invalid_kind", "graph.desired.yaml должен иметь kind=BotArchitectureGraph", str(path)))
    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list):
        issues.append(Issue("error", "nodes_not_list", "graph.desired.yaml: nodes должен быть списком", str(path)))
        nodes = []
    if not isinstance(edges, list):
        issues.append(Issue("error", "edges_not_list", "graph.desired.yaml: edges должен быть списком", str(path)))
        edges = []
    node_ids: set[str] = set()
    for i, node in enumerate(nodes):
        prefix = f"nodes[{i}]"
        if not isinstance(node, dict):
            issues.append(Issue("error", "node_not_object", f"{prefix}: узел должен быть объектом", str(path)))
            continue
        node_id = node.get("id")
        if not node_id:
            issues.append(Issue("error", "missing_node_id", f"{prefix}: отсутствует id", str(path)))
        elif node_id in node_ids:
            issues.append(Issue("error", "duplicate_node_id", f"Дублируется node.id={node_id}", str(path)))
        else:
            node_ids.add(str(node_id))
        if node.get("kind") not in NODE_KINDS:
            issues.append(Issue("error", "invalid_node_kind", f"{prefix}: неизвестный kind={node.get('kind')}", str(path)))
        layer = node.get("layer")
        if not isinstance(layer, str) or not layer.startswith("L"):
            issues.append(Issue("error", "invalid_layer", f"{prefix}: layer должен быть L0-L6", str(path)))
        title = str(node.get("title", ""))
        if looks_like_raw_id(title) or not contains_cyrillic(title):
            issues.append(Issue("error", "bad_russian_title", f"{prefix}: title должен быть понятным русским названием", str(path)))
        if node.get("lifecycle_status") not in LIFECYCLE_STATUSES:
            issues.append(Issue("error", "invalid_lifecycle_status", f"{prefix}: неверный lifecycle_status", str(path)))
        if node.get("knowledge_status") not in KNOWLEDGE_STATUSES:
            issues.append(Issue("error", "invalid_knowledge_status", f"{prefix}: неверный knowledge_status", str(path)))
        risk = ((node.get("change_control") or {}).get("risk_level") or node.get("risk_level"))
        if risk and risk not in RISK_LEVELS:
            issues.append(Issue("error", "invalid_risk_level", f"{prefix}: неверный risk_level={risk}", str(path)))
    for i, edge in enumerate(edges):
        prefix = f"edges[{i}]"
        if not isinstance(edge, dict):
            issues.append(Issue("error", "edge_not_object", f"{prefix}: связь должна быть объектом", str(path)))
            continue
        for endpoint in ["from", "to"]:
            if edge.get(endpoint) not in node_ids:
                issues.append(Issue("error", "bad_edge_endpoint", f"{prefix}: {endpoint} указывает на несуществующий узел {edge.get(endpoint)}", str(path)))
        if edge.get("type") not in RELATION_TYPES:
            issues.append(Issue("error", "invalid_relation_type", f"{prefix}: неизвестный type={edge.get('type')}", str(path)))
        title = str(edge.get("title", ""))
        if title and (looks_like_raw_id(title) or not contains_cyrillic(title)):
            issues.append(Issue("error", "bad_russian_title", f"{prefix}: title должен быть русским человеко-понятным текстом", str(path)))
    issues.extend(validate_ux_structure(data, path, node_ids))
    return issues



REQUIRED_UX_CHECKS: dict[str, str] = {
    "command_design": "Понятность команд",
    "start_onboarding": "Первое сообщение и onboarding",
    "inline_keyboard_layout": "Inline-клавиатуры и меню",
    "unknown_input_fallback": "Fallback на непонятный ввод",
    "progress_status": "Прогресс, typing/status для долгих операций",
    "human_readable_errors": "Понятные ошибки для пользователя",
    "empty_states": "Пустые состояния",
    "rate_limiting": "Лимиты и защита от Telegram rate limits",
    "persistent_user_state": "Состояние пользователя между сообщениями",
    "global_error_handler": "Глобальный обработчик ошибок",
    "token_env_safety": "Безопасность токенов и env",
    "analytics_or_observability": "Аналитика или наблюдаемость",
    "webhook_or_polling_model": "Явная модель polling/webhook/deploy",
}


def validate_ux_checks(ux: dict[str, Any], path: Path, node_ids: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    checks = ux.get("checks") or []
    if not isinstance(checks, list) or not checks:
        issues.append(Issue("error", "missing_ux_checks", "ux_structure.checks должен фиксировать UX/production checks из Telegram skills/cases", str(path)))
        return issues
    seen: set[str] = set()
    for i, check in enumerate(checks):
        prefix = f"ux_structure.checks[{i}]"
        if not isinstance(check, dict):
            issues.append(Issue("error", "ux_check_not_object", f"{prefix}: check должен быть объектом", str(path)))
            continue
        check_id = check.get("id")
        if not check_id:
            issues.append(Issue("error", "missing_ux_check_id", f"{prefix}: отсутствует id", str(path)))
            continue
        seen.add(str(check_id))
        issues.extend(_check_human_text(check.get("title"), "bad_ux_check_title", f"{prefix}.title", path))
        issues.extend(_check_human_text(check.get("why"), "bad_ux_check_why", f"{prefix}.why", path))
        status = check.get("status")
        if status not in {"covered", "not_applicable", "planned", "missing"}:
            issues.append(Issue("error", "bad_ux_check_status", f"{prefix}.status должен быть covered/not_applicable/planned/missing", str(path)))
        if status == "missing":
            issues.append(Issue("error", "missing_required_ux_check", f"{prefix}: обязательный UX-check помечен missing", str(path)))
        evidence_nodes = check.get("evidence_nodes") or []
        if status == "covered" and (not isinstance(evidence_nodes, list) or not evidence_nodes):
            issues.append(Issue("error", "ux_check_without_evidence", f"{prefix}: covered check должен иметь evidence_nodes", str(path)))
        if isinstance(evidence_nodes, list):
            for node_id in evidence_nodes:
                if node_id not in node_ids:
                    issues.append(Issue("error", "bad_ux_check_node", f"{prefix}.evidence_nodes ссылается на неизвестный узел {node_id}", str(path)))
        if check.get("source") not in {"telegram-bot-builder", "telegram-rich-messages", "telegram-video-jobs-case", "manual"}:
            issues.append(Issue("error", "bad_ux_check_source", f"{prefix}.source должен указывать skill/case источник", str(path)))
    missing_required = set(REQUIRED_UX_CHECKS) - seen
    for check_id in sorted(missing_required):
        issues.append(Issue("error", "missing_required_ux_check", f"ux_structure.checks не содержит обязательный check {check_id}: {REQUIRED_UX_CHECKS[check_id]}", str(path)))
    return issues


def validate_ux_structure(data: dict[str, Any], path: Path, node_ids: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    ux = data.get("ux_structure") or {}
    if not isinstance(ux, dict):
        issues.append(Issue("error", "ux_structure_not_object", "ux_structure должен быть объектом", str(path)))
        return issues
    sections = ux.get("sections") or []
    if not isinstance(sections, list) or not sections:
        issues.append(Issue("error", "missing_ux_sections", "graph.desired.yaml должен содержать ux_structure.sections", str(path)))
        return issues
    covered_nodes: set[str] = set()
    for i, section in enumerate(sections):
        prefix = f"ux_structure.sections[{i}]"
        if not isinstance(section, dict):
            issues.append(Issue("error", "ux_section_not_object", f"{prefix}: раздел должен быть объектом", str(path)))
            continue
        for key in ["id", "title", "purpose", "nodes", "primary_actions"]:
            if key not in section:
                issues.append(Issue("error", "missing_ux_section_field", f"{prefix}: отсутствует поле {key}", str(path)))
        issues.extend(_check_human_text(section.get("title"), "bad_ux_section_title", f"{prefix}.title", path))
        issues.extend(_check_human_text(section.get("purpose"), "bad_ux_section_purpose", f"{prefix}.purpose", path))
        nodes = section.get("nodes") or []
        if not isinstance(nodes, list) or not nodes:
            issues.append(Issue("error", "empty_ux_section_nodes", f"{prefix}.nodes должен содержать связанные узлы графа", str(path)))
        else:
            for node_id in nodes:
                if node_id not in node_ids:
                    issues.append(Issue("error", "bad_ux_section_node", f"{prefix}.nodes ссылается на неизвестный узел {node_id}", str(path)))
                else:
                    covered_nodes.add(str(node_id))
        actions = section.get("primary_actions") or []
        if not isinstance(actions, list) or not actions:
            issues.append(Issue("error", "empty_ux_section_actions", f"{prefix}.primary_actions должен содержать понятные действия", str(path)))
        else:
            for j, action in enumerate(actions):
                if not isinstance(action, dict):
                    issues.append(Issue("error", "ux_action_not_object", f"{prefix}.primary_actions[{j}] должен быть объектом", str(path)))
                    continue
                issues.extend(_check_human_text(action.get("title"), "bad_ux_action_title", f"{prefix}.primary_actions[{j}].title", path))
                if action.get("node") and action.get("node") not in node_ids:
                    issues.append(Issue("error", "bad_ux_action_node", f"{prefix}.primary_actions[{j}].node неизвестен: {action.get('node')}", str(path)))
    important_nodes = {
        str(node.get("id"))
        for node in data.get("nodes", []) or []
        if isinstance(node, dict) and node.get("kind") in {"Product", "Capability", "Flow"} and node.get("lifecycle_status") == "active"
    }
    missing = important_nodes - covered_nodes
    for node_id in sorted(missing):
        issues.append(Issue("error", "ux_structure_missing_important_node", f"UX-структура не покрывает важный узел {node_id}", str(path)))
    if len(sections) < 2:
        issues.append(Issue("warning", "ux_structure_too_flat", "UX-структура слишком плоская: нужен минимум смысловой раздел и раздел контроля/безопасности", str(path)))
    issues.extend(validate_ux_checks(ux, path, node_ids))
    return issues

def validate_change_plan(data: dict[str, Any], path: Path, graph_nodes: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    if data.get("apiVersion") != API_VERSION:
        issues.append(Issue("error", "invalid_api_version", f"ChangePlan должен иметь apiVersion={API_VERSION}", str(path)))
    if data.get("kind") != "ChangePlan":
        issues.append(Issue("error", "invalid_kind", "ChangePlan должен иметь kind=ChangePlan", str(path)))
    if data.get("status") not in CHANGE_STATUSES:
        issues.append(Issue("error", "invalid_change_status", "ChangePlan: неверный status", str(path)))
    title = str(data.get("title", ""))
    if looks_like_raw_id(title) or not contains_cyrillic(title):
        issues.append(Issue("error", "bad_russian_title", "ChangePlan: title должен быть понятным русским названием", str(path)))
    for node_id in data.get("affected_nodes", []) or []:
        if node_id not in graph_nodes:
            issues.append(Issue("error", "missing_affected_node", f"ChangePlan affected_node не найден в графе: {node_id}", str(path)))
    risk_level = ((data.get("risk") or {}).get("level"))
    approval_level = ((data.get("approval") or {}).get("level"))
    if risk_level not in RISK_LEVELS:
        issues.append(Issue("error", "invalid_risk_level", "ChangePlan: risk.level неверен", str(path)))
    if approval_level not in APPROVAL_LEVELS:
        issues.append(Issue("error", "invalid_approval_level", "ChangePlan: approval.level неверен", str(path)))
    if risk_level in RISK_LEVELS and approval_level in APPROVAL_LEVELS and not approval_level_ok(risk_level, approval_level):
        issues.append(Issue("error", "approval_below_risk", f"ChangePlan: approval {approval_level} ниже требуемого для risk {risk_level}", str(path)))
    if not data.get("verification"):
        issues.append(Issue("error", "missing_verification", "ChangePlan: отсутствует verification", str(path)))
    if risk_level in {"medium", "high", "critical"} and not data.get("rollback"):
        issues.append(Issue("error", "missing_rollback", "ChangePlan medium+ должен иметь rollback", str(path)))
    return issues


def _check_human_text(value: Any, code: str, label: str, path: Path) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(value, str) or looks_like_raw_id(value) or not contains_cyrillic(value):
        issues.append(Issue("error", code, f"{label} должен быть понятным русским текстом", str(path)))
    return issues


def validate_generated_ux(data: dict[str, Any], path: Path) -> list[Issue]:
    issues: list[Issue] = []
    kind = data.get("kind")
    if kind == "AgentContext":
        for section_name in ["allowed_next_actions", "blocked_actions"]:
            section = data.get(section_name, []) or []
            if not section:
                issues.append(Issue("error", "missing_agent_context_actions", f"agent_context должен содержать {section_name}", str(path)))
            for i, action in enumerate(section):
                if not isinstance(action, dict):
                    continue
                issues.extend(_check_human_text(action.get("title"), "bad_action_title", f"{section_name}[{i}].title", path))
        summary = data.get("summary", {}) or {}
        if summary.get("title"):
            issues.extend(_check_human_text(summary.get("title"), "bad_summary_title", "summary.title", path))
    if kind == "DriftReport":
        for i, item in enumerate(data.get("items", []) or []):
            if not isinstance(item, dict):
                continue
            if item.get("status_label"):
                issues.extend(_check_human_text(item.get("status_label"), "bad_status_label", f"items[{i}].status_label", path))
    if kind == "ArchitectureBrief":
        project = data.get("project", {}) or {}
        if project.get("title"):
            issues.extend(_check_human_text(project.get("title"), "bad_project_title", "project.title", path))
        for i, rule in enumerate(data.get("rules", []) or []):
            issues.extend(_check_human_text(rule, "bad_rule_text", f"rules[{i}]", path))
    return issues


def validate_generated_json(project: Path) -> list[Issue]:
    issues: list[Issue] = []
    control = project_control(project)
    for name in ["architecture.brief.json", "graph.observed.json", "drift.report.json", "agent_context.json"]:
        path = control / name
        if not path.exists():
            continue
        try:
            data = load_json(path)
        except Exception as exc:
            issues.append(Issue("error", "invalid_generated_json", f"{name}: невалидный JSON: {exc}", str(path)))
            continue
        if not isinstance(data, dict):
            issues.append(Issue("error", "generated_not_object", f"{name}: должен быть JSON object", str(path)))
            continue
        if data.get("apiVersion") != API_VERSION:
            issues.append(Issue("error", "invalid_generated_api_version", f"{name}: apiVersion должен быть {API_VERSION}", str(path)))
        issues.extend(validate_generated_ux(data, path))
    return issues


def verify_project(project: Path) -> tuple[list[Issue], dict[str, Any]]:
    control = project_control(project)
    issues: list[Issue] = []
    project_path = control / "project.yaml"
    graph_path = control / "graph.desired.yaml"
    graph_nodes: set[str] = set()
    if not project_path.exists():
        issues.append(Issue("error", "missing_project_yaml", "Не найден .botctl/project.yaml", str(project_path)))
    else:
        try:
            project_data = load_yaml(project_path)
            issues.extend(validate_against_schema(project_data, "project.schema.json", project_path))
            issues.extend(validate_project_yaml(project_data, project_path))
        except Exception as exc:
            issues.append(Issue("error", "project_yaml_parse_failed", str(exc), str(project_path)))
    if not graph_path.exists():
        issues.append(Issue("error", "missing_desired_graph", "Не найден .botctl/graph.desired.yaml", str(graph_path)))
    else:
        try:
            graph_data = load_yaml(graph_path)
            issues.extend(validate_against_schema(graph_data, "graph.schema.json", graph_path))
            issues.extend(validate_graph(graph_data, graph_path))
            graph_nodes = {str(node.get("id")) for node in (graph_data.get("nodes") or []) if isinstance(node, dict) and node.get("id")}
        except Exception as exc:
            issues.append(Issue("error", "desired_graph_parse_failed", str(exc), str(graph_path)))
    for plan_path in list_change_plans(project):
        try:
            plan = load_yaml(plan_path)
            issues.extend(validate_against_schema(plan, "change-plan.schema.json", plan_path))
            issues.extend(validate_change_plan(plan, plan_path, graph_nodes))
        except Exception as exc:
            issues.append(Issue("error", "change_plan_parse_failed", str(exc), str(plan_path)))
    issues.extend(validate_generated_json(project))
    summary = {
        "errors": sum(1 for issue in issues if issue.level == "error"),
        "warnings": sum(1 for issue in issues if issue.level == "warning"),
        "checked_change_plans": len(list_change_plans(project)),
    }
    return issues, summary
