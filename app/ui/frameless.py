"""Окно без системной рамки, но с родным поведением краёв.

Простой `FramelessWindowHint` снимает с окна системные стили, а вместе с ними
исчезают прилипание к краям, Aero Snap и ресайз силами Windows. Поэтому стили
возвращаются обратно, а рисовать рамку системе запрещается ответом на
`WM_NCCALCSIZE`: неклиентской области у окна нет, всё рисуем сами.

Перетаскивание и растягивание отдаются системе через `startSystemMove` и
`startSystemResize` — тогда работают и прилипание к краям экрана, и разворот
броском окна вверх.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PyQt6.QtCore import QEvent, QSize, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QFontDatabase, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOption,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme.tokens import SPACE

WINDOWS = sys.platform == "win32"

TITLEBAR_HEIGHT = 40

# Ссылки наружу. Держим их здесь, а не в разделах: страница проекта и
# исходники нужны из любого места программы, а заголовок виден всегда.
LINKS = (
    ("ВЕБ-САЙТ", "https://igorxmel.github.io/ZapretXmel/"),
    ("GITHUB", "https://github.com/igorxmel/ZapretXmel"),
)
GRIP_THICKNESS = 5

# Значки кнопок окна из иконочного шрифта Windows. Обычные символы тут не
# годятся: минус, квадрат и крестик взяты из разных мест текстового шрифта и
# рядом смотрятся разной толщины и на разной высоте.
GLYPH_MINIMIZE = chr(0xE921)  # ChromeMinimize
GLYPH_MAXIMIZE = chr(0xE922)  # ChromeMaximize
GLYPH_RESTORE = chr(0xE923)  # ChromeRestore
GLYPH_CLOSE = chr(0xE8BB)  # ChromeClose

ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

# Текстовые запасные значки на случай, если иконочного шрифта нет.
FALLBACK_GLYPHS = {
    GLYPH_MINIMIZE: "—",
    GLYPH_MAXIMIZE: "□",
    GLYPH_RESTORE: "❐",
    GLYPH_CLOSE: "✕",
}


if WINDOWS:
    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_MAXIMIZEBOX = 0x00010000
    WS_MINIMIZEBOX = 0x00020000

    WM_NCCALCSIZE = 0x0083
    WM_GETMINMAXINFO = 0x0024

    SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 1, 2, 4, 32
    SM_CXSIZEFRAME, SM_CXPADDEDBORDER = 32, 92

    class _NcCalcSizeParams(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class _MinMaxInfo(ctypes.Structure):
        _fields_ = [
            ("ptReserved", wintypes.POINT),
            ("ptMaxSize", wintypes.POINT),
            ("ptMaxPosition", wintypes.POINT),
            ("ptMinTrackSize", wintypes.POINT),
            ("ptMaxTrackSize", wintypes.POINT),
        ]

    def _window_long_funcs():
        user32 = ctypes.windll.user32
        get = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        put = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        get.restype = put.restype = ctypes.c_ssize_t
        get.argtypes = [wintypes.HWND, ctypes.c_int]
        put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        return get, put

    def enable_native_frame(handle: int) -> None:
        """Возвращает окну системные стили рамки ради прилипания и ресайза."""
        get, put = _window_long_funcs()
        style = get(handle, GWL_STYLE)
        put(
            handle,
            GWL_STYLE,
            style | WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX,
        )
        ctypes.windll.user32.SetWindowPos(
            handle, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
        )

    def frame_border() -> int:
        metric = ctypes.windll.user32.GetSystemMetrics
        return metric(SM_CXSIZEFRAME) + metric(SM_CXPADDEDBORDER)


def icon_font(size: int = 10) -> QFont | None:
    """Шрифт со значками кнопок окна, если он есть в системе."""
    families = QFontDatabase.families()
    for name in ICON_FONTS:
        if name in families:
            font = QFont(name)
            font.setPointSize(size)
            return font
    return None


class CaptionButton(QPushButton):
    """Кнопка свернуть / развернуть / закрыть."""

    def __init__(self, glyph: str, tooltip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CaptionButton")
        self.setFixedSize(QSize(46, TITLEBAR_HEIGHT))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(tooltip)

        self._font = icon_font()
        if self._font is not None:
            self.setFont(self._font)
        self.set_glyph(glyph)

    def set_glyph(self, glyph: str) -> None:
        self.setText(glyph if self._font is not None else FALLBACK_GLYPHS.get(glyph, glyph))


class TitleBar(QWidget):
    """Свой заголовок окна: логотип, название и кнопки управления."""

    def __init__(
        self,
        window: FramelessWindow,
        title: str,
        compact: bool = False,
        caption: str = "",
    ):
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(TITLEBAR_HEIGHT)

        row = QHBoxLayout(self)
        row.setContentsMargins(SPACE["md"], 0, 0, 0)
        row.setSpacing(SPACE["sm"])

        # У главного окна ни значка, ни названия: и то, и другое есть на
        # баннере в боковом меню прямо под заголовком, повторять их дважды
        # незачем. А вот у отдельного окна баннера нет, и без подписи
        # непонятно, что это вообще открылось.
        if caption:
            label = QLabel(caption)
            label.setObjectName("TitleCaption")
            row.addWidget(label)

        row.addStretch(1)

        # Ссылки наружу живут в заголовке: в разделах им места нет, а найти
        # сайт и исходники человек должен из любого места программы.
        if not compact:
            for text, url in LINKS:
                row.addWidget(self._link(text, url))

            # Линия отделяет ссылки от кнопок управления: без неё надписи
            # читаются как часть той же группы, а это разные вещи — одни
            # открывают браузер, другие управляют окном.
            separator = QWidget()
            separator.setObjectName("TitleSeparator")
            separator.setFixedWidth(1)
            row.addSpacing(SPACE["sm"])
            row.addWidget(separator)
            row.addSpacing(SPACE["sm"])

        # У вспомогательных окон остаётся только закрытие: сворачивать и
        # разворачивать там нечего, а лишние кнопки сбивают с толку.
        self.maximize: CaptionButton | None = None
        if not compact:
            minimize = CaptionButton(GLYPH_MINIMIZE, "Свернуть")
            minimize.clicked.connect(window.showMinimized)
            row.addWidget(minimize)

            self.maximize = CaptionButton(GLYPH_MAXIMIZE, "Развернуть")
            self.maximize.clicked.connect(self.toggle_maximize)
            row.addWidget(self.maximize)

        close = CaptionButton(GLYPH_CLOSE, "Закрыть")
        close.setProperty("close", True)
        close.clicked.connect(window.close)
        row.addWidget(close)

    @staticmethod
    def _link(text: str, url: str) -> QPushButton:
        """Надпись-ссылка в заголовке: открывает страницу в браузере."""
        link = QPushButton(text)
        link.setObjectName("TitleLink")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.setToolTip(url)
        link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return link

    def toggle_maximize(self) -> None:
        if self.maximize is None:
            return
        window = self.window_ref
        window.showNormal() if window.isMaximized() else window.showMaximized()

    def sync_state(self) -> None:
        """У развёрнутого окна кнопка меняется на «вернуть как было»."""
        if self.maximize is None:
            return
        maximized = self.window_ref.isMaximized()
        self.maximize.set_glyph(GLYPH_RESTORE if maximized else GLYPH_MAXIMIZE)
        self.maximize.setToolTip("Вернуть как было" if maximized else "Развернуть")

    def paintEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        """Рисует фон и нижнюю линию из таблицы стилей.

        Подклассам QWidget Qt оформление из QSS сам не рисует — нужно явно
        попросить стиль отрисовать подложку. Без этого ни фон полосы, ни
        отделяющая её линия не появляются вовсе.
        """
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_Widget, option, painter, self
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        # Перетаскивание отдаём системе: так работают прилипание и Aero Snap.
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window_ref.windowHandle()
            if handle:
                handle.startSystemMove()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        self.toggle_maximize()


class Grip(QWidget):
    """Полоска у края окна: свой курсор и растягивание силами системы.

    Отдельные виджеты, а не обработка мыши на самом окне: события мыши до окна
    не доходят — их забирают дочерние виджеты, и курсор у краёв не меняется.
    """

    def __init__(self, parent: QWidget, edges: Qt.Edge, cursor: Qt.CursorShape):
        super().__init__(parent)
        self.edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle:
                handle.startSystemResize(self.edges)


class FramelessWindow(QWidget):
    """Окно со своим заголовком и родным поведением краёв.

    Содержимое складывается в `self.body`.
    """

    def __init__(
        self,
        title: str,
        compact: bool = False,
        resizable: bool | None = None,
        caption: str = "",
    ):
        """`compact` убирает ссылки и кнопки окна, `resizable` — ручки краёв.

        Разведены нарочно: вспомогательному окну ссылки и сворачивание ни к
        чему, но растягивать его бывает нужно — например, разбору
        нейросетью, где ответ длинный, а названия моделей не помещаются.
        """
        super().__init__()
        self.setWindowFlag(Qt.WindowType.Window)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self._native_frame = False

        shell = QVBoxLayout(self)
        shell.setContentsMargins(1, 1, 1, 1)
        shell.setSpacing(0)

        self.frame = QFrame()
        self.frame.setObjectName("WindowFrame")
        shell.addWidget(self.frame)

        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        self.titlebar = TitleBar(self, title, compact=compact, caption=caption)
        inner.addWidget(self.titlebar)

        self.body = QWidget()
        inner.addWidget(self.body, 1)

        self.grips: list[Grip] = []
        if resizable is None:
            resizable = not compact
        edges_and_cursors = () if not resizable else (
            (Qt.Edge.TopEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.BottomEdge, Qt.CursorShape.SizeVerCursor),
            (Qt.Edge.LeftEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.RightEdge, Qt.CursorShape.SizeHorCursor),
            (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.BottomEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeFDiagCursor),
            (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.CursorShape.SizeBDiagCursor),
            (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge, Qt.CursorShape.SizeBDiagCursor),
        )
        for edges, cursor in edges_and_cursors:
            self.grips.append(Grip(self, edges, cursor))

    # --- системная рамка -------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().showEvent(event)
        if WINDOWS and not self._native_frame:
            enable_native_frame(int(self.winId()))
            self._native_frame = True

        # Ручки созданы раньше содержимого и лежат под ним — поднимаем наверх.
        for grip in self.grips:
            grip.raise_()

    def nativeEvent(self, kind, message):  # noqa: N802 — имя задано Qt
        if not self._native_frame or kind != b"windows_generic_MSG":
            return False, 0

        msg = wintypes.MSG.from_address(int(message))

        # Размер окна теперь ограничивает Windows, а про наш минимум он не
        # знает — без этого окно сжимается до нечитаемой каши.
        if msg.message == WM_GETMINMAXINFO:
            ratio = self.devicePixelRatioF()
            limits = _MinMaxInfo.from_address(msg.lParam)
            limits.ptMinTrackSize.x = int(self.minimumWidth() * ratio)
            limits.ptMinTrackSize.y = int(self.minimumHeight() * ratio)
            return True, 0

        if msg.message != WM_NCCALCSIZE:
            return False, 0

        # Нулевая неклиентская область: системную рамку не рисуем.
        # Про «развёрнуто» спрашиваем Windows, а не Qt: когда окно возвращают
        # из развёрнутого состояния перетаскиванием, Qt узнаёт об этом позже и
        # isMaximized() ещё отвечает «да» — в вычтенной полосе система успевает
        # нарисовать второй заголовок поверх нашего.
        if msg.wParam and ctypes.windll.user32.IsZoomed(int(self.winId())):
            border = frame_border()
            rect = _NcCalcSizeParams.from_address(msg.lParam).rgrc[0]
            rect.left += border
            rect.top += border
            rect.right -= border
            rect.bottom -= border
        return True, 0

    # --- края ------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().resizeEvent(event)
        self._place_grips()

    def changeEvent(self, event) -> None:  # noqa: N802 — имя задано Qt
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._place_grips()
            self.titlebar.sync_state()
            self._sync_edges()

    def _sync_edges(self) -> None:
        """Развёрнутому окну рамка и скруглённые углы не нужны."""
        maximized = self.isMaximized()
        self.layout().setContentsMargins(*((0, 0, 0, 0) if maximized else (1, 1, 1, 1)))
        self.frame.setProperty("flat", maximized)
        self.frame.style().unpolish(self.frame)
        self.frame.style().polish(self.frame)

    def _place_grips(self) -> None:
        if not self.grips:
            return

        if self.isMaximized():
            for grip in self.grips:
                grip.hide()
            return

        width, height = self.width(), self.height()
        thickness = GRIP_THICKNESS
        geometry = (
            (thickness, 0, width - thickness * 2, thickness),
            (thickness, height - thickness, width - thickness * 2, thickness),
            (0, thickness, thickness, height - thickness * 2),
            (width - thickness, thickness, thickness, height - thickness * 2),
            (0, 0, thickness, thickness),
            (width - thickness, height - thickness, thickness, thickness),
            (width - thickness, 0, thickness, thickness),
            (0, height - thickness, thickness, thickness),
        )
        for grip, rect in zip(self.grips, geometry, strict=True):
            grip.setGeometry(*rect)
            grip.show()
