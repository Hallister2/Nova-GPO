from __future__ import annotations

from pathlib import Path

from app.gpo.gpo_model import GpoSetting
from app.gpo.parsers.base_parser import BaseGpoParser
from app.gpo.security_template import load_security_template


class SecuritySettingsParser(BaseGpoParser):
    parser_name = "Security Settings Parser"
    parser_type = "security"

    def __init__(self, resolve_sids: bool = False) -> None:
        self._resolve_sids = resolve_sids

    def can_parse(self, backup_root: Path) -> bool:
        return any(backup_root.rglob("GptTmpl.inf"))

    def parse(self, backup_root: Path) -> list[GpoSetting]:
        items: list[GpoSetting] = []
        for path in backup_root.rglob("GptTmpl.inf"):
            items.extend(load_security_template(path, backup_root, resolve_sids=self._resolve_sids))
        return items
