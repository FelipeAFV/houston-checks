"""Job execution context — config, catalog, inventory loaded once."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.check_registry import build_check_registry
from src.configs.config import Config
from src.inventory.catalog import ChecksCatalog
from src.inventory.membership import HostIndexes
from src.utils.util import load_yaml_file


@dataclass
class ProvisionContext:
    """Shared state for one houston-provision run."""

    cfg: Config
    checks: ChecksCatalog
    static_inv: dict[str, Any]
    static_indexes: HostIndexes
    effective_inv: dict[str, Any] | None = None
    effective_indexes: HostIndexes | None = None
    checks_meta: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, cfg: Config) -> ProvisionContext:
        data = load_yaml_file(cfg.inventory_path)
        static_inv = data if isinstance(data, dict) else {}
        checks = ChecksCatalog.load(cfg.checks_path)
        return cls(
            cfg=cfg,
            checks=checks,
            static_inv=static_inv,
            static_indexes=HostIndexes.build(static_inv),
        )

    def set_effective_inventory(self, inv: dict[str, Any]) -> None:
        self.effective_inv = inv
        self.effective_indexes = HostIndexes.build(inv)

    def ensure_checks_meta(self) -> dict[str, dict[str, Any]]:
        if not self.checks_meta:
            self.checks_meta = build_check_registry(self.checks, self.cfg.scm_base_dir)
        return self.checks_meta

    @property
    def inv(self) -> dict[str, Any]:
        return self.effective_inv if self.effective_inv is not None else self.static_inv

    @property
    def indexes(self) -> HostIndexes:
        if self.effective_indexes is not None:
            return self.effective_indexes
        return self.static_indexes
