"""«Объёмное оформление» выключается одной галочкой и возвращает прежний вид."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.ui import polish
from app.ui.theme import build_stylesheet


@pytest.fixture(autouse=True)
def restore():
    yield
    polish.set_enabled(True)


def test_on_by_default() -> None:
    assert Settings().polish is True
    assert Settings.from_dict({}).polish is True


def test_switching_off_restores_the_flat_cards() -> None:
    polish.set_enabled(True)
    with_polish = build_stylesheet()
    polish.set_enabled(False)
    flat = build_stylesheet()

    assert polish.card_rules() == ""
    assert flat != with_polish
    assert with_polish.startswith(flat.rstrip()[:200])


def test_no_motion_means_no_fade(monkeypatch) -> None:
    """Галочка «Анимации» главнее: на слабой машине ничего не проявляется."""
    from app.ui import motion

    monkeypatch.setattr(motion, "_enabled", False)
    assert not polish._animated()
