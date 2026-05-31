"""Schema validation utilities."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
_SCHEMA_PATH = _SCHEMAS_DIR / "assessment.schema.json"
_schema: dict | None = None
_resolver: jsonschema.RefResolver | None = None


_BASE_ID = "https://github.com/broodforge/schemas/"


def _load_schema() -> tuple[dict, jsonschema.RefResolver]:
    global _schema, _resolver
    if _schema is None:
        _schema = json.loads(_SCHEMA_PATH.read_text())
        # Build a store keyed three ways so $ref always resolves locally:
        #   1. file:// URI  (used when base_uri is a file URI)
        #   2. bare filename
        #   3. GitHub base URL  (used when the schema's $id is a GitHub URL)
        store: dict = {}
        for schema_file in _SCHEMAS_DIR.glob("*.json"):
            sub = json.loads(schema_file.read_text())
            store[schema_file.as_uri()] = sub
            store[schema_file.name] = sub
            store[_BASE_ID + schema_file.name] = sub
            if "$id" in sub:
                store[sub["$id"]] = sub
        _resolver = jsonschema.RefResolver(
            base_uri=_SCHEMA_PATH.as_uri(),
            referrer=_schema,
            store=store,
        )
    return _schema, _resolver


def validate_assessment(data: dict) -> list[str]:
    """Return a list of validation error messages, empty if valid."""
    schema, resolver = _load_schema()
    validator = jsonschema.Draft7Validator(schema, resolver=resolver)
    return [err.message for err in validator.iter_errors(data)]
