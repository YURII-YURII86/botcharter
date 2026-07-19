from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import yaml

CONTROL_DIR = ".botctl"
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
APPROVAL_ORDER = {"none": 0, "agent_self_check": 1, "human_review": 2, "human_approval": 3, "blocked": 4}
RUSSIAN_RE = re.compile(r"[А-Яа-яЁё]")
RAW_ID_RE = re.compile(r"^[a-z0-9_.-]+$")

STATUS_LABELS = {
    "in_sync": "Согласовано",
    "missing_local": "Описано, но не найдено в проекте",
    "missing_runtime": "Описано или найдено локально, но не найдено в runtime",
    "undocumented_local": "Найдено в проекте, но не описано",
    "undocumented_runtime": "Найдено в runtime, но не описано локально",
    "stale_evidence": "Подтверждение устарело",
    "conflict": "Источники противоречат друг другу",
    "inferred_only": "Есть только гипотеза",
    "unknown": "Недостаточно данных",
}

@dataclass
class Paths:
    repo_root: Path
    project: Path
    botctl: Path

    @property
    def schemas(self) -> Path:
        return self.repo_root / "schemas"

    @property
    def project_yaml(self) -> Path:
        return self.botctl / "project.yaml"

    @property
    def desired_graph(self) -> Path:
        return self.botctl / "graph.desired.yaml"

    @property
    def observed_graph(self) -> Path:
        return self.botctl / "graph.observed.json"

    @property
    def drift_report(self) -> Path:
        return self.botctl / "drift.report.json"

    @property
    def architecture_brief(self) -> Path:
        return self.botctl / "architecture.brief.json"

    @property
    def agent_context_json(self) -> Path:
        return self.botctl / "agent_context.json"

    @property
    def agent_context_md(self) -> Path:
        return self.botctl / "agent_context.md"

    @property
    def change_plans(self) -> Path:
        return self.botctl / "change_plans"


def make_paths(project: str | None) -> Paths:
    repo_root = Path(__file__).resolve().parents[2]
    project_path = Path(project).expanduser().resolve() if project else Path.cwd().resolve()
    return Paths(repo_root=repo_root, project=project_path, botctl=project_path / CONTROL_DIR)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def load_schema(paths: Paths, name: str) -> dict[str, Any]:
    return load_json(paths.schemas / name)


def validate_schema(paths: Paths, data: Any, schema_name: str, label: str, errors: list[str]) -> None:
    try:
        jsonschema.Draft202012Validator(load_schema(paths, schema_name)).validate(data)
    except Exception as exc:
        errors.append(f"{label}: schema validation failed: {exc}")


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def project_artifacts(paths: Paths) -> dict[str, Any]:
    files = {
        "project_yaml": paths.project_yaml,
        "desired_graph": paths.desired_graph,
        "observed_graph": paths.observed_graph,
        "drift_report": paths.drift_report,
        "architecture_brief": paths.architecture_brief,
        "agent_context_json": paths.agent_context_json,
        "agent_context_md": paths.agent_context_md,
    }
    return {name: {"path": str(path.relative_to(paths.project)), "exists": path.exists()} for name, path in files.items()}


def read_desired(paths: Paths) -> dict[str, Any]:
    return load_yaml(paths.desired_graph) if paths.desired_graph.exists() else {"nodes": [], "edges": []}


def inspect_data(paths: Paths, mode: str = "json") -> dict[str, Any]:
    artifacts = project_artifacts(paths)
    desired_exists = artifacts["desired_graph"]["exists"]
    project_exists = artifacts["project_yaml"]["exists"]
    status = "ready_for_snapshot" if project_exists and desired_exists else "missing_control_files"
    safe_next = []
    blocked = []
    if project_exists and desired_exists:
        safe_next.extend([
            {"id": "action.create_snapshot", "title": "Обновить снимок архитектуры", "command": "python3 tools/botctl.py snapshot --project <project>", "risk_level": "low", "approval_level": "agent_self_check"},
            {"id": "action.verify", "title": "Проверить контракты управления", "command": "python3 tools/botctl.py verify --project <project>", "risk_level": "low", "approval_level": "none"},
        ])
    else:
        safe_next.append({"id": "action.initialize_botctl", "title": "Создать .botctl/project.yaml и .botctl/graph.desired.yaml", "risk_level": "low", "approval_level": "human_review"})
    blocked.append({"id": "action.runtime_change", "title": "Изменить runtime", "reason": "v0 не поддерживает runtime apply и требует утверждённый ChangePlan", "required_before": ["Собрать локальный снимок", "Создать и проверить ChangePlan", "Получить подтверждение при риске"]})
    return {
        "command": "inspect",
        "read_only": True,
        "format": mode,
        "project": {"path": str(paths.project), "control_dir": str(paths.botctl), "title": _project_title(paths)},
        "artifacts": artifacts,
        "status": {"code": status, "label": "Готов к снимку" if status == "ready_for_snapshot" else "Не хватает control-файлов"},
        "safe_next_actions": safe_next,
        "blocked_actions": blocked,
    }


def _project_title(paths: Paths) -> str:
    if paths.project_yaml.exists():
        try:
            return str(load_yaml(paths.project_yaml).get("title") or paths.project.name)
        except Exception:
            return paths.project.name
    return paths.project.name


def print_human_inspect(data: dict[str, Any]) -> None:
    print("Botctl inspect — безопасный read-only вход")
    print(f"Проект: {data['project']['title']}")
    print(f"Путь: {data['project']['path']}")
    print(f"Статус: {data['status']['label']} ({data['status']['code']})")
    print("\nАртефакты:")
    for name, info in data["artifacts"].items():
        mark = "есть" if info["exists"] else "нет"
        print(f"- {name}: {mark} — {info['path']}")
    print("\nБезопасные следующие действия:")
    for action in data["safe_next_actions"]:
        print(f"- {action['title']}")
    print("\nЗаблокированные действия:")
    for action in data["blocked_actions"]:
        print(f"- {action['title']}: {action['reason']}")


def discover_local(paths: Paths) -> dict[str, Any]:
    py_files = sorted(p for p in paths.project.glob("src/**/*.py") if "__pycache__" not in p.parts)
    test_files = sorted(paths.project.glob("tests/**/*.py"))
    docker_files = [p for name in ["Dockerfile", "docker-compose.yml", "compose.yml"] if (p := paths.project / name).exists()]
    makefile = paths.project / "Makefile"
    nodes = []
    edges = []
    for p in py_files:
        rel = p.relative_to(paths.project).as_posix()
        node_id = "handler." + rel.replace("/", ".").replace(".py", "").replace("src.", "")
        nodes.append(_observed_node(node_id, "Handler", "L3", f"Python-модуль {rel}", rel, p))
    for p in test_files:
        rel = p.relative_to(paths.project).as_posix()
        node_id = "test." + rel.replace("/", ".").replace(".py", "")
        nodes.append(_observed_node(node_id, "Test", "L5", f"Тест {rel}", rel, p))
    for p in docker_files:
        rel = p.relative_to(paths.project).as_posix()
        node_id = "deploy." + rel.replace("/", ".").replace(".yml", "").lower()
        nodes.append(_observed_node(node_id, "DeployTarget", "L4", f"Цель запуска {rel}", rel, p))
    if makefile.exists():
        nodes.append(_observed_node("tool.makefile", "Tool", "L3", "Команды Makefile", "Makefile", makefile))
    return {"apiVersion": "botctl.dev/v0", "kind": "ObservedGraph", "source": "observed_local", "generated_at": now_iso(), "project_path": str(paths.project), "nodes": nodes, "edges": edges}


def _observed_node(node_id: str, kind: str, layer: str, title: str, rel: str, path: Path) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "layer": layer,
        "title": title,
        "lifecycle_status": "active",
        "knowledge_status": "confirmed",
        "confidence": "high",
        "risk_level": "low",
        "source": {"type": "local_scan", "path": rel},
        "evidence": [{"type": "code" if kind == "Handler" else "file", "path": rel, "collected_at": now_iso(), "source_fingerprint": {"file_hash": file_hash(path)}, "validity": {"status": "current", "checked_at": now_iso()}}],
    }


def build_drift(paths: Paths, desired: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    desired_ids = {n["id"] for n in desired.get("nodes", [])}
    observed_ids = {n["id"] for n in observed.get("nodes", [])}
    items = []
    for node_id in sorted(desired_ids - observed_ids):
        items.append({"id": f"drift.{node_id}.missing_local", "node_id": node_id, "status": "missing_local", "status_label": STATUS_LABELS["missing_local"], "severity": "medium"})
    for node_id in sorted(observed_ids - desired_ids):
        items.append({"id": f"drift.{node_id}.undocumented_local", "node_id": node_id, "status": "undocumented_local", "status_label": STATUS_LABELS["undocumented_local"], "severity": "low"})
    summary = {"total": len(items), "by_status": {}}
    for item in items:
        summary["by_status"][item["status"]] = summary["by_status"].get(item["status"], 0) + 1
    if not items:
        summary["by_status"]["in_sync"] = 1
    return {"apiVersion": "botctl.dev/v0", "kind": "DriftReport", "generated_at": now_iso(), "comparisons": ["desired_vs_observed_local"], "summary": summary, "items": items}


def build_brief(paths: Paths, desired: dict[str, Any], observed: dict[str, Any], drift: dict[str, Any]) -> dict[str, Any]:
    return {"apiVersion": "botctl.dev/v0", "kind": "ArchitectureBrief", "generated_at": now_iso(), "project": {"title": _project_title(paths), "path": str(paths.project)}, "current_state": {"desired_nodes": len(desired.get("nodes", [])), "observed_local_nodes": len(observed.get("nodes", [])), "drift_items": drift["summary"]["total"], "runtime_status": "не проверялся в v0"}, "rules": ["botctl inspect только читает", "Runtime нельзя менять без ChangePlan", "Inferred не является основанием для apply", "Человеко-видимые названия должны быть на русском"]}


def build_agent_context(paths: Paths, brief: dict[str, Any], drift: dict[str, Any], mode: str = "brief") -> dict[str, Any]:
    return {"apiVersion": "botctl.dev/v0", "kind": "AgentContext", "mode": mode, "generated_at": now_iso(), "project": brief["project"], "rules": brief["rules"], "status": brief["current_state"], "drift_summary": drift["summary"], "critical_items": [i for i in drift.get("items", []) if i.get("severity") in {"high", "critical"}], "next_actions": {"allowed": [{"id": "action.verify", "title": "Проверить контракты управления", "command": "python3 tools/botctl.py verify --project <project>", "risk_level": "low", "approval_level": "none"}, {"id": "action.diff", "title": "Проверить расхождения", "command": "python3 tools/botctl.py diff --project <project>", "risk_level": "low", "approval_level": "none"}], "blocked": [{"id": "action.apply_runtime_change", "title": "Изменить runtime", "reason": "В v0 apply/runtime-probe не реализованы; нужен ChangePlan и подтверждение", "required_before": ["Создать ChangePlan", "Проверить drift", "Получить approval"]}]}, "links": {"desired_graph": ".botctl/graph.desired.yaml", "observed_graph": ".botctl/graph.observed.json", "drift_report": ".botctl/drift.report.json"}}


def render_agent_context_md(context: dict[str, Any]) -> str:
    lines = ["# Контекст агента", "", f"Проект: {context['project']['title']}", f"Режим: {context['mode']}", "", "## Текущее состояние", ""]
    for key, value in context["status"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Разрешённые следующие действия", ""]
    for action in context["next_actions"]["allowed"]:
        lines.append(f"- {action['title']} — `{action.get('command', '')}`")
    lines += ["", "## Заблокированные действия", ""]
    for action in context["next_actions"]["blocked"]:
        lines.append(f"- {action['title']}: {action['reason']}")
    lines.append("")
    return "\n".join(lines)


def snapshot(paths: Paths, context_mode: str = "brief") -> dict[str, Any]:
    desired = read_desired(paths)
    observed = discover_local(paths)
    drift = build_drift(paths, desired, observed)
    brief = build_brief(paths, desired, observed, drift)
    agent = build_agent_context(paths, brief, drift, context_mode)
    write_json(paths.observed_graph, observed)
    write_json(paths.drift_report, drift)
    write_json(paths.architecture_brief, brief)
    write_json(paths.agent_context_json, agent)
    paths.agent_context_md.write_text(render_agent_context_md(agent), encoding="utf-8")
    return {"written": [str(paths.observed_graph), str(paths.drift_report), str(paths.architecture_brief), str(paths.agent_context_json), str(paths.agent_context_md)]}


def verify(paths: Paths) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not paths.project_yaml.exists():
        errors.append(".botctl/project.yaml отсутствует")
    else:
        validate_schema(paths, load_yaml(paths.project_yaml), "project.schema.json", "project.yaml", errors)
    if not paths.desired_graph.exists():
        errors.append(".botctl/graph.desired.yaml отсутствует")
        desired = {"nodes": [], "edges": []}
    else:
        desired = load_yaml(paths.desired_graph)
        validate_schema(paths, desired, "graph.schema.json", "graph.desired.yaml", errors)
        _semantic_graph_checks(desired, errors)
    for cp in sorted(paths.change_plans.glob("*.yaml")) if paths.change_plans.exists() else []:
        data = load_yaml(cp)
        validate_schema(paths, data, "change-plan.schema.json", cp.name, errors)
        _semantic_change_plan_checks(data, desired, cp.name, errors)
    for generated in [paths.observed_graph, paths.drift_report, paths.architecture_brief, paths.agent_context_json]:
        if generated.exists():
            try:
                load_json(generated)
            except Exception as exc:
                errors.append(f"{generated.name}: generated JSON не читается: {exc}")
        else:
            warnings.append(f"{generated.name}: generated artifact отсутствует; запустите snapshot")
    return (not errors, errors, warnings)


def _semantic_graph_checks(graph: dict[str, Any], errors: list[str]) -> None:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    ids = [n.get("id") for n in nodes]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    if dupes:
        errors.append(f"graph.desired.yaml: дубли node.id: {', '.join(dupes)}")
    node_set = set(ids)
    for n in nodes:
        title = str(n.get("title", ""))
        if not RUSSIAN_RE.search(title):
            errors.append(f"{n.get('id')}: title должен быть понятным русским названием")
        if RAW_ID_RE.match(title):
            errors.append(f"{n.get('id')}: title выглядит как технический id")
    for e in edges:
        if e.get("from") not in node_set:
            errors.append(f"{e.get('id')}: edge.from указывает на неизвестный node {e.get('from')}")
        if e.get("to") not in node_set:
            errors.append(f"{e.get('id')}: edge.to указывает на неизвестный node {e.get('to')}")
        title = str(e.get("title", ""))
        if not RUSSIAN_RE.search(title):
            errors.append(f"{e.get('id')}: title связи должен быть на русском")


def _semantic_change_plan_checks(plan: dict[str, Any], graph: dict[str, Any], label: str, errors: list[str]) -> None:
    node_ids = {n.get("id") for n in graph.get("nodes", [])}
    for affected in plan.get("affected_nodes", []):
        if affected not in node_ids:
            errors.append(f"{label}: affected_node не найден в graph.desired.yaml: {affected}")
    risk = plan.get("risk", {}).get("level", "low")
    approval = plan.get("approval", {}).get("level", "none")
    required = "human_review" if risk == "medium" else "human_approval" if risk in {"high", "critical"} else "none"
    if APPROVAL_ORDER.get(approval, 0) < APPROVAL_ORDER[required]:
        errors.append(f"{label}: approval {approval} ниже требуемого {required} для риска {risk}")
    if RISK_ORDER.get(risk, 0) >= RISK_ORDER["medium"] and not plan.get("rollback"):
        errors.append(f"{label}: для medium+ риска нужен rollback")


def diff(paths: Paths) -> dict[str, Any]:
    if paths.drift_report.exists():
        return load_json(paths.drift_report)
    return build_drift(paths, read_desired(paths), discover_local(paths))


def plan_validate(paths: Paths) -> tuple[bool, list[str]]:
    ok, errors, _warnings = verify(paths)
    cp_errors = [e for e in errors if "ChangePlan" in e or "affected_node" in e or "approval" in e or "rollback" in e or "change" in e]
    return ok and not cp_errors, cp_errors


def add_common_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default=None, help="Путь к bot-проекту; по умолчанию текущая директория")
