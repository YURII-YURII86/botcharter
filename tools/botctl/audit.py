from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from .model import API_VERSION, load_yaml, now_iso, relative

SAFE_ROOTS = ("src", "app", "bot", "bots", "tests")
UNSAFE_PARTS = {".git", ".env", ".venv", "venv", "data", "sessions", "credentials", "secrets", "__pycache__", ".botctl"}
UNSAFE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".session"}
TECHNICAL_EVENT_TOKENS = ("transport", "telegram_api", "rich_api", "render_", "http_", "network_", "proxy_", "upload_", "download_", "trace_", "debug_")


def _safe_python_files(project: Path, *, tests: bool | None = None) -> list[Path]:
    files: list[Path] = []
    for root_name in SAFE_ROOTS:
        if tests is True and root_name != "tests":
            continue
        if tests is False and root_name == "tests":
            continue
        root = project / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            rel_parts = {part.lower() for part in path.relative_to(project).parts}
            if rel_parts & UNSAFE_PARTS or path.suffix.lower() in UNSAFE_SUFFIXES:
                continue
            if path.is_file() and path.stat().st_size <= 2_000_000:
                files.append(path)
    return sorted(set(files))


def safe_source_hash(project: Path) -> str:
    digest = hashlib.sha256()
    for path in _safe_python_files(project):
        digest.update(relative(project, path).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("*")
        return "".join(parts)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _strings(node: ast.AST) -> list[str]:
    return [child.value for child in ast.walk(node) if isinstance(child, ast.Constant) and isinstance(child.value, str)]


def _pattern_key(value: str) -> str:
    clean = value.strip()
    if not clean:
        return clean
    return clean.split(":", 1)[0]


class _RuntimeVisitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.callbacks: list[dict[str, Any]] = []
        self.handler_keys: set[str] = set()
        self.handler_evidence: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.external_calls: list[dict[str, Any]] = []

    def visit_Call(self, node: ast.Call) -> Any:
        name = _call_name(node.func)
        if name.endswith("InlineKeyboardButton"):
            callback_node = next((item.value for item in node.keywords if item.arg == "callback_data"), None)
            value = _literal(callback_node)
            if value:
                self.callbacks.append({"value": value, "key": _pattern_key(value), "path": self.rel, "line": node.lineno})
        if name.endswith(("record_behavior", "record_behavior_event")):
            candidates = [_literal(arg) for arg in node.args]
            event = next((item for item in candidates if item), None)
            if name.endswith("record_behavior_event") and len(candidates) > 1:
                event = candidates[1] or event
            if event:
                self.events.append({"name": event, "path": self.rel, "line": node.lineno})
        if any(token in name for token in ("aiohttp.ClientSession", "urllib.request.urlopen", "httpx.", "requests.", "urlopen")):
            self.external_calls.append({"category": "http_client", "call": name, "path": self.rel, "line": node.lineno})
        if name.endswith("YoutubeDL") or ".extract_info" in name:
            self.external_calls.append({"category": "media_downloader", "call": name, "path": self.rel, "line": node.lineno})
        if name.startswith("subprocess."):
            self.external_calls.append({"category": "process_runner", "call": name, "path": self.rel, "line": node.lineno})
        if any(token in name for token in ("send_message", "send_photo", "send_document", "send_rich", ".answer", ".edit_text")):
            self.external_calls.append({"category": "telegram_bot_api", "call": name, "path": self.rel, "line": node.lineno})
        call_text = ast.unparse(node.func)
        if "callback_query" in call_text:
            keys = {_pattern_key(value) for value in _strings(node.func) if ":" in value and _pattern_key(value)}
            self.handler_keys.update(keys)
            if keys:
                self.handler_evidence.append({"registration": call_text, "keys": sorted(keys), "path": self.rel, "line": node.lineno})
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        decorator_text = " ".join(ast.unparse(item) for item in node.decorator_list)
        if "callback_query" in decorator_text.lower():
            values = [value for item in node.decorator_list for value in _strings(item) if ":" in value]
            keys = {_pattern_key(value) for value in values if _pattern_key(value)}
            if not keys:
                lowered = node.name.lower()
                for prefix in ("admin", "native", "emoji", "channel", "publish", "mode", "nav"):
                    if prefix in lowered:
                        keys.add(prefix)
            self.handler_keys.update(keys)
            self.handler_evidence.append({"function": node.name, "keys": sorted(keys), "path": self.rel, "line": node.lineno})
        self.generic_visit(node)


def _scan_runtime(project: Path) -> dict[str, Any]:
    callbacks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    external: list[dict[str, Any]] = []
    handler_keys: set[str] = set()
    handler_evidence: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for path in _safe_python_files(project, tests=False):
        rel = relative(project, path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?([A-Za-z_][A-Za-z0-9_]*)", text, re.I):
            tables.append({"name": match.group(1), "path": rel, "line": text.count("\n", 0, match.start()) + 1})
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            parse_errors.append({"path": rel, "line": exc.lineno, "error": exc.msg})
            continue
        visitor = _RuntimeVisitor(rel)
        visitor.visit(tree)
        callbacks.extend(visitor.callbacks)
        events.extend(visitor.events)
        external.extend(visitor.external_calls)
        handler_keys.update(visitor.handler_keys)
        handler_evidence.extend(visitor.handler_evidence)
    tests = [relative(project, path) for path in _safe_python_files(project, tests=True)]
    test_names: set[str] = set()
    for path in _safe_python_files(project, tests=True):
        text = path.read_text(encoding="utf-8", errors="replace")
        test_names.update(re.findall(r"^def\s+(test_[A-Za-z0-9_]+)", text, re.M))
        test_names.update(re.findall(r"^async\s+def\s+(test_[A-Za-z0-9_]+)", text, re.M))
    return {"callbacks": callbacks, "handler_keys": sorted(handler_keys), "handler_evidence": handler_evidence, "events": events, "tables": tables, "external_calls": external, "tests": tests, "test_names": sorted(test_names), "parse_errors": parse_errors}


def _spec_data(specs_dir: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in ("FLOWS", "EVENTS", "UI_GRAPH", "STORAGE", "DEPENDENCIES", "CONTRACTS"):
        path = specs_dir / f"{name}.yaml"
        data = load_yaml(path) if path.exists() else {}
        result[name] = data if isinstance(data, dict) else {}
    return result


def _issue(check: str, code: str, severity: str, title: str, evidence: Any, recommendation: str) -> dict[str, Any]:
    return {"check": check, "code": code, "severity": severity, "title": title, "evidence": evidence, "recommendation": recommendation}


def audit_runtime_source(project: Path, specs_dir: Path) -> dict[str, Any]:
    project = project.resolve()
    specs = _spec_data(specs_dir.resolve())
    observed = _scan_runtime(project)
    issues: list[dict[str, Any]] = []

    callback_keys = {item["key"] for item in observed["callbacks"] if item.get("key")}
    handler_keys = set(observed["handler_keys"])
    for key in sorted(callback_keys - handler_keys):
        evidence = [item for item in observed["callbacks"] if item.get("key") == key][:10]
        issues.append(_issue("callbacks", "callback.without_handler", "error", f"Callback namespace `{key}` не покрыт найденным handler", evidence, "Добавить handler или уточнить static-audit exception."))

    ui_ids = {str(button.get("id")) for screen in specs["UI_GRAPH"].get("screens", {}).values() if isinstance(screen, dict) for button in screen.get("buttons", []) or [] if isinstance(button, dict) and button.get("id")}
    ui_ids.update(str(item) for item in specs["UI_GRAPH"].get("callback_namespaces", {}).keys())
    ui_keys = {_pattern_key(item) for item in ui_ids}
    for key in sorted(handler_keys - ui_keys):
        issues.append(_issue("ui_graph", "handler.missing_from_ui_graph", "warning", f"Handler namespace `{key}` не отражён в UI_GRAPH", [item for item in observed["handler_evidence"] if key in item.get("keys", [])][:10], "Добавить screen/button/action или описать internal handler."))

    registered_events = set(specs["EVENTS"].get("events", {}).keys())
    emitted_events = {item["name"] for item in observed["events"]}
    for name in sorted(emitted_events - registered_events):
        issues.append(_issue("events", "event.unregistered", "error", f"Событие `{name}` не зарегистрировано в EVENTS.yaml", [item for item in observed["events"] if item["name"] == name], "Добавить product event в registry или убрать его из product analytics."))

    registered_tables = set(specs["STORAGE"].get("tables", {}).keys())
    observed_tables = {item["name"] for item in observed["tables"]}
    for name in sorted(observed_tables - registered_tables):
        issues.append(_issue("storage", "table.unregistered", "error", f"Таблица `{name}` не описана в STORAGE.yaml", [item for item in observed["tables"] if item["name"] == name], "Описать owner, PII, TTL и purpose."))

    dependency_specs = specs["DEPENDENCIES"].get("dependencies", {})
    declared_dependencies = set(dependency_specs.keys())
    external_categories = {item["category"] for item in observed["external_calls"]}
    dependency_mapping = {"telegram_bot_api": "telegram_bot_api", "http_client": "media_hosts", "media_downloader": "media_downloader", "process_runner": "process_runner"}
    for category in sorted(external_categories):
        matching = [name for name, spec in dependency_specs.items() if isinstance(spec, dict) and category in (spec.get("audit_categories", []) or [])]
        dependency = dependency_mapping.get(category, category)
        if not matching and dependency not in declared_dependencies:
            issues.append(_issue("dependencies", "dependency.unregistered", "error", f"Внешние вызовы `{category}` не покрыты DEPENDENCIES.yaml", [item for item in observed["external_calls"] if item["category"] == category][:20], f"Добавить dependency `{dependency}` с risks/guards."))

    test_text = " ".join(observed["test_names"] + observed["tests"]).lower()
    for flow_id, flow in specs["FLOWS"].get("flows", {}).items():
        if not isinstance(flow, dict) or flow.get("owner") == "control_layer":
            continue
        evidence_map = flow.get("contract_evidence", {}) if isinstance(flow.get("contract_evidence"), dict) else {}
        for contract in flow.get("contract_tests", []) or []:
            evidence_paths = evidence_map.get(str(contract), [])
            if isinstance(evidence_paths, str):
                evidence_paths = [evidence_paths]
            if isinstance(evidence_paths, list) and evidence_paths and all((project / str(path)).is_file() for path in evidence_paths):
                continue
            tokens = [token for token in str(contract).lower().split("_") if len(token) >= 4]
            if tokens and not all(token in test_text for token in tokens[:2]):
                issues.append(_issue("flow_contracts", "flow.contract_test_not_found", "warning", f"Flow `{flow_id}`: contract `{contract}` не найден в tests", observed["tests"], "Добавить/переименовать contract test или уточнить spec."))

    for item in observed["events"]:
        lowered = item["name"].lower()
        if any(token in lowered for token in TECHNICAL_EVENT_TOKENS):
            issues.append(_issue("analytics_separation", "event.technical_in_product_analytics", "error", f"Техническое событие `{item['name']}` пишется как product behavior", item, "Перенести в technical trace/metrics или явно обосновать product meaning."))

    if observed["parse_errors"]:
        issues.append(_issue("scanner", "source.parse_error", "warning", "Часть Python files не разобрана", observed["parse_errors"], "Починить syntax или добавить parser adapter."))

    checks: dict[str, Any] = {}
    for check in ("callbacks", "ui_graph", "events", "storage", "dependencies", "flow_contracts", "analytics_separation"):
        related = [item for item in issues if item["check"] == check]
        checks[check] = {"status": "passed" if not related else "failed", "issues": len(related)}
    errors = sum(1 for item in issues if item["severity"] == "error")
    warnings = sum(1 for item in issues if item["severity"] == "warning")
    return {
        "apiVersion": API_VERSION,
        "kind": "BotRuntimeSourceAudit",
        "generated_at": now_iso(),
        "read_only": True,
        "target_project": str(project),
        "specs_dir": str(specs_dir.resolve()),
        "summary": {"status": "passed" if not issues else "drift_found", "errors": errors, "warnings": warnings, "issues": len(issues)},
        "checks": checks,
        "observed_summary": {"callbacks": len(observed["callbacks"]), "handler_namespaces": len(handler_keys), "events": len(observed["events"]), "tables": len(observed["tables"]), "external_calls": len(observed["external_calls"]), "test_files": len(observed["tests"])},
        "issues": issues,
        "safety": {"imports_target_code": False, "reads_runtime_databases": False, "contacts_network": False, "writes_target_project": False, "scanned_extensions": [".py"], "skipped_path_parts": sorted(UNSAFE_PARTS)},
    }
