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

showBoosty();
showVersion();
setupReveal();
setupBar();
setupLightbox();
