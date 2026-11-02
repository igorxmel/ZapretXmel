"""Тесты списка изменений, который читает сама программа.

Окно «что нового» показывается после обновления и обязано работать без
сети: её может не быть именно из-за тех блокировок, ради которых программу
и поставили.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import changelog, paths

TEXT = (
    "# Что менялось\n\n"
    "## 0.2.0\n\nНовое и прекрасное.\n\n"
    "## 0.1.16\n\n### Добавлено\n\n- журнал программы\n\n"
    "## 0.1.15\n\nстарое\n"
)


def test_section_is_taken_without_the_heading() -> None:
    assert changelog.section(TEXT, "0.1.16") == "### Добавлено\n\n- журнал программы"


def test_next_version_does_not_leak_in() -> None:
    assert changelog.section(TEXT, "0.2.0") == "Новое и прекрасное."


def test_unknown_version_gives_nothing() -> None:
    assert changelog.section(TEXT, "9.9.9") == ""


def test_packed_file_wins_over_the_source_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """В сборке список лежит рядом с картинками, в исходниках — в корне."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / changelog.FILENAME).write_text(TEXT, encoding="utf-8")

    monkeypatch.setattr(paths, "assets_dir", lambda: assets)
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)

    assert changelog.file() == assets / changelog.FILENAME
    assert "журнал программы" in changelog.read("0.1.16")


def test_source_file_is_used_when_nothing_is_packed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / changelog.FILENAME).write_text(TEXT, encoding="utf-8")
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет такой")
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)

    assert changelog.read("0.2.0") == "Новое и прекрасное."


def test_missing_file_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path / "тоже нет")

    assert changelog.read("0.1.16") == ""


def test_current_version_is_described() -> None:
    """Выпускать версию без раздела нельзя — окно откроется пустым."""
    from app import __version__

    assert changelog.read(__version__), f"нет раздела про {__version__}"


def test_version_is_the_same_in_both_places() -> None:
    """Номер версии записан дважды, и разойтись им нельзя.

    `app/__init__.py` читает самообновление, `pyproject.toml` — сборка.
    Разошлись — релиз падает на сборочной машине проверкой тега, а до неё
    об этом ничто не напоминает.
    """
    import tomllib

    from app import __version__
    from app.core import paths

    pyproject = tomllib.loads(
        (paths.app_root() / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert pyproject["project"]["version"] == __version__


# --- когда показывать окно ----------------------------------------------


def test_window_is_shown_after_an_update() -> None:
    from app.ui.views.whatsnew import should_show

    assert should_show("0.1.16", "0.1.17", first_run_done=True)


def test_window_is_not_shown_twice_for_the_same_version() -> None:
    from app.ui.views.whatsnew import should_show

    assert not should_show("0.1.17", "0.1.17", first_run_done=True)


def test_first_run_stays_silent() -> None:
    """Сравнивать не с чем, да и знакомство важнее."""
    from app.ui.views.whatsnew import should_show

    assert not should_show("", "0.1.17", first_run_done=False)


def test_update_from_a_version_without_the_mark_is_still_an_update() -> None:
    """Отметку о просмотре ввели не сразу.

    У тех, кто обновлялся с более ранней версии, она пустая — но это не
    первый запуск, и окно им показать надо.
    """
    from app.ui.views.whatsnew import should_show

    assert should_show("", "0.1.18", first_run_done=True)


def test_prerelease_uses_the_section_of_its_version() -> None:
    """Тестовая сборка берёт раздел обычной версии.

    Иначе на каждую версию пришлось бы писать два одинаковых раздела — и
    они неизбежно разъехались бы по содержанию.
    """
    text = "## 1.1.0\n\nЧто-то починили.\n\n## 1.0.0\n\nПервый выпуск.\n"

    assert changelog.section(text, "1.1.0-rc.1") == "Что-то починили."


def test_prerelease_prefers_its_own_section_when_it_exists() -> None:
    """Если про сборку есть что сказать отдельно — говорим это."""
    text = "## 1.1.0-rc.1\n\nПробная сборка.\n\n## 1.1.0\n\nЧто-то починили.\n"

    assert changelog.section(text, "1.1.0-rc.1") == "Пробная сборка."


# --- всё, что вышло с прошлого обновления ---------------------------------

HISTORY = (
    "# Что менялось\n\nВступление.\n\n"
    "## 0.1.10\n\nдесятая\n\n"
    "## 0.1.9\n\n### Добавлено\n\n- девятая\n\n"
    "## 0.1.8\n\n\n"
    "## 0.1.7\n\nседьмая\n\n"
    "## 0.1.6\n\nшестая\n"
)


@pytest.fixture
def history_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / changelog.FILENAME).write_text(HISTORY, encoding="utf-8")
    monkeypatch.setattr(paths, "assets_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(paths, "app_root", lambda: tmp_path)


def _versions(entries: list[changelog.Entry]) -> list[str]:
    return [entry.version for entry in entries]


def test_skipped_versions_are_all_listed(history_file: None) -> None:
    """Обновились через несколько версий: рассказать надо обо всех."""
    assert _versions(changelog.since("0.1.6", "0.1.10")) == ["0.1.10", "0.1.9", "0.1.7"]


def test_ordinary_update_lists_one_version(history_file: None) -> None:
    assert _versions(changelog.since("0.1.9", "0.1.10")) == ["0.1.10"]


def test_versions_compare_as_numbers_not_text(history_file: None) -> None:
    """По тексту 0.1.10 старее 0.1.9, и список выходил бы пустым."""
    assert "0.1.10" in _versions(changelog.since("0.1.9", "0.1.10"))
    assert "0.1.9" not in _versions(changelog.since("0.1.9", "0.1.10"))


def test_without_a_mark_only_current_version_is_listed(history_file: None) -> None:
    assert _versions(changelog.since("", "0.1.10")) == ["0.1.10"]


def test_rollback_tells_only_about_current_version(history_file: None) -> None:
    assert _versions(changelog.since("0.1.10", "0.1.7")) == ["0.1.7"]


def test_prerelease_is_listed_once_under_its_own_number(history_file: None) -> None:
    """Раздел тестовой сборки называется номером обычной версии."""
    found = changelog.since("0.1.9", "0.1.10-rc.1")

    assert _versions(found) == ["0.1.10-rc.1"]
    assert found[0].notes == "десятая"


def test_history_is_complete_and_starts_from_current(history_file: None) -> None:
    assert _versions(changelog.history("0.1.9")) == ["0.1.9", "0.1.7", "0.1.6"]


def test_real_changelog_is_parsed_whole() -> None:
    """Разделы не должны теряться и перемешиваться в настоящем файле."""
    from app import __version__

    found = changelog.history(__version__)

    assert found[0].version == __version__
    assert len(found) > 50
    assert all(entry.notes for entry in found)
    assert "## " not in found[0].notes.replace("### ", "")


def test_skip_note_appears_only_for_several_versions() -> None:
    from app.ui.views.whatsnew import skipped_text

    one = [changelog.Entry("0.1.10", "x")]
    two = [*one, changelog.Entry("0.1.9", "y")]

    assert skipped_text("0.1.9", one) == ""
    assert skipped_text("", two) == ""
    assert "0.1.8" in skipped_text("0.1.8", two) and "2" in skipped_text("0.1.8", two)
