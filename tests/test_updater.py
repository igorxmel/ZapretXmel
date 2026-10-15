"""Тесты апдейтера: сравнение версий и установка из настоящего архива Flowseal."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from app.core import coreinfo
from app.core.updater import install
from app.core.updater.github import is_newer, parse_version
from app.core.updater.install import InstallError, carry_over_user_files, extract, validate_bundle

# Настоящие релизы лежат в загрузках пользователя. Если их нет — тесты,
# которым нужен архив, пропускаются, а логика сравнения версий всё равно проверяется.
ARCHIVE_1_10_3 = Path(r"D:\Downloads\zapret-discord-youtube-1.10.3.zip")
needs_archive = pytest.mark.skipif(
    not ARCHIVE_1_10_3.exists(), reason="нет локального архива релиза"
)


@pytest.mark.parametrize(
    ("candidate", "installed"),
    [
        ("1.10.3", "1.10.2"),
        ("1.10.0", "1.9.9d"),
        ("1.9.9d", "1.9.9"),  # буквенный суффикс — правка поверх номерной версии
        ("1.9.8c", "1.9.8b"),
        ("2.0.0", "1.10.3"),
        ("1.10.3", ""),  # ядро ещё не установлено
    ],
)
def test_newer_versions(candidate: str, installed: str) -> None:
    assert is_newer(candidate, installed)


@pytest.mark.parametrize(
    ("candidate", "installed"),
    [
        ("1.10.2", "1.10.3"),
        ("1.9.9", "1.10.0"),
        ("1.10.3", "1.10.3"),
        ("1.9.9", "1.9.9d"),
        ("", "1.10.3"),
    ],
)
def test_not_newer_versions(candidate: str, installed: str) -> None:
    assert not is_newer(candidate, installed)


def test_version_ordering_is_numeric_not_lexicographic() -> None:
    """Строковое сравнение поставило бы 1.9 выше 1.10 — здесь этого быть не должно."""
    assert parse_version("1.10.3") > parse_version("1.9.9")


@needs_archive
def test_extract_finds_bundle_root(tmp_path: Path) -> None:
    root = extract(ARCHIVE_1_10_3, tmp_path / "staging")

    assert (root / "bin" / "winws.exe").exists()
    assert (root / "service.bat").exists()
    assert (root / "lists").is_dir()


@needs_archive
def test_real_bundle_passes_validation(tmp_path: Path) -> None:
    root = extract(ARCHIVE_1_10_3, tmp_path / "staging")

    validate_bundle(root)


@needs_archive
def test_version_is_read_from_service_bat(tmp_path: Path) -> None:
    root = extract(ARCHIVE_1_10_3, tmp_path / "staging")

    assert coreinfo.read_version(root) == "1.10.3"


def test_version_is_read_from_legacy_version_txt(tmp_path: Path) -> None:
    """В старых сборках версия лежала в version.txt."""
    shutil.copy(
        Path(__file__).parent / "fixtures" / "bundle_1_6_1" / "version.txt",
        tmp_path / "version.txt",
    )

    assert coreinfo.read_version(tmp_path) == "1.6.1"


def test_validation_rejects_archive_without_winws(tmp_path: Path) -> None:
    fake = tmp_path / "bundle"
    (fake / "bin").mkdir(parents=True)

    with pytest.raises(InstallError):
        validate_bundle(fake)


def test_validation_rejects_bundle_without_strategies(tmp_path: Path) -> None:
    fake = tmp_path / "bundle"
    (fake / "bin").mkdir(parents=True)
    (fake / "bin" / "winws.exe").write_bytes(b"")
    (fake / "bin" / "WinDivert.dll").write_bytes(b"")

    with pytest.raises(InstallError):
        validate_bundle(fake)


def test_extract_blocks_path_traversal(tmp_path: Path) -> None:
    """Архив не должен уметь писать файлы за пределы целевой папки."""
    malicious = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../escaped.txt", "нет")
        archive.writestr("bundle/ok.txt", "да")

    root = extract(malicious, tmp_path / "staging")

    assert not (tmp_path / "escaped.txt").exists()
    assert (root / "ok.txt").exists()


def test_carry_over_preserves_user_files(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "lists").mkdir(parents=True)
    (new / "lists").mkdir(parents=True)
    (old / "utils").mkdir()

    (old / "lists" / "list-general-user.txt").write_text("мой-сайт.рф\n", encoding="utf-8")
    (old / "lists" / "ipset-all.txt").write_text("1.1.1.0/24\n", encoding="utf-8")
    (old / "utils" / "game_filter.enabled").write_text("mode=all\n", encoding="utf-8")
    (old / "lists" / "list-general.txt").write_text("перезаписывается\n", encoding="utf-8")
    (new / "lists" / "list-general.txt").write_text("из нового релиза\n", encoding="utf-8")

    carried = carry_over_user_files(old, new)

    assert carried == 3
    assert (new / "lists" / "list-general-user.txt").exists()
    assert (new / "utils" / "game_filter.enabled").exists()
    assert "из нового релиза" in (new / "lists" / "list-general.txt").read_text(encoding="utf-8")


def test_carry_over_keeps_custom_strategies(tmp_path: Path) -> None:
    """Стратегия, которой нет в новой сборке, добавлена пользователем — её сохраняем."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()

    (old / "general.bat").write_text("старая версия\n", encoding="utf-8")
    (old / "моя стратегия.bat").write_text("своё\n", encoding="utf-8")
    (new / "general.bat").write_text("новая версия\n", encoding="utf-8")

    carry_over_user_files(old, new)

    assert (new / "моя стратегия.bat").exists()
    assert (new / "general.bat").read_text(encoding="utf-8") == "новая версия\n"


def test_list_backups_sorted_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install.paths, "backups_dir", lambda: tmp_path)
    (tmp_path / "20260101-120000_1.10.1").mkdir()
    (tmp_path / "20260301-120000_1.10.3").mkdir()
    (tmp_path / "20260201-120000_1.10.2").mkdir()
    (tmp_path / "мусор").mkdir()

    backups = install.list_backups()

    assert [backup.version for backup in backups] == ["1.10.3", "1.10.2", "1.10.1"]


# --- описание релиза ----------------------------------------------------


def test_release_notes_are_taken_from_the_changelog() -> None:
    """Описание релиза пишется словами в CHANGELOG.md, а не собирается из коммитов."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from release_notes import section

    text = (
        "# Что менялось\n\n"
        "## 0.2.0\n\nНовое и прекрасное.\n\n"
        "## 0.1.6\n\n### Исправлено\n\n- перенос папки\n\n"
        "## 0.1.5\n\nстарое\n"
    )

    assert section(text, "0.1.6") == "### Исправлено\n\n- перенос папки"
    assert section(text, "0.2.0") == "Новое и прекрасное."
    assert section(text, "9.9.9") == ""


def test_every_released_version_is_described() -> None:
    """Выпущенная версия без записи в CHANGELOG.md — недосмотр, а не норма."""
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tools"))
    from release_notes import section

    from app import __version__

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert section(changelog, __version__), f"в CHANGELOG.md нет раздела про {__version__}"
