from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

API_VERSION = "botctl.dev/v0"
CONTROL_DIR = ".botctl"

NODE_KINDS = {
    "Product",
    "Capability",
    "Flow",
    "Event",
    "State",
    "Handler",
    "Tool",
    "MemoryStore",
    "ConfigRef",
    "DeployTarget",
    "Test",
    "TraceSink",
    "Policy",
}

RELATION_TYPES = {
    "contains",
    "enables",
    "implements",
    "handles",
    "transitions_to",
    "uses",
    "stores_in",
    "reads_from",
    "requires",
    "deployed_to",
    "verified_by",
    "traced_by",
    "guards",
}

LIFECYCLE_STATUSES = {"planned", "active", "deprecated", "removed", "experimental"}
KNOWLEDGE_STATUSES = {"inferred", "candidate", "confirmed", "rejected", "stale", "unknown"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
APPROVAL_LEVELS = {"none", "agent_self_check", "human_review", "human_approval", "blocked"}
CHANGE_STATUSES = {
    "draft",
    "ready_for_review",
    "approved",
    "applying",
    "applied",
    "verified",
    "failed",
    "rolled_back",
    "cancelled",
    "blocked",
}

RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
APPROVAL_ORDER = {"none": 0, "agent_self_check": 1, "human_review": 2, "human_approval": 3, "blocked": 4}
RISK_MIN_APPROVAL = {
    "low": "none",
    "medium": "human_review",
    "high": "human_approval",
    "critical": "human_approval",
}

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
class Issue:
    level: str
    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"level": self.level, "code": self.code, "message": self.message}
        if self.path:
            data["path"] = self.path
        return data


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise RuntimeError("PyYAML is required for YAML files")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if data is not None else {}


def dump_yaml(path: Path, data: Any) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required for YAML files")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def project_control(project: Path) -> Path:
    return project / CONTROL_DIR


def relative(project: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project))
    except ValueError:
        return str(path)


def looks_like_raw_id(title: str) -> bool:
    stripped = title.strip()
    if not stripped:
        return True
    if re.fullmatch(r"[a-z0-9_.:-]+", stripped):
        return True
    return False


def contains_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text or ""))


def read_text_if_exists(path: Path, limit: int = 300_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[:limit]


def file_hash(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def symbol_exists(text: str, symbol: str) -> bool:
    if not symbol:
        return False
    escaped = re.escape(symbol)
    patterns = [
        rf"^\s*def\s+{escaped}\s*\(",
        rf"^\s*async\s+def\s+{escaped}\s*\(",
        rf"^\s*class\s+{escaped}\b",
        rf"\b{escaped}\b",
    ]
    return any(re.search(p, text, flags=re.M) for p in patterns)


def list_change_plans(project: Path) -> list[Path]:
    folder = project_control(project) / "change_plans"
    if not folder.exists():
        return []
    return sorted(folder.glob("*.yaml"))
