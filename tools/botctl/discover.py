from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .model import file_hash, now_iso, project_control, read_text_if_exists, relative, symbol_exists


def load_desired(project: Path) -> dict[str, Any]:
    from .model import load_yaml

    path = project_control(project) / "graph.desired.yaml"
    if not path.exists():
        return {"nodes": [], "edges": []}
    data = load_yaml(path)
    return data if isinstance(data, dict) else {"nodes": [], "edges": []}



SAFE_TEXT_MAX_FILES = 120
SAFE_TEXT_MAX_BYTES = 256_000
SAFE_PY_DIRS = ("src", "app", "bot", "bots")
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


def _is_safe_text_path(project: Path, path: Path) -> bool:
    rel = relative(project, path)
    lowered_parts = {part.lower() for part in Path(rel).parts}
    lowered_rel = rel.lower()
    if lowered_parts & UNSAFE_PATH_PARTS:
        return False
    if any(fragment in lowered_rel for fragment in UNSAFE_FILE_FRAGMENTS):
        return False
    return True


def _collect_safe_project_text(project: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    candidates: list[Path] = []
    for dirname in SAFE_PY_DIRS:
        root = project / dirname
        if root.exists():
            candidates.extend(sorted(root.rglob("*.py")))
    for rel in ["Makefile", "compose.yml", "docker-compose.yml", "Dockerfile", "pyproject.toml", "requirements.txt"]:
        p = project / rel
        if p.exists():
            candidates.append(p)
    seen: set[str] = set()
    for path in candidates:
        if len(texts) >= SAFE_TEXT_MAX_FILES:
            break
        if not path.is_file() or not _is_safe_text_path(project, path):
            continue
        rel = relative(project, path)
        if rel in seen:
            continue
        seen.add(rel)
        text = read_text_if_exists(path)
        if len(text.encode("utf-8", errors="ignore")) > SAFE_TEXT_MAX_BYTES:
            continue
        texts[rel] = text
    return texts



def _enclosing_symbol(tree: ast.AST, line_no: int) -> str | None:
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            if start <= line_no <= end and (best is None or start >= best[0]):
                best = (start, node.name)
    return best[1] if best else None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return ""


def _python_sources(texts: dict[str, str]) -> dict[str, tuple[str, ast.AST, list[str]]]:
    out: dict[str, tuple[str, ast.AST, list[str]]] = {}
    for rel, text in texts.items():
        if not rel.endswith(".py"):
            continue
        try:
            out[rel] = (text, ast.parse(text), text.splitlines())
        except SyntaxError:
            continue
    return out


def _ast_match(rel: str, lines: list[str], tree: ast.AST, node: ast.AST, pattern: str, kind: str) -> dict[str, Any]:
    line_no = int(getattr(node, "lineno", 1) or 1)
    snippet = lines[line_no - 1].strip()[:220] if 0 < line_no <= len(lines) else ""
    return {
        "path": rel,
        "line": line_no,
        "symbol": _enclosing_symbol(tree, line_no),
        "snippet": snippet,
        "pattern": pattern,
        "evidence_kind": kind,
    }


def _ast_call_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                short = name.rsplit('.', 1)[-1]
                if name in names or short in names:
                    matches.append(_ast_match(rel, lines, tree, node, '|'.join(sorted(names)), 'ast_call'))
                    if len(matches) >= max_matches:
                        return matches
    return matches


def _telegram_application_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "telegram.ext":
            for alias in node.names:
                if alias.name == "Application":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _annotation_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _annotation_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _is_telegram_application_builder_call(node: ast.AST, application_aliases: set[str]) -> bool:
    call_name = _call_name(node)
    return any(call_name == f"{alias}.builder" for alias in application_aliases)


def _is_build_call_from_builder(node: ast.AST, builder_names: set[str], application_aliases: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    call_name = _call_name(node.func)
    if call_name == "":
        return False
    if any(call_name == f"{alias}.builder.build" for alias in application_aliases):
        return True
    if call_name.endswith(".build"):
        receiver = call_name.rsplit(".", 1)[0]
        return receiver in builder_names or _is_telegram_application_builder_call(node.func, application_aliases)
    return False


def _telegram_application_vars(tree: ast.AST) -> set[str]:
    application_aliases = _telegram_application_aliases(tree)
    application_vars: set[str] = set()
    builder_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                annotation = _annotation_name(arg.annotation)
                if annotation in application_aliases or annotation.endswith(".Application"):
                    application_vars.add(arg.arg)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            annotation = _annotation_name(node.annotation)
            if annotation in application_aliases or annotation.endswith(".Application"):
                application_vars.add(node.target.id)
        elif isinstance(node, ast.Assign):
            value_call_name = _call_name(node.value)
            is_builder = _is_telegram_application_builder_call(node.value, application_aliases) or any(
                value_call_name.startswith(f"{builder_name}.") for builder_name in builder_names
            )
            is_application = _is_build_call_from_builder(node.value, builder_names, application_aliases)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if is_builder:
                        builder_names.add(target.id)
                    if is_application:
                        application_vars.add(target.id)
    return application_vars


def _ast_telegram_application_method_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        application_vars = _telegram_application_vars(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in names:
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id in application_vars:
                matches.append(_ast_match(rel, lines, tree, node, '|'.join(sorted(names)), 'ast_telegram_application_method'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_telegram_application_builder_matches(texts: dict[str, str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        application_aliases = _telegram_application_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_telegram_application_builder_call(node, application_aliases):
                matches.append(_ast_match(rel, lines, tree, node, 'Application.builder', 'ast_telegram_application_builder'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _module_aliases(tree: ast.AST, module: str) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == module:
            aliases.add(module)
    return aliases


def _module_function_aliases(tree: ast.AST, module: str, names: set[str]) -> dict[str, str]:
    aliases = {f"{module_alias}.{name}": name for module_alias in _module_aliases(tree, module) for name in names}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name in names:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _ast_module_function_call_matches(texts: dict[str, str], module: str, names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        aliases = _module_function_aliases(tree, module, names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in aliases:
                    matches.append(_ast_match(rel, lines, tree, node, aliases[name], f'ast_{module}_call'))
                    if len(matches) >= max_matches:
                        return matches
    return matches


def _module_symbol_aliases(tree: ast.AST, module: str, names: set[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module:
                    module_alias = alias.asname or alias.name
                    aliases.update({f"{module_alias}.{name}": name for name in names})
        elif isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name in names:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def _ast_imported_symbol_call_matches(texts: dict[str, str], modules: set[str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        aliases: dict[str, str] = {}
        for module in modules:
            aliases.update(_module_symbol_aliases(tree, module, names))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in aliases:
                    matches.append(_ast_match(rel, lines, tree, node, aliases[name], 'ast_imported_symbol_call'))
                    if len(matches) >= max_matches:
                        return matches
    return matches


def _ast_imported_symbol_keyword_matches(
    texts: dict[str, str], modules: set[str], call_names: set[str], keyword_names: set[str], *, max_matches: int = 12
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        aliases: dict[str, str] = {}
        for module in modules:
            aliases.update(_module_symbol_aliases(tree, module, call_names))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in aliases:
                continue
            if any(keyword.arg in keyword_names for keyword in node.keywords):
                matches.append(_ast_match(rel, lines, tree, node, '|'.join(sorted(keyword_names)), 'ast_imported_symbol_keyword'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _local_or_imported_function_aliases(tree: ast.AST, names: set[str]) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            aliases.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef) and node.name in names:
            aliases.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in names:
                    aliases.add(alias.asname or alias.name)
    return aliases


def _ast_local_or_imported_function_call_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        aliases = _local_or_imported_function_aliases(tree, names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in aliases:
                    matches.append(_ast_match(rel, lines, tree, node, name, 'ast_local_or_imported_function_call'))
                    if len(matches) >= max_matches:
                        return matches
    return matches


def _ast_telegram_bot_method_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in names:
                continue
            receiver_name = _call_name(node.func.value)
            if receiver_name == "bot" or receiver_name.endswith(".bot"):
                matches.append(_ast_match(rel, lines, tree, node, node.func.attr, 'ast_telegram_bot_method'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _constructor_assigned_vars(tree: ast.AST, module: str, symbol: str) -> set[str]:
    aliases = set(_module_symbol_aliases(tree, module, {symbol}).keys())
    vars_: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value_name = _call_name(node.value)
            if value_name in aliases:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        vars_.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        vars_.add(_call_name(target))
        elif isinstance(node, ast.AnnAssign):
            annotation = _annotation_name(node.annotation)
            if annotation == symbol or annotation.endswith(f".{symbol}"):
                if isinstance(node.target, ast.Name):
                    vars_.add(node.target.id)
                elif isinstance(node.target, ast.Attribute):
                    vars_.add(_call_name(node.target))
    return vars_


def _aiogram_router_vars(tree: ast.AST) -> set[str]:
    router_aliases = set(_module_symbol_aliases(tree, "aiogram", {"Router"}).keys())
    vars_: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            value_name = _call_name(node.value)
            if value_name in router_aliases:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        vars_.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        vars_.add(_call_name(target))
        elif isinstance(node, ast.AnnAssign):
            annotation = _annotation_name(node.annotation)
            if annotation == "Router" or annotation.endswith(".Router"):
                if isinstance(node.target, ast.Name):
                    vars_.add(node.target.id)
                elif isinstance(node.target, ast.Attribute):
                    vars_.add(_call_name(node.target))
    return vars_


def _ast_aiogram_router_method_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        router_vars = _aiogram_router_vars(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in names:
                continue
            receiver = _call_name(node.func.value)
            if receiver in router_vars:
                matches.append(_ast_match(rel, lines, tree, node, node.func.attr, 'ast_aiogram_router_method'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_aiogram_command_matches(texts: dict[str, str], *, command: str | None = None, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        aliases: dict[str, str] = {}
        aliases.update(_module_symbol_aliases(tree, "aiogram.filters", {"Command"}))
        aliases.update(_module_symbol_aliases(tree, "aiogram.types", {"BotCommand"}))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node.func)
            if name not in aliases:
                continue
            if command is not None:
                values: list[str] = []
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        values.append(arg.value.lstrip('/'))
                for keyword in node.keywords:
                    if keyword.arg == "command" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                        values.append(keyword.value.value.lstrip('/'))
                if command not in values:
                    continue
            matches.append(_ast_match(rel, lines, tree, node, command or aliases[name], 'ast_aiogram_command'))
            if len(matches) >= max_matches:
                return matches
    return matches


def _ast_aiogram_router_errors_register_matches(texts: dict[str, str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        router_vars = _aiogram_router_vars(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "register":
                continue
            receiver = node.func.value
            if not isinstance(receiver, ast.Attribute) or receiver.attr != "errors":
                continue
            if _call_name(receiver.value) in router_vars:
                matches.append(_ast_match(rel, lines, tree, node, "errors.register", 'ast_aiogram_error_handler'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_aiogram_polling_matches(texts: dict[str, str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        dispatcher_vars = _constructor_assigned_vars(tree, "aiogram", "Dispatcher")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "start_polling":
                continue
            if _call_name(node.func.value) in dispatcher_vars:
                matches.append(_ast_match(rel, lines, tree, node, "Dispatcher.start_polling", 'ast_aiogram_polling'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_any_module_function_call_matches(texts: dict[str, str], modules: set[str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for module in sorted(modules):
        matches.extend(_ast_module_function_call_matches(texts, module, names, max_matches=max_matches - len(matches)))
        if len(matches) >= max_matches:
            return matches
    return matches


def _logging_logger_vars(tree: ast.AST) -> set[str]:
    logger_vars: set[str] = set()
    logging_aliases = _module_aliases(tree, "logging")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value_name = _call_name(node.value)
        if not any(value_name == f"{alias}.getLogger" for alias in logging_aliases):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                logger_vars.add(target.id)
    return logger_vars


def _ast_logging_call_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        direct_aliases = _module_function_aliases(tree, "logging", names)
        logger_vars = _logging_logger_vars(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _call_name(node.func)
            matched_pattern: str | None = direct_aliases.get(call_name)
            if matched_pattern is None and isinstance(node.func, ast.Attribute):
                if node.func.attr in names and isinstance(node.func.value, ast.Name) and node.func.value.id in logger_vars:
                    matched_pattern = node.func.attr
            if matched_pattern is not None:
                matches.append(_ast_match(rel, lines, tree, node, matched_pattern, 'ast_logging_call'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_symbol_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
                matches.append(_ast_match(rel, lines, tree, node, '|'.join(sorted(names)), 'ast_symbol'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_import_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported = {node.module or '', *{alias.name for alias in node.names}}
            else:
                continue
            if imported & names:
                matches.append(_ast_match(rel, lines, tree, node, '|'.join(sorted(names)), 'ast_import'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _ast_attr_or_name_matches(texts: dict[str, str], names: set[str], *, max_matches: int = 12) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for rel, (_text, tree, lines) in _python_sources(texts).items():
        for node in ast.walk(tree):
            found = None
            if isinstance(node, ast.Name) and node.id in names:
                found = node.id
            elif isinstance(node, ast.Attribute) and node.attr in names:
                found = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                found = node.value
            if found:
                matches.append(_ast_match(rel, lines, tree, node, found, 'ast_name_or_attr'))
                if len(matches) >= max_matches:
                    return matches
    return matches


def _make_structured_signal(check_id: str, title: str, matches: list[dict[str, Any]], *, confidence: str) -> dict[str, Any] | None:
    if not matches:
        return None
    paths = sorted({m['path'] for m in matches})
    checked_at = now_iso()
    kinds = sorted({m.get('evidence_kind', 'unknown') for m in matches})
    return {
        'check_id': check_id,
        'title': title,
        'status': 'observed',
        'source': 'local_scan',
        'confidence': confidence,
        'evidence_kind': '+'.join(kinds),
        'paths': paths,
        'patterns': sorted({str(m.get('pattern')) for m in matches}),
        'matches': matches[:12],
        'source_fingerprints': {},
        'validity': {'status': 'current', 'checked_at': checked_at},
        'collected_at': checked_at,
    }

def _line_matches(texts: dict[str, str], pattern: str, *, max_matches: int = 8) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    regex = re.compile(pattern, flags=re.I)
    symbol_regex = re.compile(r"^\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(|^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\b")
    for rel, text in texts.items():
        current_symbol: str | None = None
        for line_no, line in enumerate(text.splitlines(), start=1):
            symbol_match = symbol_regex.search(line)
            if symbol_match:
                current_symbol = symbol_match.group(1) or symbol_match.group(2)
            if regex.search(line):
                matches.append(
                    {
                        "path": rel,
                        "line": line_no,
                        "symbol": current_symbol,
                        "snippet": line.strip()[:220],
                        "pattern": pattern,
                        "evidence_kind": "line_pattern_match",
                    }
                )
                if len(matches) >= max_matches:
                    return matches
    return matches


def _signal(
    check_id: str,
    title: str,
    texts: dict[str, str],
    patterns: list[str],
    *,
    confidence: str = "medium",
    require_all: bool = False,
) -> dict[str, Any] | None:
    evidence: list[dict[str, Any]] = []
    for pattern in patterns:
        matches = _line_matches(texts, pattern)
        if not matches and require_all:
            return None
        evidence.extend(matches)
    if not evidence:
        return None
    paths = sorted({m["path"] for m in evidence})
    checked_at = now_iso()
    return {
        "check_id": check_id,
        "title": title,
        "status": "observed",
        "source": "local_scan",
        "confidence": confidence,
        "evidence_kind": "line_pattern_match",
        "paths": paths,
        "patterns": patterns,
        "matches": evidence[:12],
        "source_fingerprints": {},
        "validity": {"status": "current", "checked_at": checked_at},
        "collected_at": checked_at,
    }


def _set_if_signal(signals: dict[str, dict[str, Any]], signal: dict[str, Any] | None) -> None:
    if signal:
        signals[str(signal["check_id"])] = signal


def discover_ux_evidence(project: Path) -> dict[str, Any]:
    texts = _collect_safe_project_text(project)
    signals: dict[str, dict[str, Any]] = {}

    _set_if_signal(
        signals,
        _make_structured_signal(
            "command_design",
            "Найдены Telegram handlers/filters",
            _ast_telegram_application_method_matches(texts, {"add_handler"})
            + _ast_imported_symbol_call_matches(texts, {"telegram.ext"}, {"MessageHandler", "CommandHandler", "CallbackQueryHandler"})
            + _ast_aiogram_router_method_matches(texts, {"message", "callback_query"})
            + _ast_aiogram_command_matches(texts),
            confidence="high",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "start_onboarding",
            "Найден обработчик или текст /start",
            _ast_imported_symbol_call_matches(texts, {"telegram.ext"}, {"CommandHandler"})
            + _ast_aiogram_command_matches(texts, command="start")
            + _line_matches(texts, r"/start|start_onboarding"),
            confidence="high",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "inline_keyboard_layout",
            "Найдены inline keyboard элементы",
            _ast_imported_symbol_call_matches(texts, {"telegram", "aiogram.types"}, {"InlineKeyboardMarkup", "InlineKeyboardButton"})
            + _ast_imported_symbol_keyword_matches(texts, {"telegram", "aiogram.types"}, {"InlineKeyboardButton"}, {"callback_data"}),
            confidence="high",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "unknown_input_fallback",
            "Найдены ветки fallback/skip для неподходящего ввода",
            _line_matches(texts, r"Skip .*not configured|Skip .*no |no mirrorable|unsupported|unknown input|fallback"),
            confidence="medium",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "progress_status",
            "Найдены heartbeat/queue/progress признаки",
            _ast_local_or_imported_function_call_matches(texts, {"write_heartbeat"})
            + _ast_telegram_bot_method_matches(texts, {"send_chat_action"})
            + _ast_symbol_matches(texts, {"queue_worker", "StatusMessage"})
            + _line_matches(texts, r"processed .*pending|progress|upload|status\.set|долг.*обрабаты|распозна"),
            confidence="medium",
        ),
    )
    error_matches = (
        _ast_telegram_application_method_matches(texts, {"add_error_handler"})
        + _ast_aiogram_router_errors_register_matches(texts)
        + _ast_logging_call_matches(texts, {"exception", "error"})
        + _ast_symbol_matches(texts, {"error_handler", "global_error"})
        + _line_matches(texts, r"RuntimeError\(")
    )
    error_signal = _make_structured_signal(
        "human_readable_errors",
        "Найдены обработчики и логирование ошибок",
        error_matches,
        confidence="high",
    )
    _set_if_signal(signals, error_signal)
    global_matches = (
        _ast_telegram_application_method_matches(texts, {"add_error_handler"})
        + _ast_aiogram_router_errors_register_matches(texts)
        + _ast_symbol_matches(texts, {"error_handler", "global_error"})
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "global_error_handler",
            "Найден глобальный обработчик ошибок",
            global_matches,
            confidence="high",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "empty_states",
            "Найдены признаки пустых/skip/DLQ состояний",
            _ast_attr_or_name_matches(texts, {"DLQ"})
            + _line_matches(texts, r"dead.?letter|no .*pending|no mirrorable|Skip .*no|summary\(\)|not found|не найден|нет .*расшифров|пуст|нельзя опубликовать"),
            confidence="medium",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "rate_limiting",
            "Найдены признаки batch/lease/retry/rate контроля",
            _ast_attr_or_name_matches(texts, {"queue_batch_size", "queue_lease_sec", "queue_max_attempts", "retry_at", "attempts", "_processing_audio", "_active_drafts"})
            + _ast_any_module_function_call_matches(texts, {"asyncio", "time"}, {"sleep"})
            + _line_matches(texts, r"backoff|lease|wait_for|shield|already .*processing|уже обрабаты|дождись"),
            confidence="medium",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "persistent_user_state",
            "Найдены признаки persistent state/SQLite/store",
            _ast_import_matches(texts, {"sqlite3"})
            + _ast_symbol_matches(texts, {"RepostStore", "Storage", "DraftStore", "RuntimePreferences"})
            + _ast_attr_or_name_matches(texts, {"state_db", "save_result", "load_result", "settings.json"})
            + _line_matches(texts, r"migrations|CREATE TABLE|queue|delivery|save_result|load_result|settings\.json"),
            confidence="high",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "token_env_safety",
            "Найдены env-based token/config refs без чтения секретов",
            _ast_module_function_call_matches(texts, "os", {"getenv"})
            + _ast_attr_or_name_matches(texts, {"TELEGRAM_BOT_TOKEN", "VK_USER_TOKEN", "OPENROUTER_API_KEY"})
            + _line_matches(texts, r"Missing required env vars|Missing required environment variables"),
            confidence="high",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "analytics_or_observability",
            "Найдены logging/heartbeat/health признаки",
            _ast_import_matches(texts, {"logging"})
            + _ast_local_or_imported_function_call_matches(texts, {"write_heartbeat"})
            + _ast_logging_call_matches(texts, {"basicConfig", "getLogger"})
            + _line_matches(texts, r"health|metrics|summary\("),
            confidence="medium",
        ),
    )
    _set_if_signal(
        signals,
        _make_structured_signal(
            "webhook_or_polling_model",
            "Найдена модель polling/webhook/deploy",
            _ast_telegram_application_method_matches(texts, {"run_polling", "run_webhook"})
            + _ast_telegram_application_builder_matches(texts)
            + _ast_aiogram_polling_matches(texts)
            + _line_matches(texts, r"webhook|docker|compose|systemd"),
            confidence="high",
        ),
    )

    fingerprints: dict[str, str | None] = {}
    for rel in sorted(texts):
        fingerprints[rel] = file_hash(project / rel)
    for signal in signals.values():
        signal["source_fingerprints"] = {rel: fingerprints.get(rel) for rel in signal.get("paths", [])}
    return {
        "type": "observed_ux_evidence",
        "source": "local_scan",
        "generated_at": now_iso(),
        "signals": signals,
        "scanned_files": sorted(texts),
        "source_fingerprints": fingerprints,
        "secret_safe": True,
        "runtime_probe": False,
    }

def discover_local(project: Path) -> dict[str, Any]:
    desired = load_desired(project)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for node in desired.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        bindings = node.get("bindings") or {}
        binding_items: list[tuple[str, dict[str, Any]]] = []
        for binding_type, binding in [
            ("code", bindings.get("code") or node.get("code_binding")),
            ("test", bindings.get("test") or node.get("test_binding")),
            ("config", bindings.get("config") or node.get("config_binding")),
        ]:
            if isinstance(binding, dict):
                binding_items.append((binding_type, binding))
        for evidence in node.get("evidence", []) or []:
            if isinstance(evidence, dict) and evidence.get("type") in {"code", "test", "config", "file"} and evidence.get("path"):
                binding_items.append((str(evidence.get("type")), evidence))
        for binding_type, binding in binding_items:
            path_value = binding.get("path")
            if not path_value:
                continue
            target = project / str(path_value)
            text = read_text_if_exists(target)
            exists = target.exists()
            symbol = binding.get("symbol")
            symbol_found = symbol_exists(text, str(symbol)) if symbol else None
            status = "confirmed" if exists and (symbol_found is not False) else "candidate"
            observed_id = f"observed.{binding_type}.{node.get('id')}"
            nodes.append(
                {
                    "id": observed_id,
                    "kind": "ObservedBinding",
                    "title": f"Найденная привязка: {node.get('title', node.get('id'))}",
                    "source_node": node.get("id"),
                    "binding_type": binding_type,
                    "path": str(path_value),
                    "symbol": symbol,
                    "exists": exists,
                    "symbol_found": symbol_found,
                    "knowledge_status": status,
                    "confidence": "high" if status == "confirmed" else "medium",
                    "evidence": [
                        {
                            "type": binding_type,
                            "path": str(path_value),
                            "symbol": symbol,
                            "collected_at": now_iso(),
                            "source_fingerprint": {"file_hash": file_hash(target)},
                            "validity": {"status": "current" if exists else "missing", "checked_at": now_iso()},
                        }
                    ],
                }
            )
            edges.append(
                {
                    "from": node.get("id"),
                    "to": observed_id,
                    "type": "observed_as",
                    "title": "Узел сопоставлен с найденной привязкой",
                    "confidence": "high" if status == "confirmed" else "medium",
                    "source": "local_scan",
                }
            )
            findings.append(
                {
                    "node_id": node.get("id"),
                    "binding_type": binding_type,
                    "path": str(path_value),
                    "symbol": symbol,
                    "exists": exists,
                    "symbol_found": symbol_found,
                }
            )

    ux_evidence = discover_ux_evidence(project)
    findings.append(ux_evidence)

    # Generic local inventory, intentionally shallow and secret-safe.
    for rel in ["pyproject.toml", "requirements.txt", "Makefile", "Dockerfile", "compose.yml", "AGENTS.md"]:
        p = project / rel
        if p.exists():
            findings.append({"type": "project_file", "path": rel, "exists": True})
    safe_texts = _collect_safe_project_text(project)
    for rel, text in sorted(safe_texts.items()):
        if not rel.endswith(".py"):
            continue
        src_file = project / rel
        functions = re.findall(r"^\s*(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text, flags=re.M)
        classes = re.findall(r"^\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\b", text, flags=re.M)
        findings.append(
            {
                "type": "python_module",
                "path": rel,
                "functions": functions[:30],
                "classes": classes[:30],
                "file_hash": file_hash(src_file),
            }
        )
    return {
        "apiVersion": "botctl.dev/v0",
        "kind": "ObservedGraph",
        "generated_at": now_iso(),
        "source": {"type": "local_scan", "project_path": str(project)},
        "runtime_probe": {"enabled": False, "reason": "v0 не обращается к production/runtime"},
        "nodes": nodes,
        "edges": edges,
        "findings": findings,
    }
