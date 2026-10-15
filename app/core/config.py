"""Настройки приложения.

Храним только то, что принадлежит интерфейсу. Состояние, которое читает и
пишет сам апстрим (игровой фильтр, режим ipset, флаг автопроверки обновлений),
живёт в файлах сборки — иначе `service.bat` и наш GUI разошлись бы в показаниях.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

from app.core import paths

log = logging.getLogger(__name__)

RunMode = Literal["service", "process"]


@dataclass
class AiSettings:
    """Настройки слоя ИИ-диагностики. Ключи здесь не хранятся — только в DPAPI."""

    provider: str = "none"
    model: str = ""
    sanitize: bool = True


@dataclass
class Settings:
    first_run_done: bool = False
    run_mode: RunMode = "service"
    selected_strategy: str = ""
    # Стратегии, помеченные звёздочкой: они поднимаются в начало списка и
    # попадают в меню трея для быстрого переключения.
    favorites: list[str] = field(default_factory=list)
    # Включать обход сразу при запуске приложения. Нужно в режиме обычного
    # процесса: служба и так стартует вместе с Windows.
    start_bypass_on_launch: bool = False
    autostart_with_windows: bool = False
    start_minimized: bool = False
    minimize_to_tray: bool = True
    check_core_updates: bool = True
    probe_timeout: int = 5
    probe_parallel: int = 8
    ai: AiSettings = field(default_factory=AiSettings)

    @classmethod
    def load(cls) -> Settings:
        path = paths.config_file()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("Не удалось прочитать %s, беру настройки по умолчанию", path)
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        """Собирает настройки, игнорируя незнакомые и отсутствующие ключи."""
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        ai_raw = data.pop("ai", {})
        settings = cls(**data)
        if isinstance(ai_raw, dict):
            ai_known = {f.name for f in fields(AiSettings)}
            settings.ai = AiSettings(**{k: v for k, v in ai_raw.items() if k in ai_known})
        return settings

    def save(self) -> None:
        paths.ensure_dirs()
        path = paths.config_file()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
