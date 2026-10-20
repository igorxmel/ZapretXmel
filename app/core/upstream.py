"""Слежение за тем, что меняется в апстриме.

Приложение устроено так, чтобы обычное обновление Flowseal подхватывалось без
правок кода: стратегии, списки, фейки и цели читаются с диска. Но часть
изменений кодом не покрывается — например, в `service.bat` появился пункт меню,
которого нет у нас, или в стратегиях возник флаг winws, о котором мы не знали.
Такие вещи легко не заметить: ничего не ломается, просто новая возможность
проходит мимо.

Поэтому здесь снимается **отпечаток** сборки: состав файлов, набор стратегий,
флагов, меток и целей. Отпечаток сравнивается с сохранённым, и расхождения
раскладываются по трём корзинам — что подхватится само, что требует внимания
и что ломает наши допущения.

Отдельно отслеживаются чужие оболочки над zapret: их релизы читаются ради
идей и найденных ими обходных путей, отпечаток по ним не строится.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from app.core import coreinfo, paths, strategies
from app.core.batfile import BatParseError, parse_bat, read_bat

log = logging.getLogger(__name__)

SNAPSHOT_NAME = "snapshot.json"
SOURCES_NAME = "sources.json"

# Метки и пункты меню берутся из service.bat — это «пульт управления» сборки,
# и новый пункт в нём означает новую возможность, которой у нас нет.
_LABEL_RE = re.compile(r"^:([a-zA-Z_][\w]*)", re.MULTILINE)
_MENU_RE = re.compile(r"^\s*echo\s+\d+\.\s+(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
_TARGET_KEY_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*=\s*"', re.MULTILINE)

DEFAULT_SOURCES = {
    "core": "Flowseal/zapret-discord-youtube",
    "sidecars": ["Flowseal/tg-ws-proxy"],
    # Движки, на которых стоит сборка. Своей сборки под zapret2 у Flowseal
    # пока нет, и подхватить его нам неоткуда — но узнать о переходе хочется
    # в день, когда он случится, а не через месяц из чужого телеграма.
    "engines": ["bol-van/zapret", "bol-van/zapret2"],
    "guis": [
        "medvedeff-true/Zapret-GUI",
        "larrriiin/zapret-ui",
        "maenotreal/zapret-gui",
        "m0xvi/zapret-gui",
        "Taxousq/Zapret-GUI",
        "gaboter/SimpleZapretGUI",
        "Noktomezo/ZapretInteractive",
    ],
}


@dataclass
class Fingerprint:
    """Слепок сборки, с которой наш интерфейс заведомо согласован."""

    version: str = ""
    checked_at: str = ""
    files: dict[str, str] = field(default_factory=dict)
    strategies: list[str] = field(default_factory=list)
    winws_flags: list[str] = field(default_factory=list)
    service_labels: list[str] = field(default_factory=list)
    service_menu: list[str] = field(default_factory=list)
    lists: list[str] = field(default_factory=list)
    fakes: list[str] = field(default_factory=list)
    target_keys: list[str] = field(default_factory=list)
    seen_releases: dict[str, str] = field(default_factory=dict)


def upstream_dir() -> Path:
    return paths.upstream_dir()


def snapshot_file() -> Path:
    return upstream_dir() / SNAPSHOT_NAME


def sources_file() -> Path:
    return upstream_dir() / SOURCES_NAME


def load_sources() -> dict:
    """Список отслеживаемых репозиториев. Его можно дополнять не трогая код."""
    path = sources_file()
    if not path.exists():
        return dict(DEFAULT_SOURCES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Не удалось прочитать %s, беру список по умолчанию", path)
        return dict(DEFAULT_SOURCES)
    return {**DEFAULT_SOURCES, **data}


def save_sources(sources: dict) -> Path:
    upstream_dir().mkdir(parents=True, exist_ok=True)
    path = sources_file()
    path.write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_flags(root: Path) -> list[str]:
    """Все флаги winws, встречающиеся в стратегиях сборки.

    Нужны именно имена: появление незнакомого флага означает, что апстрим
    научился чему-то новому, и это стоит хотя бы прочитать.
    """
    found: set[str] = set()
    for path in strategies.discover(root):
        try:
            spec = parse_bat(path, root=root)
        except (BatParseError, OSError):
            continue
        for arg in spec.argv:
            if arg.startswith("--"):
                found.add(arg.split("=", 1)[0])
    return sorted(found)


def is_user_file(name: str) -> bool:
    """Файл заведён пользователем или нами, а не апстримом.

    Такие файлы (`list-general-user.txt` и прочие из `lists.USER_LISTS`)
    создаются при установке и живут только на машине. В отпечатке им не
    место: снимок снимается с работающей установки, а сверяется со свежим
    релизом, где их нет и быть не может, — и каждая сверка объявляла бы
    пропажу этих файлов ломающим изменением.
    """
    return name.endswith("-user.txt")


def build(root: Path) -> Fingerprint:
    """Снимает отпечаток с распакованной сборки."""
    service_bat = root / "service.bat"
    service_text = read_bat(service_bat) if service_bat.exists() else ""

    targets = root / "utils" / "targets.txt"
    targets_text = targets.read_text(encoding="utf-8", errors="replace") if targets.exists() else ""

    files = {
        str(path.relative_to(root)).replace("\\", "/"): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not is_user_file(path.name)
    }

    return Fingerprint(
        version=coreinfo.read_version(root),
        checked_at=datetime.now().isoformat(timespec="seconds"),
        files=files,
        strategies=[path.name for path in strategies.discover(root)],
        winws_flags=collect_flags(root),
        service_labels=sorted(set(_LABEL_RE.findall(service_text))),
        service_menu=sorted({item.strip() for item in _MENU_RE.findall(service_text)}),
        lists=sorted(
            path.name for path in (root / "lists").glob("*.txt") if not is_user_file(path.name)
        )
        if (root / "lists").is_dir()
        else [],
        fakes=sorted(path.name for path in (root / "bin").glob("*.bin"))
        if (root / "bin").is_dir()
        else [],
        target_keys=sorted(set(_TARGET_KEY_RE.findall(targets_text))),
    )


def load_snapshot() -> Fingerprint | None:
    path = snapshot_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    known = {f for f in Fingerprint.__dataclass_fields__}
    return Fingerprint(**{k: v for k, v in data.items() if k in known})


def save_snapshot(fingerprint: Fingerprint) -> Path:
    upstream_dir().mkdir(parents=True, exist_ok=True)
    path = snapshot_file()
    path.write_text(
        json.dumps(asdict(fingerprint), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


@dataclass
class Change:
    """Одно расхождение между отпечатками."""

    what: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed


@dataclass
class Diff:
    """Расхождения, разложенные по тому, что с ними делать."""

    old_version: str = ""
    new_version: str = ""
    automatic: list[Change] = field(default_factory=list)
    attention: list[Change] = field(default_factory=list)
    breaking: list[Change] = field(default_factory=list)
    ideas: dict[str, str] = field(default_factory=dict)

    @property
    def needs_work(self) -> bool:
        """Есть ли то, ради чего придётся трогать код."""
        return bool(self.attention or self.breaking)

    @property
    def is_empty(self) -> bool:
        return not (self.automatic or self.attention or self.breaking or self.ideas)


def _change(what: str, old: list[str], new: list[str]) -> Change:
    return Change(
        what=what,
        added=sorted(set(new) - set(old)),
        removed=sorted(set(old) - set(new)),
    )


def compare(old: Fingerprint, new: Fingerprint) -> Diff:
    """Сравнивает отпечатки и раскладывает разницу по корзинам."""
    diff = Diff(old_version=old.version, new_version=new.version)

    # Подхватывается само: интерфейс читает это с диска при запуске.
    for what, before, after in (
        ("Стратегии", old.strategies, new.strategies),
        ("Списки", old.lists, new.lists),
        ("Фейковые пакеты", old.fakes, new.fakes),
        ("Цели проверок", old.target_keys, new.target_keys),
    ):
        change = _change(what, before, after)
        if change.added:
            diff.automatic.append(Change(what=change.what, added=change.added))
        if change.removed:
            # Исчезнувшее важнее: на него могли ссылаться наши настройки.
            diff.breaking.append(Change(what=f"{what} — исчезли", removed=change.removed))

    # Требует внимания: новая возможность, которой у интерфейса нет.
    for what, before, after in (
        ("Флаги winws", old.winws_flags, new.winws_flags),
        ("Пункты меню service.bat", old.service_menu, new.service_menu),
        ("Метки service.bat", old.service_labels, new.service_labels),
    ):
        change = _change(what, before, after)
        if change.added:
            diff.attention.append(Change(what=change.what, added=change.added))
        if change.removed:
            diff.breaking.append(Change(what=f"{what} — исчезли", removed=change.removed))

    return diff


def render_report(diff: Diff) -> str:
    """Собирает отчёт в markdown — его читает человек или Claude."""
    lines = [
        f"# Обновление апстрима: {diff.old_version or '—'} → {diff.new_version or '—'}",
        "",
        f"Сверка выполнена {datetime.now():%Y-%m-%d %H:%M}.",
        "",
    ]

    if diff.is_empty:
        lines += ["Расхождений нет — интерфейс согласован со сборкой.", ""]
        return "\n".join(lines)

    def section(title: str, note: str, changes: list[Change]) -> None:
        if not changes:
            return
        lines.extend([f"## {title}", "", note, ""])
        for change in changes:
            lines.append(f"**{change.what}**")
            lines.extend(f"- добавлено: `{item}`" for item in change.added)
            lines.extend(f"- убрано: `{item}`" for item in change.removed)
            lines.append("")

    section(
        "Ломающее",
        "Исчезло то, на что интерфейс опирается. Проверить в первую очередь.",
        diff.breaking,
    )
    section(
        "Требует внимания",
        "Апстрим научился новому, а интерфейс об этом не знает. "
        "Стоит прочитать и решить, нужно ли это нам.",
        diff.attention,
    )
    section(
        "Подхватится само",
        "Читается с диска при запуске — код трогать не нужно, "
        "список приведён для полноты картины.",
        diff.automatic,
    )

    if diff.ideas:
        lines.extend(
            [
                "## Идеи со стороны",
                "",
                "Новые релизы чужих оболочек над zapret. Иногда там находят обход, "
                "до которого мы не дошли, или делают удобство, которое стоит перенять.",
                "",
            ]
        )
        for repo, release in diff.ideas.items():
            lines.append(f"- **{repo}** — {release}")
        lines.append("")

    return "\n".join(lines)


def save_report(diff: Diff, text: str | None = None) -> Path:
    directory = upstream_dir() / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    name = diff.new_version or datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"{name}.md"
    path.write_text(text or render_report(diff), encoding="utf-8")
    return path
