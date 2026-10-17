"""Доступ к релизам на GitHub.

Версии сравниваются собственным разбором, потому что Flowseal использует
нестандартную схему вроде `1.9.9d` и `1.9.7b` — буквенный суффикс обозначает
правку поверх номерной версии.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class DownloadError(Exception):
    """Скачанный файл не тот, которого мы ждали."""

CORE_REPO = "Flowseal/zapret-discord-youtube"
TG_PROXY_REPO = "Flowseal/tg-ws-proxy"

API_ROOT = "https://api.github.com"
USER_AGENT = "ZapretXmel"
_VERSION_RE = re.compile(
    r"(\d+(?:\.\d+)*)([a-z]*)(?:-([0-9a-z.]+))?",
    re.IGNORECASE,
)

# Ранг обычного релиза и пре-релиза. Разделять их обязательно: по semver
# `1.1.0-rc.1` **младше** `1.1.0`, а буквенный суффикс апстрима (`1.9.9d`) —
# наоборот, правка поверх номерной версии и потому старше.
_RELEASE = 1
_PRERELEASE = 0


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    # SHA-256, посчитанный самим GitHub. Пусто, если он его не отдал.
    digest: str = ""


@dataclass(frozen=True)
class Release:
    tag: str
    name: str
    body: str
    published_at: str
    # Тестовая сборка. GitHub помечает такие сам и не отдаёт их в
    # `/releases/latest` — поэтому обычный пользователь их не видит.
    prerelease: bool = False
    # Черновик: виден только владельцу репозитория и ставиться не должен.
    draft: bool = False
    assets: list[Asset] = field(default_factory=list)

    @property
    def version(self) -> str:
        return self.tag.lstrip("vV")

    @property
    def published_date(self) -> str:
        try:
            return datetime.fromisoformat(self.published_at.replace("Z", "+00:00")).strftime(
                "%d.%m.%Y"
            )
        except ValueError:
            return self.published_at

    def zip_asset(self) -> Asset | None:
        """Основной архив сборки — самый крупный .zip релиза."""
        zips = [asset for asset in self.assets if asset.name.lower().endswith(".zip")]
        return max(zips, key=lambda a: a.size) if zips else None


def parse_version(value: str) -> tuple:
    """Разбирает версию в вид, пригодный для сравнения.

    Суффиксов два вида, и означают они противоположное:

    - буквенный сразу после номера — правка апстрима поверх версии,
      `1.9.9d` **новее** `1.9.9`;
    - через дефис — пре-релиз по semver, `1.1.0-rc.1` **старее** `1.1.0`.

    Второе важно для тестовых сборок: без этого программа считала бы
    `1.1.0-rc.1` и `1.1.0` одной версией, и человек, поставивший тестовую,
    никогда не получил бы обычную.
    """
    match = _VERSION_RE.search(value or "")
    if not match:
        return (), _RELEASE, ""

    numbers = tuple(int(part) for part in match.group(1).split("."))
    letters = (match.group(2) or "").lower()
    pre = (match.group(3) or "").lower()

    if not pre:
        return numbers, _RELEASE, letters

    # `rc.1` -> ('rc', 1): сначала по названию, потом по номеру сборки.
    parts = tuple(int(part) if part.isdigit() else part for part in pre.split("."))
    return numbers, _PRERELEASE, parts


def is_newer(candidate: str, installed: str) -> bool:
    """True, если `candidate` новее установленной версии."""
    if not installed:
        return True
    left, right = parse_version(candidate), parse_version(installed)
    if not left[0]:
        return False
    return left > right


def latest_release(repo: str = CORE_REPO, timeout: int = 20, testing: bool = False) -> Release:
    """Последний релиз. `testing` — считать и тестовые сборки тоже.

    Обычный путь — `/releases/latest`, и это не просто «первый из списка»:
    GitHub отдаёт там последний **не**тестовый и неподготовительный релиз.
    Поэтому пометка pre-release сама по себе прячет сборку от всех, кто не
    просил тестовые.
    """
    if not testing:
        response = requests.get(
            f"{API_ROOT}/repos/{repo}/releases/latest",
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return _to_release(response.json())

    # В списке релизы идут от новых к старым, но «новее» здесь определяем
    # сами: даты публикации недостаточно — релиз могли выпустить задним
    # числом или поправить описание старого.
    releases = [item for item in list_releases(repo, timeout=timeout) if not item.draft]
    if not releases:
        raise LookupError(f"у {repo} нет ни одного релиза")

    return max(releases, key=lambda item: parse_version(item.version))


def list_releases(repo: str = CORE_REPO, limit: int = 10, timeout: int = 20) -> list[Release]:
    response = requests.get(
        f"{API_ROOT}/repos/{repo}/releases",
        params={"per_page": limit},
        timeout=timeout,
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return [_to_release(item) for item in response.json()]


def _to_release(data: dict) -> Release:
    return Release(
        tag=data.get("tag_name", ""),
        name=data.get("name", ""),
        body=data.get("body", ""),
        published_at=data.get("published_at", ""),
        prerelease=bool(data.get("prerelease", False)),
        draft=bool(data.get("draft", False)),
        assets=[
            Asset(
                name=item.get("name", ""),
                url=item.get("browser_download_url", ""),
                size=int(item.get("size", 0)),
                # Приходит в виде «sha256:abc…» — держим только само значение.
                digest=str(item.get("digest", "")).removeprefix("sha256:"),
            )
            for item in data.get("assets", [])
        ],
    )


def fetch_text(asset: Asset, timeout: int = 20) -> str:
    """Читает маленький файл релиза целиком — например, файл с хешем."""
    response = requests.get(asset.url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.text


def download(
    asset: Asset,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
    timeout: int = 60,
) -> str:
    """Скачивает файл и возвращает его SHA-256.

    Загрузка идёт во временный файл и переименовывается только после успеха,
    чтобы прерванная закачка не осталась под видом готового архива.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    downloaded = 0

    with requests.get(
        asset.url, stream=True, timeout=timeout, headers={"User-Agent": USER_AGENT}
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", asset.size or 0))

        with partial.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)

    actual = digest.hexdigest()

    # Хеш считает сам GitHub, и сверить скачанное с ним дешевле всего здесь:
    # через эту функцию проходят и ядро, и прокси, и сама программа, а любой
    # из этих файлов мы потом запускаем с правами администратора.
    if asset.digest and actual.lower() != asset.digest.lower():
        partial.unlink(missing_ok=True)
        raise DownloadError(
            f"{asset.name}: скачанный файл не совпал с хешем из релиза — "
            "загрузка оборвалась или файл подменили по дороге"
        )

    partial.replace(destination)
    log.info("Скачано %s (%d байт)", destination.name, downloaded)
    return actual


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
