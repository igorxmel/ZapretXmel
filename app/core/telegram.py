"""Telegram через локальный MTProto-прокси.

Telegram Desktop не ходит по TLS с SNI, поэтому обычные стратегии zapret его не
чинят — отсюда и впечатление, будто «запрет так не умеет». Лечится отдельным
сайдкаром [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) от тех же
авторов: он поднимает локальный MTProto-прокси, читает номер дата-центра из
обфусцированного init-пакета и гонит трафик до нужного ДЦ через WebSocket
поверх TLS.

Программу не форкаем и не вкладываем внутрь — скачиваем официальный релиз и
держим его в портативном режиме рядом с собой. Благодаря этому собственная
установка tg-ws-proxy у пользователя, если она есть, остаётся нетронутой:
портативный режим включается папкой `TgWsProxy_data` рядом с исполняемым файлом
и уводит настройки туда из `%APPDATA%`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import psutil

from app.core import paths, processes
from app.core import process as managed
from app.core.process import ManagedProcess
from app.core.updater import github

log = logging.getLogger(__name__)

REPO = github.TG_PROXY_REPO
EXECUTABLE = "TgWsProxy_windows.exe"
PORTABLE_DIR = "TgWsProxy_data"
CONFIG_NAME = "config.json"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1443
SECRET_BYTES = 16


class TelegramError(Exception):
    """Прокси не установлен или его не удалось запустить."""


@dataclass(frozen=True)
class ProxyState:
    installed: bool
    running: bool
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    secret: str = ""

    @property
    def link(self) -> str:
        """Ссылка `tg://`, по которой Telegram сам пропишет прокси в настройках."""
        if not self.secret:
            return ""
        query = urlencode({"server": self.host, "port": self.port, "secret": self.secret})
        return f"tg://proxy?{query}"

    @property
    def label(self) -> str:
        if not self.installed:
            return "не установлен"
        return "работает" if self.running else "остановлен"


def home() -> Path:
    return paths.install_root() / "tgproxy"


def executable() -> Path:
    return home() / EXECUTABLE


def data_dir() -> Path:
    """Папка портативного режима: её наличие уводит настройки из %APPDATA%."""
    return home() / PORTABLE_DIR


def config_file() -> Path:
    return data_dir() / CONFIG_NAME


def is_installed() -> bool:
    return executable().exists()


def generate_secret() -> str:
    """Секрет MTProto — 16 случайных байт в шестнадцатеричном виде."""
    return secrets.token_bytes(SECRET_BYTES).hex()


def read_config() -> dict:
    path = config_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Не удалось прочитать %s", path)
        return {}
    return data if isinstance(data, dict) else {}


def write_config(values: dict) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    config_file().write_text(
        json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def ensure_config(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> dict:
    """Готовит конфигурацию прокси, сохраняя уже выбранный секрет.

    Секрет прописан в настройках Telegram у пользователя, поэтому перегенерировать
    его при каждом запуске нельзя — иначе связь отвалится после перезапуска.
    """
    config = read_config()
    config.setdefault("secret", generate_secret())
    config["host"] = host
    config["port"] = port
    # Обновлениями занимаемся мы, второй проверяющий тут лишний.
    config["check_updates"] = False
    write_config(config)
    return config


def port_is_free(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Проверяет, не занят ли порт — чаще всего это уже запущенный экземпляр."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.3)
        return probe.connect_ex((host, port)) != 0
    finally:
        probe.close()


def version_file() -> Path:
    """Версия установленного прокси.

    Храним рядом с ним самим, а не в настройках: папка переезжает вместе с
    программой, и версия должна ехать за своим файлом. Сам tg-ws-proxy
    номер версии нигде не оставляет.
    """
    return home() / "version.txt"


def installed_version() -> str:
    try:
        return version_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def has_clients(port: int = DEFAULT_PORT) -> bool:
    """Подключился ли к прокси хоть кто-нибудь.

    Прямо спросить Telegram, прописан ли у него прокси, нельзя: настройки он
    держит в своём формате, и лезть туда мы не станем. Зато видно обратное —
    установленное соединение с нашим портом. Если оно есть, значит клиент
    прокси нашёл и пользуется им; если нет — человек, скорее всего, не нажал
    «Открыть в Telegram».
    """
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, OSError):
        log.debug("Список соединений недоступен")
        return False

    return any(
        connection.status == "ESTABLISHED"
        and connection.laddr
        and connection.laddr.port == port
        for connection in connections
    )


def running_instances() -> list[int]:
    """Номера запущенных процессов прокси — по пути к нашему файлу.

    Спрашивать свой объект процесса недостаточно: tg-ws-proxy при запуске
    отпускает родительский процесс, наш дескриптор тут же становится
    мёртвым, и каждое нажатие поднимало ещё один экземпляр. В трее
    копились их значки, а порт занимал самый первый.
    """
    ours = executable()
    # Сначала по имени — это дёшево; путь спрашиваем только у совпавших.
    return [
        pid
        for pid in processes.pids_named(EXECUTABLE)
        if (path := processes.executable(pid)) and Path(path) == ours
    ]


def is_running_anywhere() -> bool:
    return bool(running_instances())


def kill_running(timeout: float = 5.0) -> int:
    """Снимает запущенные экземпляры прокси. Возвращает число снятых.

    Нужно перед заменой файла: Windows не даёт перезаписать работающий
    `.exe`, и обновление падало с «отказано в доступе» на переименовании
    скачанного `.part` — двадцать мегабайт скачивались впустую.

    Ищем по пути, а не по имени: чужую установку tg-ws-proxy, живущую
    где-то ещё, мы не трогаем.
    """
    victims: list[psutil.Process] = []
    for pid in running_instances():
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            victims.append(psutil.Process(pid))

    # Сначала по-хорошему: прокси держит свой значок в трее Windows и
    # убирает его сам при закрытии. Убитый насмерть, он оставляет фантом.
    for victim in victims:
        managed.ask_to_close(victim.pid)
    if victims:
        _, still_here = psutil.wait_procs(victims, timeout=managed.CLOSE_TIMEOUT)
        victims = still_here

    for process in victims:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    _, alive = psutil.wait_procs(victims, timeout=timeout)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return len(victims)


def latest_release(timeout: int = 20) -> github.Release:
    return github.latest_release(REPO, timeout=timeout)


def install(release: github.Release | None = None, progress=None, on_bytes=None) -> str:
    """Скачивает официальный релиз прокси рядом с приложением.

    `on_bytes` получает пару «скачано, всего»: файл весит два десятка
    мегабайт, и без счётчика установка выглядит зависшей.
    """
    release = release or latest_release()
    asset = next((a for a in release.assets if a.name == EXECUTABLE), None)
    if asset is None:
        raise TelegramError(f"в релизе {release.tag} нет файла {EXECUTABLE}")

    home().mkdir(parents=True, exist_ok=True)

    # Работающий прокси держит свой файл, и переименование скачанного на
    # его место падает с «отказано в доступе». Снимаем до загрузки, а не
    # после: иначе двадцать мегабайт качаются впустую.
    if kill_running():
        log.info("Прокси остановлен на время обновления")

    if progress:
        progress(f"Скачиваю {asset.name} ({asset.size // 1048576} МБ)…")

    try:
        github.download(asset, executable(), progress=on_bytes)
    except Exception as error:
        # Файл лежит на GitHub, а его у части провайдеров и режут — о чём
        # стоит сказать прямо, иначе человек будет искать причину в программе.
        raise TelegramError(
            f"не удалось скачать прокси: {error}. "
            "Если обход сейчас выключен, включите его и попробуйте снова — "
            "файл качается с GitHub, а он доступен не у всех провайдеров."
        ) from error
    ensure_config()
    try:
        version_file().write_text(release.version, encoding="utf-8")
    except OSError:
        log.warning("Не удалось запомнить версию прокси")

    log.info("tg-ws-proxy %s установлен", release.version)
    return release.version


class TelegramProxy:
    """Управляемый экземпляр tg-ws-proxy."""

    def __init__(self):
        # Вывод прокси не перехватываем. Раньше он шёл к нам по каналу, и
        # прокси жил на поводке у программы: стоило ей подвиснуть и перестать
        # читать канал, как тот переполнялся, прокси замирал на записи
        # очередной строки — и Telegram вставал вместе с ним. Читать там
        # нечего: прокси сам пишет журнал в `TgWsProxy_data/proxy.log`, а у
        # нас его строки только засоряли вывод winws.
        self._process = ManagedProcess(capture=False)

    def is_running(self) -> bool:
        return self._process.is_alive()

    def start(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ProxyState:
        if not is_installed():
            raise TelegramError("прокси не установлен")
        if self.is_running():
            return self.state()

        config = ensure_config(host, port)
        # Флаг портативного режима передаём явно: папку рядом с exe прокси
        # создаёт сам, но полагаться на её наличие до первого запуска нельзя.
        self._process.start([str(executable()), "--portable"], cwd=home())
        log.info("tg-ws-proxy запущен на %s:%s", host, port)
        return ProxyState(
            installed=True,
            running=True,
            host=config.get("host", host),
            port=int(config.get("port", port)),
            secret=config.get("secret", ""),
        )

    def stop(self) -> None:
        """Гасит прокси, давая ему убрать за собой значок в трее."""
        # Своего дескриптора мало: собранный одним файлом tg-ws-proxy
        # запускает второй процесс, и значок принадлежит ему, а не тому,
        # кого вернул Popen. Поэтому сперва просим закрыться всё, что
        # нашлось по нашему пути, и только потом отпускаем Job Object.
        kill_running()
        self._process.stop()

    def state(self) -> ProxyState:
        config = read_config()
        return ProxyState(
            installed=is_installed(),
            running=self.is_running(),
            host=config.get("host", DEFAULT_HOST),
            port=int(config.get("port", DEFAULT_PORT)),
            secret=config.get("secret", ""),
        )
