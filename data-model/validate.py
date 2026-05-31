#!/usr/bin/env python3
"""
Schema validator for assessment manifests.
Uses Python 3 stdlib only — no jsonschema package required.

Usage:
    python3 validate.py <manifest.json> [--schema <schema.json>]
    python3 validate.py --all <directory>

Returns exit code 0 on success, 1 on validation failure.
"""

import json
import sys
import os
import re
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Minimal JSON Schema validator (subset: type, required, enum, properties,
# items, oneOf, $ref, format, description — enough for our schemas)
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class SchemaValidator:
    def __init__(self, schema: dict, schema_dir: Optional[Path] = None):
        self.root_schema = schema
        self.schema_dir = schema_dir
        self._ref_cache: dict = {}

    def validate(self, instance: Any, schema: Optional[dict] = None, path: str = "$") -> list[ValidationError]:
        if schema is None:
            schema = self.root_schema
        errors = []
        errors.extend(self._validate_node(instance, schema, path))
        return errors

    def _resolve_ref(self, ref: str) -> dict:
        if ref in self._ref_cache:
            return self._ref_cache[ref]
        if ref.startswith("#/definitions/"):
            key = ref.split("/definitions/")[1]
            resolved = self.root_schema.get("definitions", {}).get(key)
            if resolved is None:
                raise ValidationError("$ref", f"Cannot resolve local $ref: {ref}")
            self._ref_cache[ref] = resolved
            return resolved
        raise ValidationError("$ref", f"External $ref not supported: {ref}")

    def _validate_node(self, instance: Any, schema: dict, path: str) -> list[ValidationError]:
        errors = []

        if "$ref" in schema:
            resolved = self._resolve_ref(schema["$ref"])
            errors.extend(self._validate_node(instance, resolved, path))
            return errors

        if "oneOf" in schema:
            match_errors = []
            for i, sub in enumerate(schema["oneOf"]):
                sub_errors = self._validate_node(instance, sub, path)
                if not sub_errors:
                    return []
                match_errors.append(sub_errors)
            errors.append(ValidationError(path, f"Matches none of {len(schema['oneOf'])} oneOf schemas"))
            return errors

        # type check
        if "type" in schema:
            expected = schema["type"]
            if isinstance(expected, list):
                ok = any(self._check_type(instance, t) for t in expected)
            else:
                ok = self._check_type(instance, expected)
            if not ok:
                actual = type(instance).__name__
                errors.append(ValidationError(path, f"Expected type {expected}, got {actual}"))
                return errors  # no point continuing if type is wrong

        # enum
        if "enum" in schema:
            if instance not in schema["enum"]:
                errors.append(ValidationError(path, f"Value {instance!r} not in enum {schema['enum']}"))

        # required + properties
        if "required" in schema and isinstance(instance, dict):
            for key in schema["required"]:
                if key not in instance:
                    errors.append(ValidationError(f"{path}.{key}", "Required field missing"))

        if "properties" in schema and isinstance(instance, dict):
            for key, prop_schema in schema["properties"].items():
                if key in instance:
                    errors.extend(self._validate_node(instance[key], prop_schema, f"{path}.{key}"))

        # array items
        if "items" in schema and isinstance(instance, list):
            for i, item in enumerate(instance):
                errors.extend(self._validate_node(item, schema["items"], f"{path}[{i}]"))

        # format (basic check only)
        if "format" in schema and isinstance(instance, str):
            fmt = schema["format"]
            if fmt == "date-time":
                if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", instance):
                    errors.append(ValidationError(path, f"Value {instance!r} does not match date-time format"))

        return errors

    @staticmethod
    def _check_type(instance: Any, type_name: str) -> bool:
        mapping = {
            "string":  str,
            "integer": int,
            "number":  (int, float),
            "boolean": bool,
            "array":   list,
            "object":  dict,
            "null":    type(None),
        }
        expected_type = mapping.get(type_name)
        if expected_type is None:
            return True  # unknown type, pass
        if type_name == "integer" and isinstance(instance, bool):
            return False  # bool is subclass of int in Python, but not valid JSON integer
        if type_name == "number" and isinstance(instance, bool):
            return False
        return isinstance(instance, expected_type)


# ---------------------------------------------------------------------------
# Schema auto-detection
# ---------------------------------------------------------------------------

SCHEMA_DIR = Path(__file__).parent

SCHEMA_MAP = {
    "1": "observed-state-schema.json",
    "2": "observed-state-schema.json",
    "observed": "observed-state-schema.json",
    "historical": "historical-state-schema.json",
    "recovery": "recovery-state-schema.json",
    "declared": "declared-state-schema.json",
    "configured": "configured-state-schema.json",
    "bootstrap": "bootstrap-state-schema.json",
    "service": "service-state-schema.json",
}

def detect_schema(manifest: dict) -> Optional[Path]:
    """Guess the right schema from manifest content."""
    tier = manifest.get("assessment_tier")
    if tier in (1, 2):
        return SCHEMA_DIR / "observed-state-schema.json"
    if "dependency_graph" in manifest or "readiness_report" in manifest:
        return SCHEMA_DIR / "recovery-state-schema.json"
    if "snapshots" in manifest or "diffs" in manifest:
        return SCHEMA_DIR / "historical-state-schema.json"
    if "tofu_workspaces" in manifest:
        return SCHEMA_DIR / "declared-state-schema.json"
    if "ansible_inventory" in manifest:
        return SCHEMA_DIR / "configured-state-schema.json"
    if "base_images" in manifest and "dns_registry" in manifest:
        return SCHEMA_DIR / "bootstrap-state-schema.json"
    if "backup_assignments" in manifest and "dns_registrations" in manifest:
        return SCHEMA_DIR / "service-state-schema.json"
    return None


def validate_file(manifest_path: Path, schema_path: Optional[Path] = None) -> tuple[bool, list[ValidationError]]:
    with open(manifest_path) as f:
        manifest = json.load(f)

    if schema_path is None:
        schema_path = detect_schema(manifest)
        if schema_path is None:
            return False, [ValidationError("$", "Cannot detect schema type — specify --schema")]

    with open(schema_path) as f:
        schema = json.load(f)

    validator = SchemaValidator(schema, schema_dir=schema_path.parent)
    errors = validator.validate(manifest)
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    schema_path = None
    manifest_paths = []
    all_mode = False

    i = 0
    while i < len(args):
        if args[i] == "--schema" and i + 1 < len(args):
            schema_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--all" and i + 1 < len(args):
            all_mode = True
            search_dir = Path(args[i + 1])
            manifest_paths.extend(search_dir.rglob("manifest.json"))
            i += 2
        else:
            manifest_paths.append(Path(args[i]))
            i += 1

    if not manifest_paths:
        print("No manifest files specified or found.")
        sys.exit(1)

    overall_ok = True
    for mp in manifest_paths:
        ok, errors = validate_file(mp, schema_path)
        if ok:
            print(f"  PASS  {mp}")
        else:
            overall_ok = False
            print(f"  FAIL  {mp}")
            for e in errors:
                print(f"         {e.path}: {e.message}")

    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
