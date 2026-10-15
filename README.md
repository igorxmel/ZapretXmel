<div align="center">
  <img src="assets/banner.png" width="560" alt="ZapretXmel">

  <p>
    <strong>Графическая надстройка над сборкой
    <a href="https://github.com/Flowseal/zapret-discord-youtube">Flowseal/zapret-discord-youtube</a>:
    вместо батников и консольных меню — одно окно, а стратегия подбирается перебором автоматически.</strong>
  </p>

  <p>
    <a href="https://igorxmel.github.io/ZapretXmel/"><strong>Страница проекта</strong></a> ·
    <a href="https://github.com/igorxmel/ZapretXmel/releases/latest"><strong>Скачать</strong></a>
  </p>

  <p>
    <a href="https://github.com/igorxmel/ZapretXmel/releases/latest"><img alt="Версия" src="https://img.shields.io/github/v/release/igorxmel/ZapretXmel?style=flat&logo=github&label=%D0%B2%D0%B5%D1%80%D1%81%D0%B8%D1%8F&labelColor=141416&color=f5a000&logoColor=white"></a>
    <a href="https://github.com/igorxmel/ZapretXmel/stargazers"><img alt="Звёзды" src="https://img.shields.io/github/stars/igorxmel/ZapretXmel?style=flat&logo=github&label=%D0%B7%D0%B2%D1%91%D0%B7%D0%B4%D1%8B&labelColor=141416&color=8ebe3f&logoColor=white"></a>
    <a href="https://github.com/igorxmel/ZapretXmel/releases"><img alt="Скачивания" src="https://img.shields.io/github/downloads/igorxmel/ZapretXmel/total?style=flat&logo=github&label=%D1%81%D0%BA%D0%B0%D1%87%D0%B8%D0%B2%D0%B0%D0%BD%D0%B8%D1%8F&labelColor=141416&color=9f9fa6&logoColor=white"></a>
  </p>

  <p>
    <img alt="Windows" src="https://img.shields.io/badge/Windows%2010%2F11-64%20bit-141416?style=flat&logo=windows&logoColor=9f9fa6">
    <img alt="Python" src="https://img.shields.io/badge/Python-3.12-141416?style=flat&logo=python&logoColor=9f9fa6">
    <img alt="Qt" src="https://img.shields.io/badge/PyQt6-141416?style=flat&logo=qt&logoColor=9f9fa6">
    <a href="LICENSE"><img alt="Лицензия" src="https://img.shields.io/badge/%D0%BB%D0%B8%D1%86%D0%B5%D0%BD%D0%B7%D0%B8%D1%8F-MIT-141416?style=flat&logoColor=9f9fa6"></a>
  </p>
</div>

## <img src="assets/icons/sparkle.png" width="22" align="top"> Возможности

- **Включение одной кнопкой** — службой Windows или обычным процессом, плюс значок в трее.
- **Подбор стратегии перебором** по всем сервисам сразу, с честным замером «без обхода».
- **Профили приложений** — пропустить через обход отдельную игру или клиент.
- **Telegram** через локальный MTProto-прокси: стратегии его не чинят, а это чинит.
- **Диагностика** по правилам плюс разбор нейросетью или выгрузка пакета для любого чат-бота.
- **Обновление ядра** с бэкапом и откатом; пользовательские списки переносятся сами.
- **Слежение за апстримом** — отчёт о том, чего интерфейс ещё не умеет.

## <img src="assets/icons/download.png" width="22" align="top"> Установка

1. Скачайте `ZapretXmel.exe` из [последнего релиза](https://github.com/igorxmel/ZapretXmel/releases/latest).
2. Положите его в отдельную папку — рядом появятся ядро и настройки.
3. Запустите. Права администратора программа запросит сама.

Ядро zapret внутрь не вшито: при первом запуске оно скачивается из официальных релизов
Flowseal. Так вы всегда получаете актуальную сборку, а не ту, что была на момент нашей.

Обновляется программа сама — в разделе «Обновления».

## <img src="assets/icons/monitor.png" width="22" align="top"> Требования

- Windows 10 или 11, 64 бита.
- Права администратора: без них недоступны служба и драйвер WinDivert.

## <img src="assets/icons/box.png" width="22" align="top"> Что внутри

| Часть | Откуда |
|---|---|
| Ядро обхода | [bol-van/zapret](https://github.com/bol-van/zapret) в сборке [Flowseal](https://github.com/Flowseal/zapret-discord-youtube) |
| Прокси для Telegram | [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy) |
| Хосты для проверки DPI | [hyperion-cs/dpi-checkers](https://github.com/hyperion-cs/dpi-checkers) |

Ничего из этого не форкается и не вкладывается в репозиторий: всё скачивается из
официальных релизов и обновляется отдельно от программы.

## <img src="assets/icons/target.png" width="22" align="top"> Чем отличается подбор стратегии

Обычная проверка «открылась ли страница» у многих провайдеров проходит и без обхода —
и тогда «лучшей» становится стратегия, которая просто ничего не сломала. Поэтому здесь:

- **первым делом меряется, как всё работает без обхода** — это точка отсчёта,
  и стратегия считается выигрышной, только если её превзошла;
- **счёт ведётся по сервисам**, а не общей суммой: иначе стратегия, чинящая ютуб
  и ломающая дискорд, обходит ту, после которой работает и то, и другое;
- **Discord проверяется тремя шагами самого клиента** — запрос к API, рукопожатие
  с гейтвеем, загрузка картинок. Его страница открывается и когда клиент не работает;
- если победитель что-то так и не починил, **об этом говорится прямо**;
- **активный VPN распознаётся** и подбор не запускается: через туннель открывается
  всё подряд, и измерять там нечего.

## <img src="assets/icons/code.png" width="22" align="top"> Разработка

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"

.venv\Scripts\python -m app                   # запуск
.venv\Scripts\python -m pytest tests/ -q      # тесты
.venv\Scripts\python -m ruff check app/ tests/ tools/
.venv\Scripts\python tools/screenshot.py      # снимки экранов
.venv\Scripts\python tools/build_release.py   # сборка .exe
```

Сверка с апстримом — что изменилось в сборке Flowseal и чего интерфейс ещё не умеет:

```powershell
.venv\Scripts\python tools/upstream_sync.py
```

Устройство проекта и правила — в [CLAUDE.md](CLAUDE.md).

## <img src="assets/icons/branch.png" width="22" align="top"> Как помочь

Pull request'ы открыты, и мелкие тоже — опечатка в тексте или кривая подсказка
в интерфейсе ничем не хуже новой возможности.

Перед отправкой прогоните тесты и линтер — команды выше. Если правка меняет вид
окна, приложите снимок: `tools/screenshot.py` делает их все разом.

Две вещи, о которых стоит знать заранее, потому что они определяют почти все
решения в коде:

- **Ничего из того, что может измениться в сборке Flowseal, не зашивается в код.**
  Стратегии, флаги winws, списки, фейковые пакеты и цели проверок читаются с диска
  при запуске. Список известных стратегий в коде — это ошибка: он протухнет молча.
- **Измерения должны быть честными.** Любая проверка начинается с замера без обхода,
  а если победитель что-то не починил — об этом говорится прямо, а не прячется
  в общей сумме.

Нашли ошибку — заводите задачу. Если дело в неработающем обходе, приложите пакет
из раздела «Диагностика»: там состояние системы и логи, по ним видно больше, чем
по описанию.

## <img src="assets/icons/heart.png" width="22" align="top"> Благодарности

- [bol-van/zapret](https://github.com/bol-van/zapret) — движок обхода
- [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) — сборка и стратегии
- [hyperion-cs/dpi-checkers](https://github.com/hyperion-cs/dpi-checkers) — набор хостов для проверки DPI
- [basil00/WinDivert](https://github.com/basil00/WinDivert) — перехват пакетов
- [Noktomezo/ZapretInteractive](https://github.com/Noktomezo/ZapretInteractive) и
  [medvedeff-true/Zapret-GUI](https://github.com/medvedeff-true/Zapret-GUI) — соседние
  оболочки, у которых было чему поучиться

## <img src="assets/icons/hop.png" width="22" align="top"> Поддержка

Программа бесплатная и останется такой: обход блокировок — не та вещь, которую стоит
прятать за оплату.

Поддержать проект можно будет на Boosty — ссылка появится здесь и в самой программе,
в разделе «Поддержка». Там же будет список тех, кто поддержал.
