"""Снимает экраны приложения в PNG для проверки оформления.

Используется родной графический слой Windows, иначе Qt не подгрузит системные
шрифты и весь текст выйдет пустыми квадратами. Чтобы окно при этом не мелькало
на экране и не перехватывало фокус, выставляется WA_DontShowOnScreen: разметка
и отрисовка выполняются полностью, а на рабочий стол ничего не попадает.

    python tools/screenshot.py [папка]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.ui.shell import MainWindow  # noqa: E402
from app.ui.theme import build_stylesheet  # noqa: E402
from app.ui.theme.tokens import SIZE  # noqa: E402

VIEWS = (
    "dashboard",
    "strategies",
    "autopick",
    "lists",
    "profiles",
    "telegram",
    "diagnostics",
    "updates",
    "settings",
    "support",
    "logs",
)


def main() -> int:
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "data/screenshots")
    destination.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(build_stylesheet())
    window = MainWindow(Settings.load())
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    # Снимаем в размере, с которым окно открывается на самом деле: на меньшем
    # подсказки переносятся иначе, и снимки показывают проблемы, которых нет.
    window.resize(SIZE["window_width"], SIZE["window_height"])
    window.show()

    for _ in range(3):
        app.processEvents()

    for name in VIEWS:
        window.navigate(name)
        # Часть экранов догружает данные в фоне — даём им время ответить,
        # иначе на снимке окажется пустая заготовка.
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)

        path = destination / f"{name}.png"
        window.grab().save(str(path))
        print(f"{path}")

    window.controller.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
