from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import jsonschema

from .model import API_VERSION, dump_yaml, load_yaml, now_iso, project_control, relative

COMMAND_RE = re.compile(r"(?<![\w/])/(start|help|settings|status|model|queue|admin|creator|lead|publish|cancel|cleanup|pullreels|reels|invite|broadcast|jobs|profile)\b")
CALLBACK_RE = re.compile(r"\b([a-z][a-z0-9_]*)(?::[A-Za-z0-9_{}.-]+)+")
DESIGN_SCAN_DIRS = ("src", "app", "bot", "bots")
DESIGN_MAX_FILES = 200
DESIGN_MAX_BYTES = 2_000_000
UNSAFE_PATH_PARTS = {
    ".env",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "data",
    "sessions",
    "session",
    "credentials",
    "secrets",
}
UNSAFE_FILE_FRAGMENTS = (".env", "session", "state.sqlite", "credentials", "secret", "token")
RULEPACK_DIR = Path(__file__).resolve().parent / "rulepacks"
DEFAULT_TELEGRAM_UX_RULEPACK = RULEPACK_DIR / "telegram_bot_builder_ux.yaml"

ROLE_HINTS = {
    "admin": {"admin", "owner", "moderator"},
    "creator": {"creator", "author"},
    "lead": {"lead"},
    "guest": {"guest", "pending", "invite", "registration"},
    "allowed_user": {"allowed", "allowlist", "user"},
}


def _is_safe_design_path(project: Path, path: Path) -> bool:
    rel = relative(project, path)
    lowered_parts = {part.lower() for part in Path(rel).parts}
    lowered_rel = rel.lower()
    if lowered_parts & UNSAFE_PATH_PARTS:
        return False
    if any(fragment in lowered_rel for fragment in UNSAFE_FILE_FRAGMENTS):
        return False
    return True


def _collect_design_project_text(project: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    candidates: list[Path] = []
    for dirname in DESIGN_SCAN_DIRS:
        root = project / dirname
        if root.exists():
            candidates.extend(sorted(root.rglob("*.py")))
    seen: set[str] = set()
    for path in candidates:
        if len(texts) >= DESIGN_MAX_FILES:
            break
        if not path.is_file() or not _is_safe_design_path(project, path):
            continue
        rel = relative(project, path)
        if rel in seen:
            continue
        seen.add(rel)
        try:
            if path.stat().st_size > DESIGN_MAX_BYTES:
                continue
            texts[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return texts


def _line(lines: list[str], lineno: int | None) -> str:
    if not lineno or lineno < 1 or lineno > len(lines):
        return ""
    return lines[lineno - 1].strip()


def _literal_or_pattern(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                try:
                    parts.append("{" + ast.unparse(value.value) + "}")
                except Exception:  # pragma: no cover
                    parts.append("{value}")
        return "".join(parts)
    return None


def _const_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dict_string_value(node: ast.Dict, key: str) -> str | None:
    for dict_key, value in zip(node.keys, node.values):
        if dict_key is not None and _const_key(dict_key) == key:
            return _literal_or_pattern(value)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _keyword_value(node: ast.Call, key: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == key:
            return keyword.value
    return None


def _infer_role_from_text(*values: str) -> str:
    joined = " ".join(v.lower() for v in values if v)
    for role, hints in ROLE_HINTS.items():
        if any(hint in joined for hint in hints):
            return role
    return "user"


def _callback_namespace(callback_data: str) -> str:
    return callback_data.split(":", 1)[0] if ":" in callback_data else callback_data


def _callback_allowed_roles(namespace: str, context: str) -> list[str]:
    role = _infer_role_from_text(namespace, context)
    if namespace.startswith("admin"):
        return ["admin", "owner"]
    if namespace.startswith("creator"):
        return ["creator", "lead", "admin", "owner"]
    if namespace.startswith("lead"):
        return ["lead", "admin", "owner"]
    if namespace.startswith(("job", "queue", "main", "retry", "cancel", "publish", "pullreels", "pullreelsrun")):
        return ["allowed_user", "admin", "owner"]
    return [role] if role != "user" else ["user", "allowed_user", "admin", "owner"]


def _add_unique(items: list[dict[str, Any]], item: dict[str, Any], keys: tuple[str, ...]) -> None:
    for existing in items:
        if all(existing.get(key) == item.get(key) for key in keys):
            return
    items.append(item)


class _MenuAstVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, lines: list[str]) -> None:
        self.rel = rel
        self.lines = lines
        self.stack: list[str] = []
        self.commands: list[dict[str, Any]] = []
        self.buttons: list[dict[str, Any]] = []
        self.handlers: list[dict[str, Any]] = []
        self.callback_namespaces: dict[str, dict[str, Any]] = {}

    @property
    def context(self) -> str:
        return ".".join(self.stack)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        lowered = node.name.lower()
        if any(part in lowered for part in ("handle", "callback", "command", "start", "menu", "keyboard", "fallback", "publish", "creator", "admin", "queue")):
            _add_unique(
                self.handlers,
                {
                    "id": f"handler.{self.rel}:{node.name}",
                    "name": node.name,
                    "path": self.rel,
                    "line": node.lineno,
                    "role_hint": _infer_role_from_text(node.name, self.rel),
                    "snippet": _line(self.lines, node.lineno),
                },
                ("path", "name"),
            )
        self.generic_visit(node)
        self.stack.pop()

    def visit_Dict(self, node: ast.Dict) -> Any:
        command = _dict_string_value(node, "command")
        description = _dict_string_value(node, "description") or _dict_string_value(node, "text")
        if command:
            _add_unique(
                self.commands,
                {
                    "command": command.lstrip("/"),
                    "description": description or "",
                    "role_hint": _infer_role_from_text(self.context, description or command),
                    "source": {"path": self.rel, "line": node.lineno, "context": self.context},
                },
                ("command", "role_hint"),
            )
        text = _dict_string_value(node, "text")
        callback_data = _dict_string_value(node, "callback_data")
        if callback_data:
            self._add_button(text or "", callback_data, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        name = _call_name(node.func)
        if name.endswith("BotCommand"):
            command_node = _keyword_value(node, "command") or (node.args[0] if node.args else None)
            description_node = _keyword_value(node, "description") or (node.args[1] if len(node.args) > 1 else None)
            command = _literal_or_pattern(command_node)
            description = _literal_or_pattern(description_node) or ""
            if command:
                _add_unique(
                    self.commands,
                    {
                        "command": command.lstrip("/"),
                        "description": description,
                        "role_hint": _infer_role_from_text(self.context, description or command),
                        "source": {"path": self.rel, "line": node.lineno, "context": self.context},
                    },
                    ("command", "role_hint"),
                )
        if name.endswith("Command"):
            for arg in node.args:
                command = _literal_or_pattern(arg)
                if command:
                    _add_unique(
                        self.commands,
                        {
                            "command": command.lstrip("/"),
                            "description": "",
                            "role_hint": _infer_role_from_text(self.context, command),
                            "source": {"path": self.rel, "line": node.lineno, "context": self.context},
                        },
                        ("command", "role_hint"),
                    )
        if name.endswith("InlineKeyboardButton"):
            text = _literal_or_pattern(_keyword_value(node, "text") or (node.args[0] if node.args else None)) or ""
            callback_data = _literal_or_pattern(_keyword_value(node, "callback_data"))
            if callback_data:
                self._add_button(text, callback_data, node.lineno)
        self.generic_visit(node)

    def _add_button(self, text: str, callback_data: str, lineno: int) -> None:
        namespace = _callback_namespace(callback_data)
        allowed_roles = _callback_allowed_roles(namespace, self.context)
        button = {
            "text": text,
            "callback_data": callback_data,
            "namespace": namespace,
            "allowed_roles_hint": allowed_roles,
            "menu_hint": self.context or "module",
            "source": {"path": self.rel, "line": lineno, "context": self.context},
        }
        _add_unique(self.buttons, button, ("callback_data", "menu_hint"))
        ns = self.callback_namespaces.setdefault(
            namespace,
            {
                "namespace": namespace,
                "patterns": [],
                "allowed_roles_hint": sorted(set(allowed_roles)),
                "handlers_hint": [],
                "risk_notes": [],
            },
        )
        if callback_data not in ns["patterns"]:
            ns["patterns"].append(callback_data)
        ns["allowed_roles_hint"] = sorted(set(ns["allowed_roles_hint"]) | set(allowed_roles))
        if self.context and self.context not in ns["handlers_hint"]:
            ns["handlers_hint"].append(self.context)
        if namespace.startswith(("admin", "creator", "lead", "publish", "cleanup", "cancel")):
            note = "Требует явной проверки роли/прав и безопасной обработки повторного нажатия."
            if note not in ns["risk_notes"]:
                ns["risk_notes"].append(note)


DANGEROUS_CALLBACK_NAMESPACES = {"admin", "publish", "cleanup", "delete", "cancel", "broadcast", "creator", "lead"}
NAVIGATION_HINTS = {"back", "cancel", "help", "menu", "main", "home"}
GUARD_EVIDENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "permission_guard": re.compile(r"\b(is_admin|admin_only|owner|allowed|allowlist|check_access|access_control|require_admin|role|creator|lead)\b", re.I),
    "confirmation": re.compile(r"\b(confirm|confirmation|are_you_sure|sure|preview|dry.?run|approve|подтверд|подтвержд)\b", re.I),
    "idempotency": re.compile(r"\b(idempot|duplicate|already|active|pending|lock|nonce|processed|in_progress|_active|retry|attempt|queue)\b", re.I),
}


def _guard_evidence_for_namespaces(texts: dict[str, str], namespaces: set[str], *, max_per_kind: int = 8) -> dict[str, dict[str, list[dict[str, Any]]]]:
    evidence: dict[str, dict[str, list[dict[str, Any]]]] = {
        namespace: {kind: [] for kind in GUARD_EVIDENCE_PATTERNS}
        for namespace in namespaces
    }
    global_hits: dict[str, list[dict[str, Any]]] = {kind: [] for kind in GUARD_EVIDENCE_PATTERNS}
    for rel, text in texts.items():
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            lowered = line.lower()
            matched_kinds = [kind for kind, pattern in GUARD_EVIDENCE_PATTERNS.items() if pattern.search(line)]
            if not matched_kinds:
                continue
            line_namespaces = {namespace for namespace in namespaces if namespace and (f"{namespace}:" in lowered or namespace in lowered)}
            hit = {"path": rel, "line": line_no, "snippet": line.strip()[:220]}
            for kind in matched_kinds:
                if len(global_hits[kind]) < max_per_kind:
                    global_hits[kind].append(hit)
                for namespace in line_namespaces:
                    if len(evidence[namespace][kind]) < max_per_kind:
                        evidence[namespace][kind].append(hit)
    evidence["__global__"] = global_hits
    for namespace in namespaces:
        if namespace not in DANGEROUS_CALLBACK_NAMESPACES and not any(namespace.startswith(prefix) for prefix in DANGEROUS_CALLBACK_NAMESPACES):
            continue
        for kind, hits in global_hits.items():
            if not evidence[namespace][kind]:
                evidence[namespace][kind] = hits[:max_per_kind]
    return evidence


def _guard_status(guard_evidence: dict[str, list[dict[str, Any]]] | None) -> dict[str, Any]:
    guard_evidence = guard_evidence or {}
    has_permission = bool(guard_evidence.get("permission_guard"))
    has_confirmation = bool(guard_evidence.get("confirmation"))
    has_idempotency = bool(guard_evidence.get("idempotency"))
    return {
        "permission_guard": has_permission,
        "confirmation": has_confirmation,
        "idempotency": has_idempotency,
        "supported": has_permission and (has_confirmation or has_idempotency),
    }


def load_ux_rulepack(path: Path | None = None) -> dict[str, Any]:
    rulepack_path = path or DEFAULT_TELEGRAM_UX_RULEPACK
    try:
        data = load_yaml(rulepack_path)
    except Exception:
        return {
            "apiVersion": API_VERSION,
            "kind": "BotUXRulepack",
            "id": "telegram_bot_builder_ux_unavailable",
            "rules": [],
            "load_error": str(rulepack_path),
        }
    return data if isinstance(data, dict) else {"apiVersion": API_VERSION, "kind": "BotUXRulepack", "id": "invalid", "rules": []}


def _issue(issue_id: str, severity: str, title: str, why: str, evidence: list[Any] | None = None, recommendation: str | None = None) -> dict[str, Any]:
    return {
        "id": issue_id,
        "severity": severity,
        "title": title,
        "why": why,
        "evidence": evidence or [],
        "recommendation": recommendation or "Проверить вручную и уточнить UX-контракт.",
    }


def _rulepack_severity_to_issue(severity: str) -> str:
    return {"critical": "error", "high": "warning", "medium": "warning", "low": "info"}.get(str(severity), "info")


def _menu_map_text_index(menu_map: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("commands", "menus", "callback_contract", "handlers_hint", "roles"):
        value = menu_map.get(key, [])
        if isinstance(value, list):
            parts.append(json.dumps(value, ensure_ascii=False).lower())
    return "\n".join(parts)


def evaluate_ux_rulepack(menu_map: dict[str, Any], rulepack: dict[str, Any] | None = None) -> dict[str, Any]:
    rulepack = rulepack or load_ux_rulepack()
    roles = {str(role.get("id")) for role in menu_map.get("roles", []) if isinstance(role, dict) and role.get("id")}
    commands = [item for item in menu_map.get("commands", []) if isinstance(item, dict)]
    command_names = {str(command.get("command") or "").lstrip("/") for command in commands if command.get("command")}
    menus = [item for item in menu_map.get("menus", []) if isinstance(item, dict)]
    callbacks = [item for item in menu_map.get("callback_contract", []) if isinstance(item, dict)]
    patterns = [str(pattern).lower() for item in callbacks for pattern in item.get("patterns", []) if pattern]
    namespaces = {str(item.get("namespace") or "").lower() for item in callbacks if item.get("namespace")}
    handlers = [item for item in menu_map.get("handlers_hint", []) if isinstance(item, dict)]
    handler_text = json.dumps(handlers, ensure_ascii=False).lower()
    text_index = _menu_map_text_index(menu_map)
    long_task_hints = {"video", "audio", "voice", "download", "upload", "ai", "generate", "reels", "transcribe", "queue", "job"}
    monetization_hints = {"pay", "payment", "subscription", "premium", "invoice", "billing"}
    is_long_task_bot = any(hint in text_index for hint in long_task_hints)
    has_payment_flow = any(hint in text_index for hint in monetization_hints)
    has_dangerous = bool(namespaces & DANGEROUS_CALLBACK_NAMESPACES) or any(pattern.startswith(("admin:", "publish:", "cleanup:", "delete:", "broadcast:")) for pattern in patterns)

    def covered(rule_id: str) -> tuple[str, list[Any]]:
        if rule_id == "tbb.start_onboarding":
            return ("covered", sorted(command_names)) if "start" in command_names else ("missing", sorted(command_names))
        if rule_id == "tbb.help_command":
            return ("covered", sorted(command_names)) if "help" in command_names else ("missing", sorted(command_names))
        if rule_id == "tbb.command_design_clear":
            described = [command for command in commands if command.get("description")]
            return ("covered", {"commands": len(commands), "described": len(described)}) if commands else ("missing", [])
        if rule_id == "tbb.inline_keyboard_layout":
            return ("covered", {"menus": len(menus), "callbacks": len(callbacks)}) if menus and callbacks else ("missing", {"menus": len(menus), "callbacks": len(callbacks)})
        if rule_id == "tbb.navigation_escape_paths":
            found = {hint for hint in NAVIGATION_HINTS if any(hint in pattern for pattern in patterns)}
            missing = sorted({"back", "cancel", "help"} - found)
            return ("covered", sorted(found)) if not missing else ("missing", {"found": sorted(found), "missing": missing})
        if rule_id == "tbb.unknown_input_fallback":
            ok = "fallback" in handler_text or "unknown" in handler_text or "help" in command_names
            return ("covered", handler_text[:300]) if ok else ("missing", [])
        if rule_id == "tbb.long_task_progress":
            if not is_long_task_bot:
                return ("not_applicable", [])
            ok = any(token in text_index for token in ("progress", "status", "typing", "queue", "heartbeat", "liveness"))
            return ("covered", []) if ok else ("missing", [])
        if rule_id == "tbb.human_readable_errors":
            ok = any(token in text_index for token in ("error", "ошиб", "retry", "failed", "fallback"))
            return ("covered", []) if ok else ("missing", [])
        if rule_id == "tbb.empty_states":
            ok = any(token in text_index for token in ("empty", "пуст", "not_found", "not found", "нет ", "no "))
            return ("covered", []) if ok else ("weak", [])
        if rule_id == "tbb.rate_limiting":
            ok = any(token in text_index for token in ("rate", "limit", "queue", "attempt", "retry", "idempot", "cooldown", "processing", "concurrency"))
            return ("covered", []) if ok else ("missing" if has_dangerous or is_long_task_bot else "weak", [])
        if rule_id == "tbb.persistent_sessions":
            if len(roles) <= 2 and not is_long_task_bot:
                return ("not_applicable", [])
            ok = any(token in text_index for token in ("sqlite", "store", "storage", "db", "state", "session", "preferences", "queue"))
            return ("covered", []) if ok else ("missing", [])
        if rule_id == "tbb.global_error_handler":
            ok = any(token in handler_text for token in ("error", "exception", "catch", "global_error")) or "error" in namespaces
            return ("covered", []) if ok else ("missing", [])
        if rule_id == "tbb.token_env_safety":
            ok = any(token in text_index for token in ("env", "token_env", "configref", "secret"))
            return ("covered", []) if ok else ("not_evaluated", [])
        if rule_id == "tbb.analytics_observability":
            ok = any(token in text_index for token in ("log", "analytics", "metric", "status", "liveness", "health", "heartbeat"))
            return ("covered", []) if ok else ("weak", [])
        if rule_id == "tbb.polling_webhook_model":
            ok = any(token in text_index for token in ("poll", "webhook", "getupdates", "start_polling", "deploy", "launchd", "systemd"))
            return ("covered", []) if ok else ("not_evaluated", [])
        if rule_id == "tbb.monetization_guardrails":
            if not has_payment_flow:
                return ("not_applicable", [])
            ok = any(token in text_index for token in ("confirm", "status", "limit", "refund", "support", "invoice"))
            return ("covered", []) if ok else ("missing", [])
        return ("not_evaluated", [])

    results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for rule in rulepack.get("rules", []) or []:
        if not isinstance(rule, dict) or not rule.get("id"):
            continue
        status, evidence = covered(str(rule["id"]))
        result = {
            "id": rule.get("id"),
            "status": status,
            "severity": rule.get("severity"),
            "category": rule.get("category"),
            "title": rule.get("title"),
            "why": rule.get("why"),
            "recommendation": rule.get("recommendation"),
            "evidence": evidence,
        }
        results.append(result)
        if status in {"missing", "weak"}:
            issues.append(_issue(
                f"rulepack.{rule.get('id')}",
                _rulepack_severity_to_issue(str(rule.get("severity"))),
                str(rule.get("title") or rule.get("id")),
                str(rule.get("why") or "Rulepack requirement is not satisfied."),
                [evidence] if evidence not in ([], None) else [],
                str(rule.get("recommendation") or "Закрыть правило из UX rulepack."),
            ))
    return {
        "rulepack_id": rulepack.get("id"),
        "source_skill": rulepack.get("source_skill"),
        "source_path": rulepack.get("source_path"),
        "results": results,
        "issues": issues,
        "summary": {
            "rules": len(results),
            "covered": sum(1 for result in results if result.get("status") == "covered"),
            "missing": sum(1 for result in results if result.get("status") == "missing"),
            "weak": sum(1 for result in results if result.get("status") == "weak"),
            "not_applicable": sum(1 for result in results if result.get("status") == "not_applicable"),
            "not_evaluated": sum(1 for result in results if result.get("status") == "not_evaluated"),
        },
    }


def critique_menu_map(menu_map: dict[str, Any]) -> dict[str, Any]:
    roles = {str(role.get("id")) for role in menu_map.get("roles", []) if isinstance(role, dict) and role.get("id")}
    commands = [item for item in menu_map.get("commands", []) if isinstance(item, dict)]
    menus = [item for item in menu_map.get("menus", []) if isinstance(item, dict)]
    callbacks = [item for item in menu_map.get("callback_contract", []) if isinstance(item, dict)]
    quality_gates = [item for item in menu_map.get("quality_gates", []) if isinstance(item, dict)]
    issues: list[dict[str, Any]] = []

    if not roles or roles == {"user"}:
        issues.append(_issue(
            "roles.not_explicit",
            "warning",
            "Роли почти не выражены",
            "Сложный бот без явной модели ролей обычно смешивает обычный UX, админку и опасные действия.",
            sorted(roles),
            "Явно описать guest/user/admin/owner/creator/lead роли и что каждая видит в меню.",
        ))
    if "admin" in roles and "owner" not in roles:
        issues.append(_issue(
            "roles.owner_missing",
            "info",
            "Есть admin, но owner не выделен",
            "Для production-ботов часто полезно отделять владельца от обычного администратора.",
            sorted(roles),
            "Проверить, нужен ли owner/superadmin для destructive actions и production controls.",
        ))

    command_names = {str(command.get("command")) for command in commands if command.get("command")}
    if "start" not in command_names:
        issues.append(_issue(
            "commands.start_missing",
            "error",
            "Не найдена команда /start",
            "Без /start новый пользователь или invite-flow получает слабый onboarding.",
            sorted(command_names)[:30],
            "Добавить /start или подтвердить его регистрацию в passport/menu map.",
        ))
    if "help" not in command_names:
        issues.append(_issue(
            "commands.help_missing",
            "warning",
            "Не найдена команда /help",
            "У сложного бота должна быть доступная справка, особенно при разных ролях.",
            sorted(command_names)[:30],
            "Добавить /help или явную кнопку помощи в main menu.",
        ))

    if not menus:
        issues.append(_issue(
            "menus.no_inline_buttons",
            "warning",
            "Не найдены inline-меню",
            "Для сложных сценариев без карты кнопок агент не может проверить navigation/back/cancel/error paths.",
            [],
            "Добавить inline menu map или подтвердить, что бот intentionally text-only.",
        ))
    large_menus = [menu for menu in menus if len(menu.get("buttons", []) or []) > 10]
    if large_menus:
        issues.append(_issue(
            "menus.too_many_buttons",
            "info",
            "Есть меню с большим числом кнопок",
            "Большие меню сложнее читать на мобильном и труднее поддерживать в callback contract.",
            [{"id": menu.get("id"), "buttons": len(menu.get("buttons", []) or [])} for menu in large_menus[:10]],
            "Разбить большие меню на разделы или добавить пагинацию/назад.",
        ))

    all_callback_patterns: list[str] = []
    for namespace in callbacks:
        all_callback_patterns.extend(str(pattern) for pattern in namespace.get("patterns", []) if pattern)
    nav_found = {hint for hint in NAVIGATION_HINTS if any(hint in pattern.lower() for pattern in all_callback_patterns)}
    if "back" not in nav_found and menus:
        issues.append(_issue(
            "navigation.back_missing",
            "warning",
            "Не виден явный back navigation",
            "Без back-кнопок сложные меню превращаются в тупики, особенно для creator/admin flows.",
            sorted(nav_found),
            "Добавить callback namespace/action для back/main/menu navigation или подтвердить альтернативу.",
        ))
    if "cancel" not in nav_found and callbacks:
        issues.append(_issue(
            "navigation.cancel_missing",
            "warning",
            "Не виден явный cancel/abort action",
            "Долгие операции, публикации и админские действия должны иметь безопасную отмену.",
            sorted(nav_found),
            "Добавить cancel callbacks для pending/dangerous flows или описать idempotent fallback.",
        ))

    namespaces = {str(item.get("namespace")): item for item in callbacks if item.get("namespace")}
    if callbacks and len(namespaces) < max(2, len(callbacks) // 4):
        issues.append(_issue(
            "callbacks.low_namespace_diversity",
            "info",
            "Мало callback namespaces для размера меню",
            "Слишком широкие namespaces затрудняют права, audit и routing.",
            sorted(namespaces)[:30],
            "Проверить, не стоит ли разделить callbacks по menu/action domains.",
        ))
    weak_namespaces = []
    for namespace, data in namespaces.items():
        roles_hint = set(data.get("allowed_roles_hint", []) or [])
        patterns = data.get("patterns", []) or []
        if namespace in DANGEROUS_CALLBACK_NAMESPACES or namespace.startswith(tuple(DANGEROUS_CALLBACK_NAMESPACES)):
            if not data.get("risk_notes"):
                weak_namespaces.append({"namespace": namespace, "patterns": patterns[:5], "reason": "dangerous_without_risk_note"})
            if not (roles_hint & {"admin", "owner", "creator", "lead"}):
                weak_namespaces.append({"namespace": namespace, "patterns": patterns[:5], "reason": "dangerous_without_role_hint"})
    if weak_namespaces:
        issues.append(_issue(
            "callbacks.dangerous_actions_need_guards",
            "warning",
            "Опасные callback actions требуют guard/confirmation",
            "Publish/cleanup/admin/cancel/broadcast/creator actions должны иметь явную проверку прав, idempotency и понятный rollback/confirmation UX.",
            weak_namespaces[:20],
            "Добавить в паспорт callback_contract guard, allowed_roles, confirmation и idempotency для опасных namespaces.",
        ))

    role_menu_coverage: dict[str, int] = {role: 0 for role in roles}
    for menu in menus:
        for role in menu.get("visible_for_hint", []) or []:
            if role in role_menu_coverage:
                role_menu_coverage[role] += 1
    missing_role_menus = [role for role, count in sorted(role_menu_coverage.items()) if role not in {"owner"} and count == 0]
    if missing_role_menus and menus:
        issues.append(_issue(
            "roles.menu_coverage_gaps",
            "info",
            "Не у всех ролей есть видимые menu hints",
            "Роль может существовать в командах/контексте, но не иметь явного меню или кнопок.",
            missing_role_menus,
            "Проверить меню для этих ролей или уточнить, что они text-only/system roles.",
        ))

    failed_gates = [gate for gate in quality_gates if gate.get("status") not in {"covered"}]
    if failed_gates:
        issues.append(_issue(
            "quality_gates.not_all_covered",
            "warning",
            "Не все UX quality gates покрыты",
            "BotMenuMap уже нашёл слабые места в базовой структуре меню/ролей/commands.",
            failed_gates,
            "Закрыть weak/missing gates перед тем как использовать карту как эталон дизайна.",
        ))

    rulepack_evaluation = evaluate_ux_rulepack(menu_map)
    issues.extend(rulepack_evaluation.get("issues", []))

    severity_weight = {"error": 30, "warning": 12, "info": 4}
    score = 100 - sum(severity_weight.get(issue.get("severity"), 5) for issue in issues)
    score = max(0, min(100, score))
    if score >= 90:
        status = "strong"
    elif score >= 70:
        status = "usable"
    else:
        status = "needs_design_work"
    return {
        "apiVersion": API_VERSION,
        "kind": "BotMenuDesignCritique",
        "generated_at": now_iso(),
        "project_path": menu_map.get("project_path"),
        "read_only": True,
        "source_kind": menu_map.get("kind"),
        "summary": {
            "status": status,
            "score": score,
            "roles": len(roles),
            "commands": len(commands),
            "menus": len(menus),
            "callback_namespaces": len(callbacks),
            "issues": len(issues),
            "errors": sum(1 for issue in issues if issue.get("severity") == "error"),
            "warnings": sum(1 for issue in issues if issue.get("severity") == "warning"),
            "rulepack_missing": rulepack_evaluation.get("summary", {}).get("missing", 0),
            "rulepack_weak": rulepack_evaluation.get("summary", {}).get("weak", 0),
        },
        "rulepack_evaluation": rulepack_evaluation,
        "issues": issues,
        "recommended_next_steps": [
            "Подтвердить allowed_roles_hint против access-control кода, а не только по именам.",
            "Для опасных callbacks описать confirmation, idempotency и permission guard.",
            "Проверить back/cancel/help paths для каждой важной роли.",
            "После правок заново выполнить botctl design extract-menu и critique.",
        ],
    }


def _safe_id(prefix: str, value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_") or fallback
    return f"{prefix}.{slug}"


def _button_action(callback_data: str) -> str:
    if ":" not in callback_data:
        return callback_data
    return callback_data.split(":", 1)[1].split(":", 1)[0]


def _confirmation_required(namespace: str) -> bool:
    return namespace in DANGEROUS_CALLBACK_NAMESPACES or namespace.startswith(tuple(DANGEROUS_CALLBACK_NAMESPACES))


def json_like_validation_error(validation: dict[str, Any]) -> str:
    return json.dumps({"summary": validation.get("summary"), "issues": validation.get("issues", [])}, ensure_ascii=False)


def _brief_items(brief: dict[str, Any], key: str) -> list[Any]:
    value = brief.get(key, [])
    return value if isinstance(value, list) else []


def _brief_id(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        raw = str(value.get("id") or value.get("name") or value.get("title") or fallback)
    else:
        raw = str(value or fallback)
    return re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_") or fallback


def _brief_title(value: Any, fallback: str) -> str:
    if isinstance(value, dict):
        return str(value.get("title") or value.get("name") or value.get("id") or fallback)
    return str(value or fallback)


def _role_title(role_id: str) -> str:
    return {
        "guest": "Гость",
        "user": "Обычный пользователь",
        "allowed_user": "Разрешённый пользователь",
        "creator": "Креатор",
        "lead": "Lead-креатор",
        "admin": "Администратор",
        "owner": "Владелец",
    }.get(role_id, role_id.replace("_", " ").title())


RESERVED_ROLE_IDS = {"system", "bot", "runtime", "secret", "token", "env"}
RESERVED_FLOW_IDS = {"nav", "admin"}
ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
FLOW_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
COMMAND_RE_STRICT = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def validate_design_brief(brief: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(brief.get("name") or brief.get("title"), str) or not str(brief.get("name") or brief.get("title")).strip():
        issues.append(_issue("brief.name_missing", "error", "Brief должен иметь name или title", "Без имени невозможно построить project_path/title для proposal.", [], "Добавить name: my-bot"))
    raw_roles = _brief_items(brief, "roles")
    if not raw_roles:
        issues.append(_issue("brief.roles_missing", "error", "Brief должен иметь roles", "Сложный Telegram UX требует явной модели ролей.", [], "Добавить roles: user/admin/creator/etc."))
    role_ids: list[str] = []
    for index, raw_role in enumerate(raw_roles):
        role_id = _brief_id(raw_role, f"role_{index + 1}")
        if not ROLE_ID_RE.match(role_id):
            issues.append(_issue("brief.role_id_invalid", "error", "Некорректный role id", "role id должен быть snake_case, начинаться с буквы и быть <=64 символов.", [{"role": raw_role, "normalized": role_id}], "Исправить role id, например creator/admin/owner."))
        if role_id in RESERVED_ROLE_IDS:
            issues.append(_issue("brief.role_id_reserved", "error", "Role id зарезервирован", "Некоторые role ids нельзя использовать, чтобы не смешивать пользователей с runtime/secrets.", [role_id], "Переименовать роль."))
        if role_id in role_ids:
            issues.append(_issue("brief.role_duplicate", "error", "Дублируется role id", "Повтор ролей создаёт неоднозначные permissions и меню.", [role_id], "Оставить одну роль или переименовать."))
        role_ids.append(role_id)
    if "user" not in role_ids and "creator" not in role_ids and "allowed_user" not in role_ids:
        warnings.append(_issue("brief.user_role_implicit", "warning", "Нет базовой пользовательской роли", "Proposal добавит user по умолчанию, но лучше явно описать основную роль.", role_ids, "Добавить role user/creator/allowed_user."))

    raw_flows = _brief_items(brief, "flows")
    if not raw_flows and not _brief_items(brief, "features"):
        issues.append(_issue("brief.flows_missing", "error", "Brief должен иметь flows или features", "Без сценариев невозможно спроектировать меню и callback contract.", [], "Добавить flows с id/title/roles."))
    flow_ids: list[str] = []
    commands: list[str] = []
    for index, raw_flow in enumerate(raw_flows):
        flow_id = _brief_id(raw_flow, f"flow_{index + 1}")
        if not FLOW_ID_RE.match(flow_id):
            issues.append(_issue("brief.flow_id_invalid", "error", "Некорректный flow id", "flow id должен быть snake_case, начинаться с буквы и быть <=64 символов.", [{"flow": raw_flow, "normalized": flow_id}], "Исправить flow id, например task_board."))
        if flow_id in RESERVED_FLOW_IDS:
            issues.append(_issue("brief.flow_id_reserved", "error", "Flow id зарезервирован", "nav/admin используются как системные namespaces; flow с таким id создаёт конфликт callback contract.", [flow_id], "Переименовать flow, например admin_panel или navigation_settings."))
        if flow_id in flow_ids:
            issues.append(_issue("brief.flow_duplicate", "error", "Дублируется flow id", "Два flow с одним id создают одинаковые callback namespaces/actions.", [flow_id], "Переименовать один из flows."))
        flow_ids.append(flow_id)
        if isinstance(raw_flow, dict):
            title = raw_flow.get("title") or raw_flow.get("name")
            if not isinstance(title, str) or not title.strip():
                warnings.append(_issue("brief.flow_title_missing", "warning", "У flow нет человеко-понятного title", "Без title меню будет хуже для пользователя.", [flow_id], "Добавить title на русском языке."))
            flow_roles = raw_flow.get("roles", [])
            if flow_roles is None:
                flow_roles = []
            if not isinstance(flow_roles, list) or not flow_roles:
                warnings.append(_issue("brief.flow_roles_missing", "warning", "У flow нет roles", "Flow будет виден всем ролям, что может быть опасно.", [flow_id], "Указать roles для flow."))
            else:
                for role in flow_roles:
                    if str(role) not in role_ids:
                        issues.append(_issue("brief.flow_role_unknown", "error", "Flow ссылается на неизвестную роль", "Flow visibility должен ссылаться только на roles из brief.", [{"flow": flow_id, "role": role}], "Добавить роль в roles или исправить flow.roles."))
            command = raw_flow.get("command")
            if command:
                command_name = str(command).lstrip("/")
                if not COMMAND_RE_STRICT.match(command_name):
                    issues.append(_issue("brief.command_invalid", "error", "Некорректная slash command", "Telegram command должна быть lowercase-like ASCII id <=32 символов.", [{"flow": flow_id, "command": command}], "Исправить command, например tasks."))
                if command_name in {"start", "help", "status", "admin"}:
                    issues.append(_issue("brief.command_reserved", "error", "Command конфликтует с default command", "from-brief автоматически добавляет /start, /help, /status и иногда /admin.", [{"flow": flow_id, "command": command_name}], "Выбрать другое имя команды."))
                if command_name in commands:
                    issues.append(_issue("brief.command_duplicate", "error", "Дублируется command", "Одна command не должна вести в разные flows без явного router design.", [command_name], "Переименовать одну из commands."))
                commands.append(command_name)
    result = {
        "apiVersion": API_VERSION,
        "kind": "BotDesignBriefValidation",
        "generated_at": now_iso(),
        "valid": not issues,
        "summary": {"errors": len(issues), "warnings": len(warnings), "roles": len(set(role_ids)), "flows": len(set(flow_ids)), "commands": len(set(commands))},
        "issues": issues,
        "warnings": warnings,
    }
    return result


def design_from_brief(brief: dict[str, Any], *, allow_invalid: bool = False) -> dict[str, Any]:
    validation = validate_design_brief(brief)
    if not validation.get("valid") and not allow_invalid:
        raise ValueError(json_like_validation_error(validation))
    project_name = str(brief.get("name") or brief.get("title") or "new-telegram-bot")
    project_slug = _brief_id(project_name, "telegram_bot")
    raw_roles = _brief_items(brief, "roles") or ["user", "admin"]
    roles: list[dict[str, Any]] = []
    role_ids: list[str] = []
    for raw_role in raw_roles:
        role_id = _brief_id(raw_role, "user")
        if role_id not in role_ids:
            role_ids.append(role_id)
            roles.append(
                {
                    "id": role_id,
                    "title": _brief_title(raw_role, _role_title(role_id)),
                    "description": str(raw_role.get("description", "") if isinstance(raw_role, dict) else f"Роль {role_id} из brief."),
                    "source": "brief",
                    "requires_manual_confirmation": role_id in {"admin", "owner", "creator", "lead"},
                }
            )
    if "user" not in role_ids:
        role_ids.insert(0, "user")
        roles.insert(0, {"id": "user", "title": "Обычный пользователь", "description": "Базовая пользовательская роль.", "source": "default", "requires_manual_confirmation": False})

    raw_features = _brief_items(brief, "features")
    raw_flows = _brief_items(brief, "flows") or raw_features or [{"id": "main", "title": "Основной сценарий"}]
    command_contract: list[dict[str, Any]] = [
        {"command": "/start", "visible_for": ["guest", "user"] if "guest" in role_ids else ["user"], "description": "Первый вход, onboarding и выбор основного действия.", "handler_hint": "handle_start", "source": {"type": "design_from_brief"}},
        {"command": "/help", "visible_for": role_ids, "description": "Справка по ролям, действиям и ограничениям.", "handler_hint": "handle_help", "source": {"type": "design_from_brief"}},
        {"command": "/status", "visible_for": [role for role in role_ids if role not in {"guest"}] or ["user"], "description": "Проверить текущие задачи, состояние очереди или профиль.", "handler_hint": "handle_status", "source": {"type": "design_from_brief"}},
    ]
    if "admin" in role_ids or "owner" in role_ids:
        command_contract.append({"command": "/admin", "visible_for": [role for role in ["admin", "owner"] if role in role_ids], "description": "Админское меню и операционные действия.", "handler_hint": "handle_admin", "source": {"type": "design_from_brief"}})

    menus: list[dict[str, Any]] = []
    callback_contract: dict[str, dict[str, Any]] = {}

    def add_callback(namespace: str, pattern: str, roles_for_action: list[str], handler_hint: str) -> None:
        item = callback_contract.setdefault(
            namespace,
            {
                "namespace": namespace,
                "actions_hint": [],
                "patterns": [],
                "allowed_roles": [],
                "handler_hints": [],
                "requires_permission_guard": namespace in DANGEROUS_CALLBACK_NAMESPACES or namespace in {"admin", "owner"},
                "requires_confirmation": _confirmation_required(namespace),
                "idempotency_required": _confirmation_required(namespace) or namespace in {"retry", "job", "queue"},
                "risk_notes": [],
            },
        )
        action = _button_action(pattern)
        if action not in item["actions_hint"]:
            item["actions_hint"].append(action)
        if pattern not in item["patterns"]:
            item["patterns"].append(pattern)
        item["allowed_roles"] = sorted(set(item["allowed_roles"]) | set(roles_for_action))
        if handler_hint not in item["handler_hints"]:
            item["handler_hints"].append(handler_hint)
        if item["requires_confirmation"] and not item["risk_notes"]:
            item["risk_notes"].append("Опасное действие требует confirmation, permission guard и idempotency.")

    main_buttons = []
    for index, raw_flow in enumerate(raw_flows, start=1):
        flow_id = _brief_id(raw_flow, f"flow_{index}")
        flow_title = _brief_title(raw_flow, flow_id.replace("_", " ").title())
        visible_for = list(raw_flow.get("roles", role_ids) if isinstance(raw_flow, dict) else role_ids)
        if not visible_for:
            visible_for = ["user"]
        namespace = flow_id.split("_", 1)[0] if flow_id else "flow"
        pattern = f"{namespace}:open:{flow_id}"
        handler_hint = f"handle_{flow_id}"
        add_callback(namespace, pattern, visible_for, handler_hint)
        main_buttons.append(
            {
                "text": flow_title,
                "action_id": _safe_id("action", pattern),
                "callback_namespace": namespace,
                "callback_data_pattern": pattern,
                "visible_for": visible_for,
                "requires_confirmation": False,
                "idempotency_required": False,
                "source": {"type": "brief", "flow": flow_id},
            }
        )
        command_name = raw_flow.get("command") if isinstance(raw_flow, dict) else None
        if command_name:
            command_contract.append({"command": str(command_name if str(command_name).startswith('/') else '/' + str(command_name)), "visible_for": visible_for, "description": flow_title, "handler_hint": handler_hint, "source": {"type": "brief", "flow": flow_id}})

    main_buttons.extend([
        {"text": "⬅️ Назад", "action_id": "action.nav_back", "callback_namespace": "nav", "callback_data_pattern": "nav:back", "visible_for": role_ids, "requires_confirmation": False, "idempotency_required": True, "source": {"type": "default_navigation"}},
        {"text": "❌ Отмена", "action_id": "action.nav_cancel", "callback_namespace": "nav", "callback_data_pattern": "nav:cancel", "visible_for": role_ids, "requires_confirmation": True, "idempotency_required": True, "source": {"type": "default_navigation"}},
        {"text": "❓ Помощь", "action_id": "action.nav_help", "callback_namespace": "nav", "callback_data_pattern": "nav:help", "visible_for": role_ids, "requires_confirmation": False, "idempotency_required": True, "source": {"type": "default_navigation"}},
    ])
    for pattern in ["nav:back", "nav:cancel", "nav:help"]:
        add_callback("nav", pattern, role_ids, "handle_navigation")
    menus.append(
        {
            "id": "menu.main",
            "title": "Главное меню",
            "visible_for": role_ids,
            "buttons": main_buttons,
            "navigation_requirements": {"back": True, "cancel": True, "help_or_main": True},
        }
    )

    if "admin" in role_ids or "owner" in role_ids:
        admin_roles = [role for role in ["admin", "owner"] if role in role_ids]
        admin_buttons = [
            {"text": "📊 Статус", "action_id": "action.admin_status", "callback_namespace": "admin", "callback_data_pattern": "admin:status", "visible_for": admin_roles, "requires_confirmation": False, "idempotency_required": True, "source": {"type": "default_admin"}},
            {"text": "📣 Рассылка", "action_id": "action.admin_broadcast", "callback_namespace": "admin", "callback_data_pattern": "admin:broadcast", "visible_for": admin_roles, "requires_confirmation": True, "idempotency_required": True, "source": {"type": "default_admin"}},
            {"text": "🧹 Очистка", "action_id": "action.admin_cleanup", "callback_namespace": "admin", "callback_data_pattern": "admin:cleanup", "visible_for": admin_roles, "requires_confirmation": True, "idempotency_required": True, "source": {"type": "default_admin"}},
            {"text": "⬅️ Назад", "action_id": "action.nav_back", "callback_namespace": "nav", "callback_data_pattern": "nav:back", "visible_for": admin_roles, "requires_confirmation": False, "idempotency_required": True, "source": {"type": "default_navigation"}},
        ]
        for pattern in ["admin:status", "admin:broadcast", "admin:cleanup"]:
            add_callback("admin", pattern, admin_roles, "handle_admin")
        menus.append({"id": "menu.admin", "title": "Админское меню", "visible_for": admin_roles, "buttons": admin_buttons, "navigation_requirements": {"back": True, "cancel": True, "help_or_main": True}})

    brief_debt = []
    if not raw_features and not raw_flows:
        brief_debt.append({"id": "brief.features_missing", "severity": "warning", "title": "В brief нет features/flows", "recommendation": "Добавить список сценариев, которые должны стать пунктами меню."})
    if not any(command.get("command") == "/help" for command in command_contract):
        brief_debt.append({"id": "commands.help_missing", "severity": "warning", "title": "Нет /help", "recommendation": "Добавить /help для всех ролей."})

    return {
        "apiVersion": API_VERSION,
        "kind": "BotMenuDesignProposal",
        "generated_at": now_iso(),
        "project_path": str(brief.get("project_path") or project_name),
        "read_only": True,
        "source_kind": "BotDesignBrief",
        "critique_summary": {"status": "brief_proposal", "score": 100 - 12 * len(brief_debt), "issues": len(brief_debt), "warnings": sum(1 for item in brief_debt if item.get("severity") == "warning")},
        "brief_validation": validation,
        "draft_notice": "Read-only design-from-brief proposal. Это не implementation и не runtime apply.",
        "roles": roles,
        "command_contract": command_contract,
        "menus": menus,
        "callback_contract": sorted(callback_contract.values(), key=lambda item: item["namespace"]),
        "global_navigation_requirements": {
            "missing_from_extracted_design": [],
            "required_for_complex_bots": ["back", "cancel", "help_or_main", "permission_denied", "empty_state", "retry_after_error"],
        },
        "quality_gates": [
            {"id": "callbacks_have_namespace", "status": "covered", "why": "Все generated callbacks имеют namespace."},
            {"id": "roles_are_explicit", "status": "covered", "why": "Roles заданы из brief/defaults."},
            {"id": "menus_have_buttons", "status": "covered", "why": "Main menu и role menus имеют buttons."},
            {"id": "commands_are_visible", "status": "covered", "why": "/start, /help и /status заданы по умолчанию."},
        ],
        "design_debt": brief_debt,
        "implementation_policy": {
            "mode": "proposal_only",
            "must_confirm_roles_against_access_control": True,
            "must_add_tests_before_runtime_apply": True,
            "forbidden_without_change_plan": ["create handlers", "edit handlers", "change callback_data", "restart service", "read .env", "touch runtime DB"],
        },
    }


def normalize_menu_design(menu_map: dict[str, Any], critique: dict[str, Any] | None = None) -> dict[str, Any]:
    if critique is None:
        critique = critique_menu_map(menu_map)
    roles_by_id = {str(role.get("id")): role for role in menu_map.get("roles", []) if isinstance(role, dict) and role.get("id")}
    commands = [item for item in menu_map.get("commands", []) if isinstance(item, dict)]
    menus = [item for item in menu_map.get("menus", []) if isinstance(item, dict)]
    callbacks = [item for item in menu_map.get("callback_contract", []) if isinstance(item, dict)]
    critique_issues = [item for item in critique.get("issues", []) if isinstance(item, dict)]

    role_order = ["guest", "user", "allowed_user", "creator", "lead", "admin", "owner"]
    roles: list[dict[str, Any]] = []
    for role_id in role_order:
        source = roles_by_id.get(role_id)
        if source is None:
            continue
        roles.append(
            {
                "id": role_id,
                "title": source.get("title") or role_id,
                "description": "Нормализованная роль из фактических команд, callbacks и контекстов кода.",
                "source": source.get("source"),
                "requires_manual_confirmation": role_id in {"admin", "owner", "creator", "lead"},
            }
        )

    command_contract: list[dict[str, Any]] = []
    seen_commands: set[tuple[str, str]] = set()
    for command in commands:
        name = str(command.get("command") or "").lstrip("/")
        if not name:
            continue
        role = str(command.get("role_hint") or "user")
        key = (name, role)
        if key in seen_commands:
            continue
        seen_commands.add(key)
        command_contract.append(
            {
                "command": f"/{name}",
                "visible_for": [role],
                "description": command.get("description") or "Найдено в коде, требует уточнения человеко-понятного описания.",
                "handler_hint": command.get("source", {}).get("context"),
                "source": command.get("source"),
            }
        )

    normalized_menus: list[dict[str, Any]] = []
    for menu in menus:
        buttons = [button for button in menu.get("buttons", []) if isinstance(button, dict)]
        normalized_buttons = []
        for button in buttons:
            callback_data = str(button.get("callback_data") or "")
            namespace = str(button.get("namespace") or _callback_namespace(callback_data))
            normalized_buttons.append(
                {
                    "text": button.get("text") or "<без текста>",
                    "action_id": _safe_id("action", callback_data or str(button.get("text") or "button")),
                    "callback_namespace": namespace,
                    "callback_data_pattern": callback_data,
                    "visible_for": button.get("allowed_roles_hint", []),
                    "requires_confirmation": _confirmation_required(namespace),
                    "idempotency_required": _confirmation_required(namespace) or namespace in {"retry", "job", "queue"},
                    "source": button.get("source"),
                }
            )
        normalized_menus.append(
            {
                "id": menu.get("id"),
                "title": menu.get("title"),
                "visible_for": sorted(set(menu.get("visible_for_hint", []) or [])),
                "buttons": normalized_buttons,
                "navigation_requirements": {
                    "back": any("back" in str(button.get("callback_data", "")).lower() for button in buttons),
                    "cancel": any("cancel" in str(button.get("callback_data", "")).lower() for button in buttons),
                    "help_or_main": any(any(token in str(button.get("callback_data", "")).lower() for token in ("help", "main", "menu", "home")) for button in buttons),
                },
            }
        )

    callback_contract: list[dict[str, Any]] = []
    for item in callbacks:
        namespace = str(item.get("namespace") or "")
        if not namespace:
            continue
        patterns = [str(pattern) for pattern in item.get("patterns", []) if pattern]
        callback_contract.append(
            {
                "namespace": namespace,
                "actions_hint": sorted({_button_action(pattern) for pattern in patterns if pattern}),
                "patterns": patterns,
                "allowed_roles": item.get("allowed_roles_hint", []),
                "handler_hints": item.get("handlers_hint", []),
                "requires_permission_guard": bool(set(item.get("allowed_roles_hint", [])) & {"admin", "owner", "creator", "lead"}) or _confirmation_required(namespace),
                "requires_confirmation": _confirmation_required(namespace),
                "idempotency_required": _confirmation_required(namespace) or namespace in {"retry", "job", "queue"},
                "risk_notes": item.get("risk_notes", []),
            }
        )

    missing_navigation = []
    issue_ids = {str(issue.get("id")) for issue in critique_issues}
    if "navigation.back_missing" in issue_ids:
        missing_navigation.append("back")
    if "navigation.cancel_missing" in issue_ids:
        missing_navigation.append("cancel")
    if "commands.help_missing" in issue_ids:
        missing_navigation.append("help")

    design_debt = [
        {
            "id": issue.get("id"),
            "severity": issue.get("severity"),
            "title": issue.get("title"),
            "recommendation": issue.get("recommendation"),
        }
        for issue in critique_issues
    ]

    return {
        "apiVersion": API_VERSION,
        "kind": "BotMenuDesignProposal",
        "generated_at": now_iso(),
        "project_path": menu_map.get("project_path"),
        "read_only": True,
        "source_kind": menu_map.get("kind"),
        "critique_summary": critique.get("summary", {}),
        "draft_notice": "Read-only normalized proposal. Не применять к runtime без отдельного ChangePlan, human review и тестов.",
        "roles": roles,
        "command_contract": sorted(command_contract, key=lambda item: (item.get("visible_for", [""])[0], item.get("command", ""))),
        "menus": sorted(normalized_menus, key=lambda item: str(item.get("id"))),
        "callback_contract": sorted(callback_contract, key=lambda item: str(item.get("namespace"))),
        "global_navigation_requirements": {
            "missing_from_extracted_design": missing_navigation,
            "required_for_complex_bots": ["back", "cancel", "help_or_main", "permission_denied", "empty_state", "retry_after_error"],
        },
        "quality_gates": menu_map.get("quality_gates", []),
        "design_debt": design_debt,
        "implementation_policy": {
            "mode": "proposal_only",
            "must_confirm_roles_against_access_control": True,
            "must_add_tests_before_runtime_apply": True,
            "forbidden_without_change_plan": ["edit handlers", "change callback_data", "restart service", "read .env", "touch runtime DB"],
        },
    }


def _proposal_command_set(proposal: dict[str, Any]) -> set[str]:
    return {str(item.get("command", "")).lstrip("/") for item in proposal.get("command_contract", []) if isinstance(item, dict) and item.get("command")}


def _map_command_set(menu_map: dict[str, Any]) -> set[str]:
    return {str(item.get("command", "")).lstrip("/") for item in menu_map.get("commands", []) if isinstance(item, dict) and item.get("command")}


def _proposal_callback_set(proposal: dict[str, Any]) -> set[str]:
    patterns: set[str] = set()
    for item in proposal.get("callback_contract", []) or []:
        if isinstance(item, dict):
            patterns.update(str(pattern) for pattern in item.get("patterns", []) if pattern)
    return patterns


def _map_callback_set(menu_map: dict[str, Any]) -> set[str]:
    patterns: set[str] = set()
    for item in menu_map.get("callback_contract", []) or []:
        if isinstance(item, dict):
            patterns.update(str(pattern) for pattern in item.get("patterns", []) if pattern)
    return patterns


def _proposal_namespace_set(proposal: dict[str, Any]) -> set[str]:
    return {str(item.get("namespace")) for item in proposal.get("callback_contract", []) if isinstance(item, dict) and item.get("namespace")}


def _map_namespace_set(menu_map: dict[str, Any]) -> set[str]:
    return {str(item.get("namespace")) for item in menu_map.get("callback_contract", []) if isinstance(item, dict) and item.get("namespace")}


def _proposal_role_set(proposal: dict[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in proposal.get("roles", []) if isinstance(item, dict) and item.get("id")}


def _map_role_set(menu_map: dict[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in menu_map.get("roles", []) if isinstance(item, dict) and item.get("id")}


def compare_menu_design(proposal: dict[str, Any], menu_map: dict[str, Any]) -> dict[str, Any]:
    desired_roles = _proposal_role_set(proposal)
    actual_roles = _map_role_set(menu_map)
    desired_commands = _proposal_command_set(proposal)
    actual_commands = _map_command_set(menu_map)
    desired_callbacks = _proposal_callback_set(proposal)
    actual_callbacks = _map_callback_set(menu_map)
    desired_namespaces = _proposal_namespace_set(proposal)
    actual_namespaces = _map_namespace_set(menu_map)

    desired_nav = set(proposal.get("global_navigation_requirements", {}).get("required_for_complex_bots", []) or [])
    actual_nav = {hint for hint in NAVIGATION_HINTS if any(hint in pattern.lower() for pattern in actual_callbacks)}
    desired_dangerous = {
        str(item.get("namespace"))
        for item in proposal.get("callback_contract", [])
        if isinstance(item, dict) and (item.get("requires_permission_guard") or item.get("requires_confirmation") or item.get("idempotency_required")) and item.get("namespace")
    }
    actual_guard_details: dict[str, Any] = {}
    actual_dangerous: set[str] = set()
    for item in menu_map.get("callback_contract", []):
        if not isinstance(item, dict) or not item.get("namespace"):
            continue
        namespace = str(item.get("namespace"))
        status = _guard_status(item.get("guard_evidence") if isinstance(item.get("guard_evidence"), dict) else {})
        actual_guard_details[namespace] = {
            "status": status,
            "evidence_counts": {kind: len(value) for kind, value in (item.get("guard_evidence") or {}).items()} if isinstance(item.get("guard_evidence"), dict) else {},
        }
        if namespace in DANGEROUS_CALLBACK_NAMESPACES or item.get("risk_notes"):
            if status.get("supported"):
                actual_dangerous.add(namespace)

    sections = {
        "roles": {
            "desired": sorted(desired_roles),
            "actual": sorted(actual_roles),
            "missing": sorted(desired_roles - actual_roles),
            "extra": sorted(actual_roles - desired_roles),
        },
        "commands": {
            "desired": sorted(desired_commands),
            "actual": sorted(actual_commands),
            "missing": sorted(desired_commands - actual_commands),
            "extra": sorted(actual_commands - desired_commands),
        },
        "callback_namespaces": {
            "desired": sorted(desired_namespaces),
            "actual": sorted(actual_namespaces),
            "missing": sorted(desired_namespaces - actual_namespaces),
            "extra": sorted(actual_namespaces - desired_namespaces),
        },
        "callback_patterns": {
            "desired_count": len(desired_callbacks),
            "actual_count": len(actual_callbacks),
            "missing": sorted(desired_callbacks - actual_callbacks),
            "extra": sorted(actual_callbacks - desired_callbacks),
        },
        "navigation": {
            "desired": sorted(desired_nav),
            "actual": sorted(actual_nav),
            "missing": sorted({item.split('_', 1)[0] if item.endswith('_or_main') else item for item in desired_nav if item in {"back", "cancel", "help_or_main", "help"}} - actual_nav),
        },
        "dangerous_guards": {
            "desired": sorted(desired_dangerous),
            "actual": sorted(actual_dangerous),
            "missing": sorted(desired_dangerous - actual_dangerous),
            "evidence": actual_guard_details,
        },
    }
    issues: list[dict[str, Any]] = []
    if sections["roles"]["missing"]:
        issues.append(_issue("compare.roles_missing", "warning", "В реализации не видны роли из proposal", "Role model из proposal не полностью проявился в extracted map.", sections["roles"]["missing"], "Проверить access-control и role-specific menus."))
    if sections["commands"]["missing"]:
        issues.append(_issue("compare.commands_missing", "error", "В реализации не видны команды из proposal", "Пользователь не сможет открыть часть запланированных flows через команды.", sections["commands"]["missing"], "Добавить команды или изменить proposal."))
    if sections["callback_namespaces"]["missing"]:
        issues.append(_issue("compare.callback_namespaces_missing", "warning", "В реализации не видны callback namespaces из proposal", "Часть меню/actions не реализована или extractor не видит callback_data.", sections["callback_namespaces"]["missing"], "Добавить inline buttons/callback handlers или уточнить proposal."))
    if sections["navigation"]["missing"]:
        issues.append(_issue("compare.navigation_missing", "warning", "В реализации не видны обязательные navigation actions", "Пользователь может застрять без back/cancel/help.", sections["navigation"]["missing"], "Добавить nav callbacks или описать альтернативный путь."))
    if sections["dangerous_guards"]["missing"]:
        issues.append(_issue("compare.dangerous_guards_missing", "warning", "Опасные namespaces из proposal не подтверждены implementation map", "Publish/admin/cleanup/cancel actions требуют guards/confirmation/idempotency.", sections["dangerous_guards"]["missing"], "Подтвердить guards тестами или обновить callback_contract."))

    severity_weight = {"error": 25, "warning": 10, "info": 3}
    score = max(0, min(100, 100 - sum(severity_weight.get(issue.get("severity"), 5) for issue in issues)))
    if not issues:
        status = "aligned"
    elif score >= 70:
        status = "partial"
    else:
        status = "diverged"
    return {
        "apiVersion": API_VERSION,
        "kind": "BotMenuDesignDiff",
        "generated_at": now_iso(),
        "project_path": menu_map.get("project_path") or proposal.get("project_path"),
        "read_only": True,
        "source_kinds": {"proposal": proposal.get("kind"), "actual": menu_map.get("kind")},
        "summary": {
            "status": status,
            "score": score,
            "issues": len(issues),
            "errors": sum(1 for issue in issues if issue.get("severity") == "error"),
            "warnings": sum(1 for issue in issues if issue.get("severity") == "warning"),
            "missing_commands": len(sections["commands"]["missing"]),
            "missing_callback_namespaces": len(sections["callback_namespaces"]["missing"]),
            "missing_roles": len(sections["roles"]["missing"]),
        },
        "sections": sections,
        "issues": issues,
        "recommended_next_steps": [
            "Если diff строится после реализации — закрыть missing commands/callbacks и заново выполнить extract-menu + compare.",
            "Если diff строится против legacy бота — решить, что менять: implementation или proposal.",
            "Dangerous callbacks подтверждать тестами permission/confirmation/idempotency.",
        ],
    }


def implementation_plan_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    roles = [item for item in proposal.get("roles", []) if isinstance(item, dict)]
    commands = [item for item in proposal.get("command_contract", []) if isinstance(item, dict)]
    menus = [item for item in proposal.get("menus", []) if isinstance(item, dict)]
    callbacks = [item for item in proposal.get("callback_contract", []) if isinstance(item, dict)]
    design_debt = [item for item in proposal.get("design_debt", []) if isinstance(item, dict)]
    command_handlers = sorted({str(command.get("handler_hint")) for command in commands if command.get("handler_hint")})
    callback_handlers = sorted({str(handler) for contract in callbacks for handler in contract.get("handler_hints", []) if handler})
    handler_names = sorted(set(command_handlers) | set(callback_handlers) | {"handle_fallback", "handle_permission_denied", "handle_error"})
    dangerous_callbacks = [
        {
            "namespace": item.get("namespace"),
            "patterns": item.get("patterns", []),
            "requires_confirmation": item.get("requires_confirmation"),
            "idempotency_required": item.get("idempotency_required"),
        }
        for item in callbacks
        if item.get("requires_permission_guard") or item.get("requires_confirmation") or item.get("idempotency_required")
    ]
    role_ids = [str(role.get("id")) for role in roles if role.get("id")]
    menu_ids = [str(menu.get("id")) for menu in menus if menu.get("id")]
    callback_namespaces = [str(item.get("namespace")) for item in callbacks if item.get("namespace")]
    suggested_files = [
        {"path": "app/handlers.py", "purpose": "Команды, callbacks, fallback, permission denied и error UX handlers."},
        {"path": "app/keyboards.py", "purpose": "Inline keyboard builders из normalized menus."},
        {"path": "app/roles.py", "purpose": "Role model, permission guards и visible_for checks."},
        {"path": "app/callbacks.py", "purpose": "Callback namespaces, parsing, validation and idempotency helpers."},
        {"path": "tests/test_menu_contract.py", "purpose": "Contract tests для commands, callbacks, roles, navigation и dangerous actions."},
    ]
    if any(role in {"admin", "owner", "creator", "lead"} for role in role_ids):
        suggested_files.append({"path": "app/state.py", "purpose": "Persistent state/session storage для сложных flows и role-specific state."})
    phases = [
        {
            "id": "phase.1_contract",
            "title": "Зафиксировать UX contract без runtime apply",
            "steps": [
                "Сохранить proposal как review artifact вне target .botctl или в docs/design/ после human review.",
                "Подтвердить роли против access-control требований.",
                "Уточнить тексты команд, меню и empty/error states на русском языке.",
            ],
            "verification": ["Проверить, что proposal.kind == BotMenuDesignProposal", "Проверить implementation_policy.mode == proposal_only"],
        },
        {
            "id": "phase.2_scaffold",
            "title": "Спроектировать файлы и handler skeleton",
            "steps": [
                "Создать/обновить role model без секретов и runtime state.",
                "Создать keyboard builders для каждого menu.id.",
                "Создать callback parser/validator для каждого namespace.",
                "Создать command/callback handler skeleton для handler hints.",
            ],
            "verification": ["python -m py_compile app/*.py", "tests/test_menu_contract.py должен проверять все command_contract/callback_contract entries"],
        },
        {
            "id": "phase.3_ux_quality",
            "title": "Закрыть UX quality gates",
            "steps": [
                "Для каждой роли проверить /start, /help, /status и главное меню.",
                "Для каждого dangerous callback добавить permission guard, confirmation и idempotency.",
                "Для каждого flow добавить empty_state, permission_denied, retry_after_error и fallback.",
                "Для долгих операций добавить progress/status или typing indicator.",
            ],
            "verification": ["Unit tests на permission denied", "Unit tests на repeated callback idempotency", "Smoke: unknown input fallback"],
        },
        {
            "id": "phase.4_project_passport",
            "title": "Связать implementation с botctl passport",
            "steps": [
                "Обновить .botctl/graph.desired.yaml или создать bootstrap passport только после review.",
                "Запустить botctl snapshot/verify.",
                "Сравнить design proposal с extracted menu map после реализации.",
            ],
            "verification": ["botctl verify", "botctl design extract-menu", "botctl design critique"],
        },
    ]
    test_matrix = [
        {"id": "test.commands_visible", "title": "Все команды зарегистрированы и имеют русское описание", "covers": [command.get("command") for command in commands]},
        {"id": "test.callbacks_registered", "title": "Все callback namespaces маршрутизируются", "covers": callback_namespaces},
        {"id": "test.roles_permissions", "title": "Каждая роль видит только разрешённые меню/actions", "covers": role_ids},
        {"id": "test.navigation", "title": "Back/cancel/help/main navigation не заводят пользователя в тупик", "covers": menu_ids},
        {"id": "test.dangerous_actions", "title": "Опасные действия требуют guard/confirmation/idempotency", "covers": [item.get("namespace") for item in dangerous_callbacks]},
        {"id": "test.errors_empty_states", "title": "Permission denied, empty states, retry-after-error и fallback понятны пользователю", "covers": ["permission_denied", "empty_state", "retry_after_error", "fallback"]},
    ]
    return {
        "apiVersion": API_VERSION,
        "kind": "BotMenuImplementationPlan",
        "generated_at": now_iso(),
        "project_path": proposal.get("project_path"),
        "read_only": True,
        "source_kind": proposal.get("kind"),
        "summary": {
            "mode": "plan_only",
            "roles": len(roles),
            "commands": len(commands),
            "menus": len(menus),
            "callback_namespaces": len(callbacks),
            "handler_hints": len(handler_names),
            "dangerous_callback_namespaces": len(dangerous_callbacks),
            "design_debt": len(design_debt),
        },
        "suggested_files": suggested_files,
        "handler_skeleton": [
            {"name": name, "purpose": "Skeleton only; implement under ChangePlan with tests.", "source": "command_or_callback_hint"}
            for name in handler_names
        ],
        "phases": phases,
        "test_matrix": test_matrix,
        "dangerous_callbacks": dangerous_callbacks,
        "design_debt_to_resolve": design_debt,
        "rollback_strategy": [
            "До runtime apply rollback = удалить/отклонить generated proposal/plan artifact.",
            "После code implementation rollback должен быть patch-based через git или backup до изменения handlers/keyboards/callbacks.",
            "Нельзя перезапускать service или менять .env как часть этого plan-only artifact.",
        ],
        "blocked_actions": [
            "create runtime handlers without ChangePlan",
            "edit production service",
            "read or print .env/secrets",
            "touch runtime DB/session files",
            "restart bot service",
            "send Telegram messages as verification without explicit runtime approval",
        ],
        "next_agent_prompt": "Используй этот план как skeleton. Перед кодом подтверди роли, access-control и dangerous callbacks, затем сделай ChangePlan и тесты.",
    }


CONTROL_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = CONTROL_ROOT / "schemas"

DESIGN_ARTIFACT_FILES = {
    "manifest": "manifest.yaml",
    "product_model": "product.model.yaml",
    "role_model": "roles.model.yaml",
    "journey_map": "journeys.map.yaml",
    "menu_proposal": "menu.proposal.yaml",
    "response_system": "responses.system.yaml",
    "state_model": "state.model.yaml",
    "impact_graph": "impact.graph.yaml",
    "test_matrix": "test.matrix.yaml",
    "readme": "README.md",
}


def _artifact_meta(source: str, *, status: str = "draft") -> dict[str, Any]:
    return {
        "knowledge_status": status,
        "source": source,
        "requires_review": True,
        "production_design_allowed": False,
        "confirmed_by": None,
        "confirmed_at": None,
        "assumptions": [],
        "open_questions": [],
    }


def _placeholder(kind: str, source: str, open_questions: list[str]) -> dict[str, Any]:
    payload = {
        "apiVersion": API_VERSION,
        "kind": kind,
        "generated_at": now_iso(),
        **_artifact_meta(source),
        "open_questions": open_questions,
        "notes": [
            "Placeholder создан botctl design init-system.",
            "Нельзя считать production-grade до review/confirmation.",
        ],
    }
    return payload


def _roles_model_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    roles = proposal.get("roles", []) if isinstance(proposal.get("roles"), list) else []
    return {
        "apiVersion": API_VERSION,
        "kind": "BotRoleModel",
        "generated_at": now_iso(),
        **_artifact_meta("observed_code"),
        "roles": [
            {
                "id": role.get("id"),
                "title": role.get("title") or role.get("id"),
                "description": role.get("description") or "Observed/inferred role from code/menu evidence.",
                "requires_manual_confirmation": bool(role.get("requires_manual_confirmation")),
                "goals": [],
                "allowed_actions": [],
                "forbidden_actions": [],
                "visible_menus": [],
                "permission_boundaries": [],
                "open_questions": ["Подтвердить роль, права и видимые journeys/menus."],
            }
            for role in roles
            if isinstance(role, dict) and role.get("id")
        ],
    }


def _impact_graph_from_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(node_id: str, kind: str, title: str) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({"id": node_id, "kind": kind, "title": title})

    for role in proposal.get("roles", []) or []:
        if not isinstance(role, dict) or not role.get("id"):
            continue
        add_node(f"role.{role['id']}", "Role", str(role.get("title") or role["id"]))
    for menu in proposal.get("menus", []) or []:
        if not isinstance(menu, dict) or not menu.get("id"):
            continue
        menu_id = str(menu["id"])
        add_node(menu_id, "Menu", str(menu.get("title") or menu_id))
        for role in menu.get("visible_for", []) or []:
            add_node(f"role.{role}", "Role", str(role))
            edges.append({"source": f"role.{role}", "target": menu_id, "kind": "sees"})
        for button in menu.get("buttons", []) or []:
            if not isinstance(button, dict):
                continue
            action_id = str(button.get("action_id") or _safe_id("action", str(button.get("callback_data_pattern") or button.get("text") or "button")))
            add_node(action_id, "Button", str(button.get("text") or action_id))
            edges.append({"source": menu_id, "target": action_id, "kind": "contains"})
            cb = str(button.get("callback_data_pattern") or "")
            if cb:
                cb_id = _safe_id("callback", cb)
                add_node(cb_id, "Callback", cb)
                edges.append({"source": action_id, "target": cb_id, "kind": "triggers"})
                ns = str(button.get("callback_namespace") or _callback_namespace(cb))
                handler_id = f"handler.handle_{ns}"
                add_node(handler_id, "HandlerHint", handler_id)
                edges.append({"source": cb_id, "target": handler_id, "kind": "handled_by"})
    return {
        "apiVersion": API_VERSION,
        "kind": "BotImpactGraph",
        "generated_at": now_iso(),
        **_artifact_meta("observed_code_partial"),
        "graph_status": "partial_observed_draft",
        "nodes": nodes,
        "edges": edges,
        "open_questions": [
            "Связать journeys, responses, state и tests после подтверждения ProductModel/JourneyMap/ResponseSystem.",
            "Проверить handler hints против реального кода перед ChangePlan.",
        ],
    }


def _test_matrix_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiVersion": API_VERSION,
        "kind": "BotTestMatrix",
        "generated_at": now_iso(),
        **_artifact_meta("observed_code_partial"),
        "tests": plan.get("test_matrix", []) if isinstance(plan.get("test_matrix"), list) else [],
        "required_categories": [
            "role_visibility",
            "onboarding",
            "journey_happy_paths",
            "empty_states",
            "permission_denied",
            "human_readable_errors",
            "long_running_status",
            "back_cancel_help",
            "dangerous_confirmation",
            "idempotency",
            "state_persistence",
            "impact_graph_coverage",
        ],
        "open_questions": ["Подтвердить реальные тесты и связать их с ImpactGraph."],
    }


def _design_manifest(project: Path, artifacts: dict[str, dict[str, Any]], critique: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    artifact_statuses: dict[str, Any] = {}
    for key, filename in DESIGN_ARTIFACT_FILES.items():
        if key == "readme":
            continue
        artifact = artifacts.get(key, {})
        artifact_statuses[key] = {
            "path": f".botctl/design/{filename}",
            "kind": artifact.get("kind"),
            "knowledge_status": artifact.get("knowledge_status", "missing"),
            "requires_review": artifact.get("requires_review", True),
        }
    blockers = [
        key for key, value in artifact_statuses.items()
        if value.get("knowledge_status") != "confirmed"
    ]
    return {
        "apiVersion": API_VERSION,
        "kind": "BotDesignManifest",
        "generated_at": now_iso(),
        "project_path": str(project),
        "knowledge_status": "draft",
        "source": "init_system_observed_draft",
        "requires_review": True,
        "production_design_allowed": False,
        "confirmed_by": None,
        "confirmed_at": None,
        "artifacts": artifact_statuses,
        "blockers": blockers,
        "observed_summary": {
            "critique_status": critique.get("summary", {}).get("status"),
            "critique_score": critique.get("summary", {}).get("score"),
            "critique_issues": critique.get("summary", {}).get("issues"),
            "compare_status": diff.get("summary", {}).get("status"),
            "compare_score": diff.get("summary", {}).get("score"),
            "compare_issues": diff.get("summary", {}).get("issues"),
        },
        "open_questions": [
            "Подтвердить ProductModel: purpose, target users, primary jobs, non-goals, business rules, success metrics, risk constraints.",
            "Подтвердить JourneyMap как источник правды для меню.",
            "Создать ResponseSystem с response_id, status/error/empty/confirm/success templates.",
            "Подтвердить ImpactGraph перед любым ChangePlan.",
        ],
    }


def _design_readme(artifacts: dict[str, dict[str, Any]], critique: dict[str, Any], diff: dict[str, Any]) -> str:
    lines = [
        "# Botctl Design Control Layer",
        "",
        "Status: draft / requires review",
        "",
        "Этот каталог создан `botctl design init-system` как machine-control слой проекта.",
        "YAML-файлы — source of truth после review/confirmation. Этот README — human-readable обзор.",
        "",
        "## Что создано",
        "",
    ]
    for key, filename in DESIGN_ARTIFACT_FILES.items():
        if key == "readme":
            continue
        artifact = artifacts.get(key, {})
        lines.append(f"- `{filename}` — `{artifact.get('kind', 'unknown')}`, status=`{artifact.get('knowledge_status', 'missing')}`, source=`{artifact.get('source', 'unknown')}`")
    lines.extend([
        "",
        "## UX/design debts",
        "",
    ])
    issues = critique.get("issues", []) if isinstance(critique.get("issues"), list) else []
    if issues:
        for issue in issues[:20]:
            lines.append(f"- `{issue.get('severity')}` `{issue.get('id')}` — {issue.get('title')}")
    else:
        lines.append("- Явных UX issues в critique не найдено, но artifacts всё равно draft до review.")
    lines.extend([
        "",
        "## Compare summary",
        "",
        f"- status: `{diff.get('summary', {}).get('status')}`",
        f"- score: `{diff.get('summary', {}).get('score')}`",
        f"- issues: `{diff.get('summary', {}).get('issues')}`",
        "",
        "## Что требует review",
        "",
        "- ProductModel: продуктовая цель, аудитории, jobs-to-be-done, non-goals, business rules.",
        "- JourneyMap: role-specific paths как источник правды для меню.",
        "- ResponseSystem: тексты, статусы, ошибки, empty states, confirmations, success messages.",
        "- StateModel: persistence, locks, idempotency, retry/timeout behavior.",
        "- ImpactGraph/TestMatrix: связать role→journey→menu→callback→handler→state→response→test.",
        "",
        "## Запрещено без confirmation / ChangePlan",
        "",
        "- генерировать или менять production handlers;",
        "- менять callback_data/callback namespaces;",
        "- править `.env`, secrets, runtime DB/session files;",
        "- рестартить service/runtime;",
        "- считать observed legacy design confirmed;",
        "- применять изменения без approved ChangePlan.",
        "",
        "## Next steps",
        "",
        "1. Заполнить и подтвердить `product.model.yaml`.",
        "2. Подтвердить `roles.model.yaml`.",
        "3. Спроектировать и подтвердить `journeys.map.yaml`.",
        "4. Заполнить `responses.system.yaml`.",
        "5. Достроить `impact.graph.yaml` и `test.matrix.yaml`.",
        "6. Только после confirmed artifacts создавать ChangePlan.",
        "",
    ])
    return "\n".join(lines)


def build_design_init_artifacts(project: Path) -> dict[str, Any]:
    menu_map = extract_menu_map(project)
    critique = critique_menu_map(menu_map)
    proposal = normalize_menu_design(menu_map, critique)
    diff = compare_menu_design(proposal, menu_map)
    plan = implementation_plan_from_proposal(proposal)
    product = _placeholder(
        "BotProductModel",
        "placeholder",
        [
            "Какова главная цель бота?",
            "Кто целевые пользователи и какие jobs-to-be-done?",
            "Какие non-goals, business rules, success metrics и risk constraints?",
        ],
    )
    journeys = _placeholder(
        "BotJourneyMap",
        "placeholder",
        [
            "Какие role-specific journeys являются source of truth для меню?",
            "Где happy paths, empty states, errors, retry/timeout и exits?",
        ],
    )
    responses = _placeholder(
        "BotResponseSystem",
        "placeholder",
        [
            "Какие response_id нужны для start/help/status/error/empty/confirm/success?",
            "Какие tone, formatting, emoji и live-status правила?",
        ],
    )
    state = _placeholder(
        "BotStateModel",
        "placeholder",
        [
            "Какие состояния transient/persistent?",
            "Где нужны locks, idempotency, retry counters, sessions/storage?",
        ],
    )
    roles = _roles_model_from_proposal(proposal)
    impact = _impact_graph_from_proposal(proposal)
    test_matrix = _test_matrix_from_plan(plan)
    proposal = dict(proposal)
    proposal.update(_artifact_meta("observed_code"))
    artifacts = {
        "product_model": product,
        "role_model": roles,
        "journey_map": journeys,
        "menu_proposal": proposal,
        "response_system": responses,
        "state_model": state,
        "impact_graph": impact,
        "test_matrix": test_matrix,
    }
    manifest = _design_manifest(project, artifacts, critique, diff)
    artifacts["manifest"] = manifest
    return {"artifacts": artifacts, "critique": critique, "diff": diff, "plan": plan, "menu_map": menu_map, "readme": _design_readme(artifacts, critique, diff)}


def write_design_init_system(project: Path, target_dir: Path, *, preview: bool = False, force: bool = False) -> dict[str, Any]:
    design_dir = project_control(project) / "design"
    if not preview and design_dir.exists():
        raise FileExistsError(f"design layer already exists: {design_dir}")
    if preview:
        if target_dir.exists() and any(target_dir.iterdir()) and not force:
            raise FileExistsError(f"preview output already exists and is not empty: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_design_init_artifacts(project)
    artifacts: dict[str, dict[str, Any]] = bundle["artifacts"]
    written: list[str] = []
    for key, filename in DESIGN_ARTIFACT_FILES.items():
        path = target_dir / filename
        if key == "readme":
            path.write_text(bundle["readme"], encoding="utf-8")
        else:
            dump_yaml(path, artifacts[key])
        written.append(str(path))
    (target_dir / "changeplans").mkdir(exist_ok=True)
    written.append(str(target_dir / "changeplans"))
    return {
        "apiVersion": API_VERSION,
        "kind": "BotDesignInitResult",
        "generated_at": now_iso(),
        "project_path": str(project),
        "target_dir": str(target_dir),
        "preview": preview,
        "written": written,
        "production_design_allowed": False,
        "summary": {
            "artifacts": len([key for key in DESIGN_ARTIFACT_FILES if key != "readme"]),
            "knowledge_status": "draft",
            "requires_review": True,
            "critique_status": bundle["critique"].get("summary", {}).get("status"),
            "critique_score": bundle["critique"].get("summary", {}).get("score"),
            "diff_status": bundle["diff"].get("summary", {}).get("status"),
            "diff_score": bundle["diff"].get("summary", {}).get("score"),
        },
    }


DESIGN_ARTIFACT_SCHEMAS = {
    "manifest": "design-manifest.schema.json",
    "product_model": "product-model.schema.json",
    "role_model": "role-model.schema.json",
    "journey_map": "journey-map.schema.json",
    "menu_proposal": "menu-design-proposal.schema.json",
    "response_system": "response-system.schema.json",
    "state_model": "state-model.schema.json",
    "impact_graph": "impact-graph.schema.json",
    "test_matrix": "test-matrix.schema.json",
}


def design_status_readiness(project: Path, *, design_dir: Path | None = None) -> dict[str, Any]:
    design_dir = design_dir or (project_control(project) / "design")
    exists = design_dir.exists()
    artifacts: dict[str, Any] = {}
    blockers: list[dict[str, Any]] = []
    schema_results: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {}
    if not exists:
        return {
            "apiVersion": API_VERSION,
            "kind": "BotDesignReadiness",
            "generated_at": now_iso(),
            "project_path": str(project),
            "design_dir": str(design_dir),
            "design_exists": False,
            "production_design_allowed": False,
            "readiness_status": "missing_design_layer",
            "readiness_score": 0,
            "artifacts": {},
            "schema_validation": [],
            "blockers": [{"id": "design.missing", "severity": "error", "title": ".botctl/design/ не найден", "recommendation": "Запустить botctl design init-system."}],
            "next_steps": ["Запустить botctl design init-system для создания draft design-control layer."],
        }
    manifest_path = design_dir / DESIGN_ARTIFACT_FILES["manifest"]
    if manifest_path.exists():
        try:
            loaded = load_yaml(manifest_path)
            manifest = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            blockers.append({"id": "manifest.read_failed", "severity": "error", "title": "Не удалось прочитать manifest.yaml", "evidence": [str(exc)], "recommendation": "Починить YAML manifest."})
    else:
        blockers.append({"id": "manifest.missing", "severity": "error", "title": "manifest.yaml отсутствует", "recommendation": "Пересоздать preview/init или восстановить manifest."})

    for key, filename in DESIGN_ARTIFACT_FILES.items():
        if key == "readme":
            continue
        path = design_dir / filename
        entry = {
            "path": str(path),
            "exists": path.exists(),
            "kind": None,
            "knowledge_status": "missing",
            "requires_review": True,
            "production_design_allowed": False,
        }
        if not path.exists():
            blockers.append({"id": f"artifact.{key}.missing", "severity": "error", "title": f"{filename} отсутствует", "recommendation": "Восстановить artifact или заново создать init preview."})
            artifacts[key] = entry
            continue
        try:
            payload = load_yaml(path)
            if not isinstance(payload, dict):
                raise ValueError("artifact is not a YAML object")
            entry.update({
                "kind": payload.get("kind"),
                "knowledge_status": payload.get("knowledge_status", "missing"),
                "requires_review": payload.get("requires_review", True),
                "production_design_allowed": payload.get("production_design_allowed", False),
                "open_questions": len(payload.get("open_questions", []) or []) if isinstance(payload.get("open_questions", []), list) else 0,
            })
            if entry["knowledge_status"] == "confirmed" and entry["open_questions"]:
                blockers.append({"id": f"artifact.{key}.confirmed_with_open_questions", "severity": "error", "title": f"{filename} confirmed, но содержит open_questions", "evidence": [entry["open_questions"]], "recommendation": "Решить и удалить open_questions либо вернуть artifact в reviewed."})
            if entry["knowledge_status"] == "confirmed" and payload.get("assumptions_required_confirmation") is True:
                blockers.append({"id": f"artifact.{key}.confirmed_with_unresolved_assumptions", "severity": "error", "title": f"{filename} confirmed с неподтверждёнными assumptions", "recommendation": "Подтвердить assumptions и установить assumptions_required_confirmation=false."})
            schema_name = DESIGN_ARTIFACT_SCHEMAS.get(key)
            if schema_name:
                schema_path = SCHEMA_DIR / schema_name
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator(schema).validate(payload)
                schema_results.append({"artifact": key, "schema": schema_name, "valid": True})
            if key in DESIGN_CONFIRMABLE_ARTIFACTS and entry["knowledge_status"] == "confirmed":
                semantic = validate_design_artifact_semantics(project, key)
                if not semantic["valid"]:
                    blockers.append({"id": f"artifact.{key}.semantic_invalid", "severity": "error", "title": f"{filename} confirmed, но не проходит semantic validation", "evidence": [issue["code"] for issue in semantic["issues"]], "recommendation": "Вернуть artifact в reviewed и исправить содержание."})
        except Exception as exc:
            schema_results.append({"artifact": key, "schema": DESIGN_ARTIFACT_SCHEMAS.get(key), "valid": False, "error": str(exc)})
            blockers.append({"id": f"artifact.{key}.invalid", "severity": "error", "title": f"{filename} не проходит чтение/schema validation", "evidence": [str(exc)], "recommendation": "Починить artifact shape перед review/confirmation."})
        artifacts[key] = entry

    readme_exists = (design_dir / DESIGN_ARTIFACT_FILES["readme"]).exists()
    changeplans_exists = (design_dir / "changeplans").is_dir()
    if not readme_exists:
        blockers.append({"id": "readme.missing", "severity": "warning", "title": "README.md отсутствует", "recommendation": "Сгенерировать human-readable design overview."})
    if not changeplans_exists:
        blockers.append({"id": "changeplans.missing", "severity": "warning", "title": "changeplans/ отсутствует", "recommendation": "Создать каталог для ChangePlan artifacts."})

    confirmed_required = ["product_model", "role_model", "journey_map", "menu_proposal", "response_system", "impact_graph", "test_matrix"]
    not_confirmed = [key for key in confirmed_required if artifacts.get(key, {}).get("knowledge_status") != "confirmed"]
    for key in not_confirmed:
        blockers.append({"id": f"readiness.{key}.not_confirmed", "severity": "blocker", "title": f"{key} не confirmed", "evidence": [artifacts.get(key, {}).get("knowledge_status")], "recommendation": "Review и подтвердить artifact перед production-grade implementation."})
    manifest_allowed = bool(manifest.get("production_design_allowed"))
    all_confirmed = not not_confirmed
    production_allowed = bool(manifest_allowed and all_confirmed and not any(b.get("severity") == "error" for b in blockers))
    confirmed_count = len(confirmed_required) - len(not_confirmed)
    readiness_score = int(100 * confirmed_count / len(confirmed_required)) if confirmed_required else 0
    if not exists:
        readiness_status = "missing_design_layer"
    elif production_allowed:
        readiness_status = "ready"
    elif any(b.get("severity") == "error" for b in blockers):
        readiness_status = "invalid"
    else:
        readiness_status = "blocked"
    next_steps = []
    if not_confirmed:
        next_steps.append("Подтвердить core artifacts: " + ", ".join(not_confirmed))
    if not manifest_allowed:
        next_steps.append("После confirmation core artifacts обновить manifest.production_design_allowed=true.")
    if not readme_exists:
        next_steps.append("Восстановить .botctl/design/README.md для human-readable handoff.")
    if not changeplans_exists:
        next_steps.append("Создать .botctl/design/changeplans/ перед production changes.")
    return {
        "apiVersion": API_VERSION,
        "kind": "BotDesignReadiness",
        "generated_at": now_iso(),
        "project_path": str(project),
        "design_dir": str(design_dir),
        "design_exists": True,
        "readiness_status": readiness_status,
        "readiness_score": readiness_score,
        "production_design_allowed": production_allowed,
        "manifest_production_design_allowed": manifest_allowed,
        "artifacts": artifacts,
        "schema_validation": schema_results,
        "summary": {
            "artifacts": len(artifacts),
            "confirmed_required": confirmed_count,
            "required_total": len(confirmed_required),
            "blockers": len([b for b in blockers if b.get("severity") == "blocker"]),
            "errors": len([b for b in blockers if b.get("severity") == "error"]),
            "warnings": len([b for b in blockers if b.get("severity") == "warning"]),
        },
        "blockers": blockers,
        "next_steps": next_steps,
    }


DESIGN_CONFIRMABLE_ARTIFACTS = {
    "product_model",
    "role_model",
    "journey_map",
    "menu_proposal",
    "response_system",
    "state_model",
    "impact_graph",
    "test_matrix",
}
DESIGN_KNOWLEDGE_STATUSES = {"draft", "reviewed", "confirmed", "deprecated"}
DESIGN_CHANGE_PLAN_AFFECTED_FIELDS = (
    "affected_roles", "affected_journeys", "affected_menus", "affected_callbacks",
    "affected_handlers", "affected_responses", "affected_states", "affected_tests",
)


def _load_design_artifact(design_dir: Path, artifact_key: str) -> tuple[Path, dict[str, Any]]:
    if artifact_key not in DESIGN_ARTIFACT_FILES or artifact_key in {"manifest", "readme"}:
        raise ValueError(f"unknown or non-confirmable artifact: {artifact_key}")
    path = design_dir / DESIGN_ARTIFACT_FILES[artifact_key]
    if not path.exists():
        raise FileNotFoundError(f"design artifact not found: {path}")
    payload = load_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError(f"design artifact must be YAML object: {path}")
    schema_name = DESIGN_ARTIFACT_SCHEMAS.get(artifact_key)
    if schema_name:
        schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)
    return path, payload


def _semantic_issue(code: str, title: str, recommendation: str, *, path: str | None = None) -> dict[str, Any]:
    issue = {"code": code, "severity": "error", "title": title, "recommendation": recommendation}
    if path:
        issue["path"] = path
    return issue


def validate_design_artifact_semantics(project: Path, artifact_key: str) -> dict[str, Any]:
    design_dir = project_control(project) / "design"
    artifact_path, payload = _load_design_artifact(design_dir, artifact_key)
    issues: list[dict[str, Any]] = []

    def require_text(field: str, title: str) -> None:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            issues.append(_semantic_issue(f"{artifact_key}.{field}.missing", title, f"Заполнить непустое поле {field}.", path=field))

    def require_list(field: str, title: str) -> list[Any]:
        value = payload.get(field)
        if not isinstance(value, list) or not value:
            issues.append(_semantic_issue(f"{artifact_key}.{field}.empty", title, f"Добавить хотя бы один элемент в {field}.", path=field))
            return []
        return value

    if payload.get("source") == "placeholder":
        issues.append(_semantic_issue(f"{artifact_key}.placeholder", "Placeholder нельзя подтверждать", "Заменить placeholder на проверенное описание и указать source."))

    if artifact_key == "product_model":
        require_text("purpose", "Не описана цель продукта")
        for field in ("target_users", "primary_jobs", "non_goals", "business_rules", "success_metrics", "risk_constraints"):
            require_list(field, f"Не заполнен {field}")
    elif artifact_key == "role_model":
        roles = require_list("roles", "Не описаны роли")
        for index, role in enumerate(roles):
            if not isinstance(role, dict):
                issues.append(_semantic_issue("role_model.role.invalid", "Роль должна быть object", "Описать id, title, goals и permission_boundaries.", path=f"roles[{index}]"))
                continue
            for field in ("id", "title"):
                if not isinstance(role.get(field), str) or not role[field].strip():
                    issues.append(_semantic_issue(f"role_model.role.{field}.missing", f"У роли нет {field}", f"Заполнить {field}.", path=f"roles[{index}].{field}"))
            for field in ("goals", "permission_boundaries"):
                if not isinstance(role.get(field), list) or not role[field]:
                    issues.append(_semantic_issue(f"role_model.role.{field}.empty", f"У роли не заполнен {field}", f"Описать {field} для роли.", path=f"roles[{index}].{field}"))
    elif artifact_key == "journey_map":
        journeys = require_list("journeys", "Не описаны user journeys")
        for index, journey in enumerate(journeys):
            if not isinstance(journey, dict) or not journey.get("role_id") or not journey.get("goal") or not journey.get("steps"):
                issues.append(_semantic_issue("journey_map.journey.incomplete", "Journey не связывает роль, цель и шаги", "Заполнить role_id, goal и steps.", path=f"journeys[{index}]"))
    elif artifact_key == "menu_proposal":
        require_list("roles", "В menu proposal нет ролей")
        require_list("menus", "В menu proposal нет экранов/меню")
        require_list("callback_contract", "В menu proposal нет callback contract")
    elif artifact_key == "response_system":
        require_list("responses", "Нет response templates")
        require_list("tone_rules", "Не описаны tone rules")
    elif artifact_key == "state_model":
        require_list("states", "Не описаны states")
    elif artifact_key == "impact_graph":
        nodes = require_list("nodes", "Impact graph не содержит nodes")
        edges = require_list("edges", "Impact graph не содержит edges")
        node_ids = {item.get("id") for item in nodes if isinstance(item, dict)}
        for index, edge in enumerate(edges):
            if isinstance(edge, dict) and (edge.get("source") not in node_ids or edge.get("target") not in node_ids):
                issues.append(_semantic_issue("impact_graph.edge.unknown_node", "Impact edge ссылается на неизвестный node", "Исправить source/target или добавить node.", path=f"edges[{index}]"))
    elif artifact_key == "test_matrix":
        require_list("tests", "Test matrix не содержит tests")
        require_list("required_categories", "Test matrix не содержит required categories")

    return {
        "apiVersion": API_VERSION,
        "kind": "BotDesignArtifactValidation",
        "generated_at": now_iso(),
        "project_path": str(project),
        "artifact": artifact_key,
        "path": str(artifact_path),
        "valid": not issues,
        "issues": issues,
        "summary": {"errors": len(issues)},
    }


def _design_change_plan_path(project: Path, change_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,79}", change_id or ""):
        raise ValueError("change_id must be 3-80 lowercase latin letters, digits, dot, dash or underscore")
    return project_control(project) / "design" / "changeplans" / f"{change_id}.yaml"


def create_design_change_plan(project: Path, change_id: str, intent: str, risk_level: str) -> dict[str, Any]:
    readiness = design_status_readiness(project)
    if readiness.get("readiness_status") != "ready":
        raise ValueError("design ChangePlan requires readiness_status=ready")
    if not intent or not intent.strip():
        raise ValueError("intent must be non-empty")
    if risk_level not in {"low", "medium", "high", "critical"}:
        raise ValueError("invalid risk_level")
    path = _design_change_plan_path(project, change_id)
    if path.exists():
        raise FileExistsError(f"design ChangePlan already exists: {path}")
    plan = {
        "apiVersion": API_VERSION,
        "kind": "BotDesignChangePlan",
        "change_id": change_id,
        "knowledge_status": "draft",
        "approval_status": "not_requested",
        "created_at": now_iso(),
        "intent": intent.strip(),
        **{field: [] for field in DESIGN_CHANGE_PLAN_AFFECTED_FIELDS},
        "risk_level": risk_level,
        "verification_plan": [],
        "rollback_plan": [],
        "open_questions": [],
        "review_history": [],
        "approved_by": None,
        "approved_at": None,
        "runtime_apply_allowed": False,
    }
    schema = json.loads((SCHEMA_DIR / "change-plan-design.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(plan)
    dump_yaml(path, plan)
    return {"apiVersion": API_VERSION, "kind": "BotDesignChangePlanCreateResult", "path": str(path), "change_id": change_id, "knowledge_status": "draft", "runtime_apply_allowed": False}


def _design_reference_catalog(project: Path) -> dict[str, set[str]]:
    design_dir = project_control(project) / "design"

    def artifact(key: str) -> dict[str, Any]:
        path = design_dir / DESIGN_ARTIFACT_FILES[key]
        if not path.exists():
            return {}
        data = load_yaml(path)
        return data if isinstance(data, dict) else {}

    roles = artifact("role_model")
    journeys = artifact("journey_map")
    menus = artifact("menu_proposal")
    responses = artifact("response_system")
    states = artifact("state_model")
    impact = artifact("impact_graph")
    tests = artifact("test_matrix")
    catalog: dict[str, set[str]] = {field: set() for field in DESIGN_CHANGE_PLAN_AFFECTED_FIELDS}
    catalog["affected_roles"].update(str(item["id"]) for item in roles.get("roles", []) if isinstance(item, dict) and item.get("id"))
    catalog["affected_journeys"].update(str(item["id"]) for item in journeys.get("journeys", []) if isinstance(item, dict) and item.get("id"))
    for menu in menus.get("menus", []) or []:
        if not isinstance(menu, dict):
            continue
        if menu.get("id"):
            catalog["affected_menus"].add(str(menu["id"]))
        for button in menu.get("buttons", []) or []:
            if not isinstance(button, dict):
                continue
            for key in ("action_id", "callback_data_pattern", "callback_namespace"):
                if button.get(key):
                    catalog["affected_callbacks"].add(str(button[key]))
    for contract in menus.get("callback_contract", []) or []:
        if not isinstance(contract, dict):
            continue
        if contract.get("namespace"):
            catalog["affected_callbacks"].add(str(contract["namespace"]))
        catalog["affected_callbacks"].update(str(item) for item in contract.get("patterns", []) if item)
        catalog["affected_handlers"].update(str(item) for item in contract.get("handler_hints", []) if item)
    catalog["affected_responses"].update(str(item["id"]) for item in responses.get("responses", []) if isinstance(item, dict) and item.get("id"))
    catalog["affected_states"].update(str(item["id"]) for item in states.get("states", []) if isinstance(item, dict) and item.get("id"))
    catalog["affected_tests"].update(str(item["id"]) for item in tests.get("tests", []) if isinstance(item, dict) and item.get("id"))
    impact_kind_to_field = {
        "Role": "affected_roles", "Journey": "affected_journeys", "Menu": "affected_menus",
        "Button": "affected_callbacks", "Callback": "affected_callbacks", "Handler": "affected_handlers",
        "HandlerHint": "affected_handlers", "Response": "affected_responses", "State": "affected_states", "Test": "affected_tests",
    }
    for node in impact.get("nodes", []) or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        field = impact_kind_to_field.get(str(node.get("kind")))
        if field:
            catalog[field].add(str(node["id"]))
    return catalog


def validate_design_change_plan(project: Path, change_id: str) -> dict[str, Any]:
    path = _design_change_plan_path(project, change_id)
    if not path.exists():
        raise FileNotFoundError(f"design ChangePlan not found: {path}")
    payload = load_yaml(path)
    if not isinstance(payload, dict):
        raise ValueError("design ChangePlan must be a YAML object")
    issues: list[dict[str, Any]] = []
    try:
        schema = json.loads((SCHEMA_DIR / "change-plan-design.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)
    except jsonschema.ValidationError as exc:
        issues.append(_semantic_issue("change_plan.schema_invalid", "ChangePlan не проходит schema", str(exc.message)))
    if payload.get("change_id") != change_id:
        issues.append(_semantic_issue("change_plan.id_mismatch", "change_id не совпадает с именем файла", "Исправить change_id."))
    if not isinstance(payload.get("intent"), str) or len(payload["intent"].strip()) < 10:
        issues.append(_semantic_issue("change_plan.intent_too_short", "Цель изменения не описана", "Описать intent не короче 10 символов."))
    affected_count = 0
    reference_catalog = _design_reference_catalog(project)
    for field in DESIGN_CHANGE_PLAN_AFFECTED_FIELDS:
        value = payload.get(field)
        if not isinstance(value, list):
            issues.append(_semantic_issue(f"change_plan.{field}.invalid", f"{field} должен быть списком", f"Исправить {field}."))
        else:
            affected_count += len(value)
            for index, item in enumerate(value):
                if not isinstance(item, str) or not item.strip():
                    issues.append(_semantic_issue(f"change_plan.{field}.invalid_id", f"В {field} есть пустой или нестроковый id", "Указать строковый id из confirmed design artifacts.", path=f"{field}[{index}]"))
                elif item not in reference_catalog[field]:
                    issues.append(_semantic_issue(f"change_plan.{field}.unknown_id", f"{item} не найден в confirmed design source-of-truth", f"Выбрать id из {field} catalog или сначала обновить design artifact/ImpactGraph.", path=f"{field}[{index}]"))
    if affected_count == 0:
        issues.append(_semantic_issue("change_plan.no_affected_items", "Не указано, что затронет изменение", "Заполнить хотя бы один affected_* список."))
    for field in ("verification_plan", "rollback_plan"):
        if not isinstance(payload.get(field), list) or not payload[field]:
            issues.append(_semantic_issue(f"change_plan.{field}.empty", f"Не заполнен {field}", f"Добавить конкретные шаги в {field}."))
    if payload.get("open_questions"):
        issues.append(_semantic_issue("change_plan.open_questions", "В ChangePlan остались open_questions", "Решить вопросы до approval."))
    readiness = design_status_readiness(project)
    if readiness.get("readiness_status") != "ready":
        issues.append(_semantic_issue("change_plan.design_not_ready", "Design package не ready", "Подтвердить core design artifacts до approval."))
    return {"apiVersion": API_VERSION, "kind": "BotDesignChangePlanValidation", "generated_at": now_iso(), "change_id": change_id, "path": str(path), "valid": not issues, "issues": issues, "summary": {"errors": len(issues), "reference_catalog": {field: len(values) for field, values in reference_catalog.items()}}, "knowledge_status": payload.get("knowledge_status"), "approval_status": payload.get("approval_status", "not_requested"), "runtime_apply_allowed": False}


def update_design_change_plan_status(project: Path, change_id: str, target: str, *, actor: str, note: str | None = None) -> dict[str, Any]:
    if target not in {"reviewed", "approved"}:
        raise ValueError("target must be reviewed or approved")
    if not actor or not actor.strip():
        raise ValueError("actor is required")
    validation = validate_design_change_plan(project, change_id)
    if not validation["valid"]:
        codes = ", ".join(item["code"] for item in validation["issues"][:5])
        raise ValueError(f"ChangePlan validation failed: {codes}")
    path = _design_change_plan_path(project, change_id)
    payload = load_yaml(path)
    previous = payload.get("knowledge_status", "draft")
    if target == "reviewed" and previous != "draft":
        raise ValueError(f"review requires draft plan; current status is {previous}")
    if target == "approved" and previous != "reviewed":
        raise ValueError(f"approval requires reviewed plan; current status is {previous}")
    now = now_iso()
    history = payload.get("review_history", []) if isinstance(payload.get("review_history"), list) else []
    history.append({"at": now, "actor": actor.strip(), "from": previous, "to": "confirmed" if target == "approved" else "reviewed", "note": note or ""})
    payload["review_history"] = history
    payload["knowledge_status"] = "confirmed" if target == "approved" else "reviewed"
    payload["approval_status"] = "approved" if target == "approved" else "reviewed"
    payload["reviewed_by"] = actor.strip()
    payload["reviewed_at"] = now
    payload["runtime_apply_allowed"] = False
    if target == "approved":
        payload["approved_by"] = actor.strip()
        payload["approved_at"] = now
    dump_yaml(path, payload)
    return {"apiVersion": API_VERSION, "kind": "BotDesignChangePlanStatusResult", "change_id": change_id, "path": str(path), "previous_status": previous, "knowledge_status": payload["knowledge_status"], "approval_status": payload["approval_status"], "actor": actor.strip(), "runtime_apply_allowed": False}


def design_gate_status(project: Path, *, change_id: str | None = None) -> dict[str, Any]:
    readiness = design_status_readiness(project)
    plans_dir = project_control(project) / "design" / "changeplans"
    plan_paths = [_design_change_plan_path(project, change_id)] if change_id else sorted(plans_dir.glob("*.yaml")) if plans_dir.is_dir() else []
    plans: list[dict[str, Any]] = []
    for path in plan_paths:
        plan_id = path.stem
        if not path.exists():
            plans.append({"change_id": plan_id, "path": str(path), "exists": False, "valid": False, "knowledge_status": "missing", "approval_status": "missing", "approved": False, "issues": ["change_plan.missing"]})
            continue
        try:
            validation = validate_design_change_plan(project, plan_id)
            payload = load_yaml(path)
            approved = bool(validation["valid"] and payload.get("knowledge_status") == "confirmed" and payload.get("approval_status") == "approved" and payload.get("approved_by") and payload.get("approved_at"))
            plans.append({
                "change_id": plan_id,
                "path": str(path),
                "exists": True,
                "valid": validation["valid"],
                "knowledge_status": payload.get("knowledge_status", "draft"),
                "approval_status": payload.get("approval_status", "not_requested"),
                "approved": approved,
                "approved_by": payload.get("approved_by"),
                "approved_at": payload.get("approved_at"),
                "risk_level": payload.get("risk_level"),
                "issues": [item["code"] for item in validation["issues"]],
            })
        except Exception as exc:
            plans.append({"change_id": plan_id, "path": str(path), "exists": True, "valid": False, "knowledge_status": "unknown", "approval_status": "unknown", "approved": False, "issues": [str(exc)]})
    approved_plans = [plan for plan in plans if plan["approved"]]
    design_ready = readiness.get("readiness_status") == "ready"
    blockers: list[dict[str, Any]] = []
    if not design_ready:
        blockers.append({"id": "gate.design_not_ready", "title": "Design package не ready", "recommendation": "Устранить blockers из design status."})
    if not plans:
        blockers.append({"id": "gate.change_plan_missing", "title": "Design ChangePlan не найден", "recommendation": "Создать и заполнить design ChangePlan."})
    elif not approved_plans:
        blockers.append({"id": "gate.approved_change_plan_missing", "title": "Нет valid approved ChangePlan", "recommendation": "Проверить, review и approve ChangePlan."})
    planning_allowed = bool(design_ready and approved_plans)
    if planning_allowed:
        gate_status = "ready_for_implementation_planning"
    elif not readiness.get("design_exists"):
        gate_status = "missing_design_layer"
    elif not design_ready:
        gate_status = "design_blocked"
    elif not plans:
        gate_status = "missing_change_plan"
    else:
        gate_status = "change_plan_blocked"
    return {
        "apiVersion": API_VERSION,
        "kind": "BotDesignGate",
        "generated_at": now_iso(),
        "project_path": str(project),
        "gate_status": gate_status,
        "design_ready": design_ready,
        "implementation_planning_allowed": planning_allowed,
        "runtime_apply_allowed": False,
        "design_readiness": {
            "readiness_status": readiness.get("readiness_status"),
            "readiness_score": readiness.get("readiness_score", 0),
            "production_design_allowed": readiness.get("production_design_allowed", False),
            "blockers": readiness.get("blockers", []),
        },
        "change_plans": plans,
        "summary": {"change_plans": len(plans), "approved_change_plans": len(approved_plans), "blockers": len(blockers)},
        "blockers": blockers,
        "next_steps": [] if planning_allowed else [item["recommendation"] for item in blockers],
    }


def _refresh_manifest_from_artifacts(project: Path, design_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    artifact_statuses: dict[str, Any] = {}
    for key, filename in DESIGN_ARTIFACT_FILES.items():
        if key == "readme":
            continue
        path = design_dir / filename
        if path.exists():
            try:
                payload = load_yaml(path)
                payload = payload if isinstance(payload, dict) else {}
            except Exception:
                payload = {}
        else:
            payload = {}
        artifact_statuses[key] = {
            "path": f".botctl/design/{filename}",
            "kind": payload.get("kind"),
            "knowledge_status": payload.get("knowledge_status", "missing"),
            "requires_review": payload.get("requires_review", True),
        }
    required = ["product_model", "role_model", "journey_map", "menu_proposal", "response_system", "impact_graph", "test_matrix"]
    blockers = [key for key in required if artifact_statuses.get(key, {}).get("knowledge_status") != "confirmed"]
    manifest.update({
        "apiVersion": API_VERSION,
        "kind": "BotDesignManifest",
        "generated_at": now_iso(),
        "project_path": str(project),
        "artifacts": artifact_statuses,
        "blockers": blockers,
        "production_design_allowed": not blockers,
        "knowledge_status": "confirmed" if not blockers else "draft",
        "requires_review": bool(blockers),
    })
    if not blockers:
        manifest["open_questions"] = []
    if not blockers and not manifest.get("confirmed_at"):
        manifest["confirmed_at"] = now_iso()
    if blockers:
        manifest["confirmed_at"] = manifest.get("confirmed_at")
    return manifest


def update_design_artifact_status(
    project: Path,
    artifact_key: str,
    status: str,
    *,
    actor: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if artifact_key not in DESIGN_CONFIRMABLE_ARTIFACTS:
        raise ValueError(f"artifact must be one of: {', '.join(sorted(DESIGN_CONFIRMABLE_ARTIFACTS))}")
    if status not in DESIGN_KNOWLEDGE_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(DESIGN_KNOWLEDGE_STATUSES))}")
    design_dir = project_control(project) / "design"
    if not design_dir.exists():
        raise FileNotFoundError(f"design layer not found: {design_dir}")
    artifact_path, artifact = _load_design_artifact(design_dir, artifact_key)
    now = now_iso()
    previous_status = artifact.get("knowledge_status", "missing")
    if status == "reviewed" and previous_status not in {"draft", "reviewed"}:
        raise ValueError(f"review requires draft/reviewed artifact; current status is {previous_status}")
    if status == "confirmed":
        if previous_status != "reviewed":
            raise ValueError(f"confirm requires reviewed artifact; current status is {previous_status}")
        if not actor or not actor.strip():
            raise ValueError("confirm requires a non-empty actor")
        open_questions = artifact.get("open_questions", [])
        if isinstance(open_questions, list) and open_questions:
            raise ValueError("confirm blocked: artifact still has open_questions")
        if artifact.get("assumptions_required_confirmation") is True:
            raise ValueError("confirm blocked: assumptions_required_confirmation is true")
        semantic_validation = validate_design_artifact_semantics(project, artifact_key)
        if not semantic_validation["valid"]:
            codes = ", ".join(issue["code"] for issue in semantic_validation["issues"][:5])
            raise ValueError(f"confirm blocked by semantic validation: {codes}")
    history = artifact.get("review_history", [])
    if not isinstance(history, list):
        history = []
    history.append({
        "at": now,
        "actor": actor or "unknown",
        "from": previous_status,
        "to": status,
        "note": note or "",
    })
    artifact["knowledge_status"] = status
    artifact["requires_review"] = status != "confirmed"
    # Individual artifacts never authorize production on their own. The package
    # gate lives in manifest.yaml and is opened only when every core artifact is confirmed.
    artifact["production_design_allowed"] = False
    artifact["reviewed_by"] = actor or artifact.get("reviewed_by")
    artifact["reviewed_at"] = now
    artifact["review_history"] = history
    if status == "confirmed":
        artifact["confirmed_by"] = actor or "unknown"
        artifact["confirmed_at"] = now
    elif status in {"draft", "reviewed"}:
        artifact["confirmed_by"] = None
        artifact["confirmed_at"] = None
    dump_yaml(artifact_path, artifact)

    manifest_path = design_dir / DESIGN_ARTIFACT_FILES["manifest"]
    manifest = load_yaml(manifest_path) if manifest_path.exists() else {}
    if not isinstance(manifest, dict):
        manifest = {}
    manifest_history = manifest.get("review_history", [])
    if not isinstance(manifest_history, list):
        manifest_history = []
    manifest_history.append({"at": now, "actor": actor or "unknown", "artifact": artifact_key, "from": previous_status, "to": status, "note": note or ""})
    manifest["review_history"] = manifest_history
    manifest = _refresh_manifest_from_artifacts(project, design_dir, manifest)
    if not manifest.get("blockers"):
        manifest["confirmed_by"] = actor or manifest.get("confirmed_by") or "unknown"
        manifest["confirmed_at"] = now
    else:
        manifest["confirmed_by"] = None
    dump_yaml(manifest_path, manifest)
    readiness = design_status_readiness(project)
    return {
        "apiVersion": API_VERSION,
        "kind": "BotDesignReviewResult",
        "generated_at": now,
        "project_path": str(project),
        "artifact": artifact_key,
        "path": str(artifact_path),
        "previous_status": previous_status,
        "new_status": status,
        "actor": actor or "unknown",
        "production_design_allowed": readiness.get("production_design_allowed", False),
        "readiness_status": readiness.get("readiness_status"),
        "readiness_score": readiness.get("readiness_score"),
        "remaining_blockers": [b for b in readiness.get("blockers", []) if b.get("severity") in {"blocker", "error"}],
    }


def extract_menu_map(project: Path) -> dict[str, Any]:
    texts = _collect_design_project_text(project)
    commands: list[dict[str, Any]] = []
    buttons: list[dict[str, Any]] = []
    handlers: list[dict[str, Any]] = []
    namespaces: dict[str, dict[str, Any]] = {}
    roles_seen = {"user"}

    for rel, text in sorted(texts.items()):
        if not rel.endswith(".py"):
            continue
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        visitor = _MenuAstVisitor(rel, lines)
        visitor.visit(tree)
        for command in visitor.commands:
            roles_seen.add(command.get("role_hint") or "user")
            _add_unique(commands, command, ("command", "role_hint"))
        for button in visitor.buttons:
            roles_seen.update(button.get("allowed_roles_hint", []))
            _add_unique(buttons, button, ("callback_data", "menu_hint"))
        for handler in visitor.handlers:
            roles_seen.add(handler.get("role_hint") or "user")
            _add_unique(handlers, handler, ("path", "name"))
        for namespace, data in visitor.callback_namespaces.items():
            target = namespaces.setdefault(
                namespace,
                {
                    "namespace": namespace,
                    "patterns": [],
                    "allowed_roles_hint": [],
                    "handlers_hint": [],
                    "risk_notes": [],
                },
            )
            target["patterns"] = sorted(set(target["patterns"]) | set(data.get("patterns", [])))
            target["allowed_roles_hint"] = sorted(set(target["allowed_roles_hint"]) | set(data.get("allowed_roles_hint", [])))
            target["handlers_hint"] = sorted(set(target["handlers_hint"]) | set(data.get("handlers_hint", [])))
            target["risk_notes"] = sorted(set(target["risk_notes"]) | set(data.get("risk_notes", [])))
        for match in COMMAND_RE.finditer(text):
            command = match.group(1)
            role_hint = _infer_role_from_text(rel, command)
            roles_seen.add(role_hint)
            _add_unique(
                commands,
                {
                    "command": command,
                    "description": "Найдено как slash-command mention в безопасном коде.",
                    "role_hint": role_hint,
                    "source": {"path": rel, "line": text[: match.start()].count("\n") + 1, "context": "regex"},
                },
                ("command", "role_hint"),
            )
        for line_no, line in enumerate(text.splitlines(), start=1):
            if "callback_data" not in line and "callback" not in line.lower():
                continue
            for match in CALLBACK_RE.finditer(line):
                namespace = match.group(1)
                if namespace in {"http", "https", "tg"}:
                    continue
                pattern = match.group(0)
                target = namespaces.setdefault(namespace, {"namespace": namespace, "patterns": [], "allowed_roles_hint": [], "handlers_hint": [], "risk_notes": []})
                if pattern not in target["patterns"]:
                    target["patterns"].append(pattern)
                roles = _callback_allowed_roles(namespace, rel)
                target["allowed_roles_hint"] = sorted(set(target["allowed_roles_hint"]) | set(roles))
                target["handlers_hint"] = sorted(set(target["handlers_hint"]) | {f"{rel}:{line_no}"})
                roles_seen.update(roles)

    roles = []
    role_titles = {
        "guest": "Гость / приглашённый пользователь",
        "user": "Обычный пользователь",
        "allowed_user": "Разрешённый пользователь",
        "creator": "Креатор",
        "lead": "Lead-креатор",
        "admin": "Администратор",
        "owner": "Владелец",
    }
    guard_evidence = _guard_evidence_for_namespaces(texts, set(namespaces))
    global_guard_evidence = guard_evidence.get("__global__", {kind: [] for kind in GUARD_EVIDENCE_PATTERNS})
    privileged_roles = {"admin", "owner", "creator", "lead"}
    for namespace, target in namespaces.items():
        target["guard_evidence"] = guard_evidence.get(namespace, {kind: [] for kind in GUARD_EVIDENCE_PATTERNS})
        if privileged_roles & set(target.get("allowed_roles_hint", [])):
            for kind, hits in global_guard_evidence.items():
                if not target["guard_evidence"].get(kind):
                    target["guard_evidence"][kind] = hits[:8]
        target["guard_status"] = _guard_status(target["guard_evidence"])
        if target["guard_status"].get("supported"):
            note = "Guard evidence найден в коде: permission + confirmation/idempotency markers."
            if note not in target["risk_notes"]:
                target["risk_notes"].append(note)

    for role in ["guest", "user", "allowed_user", "creator", "lead", "admin", "owner"]:
        if role in roles_seen:
            roles.append({"id": role, "title": role_titles[role], "source": "inferred_from_commands_callbacks_or_names"})

    menu_groups: dict[str, dict[str, Any]] = {}
    for button in buttons:
        menu_id = "menu." + re.sub(r"[^a-z0-9_]+", "_", str(button.get("menu_hint") or "module").lower()).strip("_")
        group = menu_groups.setdefault(menu_id, {"id": menu_id, "title": str(button.get("menu_hint") or "module"), "buttons": [], "visible_for_hint": []})
        group["buttons"].append(button)
        group["visible_for_hint"] = sorted(set(group["visible_for_hint"]) | set(button.get("allowed_roles_hint", [])))

    return {
        "apiVersion": API_VERSION,
        "kind": "BotMenuMap",
        "generated_at": now_iso(),
        "project_path": str(project),
        "read_only": True,
        "confidence": "medium",
        "notes": [
            "Это извлечённая карта фактических меню/ролей/callbacks, а не финальный UX design.",
            "allowed_roles_hint вычисляется эвристически по именам, namespaces и контексту; критичные права нужно подтвердить кодом доступа.",
            "Секреты, .env, sessions, runtime DB и большие/data paths не читаются.",
        ],
        "roles": roles,
        "commands": sorted(commands, key=lambda item: (item.get("role_hint", ""), item.get("command", ""))),
        "menus": sorted(menu_groups.values(), key=lambda item: item["id"]),
        "callback_contract": sorted(namespaces.values(), key=lambda item: item["namespace"]),
        "handlers_hint": sorted(handlers, key=lambda item: (item.get("path", ""), item.get("line", 0))),
        "quality_gates": [
            {"id": "callbacks_have_namespace", "status": "covered" if namespaces else "missing", "why": "callback_data должны иметь namespace/action для безопасной маршрутизации"},
            {"id": "roles_are_explicit", "status": "covered" if len(roles) > 1 else "weak", "why": "сложные боты должны явно различать роли пользователя"},
            {"id": "menus_have_buttons", "status": "covered" if buttons else "missing", "why": "сложный UX должен иметь проверяемую карту кнопок"},
            {"id": "commands_are_visible", "status": "covered" if commands else "missing", "why": "Telegram menu / slash commands должны быть понятны пользователю"},
        ],
    }
