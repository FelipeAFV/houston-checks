"""Check options parsing — checks_options.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.util import load_yaml_file

@dataclass
class JobOption:
    name: str
    description: str = ""
    required: bool = False
    default: str = ""

@dataclass
class ChecksOptions:
    """Parsed checks_options.yaml."""

    checks_options: dict[str, list[JobOption]] = field(default_factory=dict)

    @classmethod
    def load(cls, checks_options_path: str) -> ChecksOptions:
        data = load_yaml_file(checks_options_path)
        raw = data if isinstance(data, dict) else {}
        return cls(checks_options=raw)


    def get(self, check_id: str) -> list[JobOption]:
        return self.checks_options.get(check_id, [])
