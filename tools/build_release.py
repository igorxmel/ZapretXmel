"""Сборка распространяемой версии.

Собирает один .exe, внутрь которого кладутся картинки. Ядро zapret внутрь не
попадает намеренно: оно скачивается из официальных релизов Flowseal при первом
запуске и обновляется отдельно — так пользователь всегда получает актуальную
сборку, а не ту, что была на момент нашей.

    python tools/build_release.py

Рядом с .exe кладётся файл с его SHA-256: по нему программа при самообновлении
и человек вручную могут убедиться, что скачали то же самое.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Вывод здесь русский, а на сборочной машине GitHub стандартный поток
# открывается в cp1252 — без этого скрипт падает на первой же строке с
# кириллицей, ещё не начав собирать.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from app import __version__  # noqa: E402

NAME = "ZapretXmel"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def ensure_dependencies() -> None:
    """Проверяет, что в окружении есть всё, что должно попасть в сборку."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "не установлен PyInstaller — выполните:\n"
            "    .venv\\Scripts\\pip install pyinstaller"
        ) from None

    # Без этого пакета сборка пройдёт, но разбор через Claude в ней молча не
    # заработает — и заметит это уже пользователь.
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise SystemExit(
            "не установлен anthropic — без него в сборке не будет разбора через Claude:\n"
            '    .venv\\Scripts\\pip install -e ".[ai]"'
        ) from None


def build() -> Path:
    ensure_dependencies()

    for directory in (DIST, BUILD):
        shutil.rmtree(directory, ignore_errors=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        f"--name={NAME}",
        f"--icon={ROOT / 'assets' / 'logo.ico'}",
        # Картинки нужны в собранном виде: logo для значка и трея,
        # banner для шапки, chevron для выпадающих списков.
        f"--add-data={ROOT / 'assets'}{';'}assets",
        # Запрос прав вшивается в манифест, иначе программа каждый раз
        # перезапускалась бы через UAC вручную.
        "--uac-admin",
        str(ROOT / "app" / "__main__.py"),
    ]

    print("собираю:", NAME, __version__)
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit("PyInstaller завершился с ошибкой")

    built = DIST / f"{NAME}.exe"
    if not built.exists():
        raise SystemExit(f"не найден результат сборки: {built}")
    return built


def write_hash(path: Path) -> Path:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b""):
            digest.update(chunk)

    target = path.with_suffix(path.suffix + ".sha256")
    target.write_text(f"{digest.hexdigest()}  {path.name}\n", encoding="utf-8")
    return target


def main() -> int:
    built = build()
    checksum = write_hash(built)

    size = built.stat().st_size / 1024 / 1024
    print()
    print(f"готово: {built}  ({size:.1f} МБ)")
    print(f"хеш:    {checksum}")
    print()
    print("Выкладывать в релиз нужно оба файла: .exe и .sha256.")
    print(f"Имя .exe менять нельзя — самообновление ищет ровно «{NAME}.exe».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
