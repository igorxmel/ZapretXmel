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

showBoosty();
showVersion();
