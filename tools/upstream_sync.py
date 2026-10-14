"""Сверка с апстримом: что изменилось и чего интерфейс ещё не умеет.

Скачивает последний релиз Flowseal во временную папку, снимает с него
отпечаток и сравнивает с сохранённым. Результат — отчёт в `upstream/reports/`.
Сама сборка при этом не трогается: скрипт только смотрит.

    python tools/upstream_sync.py              # сверить и написать отчёт
    python tools/upstream_sync.py --accept     # принять новое состояние
    python tools/upstream_sync.py --local      # сверить с уже установленным ядром

Код возврата 1 означает, что найдено требующее внимания или ломающее — удобно
для запуска по расписанию.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths, upstream  # noqa: E402
from app.core.updater import github, install  # noqa: E402


def fetch_release(destination: Path) -> tuple[str, Path]:
    """Скачивает и распаковывает последний релиз ядра."""
    release = github.latest_release(upstream.load_sources()["core"])
    asset = release.zip_asset()
    if asset is None:
        raise SystemExit(f"в релизе {release.tag} нет архива сборки")

    print(f"последний релиз: {release.version} от {release.published_date}")
    archive = destination / asset.name
    github.download(asset, archive)
    return release.version, install.extract(archive, destination / "unpacked")


def collect_ideas(previous: dict[str, str]) -> dict[str, str]:
    """Смотрит релизы чужих оболочек и возвращает только новые для нас."""
    sources = upstream.load_sources()
    ideas: dict[str, str] = {}

    for repo in [*sources.get("guis", []), *sources.get("sidecars", [])]:
        try:
            release = github.latest_release(repo)
        except Exception as error:  # noqa: BLE001 — недоступный репозиторий не повод падать
            print(f"  {repo}: не удалось прочитать релизы ({error})")
            continue

        marker = f"{release.tag} от {release.published_date}"
        if previous.get(repo) != release.tag:
            ideas[repo] = marker
        previous[repo] = release.tag

    return ideas


def main() -> int:
    parser = argparse.ArgumentParser(description="Сверка с апстримом")
    parser.add_argument(
        "--accept",
        action="store_true",
        help="принять новое состояние как согласованное с интерфейсом",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="сверять с уже установленным ядром, ничего не скачивая",
    )
    args = parser.parse_args()

    paths.ensure_dirs()
    previous = upstream.load_snapshot()

    temporary: Path | None = None
    try:
        if args.local:
            root = paths.core_dir()
            if not root.is_dir():
                print("ядро не установлено — нечего сверять")
                return 1
            print(f"сверяю с установленным ядром: {root}")
        else:
            temporary = Path(tempfile.mkdtemp(prefix="zapretxmel-upstream-"))
            _, root = fetch_release(temporary)

        current = upstream.build(root)
        print(f"отпечаток снят: версия {current.version or '—'}, файлов {len(current.files)}")

        print("смотрю релизы чужих оболочек…")
        seen = dict(previous.seen_releases) if previous else {}
        ideas = collect_ideas(seen)
        current.seen_releases = seen

        if previous is None:
            print("\nсохранённого отпечатка нет — это первая сверка, принимаю как есть")
            upstream.save_snapshot(current)
            return 0

        diff = upstream.compare(previous, current)
        diff.ideas = ideas

        report = upstream.render_report(diff)
        path = upstream.save_report(diff, report)
        print()
        print(report)
        print(f"отчёт сохранён: {path}")

        if args.accept:
            upstream.save_snapshot(current)
            print("новое состояние принято как согласованное")
            return 0

        if diff.needs_work:
            print("\nесть изменения, требующие правок в интерфейсе")
            return 1
        return 0
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
