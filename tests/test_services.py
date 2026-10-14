"""Тесты сервисной модели и выбора лучшей стратегии.

Главное, что здесь проверяется: победителем становится стратегия, починившая
больше сервисов целиком, а не набравшая больше проверок в сумме.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.probe import services
from app.core.probe.autopick import Report, StrategyScore, build_services_score
from app.core.probe.services import CheckResult, ServiceResult


def result(name: str, ok: int, total: int) -> ServiceResult:
    checks = [CheckResult(name=f"{name}-{i}", ok=i < ok) for i in range(total)]
    return ServiceResult(service=name, checks=checks)


def score(name: str, *parts: ServiceResult) -> StrategyScore:
    return build_services_score(name, list(parts), durations=[])


# --- отдельный сервис ---------------------------------------------------


def test_service_works_only_when_everything_passes() -> None:
    assert result("YouTube", ok=3, total=3).works
    assert not result("YouTube", ok=2, total=3).works


def test_service_counts_are_reported() -> None:
    item = result("Discord", ok=1, total=3)

    assert item.ok_count == 1
    assert item.total == 3
    assert item.label == "Discord 1/3"
    assert not item.dead


def test_fully_failed_service_is_dead() -> None:
    assert result("Discord", ok=0, total=3).dead


def test_empty_service_is_neither_working_nor_dead() -> None:
    empty = ServiceResult(service="Пусто", checks=[])

    assert not empty.works
    assert not empty.dead


# --- счёт стратегии -----------------------------------------------------


def test_score_sums_checks_across_services() -> None:
    item = score("тест", result("YouTube", 6, 6), result("Discord", 1, 3))

    assert item.ok == 7
    assert item.error == 2
    assert item.working_services == ["YouTube"]
    assert item.broken_services == ["Discord"]


def test_summary_mentions_services() -> None:
    item = score("тест", result("YouTube", 6, 6), result("Discord", 0, 3))

    assert "сервисов работает 1 из 2" in item.summary


def test_services_label_lists_every_service() -> None:
    item = score("тест", result("YouTube", 6, 6), result("Discord", 2, 3))

    assert item.services_label == "YouTube 6/6 · Discord 2/3"


# --- выбор победителя ---------------------------------------------------


def make_report(*scores: StrategyScore, baseline: StrategyScore | None = None) -> Report:
    report = Report(mode="services", started_at="", finished_at="", checked=[])
    report.baseline = baseline
    report.scores = [*( [baseline] if baseline else [] ), *scores]
    return report


def test_whole_services_beat_raw_check_count() -> None:
    """Число целиком работающих сервисов важнее суммы пройденных проверок.

    Крупный сервис иначе перевешивает два мелких: стратегия чинит один ютуб из
    десяти проверок и выигрывает у той, после которой заработали и дискорд,
    и телеграм — хотя пользоваться можно как раз второй.
    """
    lopsided = score(
        "только YouTube",
        result("YouTube", 10, 10),
        result("Discord", 0, 2),
        result("Telegram", 0, 2),
    )
    balanced = score(
        "мелкие целиком",
        result("YouTube", 3, 10),
        result("Discord", 2, 2),
        result("Telegram", 2, 2),
    )
    baseline = score(
        "без обхода",
        result("YouTube", 0, 10),
        result("Discord", 0, 2),
        result("Telegram", 0, 2),
    )
    baseline.is_baseline = True

    report = make_report(lopsided, balanced, baseline=baseline)

    assert lopsided.ok > balanced.ok, "перекошенная действительно набрала больше проверок"
    assert len(balanced.working_services) > len(lopsided.working_services)
    assert report.best is not None
    assert report.best.name == "мелкие целиком"


def test_verdict_warns_about_services_left_broken() -> None:
    baseline = score("без обхода", result("YouTube", 0, 6), result("Discord", 0, 3))
    baseline.is_baseline = True
    partial = score("частично", result("YouTube", 6, 6), result("Discord", 0, 3))

    report = make_report(partial, baseline=baseline)

    assert report.best is partial
    assert "не работает" in report.verdict
    assert "Discord" in report.verdict


def test_verdict_celebrates_full_success() -> None:
    baseline = score("без обхода", result("YouTube", 0, 6), result("Discord", 0, 3))
    baseline.is_baseline = True
    winner = score("всё чинит", result("YouTube", 6, 6), result("Discord", 3, 3))

    report = make_report(winner, baseline=baseline)

    assert "Все проверенные сервисы работают" in report.verdict


def test_strategy_not_better_than_baseline_is_not_best() -> None:
    baseline = score("без обхода", result("YouTube", 6, 6), result("Discord", 3, 3))
    baseline.is_baseline = True
    same = score("не хуже", result("YouTube", 6, 6), result("Discord", 3, 3))

    report = make_report(same, baseline=baseline)

    assert report.best is None
    assert "Блокировки не обнаружено" in report.verdict


def test_fixing_one_service_counts_as_improvement() -> None:
    baseline = score("без обхода", result("YouTube", 6, 6), result("Discord", 0, 3))
    baseline.is_baseline = True
    winner = score("чинит дискорд", result("YouTube", 6, 6), result("Discord", 3, 3))

    report = make_report(winner, baseline=baseline)

    assert report.best is winner


def test_strategy_that_did_not_start_is_never_best() -> None:
    baseline = score("без обхода", result("Discord", 0, 3))
    baseline.is_baseline = True
    dead = StrategyScore(name="не запустилась", started=False, ok=99)
    alive = score("рабочая", result("Discord", 1, 3))

    report = make_report(dead, alive, baseline=baseline)

    assert report.best is alive


def test_ranked_puts_best_first() -> None:
    weak = score("слабая", result("YouTube", 1, 6), result("Discord", 0, 3))
    strong = score("сильная", result("YouTube", 6, 6), result("Discord", 3, 3))

    report = make_report(weak, strong)

    assert [item.name for item in report.ranked] == ["сильная", "слабая"]


# --- состав сервисов ----------------------------------------------------


@pytest.fixture
def core_utils(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(services.paths, "core_utils", lambda: tmp_path)
    return tmp_path


def test_discord_uses_step_checks_not_page_requests(
    core_utils: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Страница Discord открывается и при неработающем клиенте — проверяем шаги."""
    monkeypatch.setattr(services, "load", lambda: [])

    found = {service.name: service for service in services.discover()}

    assert found["Discord"].kind == "discord"
    assert found["Discord"].size == 3


def test_user_targets_add_their_own_service(
    core_utils: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "load", lambda: [])
    services.user_targets_file().write_text(
        '### Мои сайты\nSite = "https://example.com"\n', encoding="utf-8"
    )

    names = [service.name for service in services.discover()]

    assert "Мои сайты" in names


def test_user_targets_template_is_created(core_utils: Path) -> None:
    services.ensure_user_targets()

    assert services.user_targets_file().exists()
    assert "###" in services.user_targets_file().read_text(encoding="utf-8")


def test_existing_user_targets_are_not_overwritten(core_utils: Path) -> None:
    services.user_targets_file().write_text("### Моё\n", encoding="utf-8")

    services.ensure_user_targets()

    assert services.user_targets_file().read_text(encoding="utf-8") == "### Моё\n"
