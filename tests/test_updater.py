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
        ("1.1.0-rc.1", "1.0.0"),  # тестовая сборка новее прошлого релиза
        ("1.1.0", "1.1.0-rc.1"),  # обычная версия старше своей тестовой
        ("1.1.0-rc.2", "1.1.0-rc.1"),
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
        ("1.1.0-rc.1", "1.1.0"),  # назад с обычной версии на тестовую не зовём
        ("1.1.0-rc.1", "1.1.0-rc.2"),
    ],
)
def test_not_newer_versions(candidate: str, installed: str) -> None:
    assert not is_newer(candidate, installed)


def test_version_ordering_is_numeric_not_lexicographic() -> None:
    """Строковое сравнение поставило бы 1.9 выше 1.10 — здесь этого быть не должно."""
    assert parse_version("1.10.3") > parse_version("1.9.9")


def test_prerelease_is_not_the_same_as_the_release() -> None:
    """Иначе тестер застрянет на тестовой сборке навсегда.

    Для программы `1.1.0-rc.1` и `1.1.0` были одной версией: суффикс просто
    отбрасывался. Человек, поставивший тестовую, обычную уже не получал —
    обновляться, с точки зрения программы, было некуда.
    """
    assert parse_version("1.1.0-rc.1") < parse_version("1.1.0")


def test_upstream_letter_suffix_still_means_newer() -> None:
    """У апстрима буква после номера — правка поверх версии, а не пре-релиз."""
    assert parse_version("1.9.9d") > parse_version("1.9.9")


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


# --- обновление самой программы -----------------------------------------


class FakeAsset:
    def __init__(self, name: str, size: int = 50 * 1048576):
        self.name = name
        self.size = size
        self.url = f"https://example.invalid/{name}"


class FakeRelease:
    tag = "0.1.8"
    version = "0.1.8"

    def __init__(self, assets):
        self.assets = assets


def test_broken_download_is_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Недокачанный файл нельзя ставить на место рабочей программы.

    Полсотни мегабайт по дороге могут оборваться, и тогда мы заменим
    работающую программу на ту, что не запустится вовсе.
    """
    from app.core.updater import selfupdate

    target = tmp_path / "ZapretXmel.exe"
    monkeypatch.setattr(selfupdate, "executable", lambda: target)
    def half_a_file(_asset, destination, progress=None):
        destination.write_bytes(b"x" * 2048)
        return "0" * 64

    monkeypatch.setattr(selfupdate.github, "download", half_a_file)
    monkeypatch.setattr(selfupdate, "_published_hash", lambda _: "f" * 64)

    release = FakeRelease([FakeAsset("ZapretXmel.exe")])

    with pytest.raises(selfupdate.SelfUpdateError, match="не совпал"):
        selfupdate.download(release)

    assert not (tmp_path / "ZapretXmel.new.exe").exists(), "битую копию надо убирать"


def test_matching_hash_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.updater import selfupdate

    target = tmp_path / "ZapretXmel.exe"
    monkeypatch.setattr(selfupdate, "executable", lambda: target)
    monkeypatch.setattr(selfupdate, "_published_hash", lambda _: "A" * 64)

    def fake_download(_asset, destination, progress=None):
        destination.write_bytes(b"x" * 2048)
        return "a" * 64

    monkeypatch.setattr(selfupdate.github, "download", fake_download)

    result = selfupdate.download(FakeRelease([FakeAsset("ZapretXmel.exe")]))

    assert result == tmp_path / "ZapretXmel.new.exe"


def test_leftovers_from_a_previous_attempt_are_cleared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вторая попытка не должна писать в файл, оставшийся от первой."""
    from app.core.updater import selfupdate

    target = tmp_path / "ZapretXmel.exe"
    monkeypatch.setattr(selfupdate, "executable", lambda: target)
    monkeypatch.setattr(selfupdate, "_published_hash", lambda _: "")

    leftover = tmp_path / "ZapretXmel.new.exe"
    leftover.write_bytes(b"leftover")
    (tmp_path / "ZapretXmel.new.exe.part").write_bytes(b"half")

    seen: list[bool] = []

    def fake_download(_asset, destination, progress=None):
        seen.append(destination.exists())
        destination.write_bytes(b"x" * 2048)
        return "a" * 64

    monkeypatch.setattr(selfupdate.github, "download", fake_download)
    selfupdate.download(FakeRelease([FakeAsset("ZapretXmel.exe")]))

    assert seen == [False], "старый файл должен быть убран до загрузки"
    assert not (tmp_path / "ZapretXmel.new.exe.part").exists()


# --- целостность скачанного ---------------------------------------------


def test_download_rejects_a_file_that_does_not_match_the_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Скачанное сверяется с хешем из релиза.

    Любой из этих файлов мы потом запускаем с правами администратора, так что
    оборванная загрузка или подмена по дороге не должны доходить до диска.
    """
    from app.core.updater import github

    class FakeResponse:
        headers = {"Content-Length": "4"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"not the expected bytes"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(github.requests, "get", lambda *_, **__: FakeResponse())

    asset = github.Asset(
        name="ZapretXmel.exe", url="https://example.invalid/x", size=4, digest="f" * 64
    )
    target = tmp_path / "ZapretXmel.exe"

    with pytest.raises(github.DownloadError, match="не совпал"):
        github.download(asset, target)

    assert not target.exists()
    assert not list(tmp_path.glob("*.part")), "обрывки оставлять нельзя"


def test_download_without_a_published_hash_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Старые релизы хеша не несут — проверять тогда нечего."""
    from app.core.updater import github

    class FakeResponse:
        headers = {"Content-Length": "5"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"bytes"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(github.requests, "get", lambda *_, **__: FakeResponse())

    asset = github.Asset(name="core.zip", url="https://example.invalid/x", size=5)
    target = tmp_path / "core.zip"

    github.download(asset, target)

    assert target.read_bytes() == b"bytes"


def test_digest_prefix_is_stripped() -> None:
    """GitHub отдаёт его как «sha256:…», а сравниваем мы голое значение."""
    from app.core.updater.github import _to_release

    release = _to_release(
        {
            "tag_name": "1.0",
            "assets": [
                {"name": "x.zip", "browser_download_url": "u", "size": 1, "digest": "sha256:abc"}
            ],
        }
    )

    assert release.assets[0].digest == "abc"
