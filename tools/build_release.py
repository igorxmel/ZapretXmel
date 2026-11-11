"""Сборка распространяемой версии — в двух вариантах.

- `ZapretXmel.exe` — переносная: один файл, кладётся куда угодно.
- `ZapretXmel-Setup.exe` — установщик (Inno Setup) поверх сборки папкой. Она
  запускается вдвое быстрее: ей не нужно при каждом запуске распаковывать
  полсотни мегабайт во временную папку под проверкой антивируса.

Ядро zapret внутрь не попадает намеренно: оно скачивается из официальных
релизов Flowseal при первом запуске и обновляется отдельно — так пользователь
всегда получает актуальную сборку, а не ту, что была на момент нашей.

    python tools/build_release.py                 # оба варианта
    python tools/build_release.py --portable-only # без установщика

Для установщика нужен Inno Setup 6 (`ISCC.exe` в PATH, в стандартной папке
или в переменной ISCC). Рядом с каждым файлом кладётся его SHA-256: по нему
программа при самообновлении и человек вручную могут убедиться, что скачали
то же самое.
"""

from __future__ import annotations

import hashlib
import os
import re
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
SETUP_NAME = f"{NAME}-Setup"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
INSTALLER_SCRIPT = ROOT / "installer" / f"{NAME}.iss"

ISCC_PLACES = tuple(
    Path(os.environ.get(variable, default)) / "Inno Setup 6" / "ISCC.exe"
    for variable, default in (
        ("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        ("PROGRAMFILES", r"C:\Program Files"),
    )
)


def version_numbers(version: str) -> tuple[int, int, int, int]:
    """«0.1.51» → (0, 1, 51, 0). Хвосты вроде `d` и `-rc.1` в числа не идут.

    У ресурса версии Windows ровно четыре числа, а у нас в номере бывают и
    буквенный суффикс (правка поверх апстрима), и пре-релиз.
    """
    found = [int(part) for part in re.findall(r"\d+", version.split("-")[0])[:3]]
    found += [0] * (4 - len(found))
    return tuple(found)  # type: ignore[return-value]


def version_resource(version: str) -> str:
    """Текст ресурса версии для `--version-file`.

    Без него у `.exe` пустые «Издатель», «Описание» и «Версия» в свойствах файла.
    Неподписанный файл, который просит права администратора, грузит драйвер и
    ничего о себе не сообщает, выглядит для эвристик антивируса подозрительнее
    такого же с заполненными полями и ссылкой на репозиторий. Это не защита и не
    обход чего-либо: честные метаданные, какие есть у любой обычной программы.
    """
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = version_numbers(version)
    strings = [
        ("CompanyName", "ZapretXmel project"),
        # Это поле Windows показывает как имя программы: в диспетчере задач и
        # в уведомлениях. Длинное описание выглядело там огромной строкой.
        ("FileDescription", NAME),
        ("FileVersion", version),
        ("InternalName", NAME),
        ("LegalCopyright", "Licensed under GPL-3.0-only"),
        ("OriginalFilename", f"{NAME}.exe"),
        ("ProductName", NAME),
        ("ProductVersion", version),
        ("Comments", "https://github.com/igorxmel/ZapretXmel"),
    ]
    info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numbers,
            prodvers=numbers,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,  # Windows NT
            fileType=0x1,  # приложение
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            # 0409 — английский (США), 04B0 — Unicode.
            StringFileInfo([StringTable("040904B0", [StringStruct(k, v) for k, v in strings])]),
            VarFileInfo([VarStruct("Translation", [0x409, 1200])]),
        ],
    )
    return str(info)


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


def build(onedir: bool = False) -> Path:
    """Собирает программу. Одним файлом — в `dist`, папкой — в `build/onedir`.

    Папка не кладётся в `dist`: в релиз она уходит только внутри установщика.
    """
    BUILD.mkdir(parents=True, exist_ok=True)
    version_file = BUILD / "version_info.txt"
    version_file.write_text(version_resource(__version__), encoding="utf-8")

    mode = "onedir" if onedir else "onefile"
    target = BUILD / "onedir" if onedir else DIST

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        f"--{mode}",
        f"--distpath={target}",
        f"--workpath={BUILD / mode}",
        f"--specpath={BUILD / mode}",
        "--windowed",
        # UPX сжимает исполняемый файл упаковщиком, и именно упакованные файлы
        # антивирусы подозревают первыми. Выигрыш — несколько мегабайт, цена —
        # ложные срабатывания; PyInstaller берёт UPX сам, если тот есть в PATH.
        "--noupx",
        f"--version-file={version_file}",
        f"--name={NAME}",
        f"--icon={ROOT / 'assets' / 'logo.ico'}",
        # Картинки нужны в собранном виде: logo для значка и трея,
        # banner для шапки, chevron для выпадающих списков.
        f"--add-data={ROOT / 'assets'}{';'}assets",
        # Список изменений показывается в окне «что нового» после
        # обновления; кладём к картинкам — это единственная папка с
        # данными, которую забирает сборка.
        f"--add-data={ROOT / 'CHANGELOG.md'}{';'}assets",
        # То же для вопросов в окне справки: сети может не быть именно из-за
        # блокировок, про которые человек и спрашивает.
        f"--add-data={ROOT / 'FAQ.md'}{';'}assets",
        # Точка входа — файл внутри пакета, поэтому в путях разбора оказывается
        # папка app, а не корень проекта: без этой строки `app.core` ищется и
        # не находится. На машине разработчика корень попадает в пути сам —
        # через установку `pip install -e .`, — и сборка получается рабочей,
        # а на чистой сборочной машине падает при первом же импорте.
        f"--paths={ROOT}",
        # Пакет собирается целиком. Часть модулей подтягивается отложенным
        # импортом внутри функций (экраны, профили, место установки), и по
        # одному анализу вызовов PyInstaller их не видит.
        "--collect-submodules=app",
        # Запрос прав вшивается в манифест, иначе программа каждый раз
        # перезапускалась бы через UAC вручную.
        "--uac-admin",
        # Выполняется до импорта Qt: ловит чужие пути во временную папку,
        # доставшиеся от программы, которая нас запустила.
        f"--runtime-hook={ROOT / 'tools' / 'runtime_hook_clean_env.py'}",
        str(ROOT / "app" / "__main__.py"),
    ]

    print("собираю:", NAME, __version__, mode)
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit("PyInstaller завершился с ошибкой")

    built = target / NAME / f"{NAME}.exe" if onedir else target / f"{NAME}.exe"
    if not built.exists():
        raise SystemExit(f"не найден результат сборки: {built}")
    return built


def find_iscc() -> Path:
    """Компилятор Inno Setup: из переменной ISCC, из PATH или из стандартной папки."""
    candidates = [os.environ.get("ISCC", ""), shutil.which("ISCC") or "", *ISCC_PLACES]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise SystemExit(
        "не найден Inno Setup 6 (ISCC.exe) — поставьте его или соберите без установщика:\n"
        "    python tools/build_release.py --portable-only"
    )


def build_installer(folder: Path) -> Path:
    """Собирает установщик поверх сборки папкой."""
    numbers = ".".join(str(part) for part in version_numbers(__version__))
    command = [
        str(find_iscc()),
        "/Q",
        f"/DAppVersion={__version__}",
        f"/DFileVersion={numbers}",
        f"/DSourceDir={folder}",
        f"/DOutputDir={DIST}",
        f"/DRoot={ROOT}",
        str(INSTALLER_SCRIPT),
    ]
    print("собираю установщик:", SETUP_NAME, __version__)
    result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        raise SystemExit("Inno Setup завершился с ошибкой")

    built = DIST / f"{SETUP_NAME}.exe"
    if not built.exists():
        raise SystemExit(f"не найден установщик: {built}")
    return built


def write_hash(path: Path) -> Path:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(256 * 1024), b""):
            digest.update(chunk)

    target = path.with_suffix(path.suffix + ".sha256")
    target.write_text(f"{digest.hexdigest()}  {path.name}\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    portable_only = "--portable-only" in (sys.argv[1:] if argv is None else argv)
    ensure_dependencies()
    if not portable_only:
        find_iscc()  # до долгой сборки, а не после неё

    for directory in (DIST, BUILD):
        shutil.rmtree(directory, ignore_errors=True)

    built = [build()]
    if not portable_only:
        built.append(build_installer(build(onedir=True).parent))

    print()
    for path in built:
        checksum = write_hash(path)
        size = path.stat().st_size / 1024 / 1024
        print(f"готово: {path}  ({size:.1f} МБ)")
        print(f"хеш:    {checksum}")
    print()
    print("Выкладывать в релиз нужно все файлы вместе с .sha256.")
    print(
        f"Имена менять нельзя — самообновление ищет ровно «{NAME}.exe» и «{SETUP_NAME}.exe»."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
