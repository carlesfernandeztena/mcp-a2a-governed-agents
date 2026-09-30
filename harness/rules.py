"""Loads rules.yaml once. Every rule parameter comes from there, never hardcoded."""
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@cache
def rules() -> dict:
    return yaml.safe_load((ROOT / "rules.yaml").read_text())
