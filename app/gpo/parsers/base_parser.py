from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.gpo.gpo_model import GpoSetting


class BaseGpoParser(ABC):
    parser_name = "Base Parser"
    parser_type = "generic"

    @abstractmethod
    def can_parse(self, backup_root: Path) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self, backup_root: Path) -> list[GpoSetting]:
        raise NotImplementedError
