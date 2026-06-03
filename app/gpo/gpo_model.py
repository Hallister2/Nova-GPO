from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiffStatus(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class GpoSetting:
    key: str
    category: str
    name: str
    value: str
    source_file: str = ""


@dataclass(frozen=True)
class GpoBackup:
    path: str
    name: str
    settings: list[GpoSetting]
    detected_parsers: tuple[str, ...] = ()


@dataclass(frozen=True)
class GpoDiffItem:
    status: DiffStatus
    key: str
    category: str
    name: str
    old_value: str
    new_value: str