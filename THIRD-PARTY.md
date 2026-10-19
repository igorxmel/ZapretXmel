# Сторонние компоненты

Программа состоит из своего кода под GPLv3 и чужих частей под своими лицензиями.
Здесь перечислены все; под GPLv3 выпускается собранный `ZapretXmel.exe` целиком.

## Внутри сборки

Эти библиотеки PyInstaller кладёт прямо в `.exe`.

| Компонент | Лицензия | Что делает |
|---|---|---|
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) (Riverbank) | GPL-3.0-only | Привязки Qt к Python — весь интерфейс |
| [Qt 6](https://www.qt.io/) (The Qt Company) | LGPL-3.0 | Сам графический слой |
| [PyQt6-sip](https://pypi.org/project/PyQt6-sip/) | BSD-2-Clause | Прослойка между Python и C++ |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause | Перебор процессов и сетевых соединений |
| [requests](https://github.com/psf/requests) | Apache-2.0 | Запросы к GitHub и к сервисам разбора |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | MIT | Необязательная зависимость: разбор через Claude |

**Именно PyQt6 определяет лицензию всей сборки.** Riverbank выпускает его под
GPLv3 либо по платной коммерческой лицензии, третьего нет; собранный одним
файлом `.exe` содержит его внутри и потому распространяется на условиях GPLv3.
Qt при этом под LGPL — ограничение идёт не от него, а от привязок.

## Скачивается во время работы

Этого в репозитории и в сборке нет. Программа забирает всё перечисленное из
официальных релизов при первом запуске и при обновлении; каждый файл сверяется
с хешем, который GitHub публикует рядом с ним.

| Компонент | Лицензия | Что делает |
|---|---|---|
| [zapret](https://github.com/bol-van/zapret) (bol-van) | MIT | Сам обход блокировок |
| [zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) (Flowseal) | MIT | Сборка zapret со стратегиями — ядро программы |
| [WinDivert](https://github.com/basil00/WinDivert) (basil00) | LGPL-3.0 либо GPL-2.0 на выбор получателя | Драйвер перехвата пакетов, идёт внутри сборки Flowseal |
| [tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) (Flowseal) | MIT | Локальный MTProto-прокси для Telegram |

## Данные, а не код

| Источник | Лицензия | Что берём |
|---|---|---|
| [dpi-checkers](https://github.com/hyperion-cs/dpi-checkers) (hyperion-cs) | Apache-2.0 | Набор хостов для режима «Проверка DPI» и сама методика проверки по переданным байтам |

Кода оттуда не взято ни строки: список хостов запрашивается с их страницы во
время проверки и нигде не копируется.
