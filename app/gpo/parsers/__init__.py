from __future__ import annotations

from pathlib import Path

from app.gpo.gpo_model import GpoSetting
from app.gpo.parsers.base_parser import BaseGpoParser
from app.gpo.parsers.registry_parser import RegistryPolicyParser
from app.gpo.parsers.security_parser import SecuritySettingsParser

_PARSERS: list[BaseGpoParser] = [
    RegistryPolicyParser(),
    SecuritySettingsParser(),
]


def detect_parsers(backup_root: Path) -> tuple[str, ...]:
    """Return the names of all parsers whose content is present in the backup."""
    return tuple(
        parser.parser_name
        for parser in _PARSERS
        if parser.can_parse(backup_root)
    )


def run_parsers(backup_root: Path, resolve_sids: bool = False) -> list[GpoSetting]:
    """Parse *backup_root* with all applicable parsers and return combined settings."""
    parsers: list[BaseGpoParser] = [
        RegistryPolicyParser(resolve_sids=resolve_sids),
        SecuritySettingsParser(resolve_sids=resolve_sids),
    ]
    items: list[GpoSetting] = []
    for parser in parsers:
        if parser.can_parse(backup_root):
            items.extend(parser.parse(backup_root))
    return items
