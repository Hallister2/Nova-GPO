from __future__ import annotations

from pathlib import Path

from app.gpo.gpo_model import GpoSetting
from app.gpo.parsers.base_parser import BaseGpoParser
from app.gpo.registry_pol import load_registry_pol


class RegistryPolicyParser(BaseGpoParser):
    parser_name = "Registry Policy Parser"
    parser_type = "registry"

    def __init__(self, resolve_sids: bool = False) -> None:
        self._resolve_sids = resolve_sids

    def can_parse(self, backup_root: Path) -> bool:
        return any(backup_root.rglob("Registry.pol"))

    def parse(self, backup_root: Path) -> list[GpoSetting]:
        items: list[GpoSetting] = []
        for path in backup_root.rglob("Registry.pol"):
            items.extend(load_registry_pol(path, backup_root, resolve_sids=self._resolve_sids))
        return items
