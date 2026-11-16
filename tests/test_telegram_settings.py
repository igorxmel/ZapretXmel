"""Настройки tg-ws-proxy в программе и признак «прокси застрял».

Поводом стал прокси у знакомого: Telegram стучался в него, а до серверов не доходило
ничего — ни напрямую, ни через Cloudflare. Помогла галочка «Без TLS» в окне самого
прокси; теперь её и остальные настройки видно в разделе Telegram.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import telegram

# Строки из настоящего журнала, без ключа и ссылки.
STARTED = "2026-11-16 21:16:38  INFO   tg-ws-tray  TG WS Proxy версия 1.11.4 starting"
STUCK = (
    "2026-11-16 21:21:14  INFO     tg-mtproto-proxy  stats: total=172 active=11 ws=0 h2=0 "
    "h2_tcp=0 h2_req=0 h2_err=0 tcp_fb=0 cf=0 front=0 bad=0 masked=0 err=436 pool=0/82 "
    "cf_pool=n/a up=0.0B down=0.0B"
)
HEALTHY = (
    "2026-11-16 22:00:00  INFO     tg-mtproto-proxy  stats: total=40 active=6 ws=31 h2=0 "
    "cf=0 err=2 pool=4/8 up=1.2MB down=18.5MB"
)


@pytest.fixture
def proxy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(telegram, "home", lambda: tmp_path)
    (tmp_path / telegram.PORTABLE_DIR).mkdir()
    return tmp_path / telegram.PORTABLE_DIR


def _log(proxy: Path, *lines: str) -> None:
    (proxy / "proxy.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_stuck_proxy_is_recognised(proxy) -> None:
    _log(proxy, STARTED, STUCK)

    assert telegram.is_stuck(telegram.last_stats())


def test_working_proxy_is_not_stuck(proxy) -> None:
    _log(proxy, STARTED, HEALTHY)

    assert not telegram.is_stuck(telegram.last_stats())


def test_stats_from_a_previous_run_do_not_count(proxy) -> None:
    """После перезапуска старая статистика говорит о прошлом разе."""
    _log(proxy, STARTED, STUCK, STARTED)

    assert telegram.last_stats() == {}
    assert not telegram.is_stuck(telegram.last_stats())


def test_no_log_means_nothing_known(proxy) -> None:
    assert telegram.last_stats() == {}


def test_settings_have_defaults_and_keep_the_secret(proxy) -> None:
    telegram.ensure_config()
    secret = telegram.read_config()["secret"]

    telegram.save_settings({"no_secure": True, "port": 1555, "buf_kb": 512})

    current = telegram.settings()
    assert current["no_secure"] is True and current["port"] == 1555 and current["buf_kb"] == 512
    assert current["cfproxy"] is True, "не тронутые — по умолчанию"
    assert telegram.read_config()["secret"] == secret


def test_chosen_port_survives_a_restart(proxy) -> None:
    """Раньше запуск каждый раз ставил 1443, и смена порта молча откатывалась."""
    telegram.save_settings({"port": 1555})

    assert telegram.ensure_config()["port"] == 1555
    assert telegram.configured_port() == 1555


def test_proxy_only_listens_on_this_computer(proxy) -> None:
    telegram.write_config({"host": "0.0.0.0"})

    assert telegram.ensure_config()["host"] == "127.0.0.1"


@pytest.mark.parametrize(
    ("key", "value"), [("port", 80), ("buf_kb", 0), ("pool_size", 999), ("log_max_mb", 0)]
)
def test_numbers_outside_limits_are_refused(proxy, key: str, value: int) -> None:
    with pytest.raises(ValueError):
        telegram.save_settings({key: value})


def test_unknown_settings_are_refused(proxy) -> None:
    with pytest.raises(ValueError):
        telegram.save_settings({"secret": "x"})


def test_dc_rules_are_checked() -> None:
    assert telegram.parse_dc_rules("2:149.154.167.220\n\n 4:149.154.167.220 ") == [
        "2:149.154.167.220",
        "4:149.154.167.220",
    ]
    with pytest.raises(ValueError, match="2:300.1.1.1"):
        telegram.parse_dc_rules("2:300.1.1.1")
    with pytest.raises(ValueError):
        telegram.parse_dc_rules("просто текст")


def test_domains_are_checked() -> None:
    assert telegram.parse_domains("a.example.com, B.example.org  c.io") == [
        "a.example.com",
        "b.example.org",
        "c.io",
    ]
    with pytest.raises(ValueError, match="не похоже на домен: not"):
        telegram.parse_domains("not a domain")


def test_new_secret_differs(proxy) -> None:
    telegram.ensure_config()
    old = telegram.read_config()["secret"]

    assert telegram.new_secret() != old
