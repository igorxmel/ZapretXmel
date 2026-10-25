// Версия и размер берутся у GitHub на месте, а не вписываются в страницу:
// иначе их пришлось бы править при каждом релизе, и рано или поздно цифра
// разошлась бы с тем, что лежит в кнопке. Ссылка на скачивание постоянная —
// releases/latest/download отдаёт файл из последнего релиза сам.

const REPO = "igorxmel/ZapretXmel";

// Boosty появится, когда страница будет готова принимать поддержку. Пустая
// строка прячет кнопку целиком: неактивная кнопка «ссылка появится позже»
// выглядит хуже, чем её отсутствие.
const BOOSTY = "";

function showBoosty() {
  if (!BOOSTY) return;
  const button = document.getElementById("boosty");
  button.href = BOOSTY;
  button.hidden = false;
}

function describe(release) {
  const asset = (release.assets || []).find((item) => item.name === "ZapretXmel.exe");
  const parts = [`Версия ${release.tag_name}`];

  if (asset) {
    parts.push(`${Math.round(asset.size / 1048576)} МБ`);
  }
  parts.push("Windows 10/11 · 64 бита · без установки");

  return parts.join(" · ");
}

async function showVersion() {
  try {
    const response = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`);
    if (!response.ok) return;

    document.getElementById("meta").textContent = describe(await response.json());
  } catch {
    // Молчим намеренно: GitHub мог ответить отказом из-за ограничения на
    // число запросов, и подпись под кнопкой — не та причина, по которой
    // стоит беспокоить читателя сообщением об ошибке.
  }
}

// --- появление и верхняя панель ---------------------------------------

// Блоки проявляются при подходе к ним. Если браузер не умеет наблюдать за
// пересечениями или человек выключил анимацию в системе, всё показывается
// сразу: страница обязана читаться в любом случае.
function setupReveal() {
  const blocks = [...document.querySelectorAll(".reveal")];
  const motionOff = matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (motionOff || !("IntersectionObserver" in window)) {
    blocks.forEach((block) => block.classList.add("seen"));
    return;
  }

  // Шапку показываем сразу — она уже перед глазами, ждать прокрутки нечего.
  document.querySelectorAll(".hero .reveal").forEach((block) => block.classList.add("seen"));

  const watcher = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("seen");
        watcher.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -12% 0px" }
  );

  blocks.filter((block) => !block.closest(".hero")).forEach((block) => watcher.observe(block));
}

function setupBar() {
  const bar = document.getElementById("bar");
  const hero = document.querySelector(".hero");
  if (!bar || !hero) return;

  const toggle = () => {
    bar.classList.toggle("shown", window.scrollY > hero.offsetHeight - 80);
  };

  addEventListener("scroll", toggle, { passive: true });
  toggle();
}

// --- снимок во весь экран ---------------------------------------------

function setupLightbox() {
  const box = document.getElementById("lightbox");
  const full = document.getElementById("lightbox-image");
  const close = document.getElementById("lightbox-close");
  if (!box || !full) return;

  function open(image) {
    full.src = image.currentSrc || image.src;
    full.alt = image.alt;
    box.hidden = false;
    close.focus();
  }

  function hide() {
    box.hidden = true;
    // Путь сбрасываем, чтобы следующий снимок не мелькнул предыдущим.
    full.removeAttribute("src");
  }

  for (const image of document.querySelectorAll(".shot img")) {
    image.addEventListener("click", () => open(image));
  }

  box.addEventListener("click", hide);
  addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !box.hidden) hide();
  });
}

/**
 * Переключатель оформления.
 *
 * Пока выбора не делали, идём за системой — это решает CSS. Как только
 * выбрали, запоминаем: иначе при каждом заходе страница возвращалась бы к
 * системной теме, и выбор выглядел бы неработающим.
 *
 * Снимки экранов подменяются вместе с темой: показывать тёмное окно на
 * светлой странице странно, а файлы у них парные — «-light» рядом.
 */
function setupTheme() {
  const button = document.getElementById("theme-toggle");
  if (!button) return;

  const dark = matchMedia("(prefers-color-scheme: dark)");

  // Признак уже проставлен скриптом в <head> — до первой отрисовки.
  const current = () => document.documentElement.dataset.theme || "dark";

  const shots = () => {
    const light = current() === "light";
    document.querySelectorAll("img[data-shot]").forEach((image) => {
      const name = image.dataset.shot;
      const dark = `assets/${name}.png`;
      // Светлый снимок есть не у всех экранов: обзор и подбор показывают
      // название активного VPN, и пересняты они могут быть только с
      // выключенным туннелем. Нет файла — показываем тёмный, это лучше
      // битой картинки.
      image.onerror = () => {
        image.onerror = null;
        image.src = dark;
      };
      image.src = light ? `assets/${name}-light.png` : dark;
    });
  };

  // Снимки второго оформления браузер не трогает, пока их не попросят, —
  // и первое переключение выходило с заминкой: картинка качалась ровно в
  // этот момент. Просим их заранее, но после того, как страница загрузилась
  // целиком: четверть мегабайта не должна соперничать с тем, что человек
  // видит сейчас. Дальше они берутся из кэша, и переключение мгновенно.
  const warm = () => {
    const light = current() === "light";
    document.querySelectorAll("img[data-shot]").forEach((image) => {
      const other = new Image();
      other.src = light
        ? `assets/${image.dataset.shot}.png`
        : `assets/${image.dataset.shot}-light.png`;
    });
  };

  const apply = (theme) => {
    document.documentElement.dataset.theme = theme;
    shots();
  };

  shots();

  if (document.readyState === "complete") warm();
  else addEventListener("load", warm, { once: true });

  // Система могла сменить тему, пока страница открыта. Слушаем только
  // пока человек не выбрал сам: его выбор важнее.
  dark.addEventListener("change", (event) => {
    if (!localStorage.getItem("theme")) apply(event.matches ? "dark" : "light");
  });

  button.addEventListener("click", () => {
    const next = current() === "light" ? "dark" : "light";
    localStorage.setItem("theme", next);
    apply(next);
  });
}

/*
 * Плавное раскрытие вопросов.
 *
 * У <details> высота прыгает: браузер просто убирает и возвращает содержимое, и
 * средствами одного CSS это анимируется не везде (новый способ работает только в
 * Chrome). Поэтому высота меняется скриптом. Без скрипта и при включённой в системе
 * настройке «уменьшить движение» остаётся обычное мгновенное поведение: вопросы
 * от этого не пропадают и не ломаются.
 *
 * Быстрый повторный щелчок не должен дёргать блок. Новая анимация стартует с той
 * высоты, на которой блок сейчас, а не с прежнего края.
 */
function setupFaq() {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const DURATION = 240;

  // Высота блока в нужном состоянии. Состояние переключается и возвращается
  // синхронно, до отрисовки: на экране этого не видно, а измерить иначе нельзя.
  const heightWhen = (details, open) => {
    const was = details.open;
    details.open = open;
    const height = details.getBoundingClientRect().height;
    details.open = was;
    return height;
  };

  document.querySelectorAll(".faq details").forEach((details) => {
    const summary = details.querySelector("summary");
    let animation = null;

    summary.addEventListener("click", (event) => {
      if (reduced.matches || !details.animate) return;
      event.preventDefault();

      // Блок «открывается», если он закрыт или прямо сейчас закрывается.
      const opening = !details.open || details.classList.contains("closing");
      const from = details.getBoundingClientRect().height;

      // Старую анимацию снимаем до измерения: пока она держит блок на промежуточной
      // высоте, «конечная» высота измерилась бы той же промежуточной, и разворот шёл
      // бы из середины в середину, а потом блок прыгал.
      if (animation) animation.cancel();
      const to = heightWhen(details, opening);

      details.open = true;
      details.classList.toggle("closing", !opening);
      details.style.overflow = "hidden";

      // fill: "forwards" держит конечную высоту до тех пор, пока не сменится само
      // состояние. Без него между концом анимации и обработчиком окончания блок на
      // кадр возвращался к полной высоте — при закрытии это вспышка в самом конце.
      const current = details.animate(
        { height: [`${from}px`, `${to}px`] },
        { duration: DURATION, easing: "cubic-bezier(0.2, 0.7, 0.2, 1)", fill: "forwards" },
      );
      animation = current;

      current.onfinish = () => {
        details.open = opening;
        details.classList.remove("closing");
        details.style.overflow = "";
        current.cancel(); // конечная высота теперь обычная, удерживать её незачем
        if (animation === current) animation = null;
      };
    });
  });
}

setupTheme();
setupFaq();
showBoosty();
showVersion();
setupReveal();
setupBar();
setupLightbox();
