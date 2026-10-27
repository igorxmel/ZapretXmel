"""Запуск программы вместе с Windows.

Очевидный способ — ключ `Run` в реестре — здесь не работает, и это не
случайность. Программа собрана с требованием прав администратора: она
создаёт службу и грузит драйвер. Windows не поднимает такие программы из
`Run` при входе в систему — показать запрос UAC посреди загрузки рабочего
стола некому, и запись просто игнорируется. Со стороны выглядит как
«галочка есть, автозапуск не работает».

Поэтому задача в планировщике с флагом «с наивысшими правами»: он для того
и придуман. Старую запись в `Run` убираем — она осталась у тех, кто ставил
галочку раньше, и ничего не делает.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import tempfile
import winreg
from pathlib import Path
from xml.sax.saxutils import escape

from app.core import elevation, paths
from app.core.process import CREATE_NO_WINDOW, child_environment

log = logging.getLogger(__name__)

TASK_NAME = "ZapretXmel"

# Прежний способ: оставлен только затем, чтобы убрать за собой.
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "ZapretXmel"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — фиксированная системная утилита
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=CREATE_NO_WINDOW,
        env=child_environment(),
        check=False,
    )


def enabled() -> bool:
    """Есть ли задача автозапуска."""
    try:
        result = _run(["schtasks", "/query", "/tn", TASK_NAME])
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _command() -> tuple[str, str]:
    """Что запускать и с какими аргументами."""
    if getattr(sys, "frozen", False):
        return str(paths.executable()), ""
    return sys.executable, f'"{Path(sys.argv[0]).resolve()}"'


def _user() -> str:
    """Пользователь в виде домена и имени; пусто, если среда его не отдала."""
    name = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return domain + chr(92) + name if name and domain else name


def task_xml() -> str:
    """Описание задачи.

    Условия питания выключены намеренно, см. описание модуля. Ограничение по
    времени снято: по умолчанию планировщик убивает задачу через три дня.
    """
    command, arguments = _command()
    user = escape(_user())
    who = f"<UserId>{user}</UserId>" if user else ""
    args = f"<Arguments>{escape(arguments)}</Arguments>" if arguments else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      {who}
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      {who}
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      {args}
    </Exec>
  </Actions>
</Task>
"""


def _create() -> subprocess.CompletedProcess:
    # schtasks читает XML только в UTF-16 с меткой порядка байтов.
    handle, name = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(handle, "w", encoding="utf-16") as stream:
            stream.write(task_xml())
        return _run(["schtasks", "/create", "/tn", TASK_NAME, "/xml", name, "/f"])
    finally:
        with contextlib.suppress(OSError):
            os.remove(name)


def needs_repair() -> bool:
    """Задача есть, но создана старым способом и зависит от питания."""
    try:
        result = _run(["schtasks", "/query", "/tn", TASK_NAME, "/xml"])
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    return _stops_on_battery(result.stdout)


def _stops_on_battery(xml: str) -> bool:
    # Теги не локализуются, в отличие от остального вывода schtasks.
    # Если тега нет, действует значение по умолчанию — «true».
    for tag in ("DisallowStartIfOnBatteries", "StopIfGoingOnBatteries"):
        if f"<{tag}>false</{tag}>" not in xml:
            return True
    return False


def repair() -> None:
    """Чинит задачу, созданную прежними версиями. Зовётся при запуске."""
    if elevation.is_admin() and needs_repair() and set_enabled(True):
        log.info("Задача автозапуска пересоздана без привязки к питанию")


def _drop_legacy_run_key() -> None:
    """Убирает запись в `Run`, оставшуюся от прежних версий."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key, contextlib.suppress(FileNotFoundError):
            winreg.DeleteValue(key, _RUN_VALUE)
    except OSError:
        log.debug("Старую запись автозапуска убрать не удалось")


def set_enabled(wanted: bool) -> bool:
    """Создаёт или убирает задачу. False — не получилось."""
    _drop_legacy_run_key()

    try:
        if not wanted:
            result = _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
            # Задачи и так нет — это не ошибка, результат тот же.
            return result.returncode == 0 or not enabled()

        if not elevation.is_admin():
            log.warning("Задачу автозапуска создаёт только администратор")
            return False

        result = _create()
        if result.returncode != 0:
            log.warning("Планировщик отказал: %s", result.stdout.strip() or result.stderr.strip())
            return False

        log.info("Автозапуск: задача %s создана", TASK_NAME)
        return True
    except (OSError, subprocess.SubprocessError):
        log.exception("Не удалось изменить автозапуск")
        return False


def retarget() -> None:
    """Перенацеливает задачу после переезда программы в другую папку."""
    if enabled():
        set_enabled(True)
