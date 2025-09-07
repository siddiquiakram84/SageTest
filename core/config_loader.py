# core/config_loader.py
"""
Config loader & validator for SageTest testcases.

Usage:
    from core.config_loader import load_config
    cfg = load_config(Path("aut/config/testcase.json"))
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any
from jsonschema import validate, ValidationError

# Basic schema (keep in sync with runner/conftest expectations)
CONFIG_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "suite_name", "env", "groups"],
    "properties": {
        "schema_version": {"type": "string"},
        "suite_name": {"type": "string"},
        "env": {"type": "object"},
        "execution": {"type": "object"},
        "filters": {"type": "object"},
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "tests"],
                "properties": {
                    "name": {"type": "string"},
                    "tests": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "run"],
                            "properties": {
                                "id": {"type": "string"},
                                "run": {"type": "boolean"},
                                "tags": {"type": "array"},
                                "priority": {"type": "string"}
                            }
                        }
                    }
                }
            }
        },
        "artifacts": {"type": "object"},
        "hooks": {"type": "object"}
    }
}

def load_config(path: Path) -> Dict[str, Any]:
    """
    Load and validate testcase.json. Raises:
      - FileNotFoundError if path missing
      - ValueError if JSON invalid or schema validation fails
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as e:
        raise ValueError(f"Failed to parse JSON: {e}")

    try:
        validate(instance=data, schema=CONFIG_SCHEMA)
    except ValidationError as e:
        raise ValueError(f"Config schema validation failed: {e.message}")

    return data
