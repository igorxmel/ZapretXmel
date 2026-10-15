"""Тесты разбора целей, классификации проб и скоринга стратегий."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.probe import targets as targets_module
from app.core.probe.http import Outcome, _classify
from app.core.probe.targets import Target, parse, quick

FIXTURE_TARGETS = (
    Path(__file__).parent / "fixtures" / "bundle_1_10_3" / "utils" / "targets.txt"
)


def test_parses_real_targets_file() -> None:
    parsed = parse(FIXTURE_TARGETS.read_text(encoding="utf-8"))
    names = {target.name for target in parsed}

    assert "DiscordMain" in names
    assert "CloudflareDNS1111" in names
    assert len(parsed) >= 15


def test_url_and_ping_targets_are_distinguished() -> None:
    parsed = {target.name: target for target in parse(FIXTURE_TARGETS.read_text(encoding="utf-8"))}

    assert parsed["DiscordMain"].url == "https://discord.com"
    assert not parsed["DiscordMain"].is_ping_only

    assert parsed["CloudflareDNS1111"].ping_host == "1.1.1.1"
    assert parsed["CloudflareDNS1111"].is_ping_only


def test_group_headers_are_captured() -> None:
    parsed = {target.name: target for target in parse(FIXTURE_TARGETS.read_text(encoding="utf-8"))}

    assert parsed["DiscordMain"].group == "Discord"
    assert parsed["YouTubeWeb"].group == "YouTube"


def test_comments_and_garbage_are_skipped() -> None:
    parsed = parse(
        '# комментарий\n'
        'Good = "https://example.com"\n'
        'сломанная строка\n'
        'NoQuotes = https://example.org\n'
    )

    assert [target.name for target in parsed] == ["Good"]


def test_host_is_derived_from_url() -> None:
    assert Target("X", url="https://cdn.discordapp.com/attachments").host == "cdn.discordapp.com"
    assert Target("Y", ping_host="8.8.8.8").host == "8.8.8.8"


def test_load_falls_back_to_builtin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(targets_module.paths, "core_utils", lambda: tmp_path)

    assert targets_module.load() == list(targets_module.BUILTIN)


def test_quick_subset_is_smaller_but_not_empty() -> None:
    full = parse(FIXTURE_TARGETS.read_text(encoding="utf-8"))
    subset = quick(full)

    assert 0 < len(subset) < len(full)
    assert all(target in full for target in subset)


# --- классификация ответов curl ----------------------------------------


def test_success_is_ok() -> None:
    assert _classify(0, "") is Outcome.OK


def test_connection_failure_is_error() -> None:
    assert _classify(28, "Operation timed out") is Outcome.ERROR


@pytest.mark.parametrize(
    "stderr",
    [
        "curl: (6) Could not resolve host: discord.com",
        "SSL certificate problem: self-signed certificate",
        "schannel: certificate verify failed",
        "unable to get local issuer certificate",
    ],
)
def test_dns_and_certificate_problems_are_ssl(stderr: str) -> None:
    """Эти ошибки означают подмену DNS или сертификата, а не слабый обход."""
    assert _classify(60, stderr) is Outcome.SSL


def test_unsupported_tls_version_is_marked_separately() -> None:
    assert _classify(35, "") is Outcome.UNSUPPORTED
    assert _classify(2, "TLS 1.3 is not supported by schannel") is Outcome.UNSUPPORTED


def test_ssl_wins_over_unsupported() -> None:
    """Подмена сертификата важнее для вердикта, чем неподдержанный протокол."""
    assert _classify(35, "SSL certificate problem") is Outcome.SSL


# --- история прогонов ---------------------------------------------------


def test_history_keeps_only_recent_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подбор запускают помногу раз, и каждый прогон — отдельный файл.

    Без прополки папка растёт бесконечно, а отчёты полугодовой давности не с
    чем сравнивать: сборка за это время обновляется.
    """
    from app.core import paths
    from app.core.probe import autopick

    history = tmp_path / "history"
    history.mkdir()
    for number in range(40):
        (history / f"autopick-2026010{number % 10}-00000{number}.json").write_text(
            "{}", encoding="utf-8"
        )

    monkeypatch.setattr(paths, "history_dir", lambda: history)

    removed = autopick.prune_history(keep=5)

    assert removed == 35
    assert len(list(history.glob("autopick-*.json"))) == 5


def test_history_pruning_survives_an_empty_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import paths
    from app.core.probe import autopick

    monkeypatch.setattr(paths, "history_dir", lambda: tmp_path / "нет такой")

    assert autopick.prune_history() == 0
