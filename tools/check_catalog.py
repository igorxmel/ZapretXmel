"""Проверяет данные ветки без запуска кода оболочки."""

import argparse
from pathlib import Path

from ui_packages import PackageError, load_catalog, load_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        entries = load_catalog(args.root)
        for name in sorted(entries):
            routes = load_package(args.root, name)
            directory = args.root / name
            expected = {url[1:] for url in routes if url != "/"} | {"manifest.json"}
            if {item.name for item in directory.iterdir()} != expected:
                raise PackageError(f"Содержимое {name} не совпадает с манифестом.")
            print(f"Проверен пакет {name}")
    except (PackageError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"Пакетов проверено: {len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
