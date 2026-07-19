from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from .model import Issue, load_json

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover
    jsonschema = None


def control_layer_root() -> Path:
    repository_root = Path(__file__).resolve().parents[2]
    if (repository_root / "schemas").is_dir():
        return repository_root
    return Path(sys.prefix) / "share" / "botctl"


def schemas_dir() -> Path:
    return control_layer_root() / "schemas"


def validate_against_schema(data: Any, schema_name: str, source_path: Path) -> list[Issue]:
    schema_path = schemas_dir() / schema_name
    if not schema_path.exists():
        return [Issue("error", "missing_schema_file", f"Не найдена schema {schema_name}", str(schema_path))]
    if jsonschema is None:
        return [Issue("error", "jsonschema_missing", "Python package jsonschema is required for schema validation", str(source_path))]
    try:
        schema = load_json(schema_path)
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:  # type: ignore[attr-defined]
        location = "/".join(str(part) for part in exc.path)
        suffix = f" at {location}" if location else ""
        return [Issue("error", "schema_validation_failed", f"{schema_name}{suffix}: {exc.message}", str(source_path))]
    except Exception as exc:
        return [Issue("error", "schema_validation_error", f"{schema_name}: {exc}", str(source_path))]
    return []
