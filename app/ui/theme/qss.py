"""Сборка таблицы стилей из токенов.

Qt не знает CSS-переменных, поэтому стили собираются подстановкой значений из
`tokens.py`. Зато правило остаётся одно на весь интерфейс: цвета и отступы
нигде не пишутся числами по месту.
"""

from __future__ import annotations

from app.core import paths
from app.ui.theme.tokens import BRAND, COLORS, FONT_SIZE, FONTS, RADIUS, SIZE, SPACE


def _asset_url(name: str) -> str:
    """Путь к картинке в виде, который понимает QSS: прямые слэши."""
    return str(paths.assets_dir() / name).replace("\\", "/")


def build_stylesheet() -> str:
    c, s, r, z = COLORS, SPACE, RADIUS, SIZE
    chevron = _asset_url("chevron.png")
    chevron_hover = _asset_url("chevron-hover.png")
    return f"""
    QWidget {{
        background: {c["bg"]};
        color: {c["text"]};
        font-family: {FONTS["ui"]};
        font-size: {FONT_SIZE["body"]}px;
    }}

    /* Подписи и флажки не должны закрашивать фон: иначе на карточке, у которой
       своя поверхность, они проступают тёмными прямоугольниками. */
    QLabel, QCheckBox, QRadioButton {{
        background: transparent;
    }}

    QToolTip {{
        background: {c["elevated"]};
        color: {c["text"]};
        border: 1px solid {c["border"]};
        padding: {s["xs"]}px {s["sm"]}px;
    }}

    /* --- окно и свой заголовок --- */

    /* Углы прямые намеренно. Скругление рисовалось бы только внутри окна, а
       само окно остаётся прямоугольным — получается светлая ступенька по углам
       вместо скругления. Настоящее скругление окна умеет лишь Windows 11,
       поэтому честнее прямой угол: он и так родной для десятки. */
    QFrame#WindowFrame {{
        background: {c["bg"]};
        border: 1px solid {c["border_strong"]};
        border-radius: 0;
    }}

    QFrame#WindowFrame[flat="true"] {{ border: none; }}

    /* Полоса заголовка отделяется заметной линией, а не той, что идёт по
       границам карточек: на почти одинаковых по яркости поверхностях слабая
       линия пропадает, и кнопки управления выглядят висящими в воздухе. */
    #TitleBar {{
        background: {c["sidebar"]};
        border-bottom: 1px solid {c["border_strong"]};
    }}

    QLabel#TitleBarText {{
        color: {c["text_dim"]};
        font-size: {FONT_SIZE["caption"]}px;
    }}

    QPushButton#CaptionButton {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 0;
        min-height: 0;
        color: {c["text_dim"]};
        font-family: {FONTS["icons"]};
        font-size: 10px;
    }}

    QPushButton#CaptionButton:hover {{ background: {c["elevated"]}; color: {c["text"]}; }}
    QPushButton#CaptionButton:pressed {{ background: {c["surface_hover"]}; }}

    /* Закрытие помечено свойством, а не отдельным objectName: иначе кнопка
       выпала бы из правил выше и нарисовалась обычной, с рамкой. */
    QPushButton#CaptionButton[close="true"]:hover {{
        background: {c["danger"]};
        color: {c["text"]};
    }}

    /* Полоса о новой версии. Единственное место, кроме активного пункта
       меню, где появляется оранжевый: это и есть сигнал «обрати внимание». */
    #UpdateBanner {{
        background: {c["surface"]};
        border: 1px solid {BRAND["orange"]};
        border-radius: {r["md"]}px;
    }}

    #UpdateBannerText {{
        background: transparent;
        color: {c["text"]};
        font-weight: 600;
    }}

    QPushButton#BannerClose {{
        background: transparent;
        border: none;
        color: {c["text_muted"]};
        font-family: {FONTS["icons"]};
        font-size: {FONT_SIZE["caption"]}px;
        padding: {s["xs"]}px {s["sm"]}px;
    }}

    QPushButton#BannerClose:hover {{ color: {c["text"]}; }}

    /* --- боковое меню --- */

    #Sidebar {{
        background: {c["sidebar"]};
        border-right: 1px solid {c["border"]};
    }}

    /* Шапка меню отделена от пунктов такой же линией, какими разделены
       блоки по всему окну: логотип с версией — своя часть, и без неё он
       сливался со списком разделов. */
    QPushButton#TitleLink {{
        background: transparent;
        border: none;
        color: {c["text_muted"]};
        font-size: {FONT_SIZE["caption"]}px;
        font-weight: 600;
        letter-spacing: 1px;
        padding: {s["xs"]}px {s["sm"]}px;
    }}

    QPushButton#TitleLink:hover {{
        color: {c["text"]};
    }}

    /* Подпись отдельного окна: у него нет баннера в боковом меню, и без
       неё непонятно, что именно открылось. */
    QLabel#TitleCaption {{
        color: {c["text_muted"]};
        font-size: {FONT_SIZE["caption"]}px;
        font-weight: 600;
        letter-spacing: 1px;
        padding-left: {s["xs"]}px;
    }}

    #TitleSeparator {{
        background: {c["border"]};
        margin: {s["md"]}px 0;
    }}

    #SidebarHeader {{
        /* Фон обязан быть прозрачным: рамка делает виджет styled, и он
           начинает заливать свою область фоном окна — вместе с ней
           пропадала и правая граница меню. */
        background: transparent;
        border-bottom: 1px solid {c["border"]};
    }}

    #SidebarLogo {{
        color: {c["text"]};
        font-size: {FONT_SIZE["subtitle"]}px;
        font-weight: 600;
    }}

    #SidebarVersion {{
        color: {c["text_muted"]};
        font-size: {FONT_SIZE["caption"]}px;
    }}

    QPushButton#NavButton {{
        background: transparent;
        border: none;
        outline: none;
        border-left: 2px solid transparent;
        border-radius: 0;
        color: {c["text_dim"]};
        text-align: left;
        padding: {s["sm"]}px {s["lg"]}px;
        min-height: {z["row_height"]}px;
    }}

    QPushButton#NavButton:hover {{
        background: {c["surface"]};
        color: {c["text"]};
    }}

    /* Пункт с непрочитанной новостью: человек мог закрыть полосу, но
       напоминание должно остаться там, куда он за обновлением пойдёт. */
    QPushButton#NavButton[alert="true"] {{
        color: {BRAND["orange"]};
    }}

    QPushButton#NavButton:checked {{
        background: {c["surface"]};
        color: {c["text"]};
        font-weight: 600;
    }}

    /* --- заголовки и текст --- */

    QLabel#ViewTitle {{
        font-size: {FONT_SIZE["title"]}px;
        font-weight: 600;
        color: {c["text"]};
    }}

    QLabel#ViewSubtitle {{ color: {c["text_dim"]}; }}

    QLabel#SectionTitle {{
        color: {c["text_muted"]};
        font-size: {FONT_SIZE["caption"]}px;
        font-weight: 600;
        letter-spacing: 1px;
    }}

    QLabel#Dim {{ color: {c["text_dim"]}; }}
    QLabel#Muted {{ color: {c["text_muted"]}; font-size: {FONT_SIZE["caption"]}px; }}
    QLabel#Display {{ font-size: {FONT_SIZE["display"]}px; font-weight: 600; }}

    /* Вопрос в своём модальном окне — вместо системного QMessageBox. */
    QLabel#DialogText {{ font-size: {FONT_SIZE["subtitle"]}px; font-weight: 600; }}

    /* --- карточки --- */

    QFrame#Card {{
        background: {c["surface"]};
        border: 1px solid {c["border"]};
        border-radius: {r["lg"]}px;
    }}

    QFrame#Divider {{
        background: {c["border"]};
        max-height: 1px;
        border: none;
    }}

    /* --- кнопки --- */

    /* Без outline Qt рисует вокруг кнопки с фокусом пунктирный прямоугольник —
       он появляется после щелчка и выглядит как случайная обводка. */
    QPushButton {{
        background: {c["elevated"]};
        border: 1px solid {c["border"]};
        border-radius: {r["md"]}px;
        color: {c["text"]};
        padding: {s["sm"]}px {s["lg"]}px;
        min-height: {z["control_height"]}px;
        outline: none;
    }}

    QPushButton:hover {{ background: {c["surface_hover"]}; border-color: {c["border_strong"]}; }}
    QPushButton:pressed {{ background: {c["surface"]}; }}
    QPushButton:disabled {{ color: {c["text_muted"]}; background: {c["surface"]}; }}

    QPushButton#Primary {{
        background: {c["accent"]};
        border: 1px solid {c["accent"]};
        color: {c["text_inverted"]};
        font-weight: 600;
    }}

    QPushButton#Primary:hover {{ background: {c["accent_hover"]}; }}
    QPushButton#Primary:disabled {{
        background: {c["elevated"]};
        border-color: {c["border"]};
        color: {c["text_muted"]};
    }}

    QPushButton#Danger {{ border-color: {c["danger"]}; color: {c["danger"]}; }}
    QPushButton#Danger:hover {{ background: {c["danger"]}; color: {c["text"]}; }}

    QPushButton#Ghost {{
        background: transparent;
        border: none;
        color: {c["text_dim"]};
        padding: {s["xs"]}px {s["sm"]}px;
        min-height: 0;
    }}

    QPushButton#Ghost:hover {{ color: {c["text"]}; }}

    /* Переключатель-таблетка: режимы выбираются им вместо выпадающего списка —
       все варианты видны сразу и не обрезаются по ширине. */
    QPushButton#Chip {{
        background: transparent;
        border: 1px solid {c["border"]};
        border-radius: {r["pill"]}px;
        color: {c["text_dim"]};
        font-size: {FONT_SIZE["caption"]}px;
        padding: {s["xs"]}px {s["md"]}px;
        min-height: 24px;
    }}

    QPushButton#Chip:hover {{ color: {c["text"]}; border-color: {c["border_strong"]}; }}
    QPushButton#Chip:checked {{
        background: {c["accent"]};
        border-color: {c["accent"]};
        color: {c["text_inverted"]};
        font-weight: 600;
    }}

    /* Выключенная таблетка должна выглядеть выключенной. В режиме проверки
       DPI сервисы не проверяются вовсе, но выбранные оставались белыми — и
       казалось, что проверка идёт и по DPI, и по ним заодно. */
    QPushButton#Chip:disabled {{
        color: {c["text_muted"]};
        border-color: {c["border"]};
    }}

    QPushButton#Chip:checked:disabled {{
        background: {c["surface_hover"]};
        border-color: {c["border"]};
        color: {c["text_muted"]};
        font-weight: 400;
    }}

    /* --- поля ввода --- */

    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
        background: {c["bg"]};
        border: 1px solid {c["border"]};
        border-radius: {r["md"]}px;
        padding: {s["xs"]}px {s["sm"]}px;
        selection-background-color: {c["accent"]};
        selection-color: {c["text_inverted"]};
        min-height: {z["control_height"]}px;
    }}

    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border-color: {c["border_strong"]};
    }}

    QPlainTextEdit, QTextEdit {{ font-family: {FONTS["mono"]}; }}

    /* Стрелку приходится задавать картинкой: нарисовать её средствами QSS
       нельзя, а символ из шрифта садится мимо центра. Путь абсолютный —
       относительный Qt считал бы от рабочей папки, а она у службы и у
       ярлыка разная. */
    QComboBox::drop-down {{
        border: none;
        width: {s["xl"]}px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{
        image: url({chevron});
        width: 14px;
        height: 14px;
    }}
    QComboBox::down-arrow:hover, QComboBox::down-arrow:on {{
        image: url({chevron_hover});
    }}
    QComboBox QAbstractItemView {{
        background: {c["elevated"]};
        border: 1px solid {c["border"]};
        selection-background-color: {c["accent"]};
        selection-color: {c["text_inverted"]};
        outline: none;
    }}

    /* --- списки и таблицы --- */

    QListWidget, QTreeWidget, QTableWidget {{
        background: {c["bg"]};
        border: 1px solid {c["border"]};
        border-radius: {r["md"]}px;
        outline: none;
    }}

    QListWidget {{ font-family: {FONTS["mono"]}; font-size: {FONT_SIZE["caption"]}px; }}

    QListWidget::item, QTreeWidget::item {{
        padding: {s["xs"]}px {s["sm"]}px;
        border-radius: {r["sm"]}px;
    }}

    /* Цвет выделения задаётся и для неактивного окна тоже: иначе Qt подставляет
       системный, и текст выбранной строки становится чёрным, стоит переключиться
       на другое приложение. */
    QListWidget::item:selected, QTreeWidget::item:selected,
    QListWidget::item:selected:!active, QTreeWidget::item:selected:!active {{
        background: {c["accent"]};
        color: {c["text_inverted"]};
    }}

    QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected {{
        background: {c["surface_hover"]};
    }}

    QHeaderView::section {{
        background: {c["bg"]};
        border: none;
        border-bottom: 1px solid {c["border"]};
        color: {c["text_muted"]};
        font-size: {FONT_SIZE["caption"]}px;
        font-weight: 600;
        padding: {s["sm"]}px {s["sm"]}px;
    }}

    QTableWidget {{ gridline-color: transparent; }}
    QTableWidget::item {{ padding: {s["xs"]}px {s["sm"]}px; border: none; }}
    QTableWidget::item:selected, QTableWidget::item:selected:!active {{
        background: {c["elevated"]};
        color: {c["text"]};
    }}

    /* --- прочие элементы --- */

    QCheckBox, QRadioButton {{ spacing: {s["sm"]}px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {c["border_strong"]};
        border-radius: {r["sm"]}px;
        background: {c["bg"]};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {c["accent"]};
        border-color: {c["accent"]};
    }}
    QRadioButton::indicator {{ border-radius: 8px; }}

    QProgressBar {{
        background: {c["bg"]};
        border: 1px solid {c["border"]};
        border-radius: {r["sm"]}px;
        height: 5px;
        text-align: center;
    }}
    QProgressBar::chunk {{ background: {BRAND["orange"]}; border-radius: {r["sm"]}px; }}

    /* Полоса шире самого ползунка: разницу съедают поля, и он не липнет
       ни к тексту слева, ни к краю окна справа. Без этого он проходил
       впритык к содержимому и читался как его часть. */
    QScrollBar:vertical {{
        background: transparent;
        width: {s["lg"]}px;
        margin: {s["xs"]}px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c["border_strong"]};
        border-radius: 3px;
        min-height: 28px;
        margin: 0 {s["xs"]}px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c["text_muted"]}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QScrollBar:horizontal {{
        background: transparent;
        height: {s["lg"]}px;
        margin: 0 {s["xs"]}px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c["border_strong"]};
        border-radius: 3px;
        min-width: 28px;
        margin: {s["xs"]}px 0;
    }}

    QScrollArea {{ border: none; background: transparent; }}

    QMenu {{
        background: {c["elevated"]};
        border: 1px solid {c["border_strong"]};
        border-radius: {r["md"]}px;
        padding: {s["sm"]}px;
    }}
    QMenu::item {{
        padding: {s["sm"]}px {s["xl"]}px {s["sm"]}px {s["md"]}px;
        border-radius: {r["sm"]}px;
        min-width: 180px;
    }}
    QMenu::item:selected {{ background: {c["surface_hover"]}; }}
    QMenu::item:disabled {{ color: {c["text_muted"]}; font-size: {FONT_SIZE["caption"]}px; }}
    QMenu::separator {{ height: 1px; background: {c["border"]}; margin: {s["xs"]}px {s["sm"]}px; }}
    """
