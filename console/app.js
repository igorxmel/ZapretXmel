"use strict";

const fragment = location.hash.slice(1);
if (fragment) {
  sessionStorage.setItem("zapret-ui-session", fragment);
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("zapret-ui-session");
const connection = document.querySelector("#connection");
const strategy = document.querySelector("#strategy");
const bypass = document.querySelector("#bypass");
const proxy = document.querySelector("#proxy");
const notice = document.querySelector("#notice");
let state;
let busy = false;
let refreshing = false;
let loadedStrategies = false;

async function api(action, payload) {
  if (!token) throw new Error("Откройте адрес из окна ZapretXmel.");
  const response = await fetch("/api/v1/" + action, {
    method: payload ? "POST" : "GET",
    headers: {
      Authorization: "Bearer " + token,
      ...(payload ? {"Content-Type": "application/json"} : {}),
    },
    body: payload ? JSON.stringify(payload) : undefined,
    signal: AbortSignal.timeout(8000),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function render() {
  const blocked = !state || state.busy || busy;
  strategy.disabled = blocked || !loadedStrategies || !strategy.options.length;
  bypass.disabled = blocked || !state?.core || state.externalInstall;
  proxy.disabled = blocked || !state?.proxyInstalled;
  if (!state) return;

  strategy.value = state.strategy;
  bypass.textContent = state.bypass || state.paused ? "Выключить" : "Включить";
  proxy.textContent = state.proxy ? "Выключить" : "Включить";
  bypass.closest("section").classList.toggle("running", state.bypass);
  proxy.closest("section").classList.toggle("running", state.proxy);
  document.querySelector("#bypass-state").textContent =
    state.externalInstall ? "Обход управляется другой установкой" :
    !state.core ? "Установите ядро во встроенном окне" :
    state.paused ? "На паузе из-за VPN" :
    state.bypass ? (state.activeStrategy || "Работает") : "Выключен";
  document.querySelector("#proxy-state").textContent =
    !state.proxyInstalled ? "Установите прокси во встроенном окне" :
    !state.proxy ? "Выключен" :
    state.proxyConnected ? "Клиент подключён" : "Ожидает клиента";
}

async function refresh() {
  if (refreshing || busy) return;
  refreshing = true;
  try {
    const current = await api("state");
    if (!loadedStrategies || state?.strategyCount !== current.strategyCount) {
      const {strategies} = await api("strategies");
      strategy.replaceChildren(...strategies.map(name => new Option(name, name)));
      loadedStrategies = true;
    }
    state = current;
    connection.textContent = current.busy ? "Приложение занято" : "На связи";
  } catch {
    state = null;
    connection.textContent = token ? "Нет связи с ZapretXmel" : "Откройте адрес из ZapretXmel";
  } finally {
    refreshing = false;
    render();
  }
}

async function command(action, body) {
  if (busy || !state) return;
  busy = true;
  notice.textContent = "";
  render();
  try {
    await api(action, body);
  } catch (error) {
    notice.textContent = error.message;
  } finally {
    busy = false;
    await refresh();
  }
}

strategy.addEventListener("change", () => command("select-strategy", {name: strategy.value}));
bypass.addEventListener("click", () => command("set-bypass", {enabled: !(state.bypass || state.paused)}));
proxy.addEventListener("click", () => command("set-proxy", {enabled: !state.proxy}));
refresh();
setInterval(refresh, 2000);
