"""Запускается ли стратегия вообще — без перехвата трафика.

winws с ключом `--wf-save` разбирает все аргументы, строит фильтр, сохраняет его в
файл и выходит, ничего не перехватывая. Если в аргументах ошибка, он падает с той
же причиной, что и при настоящем запуске. Так нашлась бы, например, стратегия
«general (FAKE TLS AUTO)»: из-за `^!`, переданного дословно, winws не находил
файла и выходил, а программа месяцами показывала её как обычную, и подбор
молча ставил её последней.

Проверка дешёвая, но не бесплатная — по процессу winws на стратегию, — поэтому
результат хранится в `data` и пересчитывается, только когда меняются аргументы
стратегии или сам winws (новая версия ядра).
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core import elevation, lists, paths
from app.core.batfile import StrategySpec

log = logging.getLogger(__name__)

FILENAME = "strategy-check.json"
CREATE_NO_WINDOW = 0x08000000
TIMEOUT = 15

# Первой строкой winws пишет свою версию — к причине она отношения не имеет.
_BANNER = "github version"


def _file() -> Path:
    return paths.data_dir() / FILENAME


def _key(spec: StrategySpec, exe: Path) -> str:
    """Отпечаток: аргументы стратегии и сам winws. Сменился любой — проверяем заново."""
    try:
        stat = exe.stat()
        binary = f"{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        binary = "-"
    digest = hashlib.sha256("\0".join([binary, *spec.argv]).encode("utf-8"))
    return digest.hexdigest()[:16]


def _reason(output: str, code: int) -> str:
    """Последняя содержательная строка вывода winws — обычно это и есть причина."""
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not line.strip().lower().startswith(_BANNER)
    ]
    return lines[-1] if lines else f"winws завершился с кодом {code}"


def check(spec: StrategySpec, exe: Path | None = None) -> str:
    """Пусто — стратегия запускается. Иначе — почему нет, словами winws."""
    exe = exe or paths.winws_exe()
    with tempfile.TemporaryDirectory(prefix="zx-check-") as folder:
        saved = Path(folder) / "filter.txt"
        try:
            done = subprocess.run(  # noqa: S603 — winws из нашей сборки ядра
                [str(exe), *spec.argv, f"--wf-save={saved}"],
                cwd=str(exe.parent.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT,
                creationflags=CREATE_NO_WINDOW,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"winws не ответил за {TIMEOUT} с"
        except OSError as error:
            return f"winws не запустился: {error}"

        if done.returncode == 0 and saved.exists():
            return ""
        return _reason(done.stdout + "\n" + done.stderr, done.returncode)


def _load() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict[str, str]]) -> None:
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        _file().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.warning("Не удалось сохранить результат проверки стратегий", exc_info=True)


def known_broken() -> dict[str, str]:
    """Что уже известно: стратегия → причина. Без проверки — только из файла."""
    return {
        name: entry.get("error", "")
        for name, entry in _load().items()
        if isinstance(entry, dict) and entry.get("error")
    }


def check_all(specs: list[StrategySpec], exe: Path | None = None) -> dict[str, str]:
    """Проверяет то, что изменилось с прошлого раза. Итог — стратегия → причина.

    Без прав администратора winws не запустится вовсе, и любая стратегия выглядела
    бы сломанной; тогда проверки нет, а прошлый результат остаётся как есть.
    """
    exe = exe or paths.winws_exe()
    if not exe.exists() or not elevation.is_admin():
        return known_broken()

    # Стратегии ссылаются на пользовательские списки; без них winws падает сразу.
    lists.ensure_user_lists()

    stored = _load()
    keys = {spec.name: _key(spec, exe) for spec in specs}
    stale = [spec for spec in specs if stored.get(spec.name, {}).get("key") != keys[spec.name]]

    if stale:
        with ThreadPoolExecutor(max_workers=4) as pool:
            reasons = list(pool.map(lambda spec: check(spec, exe), stale))
        for spec, reason in zip(stale, reasons, strict=True):
            stored[spec.name] = {"key": keys[spec.name], "error": reason}
            if reason:
                log.warning("Стратегия «%s» не запускается: %s", spec.name, reason)
        log.info("Проверено стратегий без запуска: %d", len(stale))

    # Удалённые стратегии из файла убираем: иначе он копил бы их вечно.
    current = {name: stored[name] for name in keys if name in stored}
    if current != stored or stale:
        _save(current)
    return {name: entry["error"] for name, entry in current.items() if entry.get("error")}
