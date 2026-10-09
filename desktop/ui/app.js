"use strict";

const invoke = window.__TAURI__.core.invoke;
const listen = window.__TAURI__.event.listen;

const EXIT_VIEWS = {
  11: "docker-down",
  12: "docker-down",
  17: "not-found",
  18: "not-installed",
  32: "unsupported",
};

const MAX_OUTPUT_LINES = 400;

const state = {
  info: null,
  view: null,
  phase: null,
  startedAt: null,
  ticker: null,
  output: [],
  services: {},
  ready: false,
  lastFailure: null,
  lastExit: null,
};

function show(view) {
  state.view = view;
  for (const section of document.querySelectorAll(".view")) {
    section.classList.toggle("active", section.dataset.view === view);
  }
  const subtitles = {
    "locating": "Starting up",
    "not-found": "Cannot find the Horus folder",
    "no-python": "Python is missing",
    "docker-down": "Docker is not running",
    "not-installed": "Not installed yet",
    "unsupported": "Not enough memory",
    "starting": "Starting the stack",
    "failed": "Something went wrong",
    "running": "Running",
    "close-prompt": "Closing",
    "stopping": "Stopping",
    "stopped": "Stopped",
  };
  document.getElementById("subtitle").textContent = subtitles[view] || "";
}

function footer(text) {
  document.getElementById("footer").textContent = text || "";
}

function on(id, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("click", handler);
}

function elapsedText(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function startTicker() {
  state.startedAt = Date.now();
  stopTicker();
  const tick = () => {
    const el = document.getElementById("elapsed");
    if (el) el.textContent = elapsedText((Date.now() - state.startedAt) / 1000);
  };
  tick();
  state.ticker = setInterval(tick, 1000);
}

function stopTicker() {
  if (state.ticker !== null) {
    clearInterval(state.ticker);
    state.ticker = null;
  }
}

function appendOutput(text) {
  if (!text) return;
  state.output.push(text);
  if (state.output.length > MAX_OUTPUT_LINES) {
    state.output.splice(0, state.output.length - MAX_OUTPUT_LINES);
  }
  const joined = state.output.join("\n");
  for (const id of ["output", "stopping-output"]) {
    const pre = document.getElementById(id);
    if (!pre) continue;
    const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
    pre.textContent = joined;
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }
}

function classifyService(entry) {
  const st = (entry.state || "").toLowerCase();
  const health = (entry.health || "").toLowerCase();
  if (st !== "running") {
    if (st === "missing" || st === "") return ["state-missing", "waiting"];
    if (st === "exited" || st === "dead") return ["state-bad", st];
    return ["state-wait", st];
  }
  if (health === "" || health === "healthy") return ["state-ok", "ready"];
  if (health === "unhealthy") return ["state-bad", "unhealthy"];
  return ["state-wait", health];
}

function renderServices(payload) {
  const services = payload.services || {};
  const expected = payload.expected || Object.keys(services);
  state.services = services;

  const table = document.getElementById("services");
  const body = table.querySelector("tbody");
  body.textContent = "";
  for (const name of expected) {
    const entry = services[name] || { state: "missing", health: "" };
    const [cls, label] = classifyService(entry);
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    td1.className = "name";
    td1.textContent = name;
    const td2 = document.createElement("td");
    const span = document.createElement("span");
    span.className = cls;
    span.textContent = label;
    td2.appendChild(span);
    tr.appendChild(td1);
    tr.appendChild(td2);
    body.appendChild(tr);
  }
  table.hidden = expected.length === 0;
}

function renderDownload(data) {
  const box = document.getElementById("download");
  const bar = document.getElementById("download-bar");
  if (data.phase === "verified") {
    box.hidden = true;
    return;
  }
  const label = data.phase === "downloading" ? "Downloading the language model" : "";
  document.getElementById("download-text").textContent =
    label ? `${label}: ${data.text || ""}` : data.text || "";
  if (data.phase === "downloading" && typeof data.percent === "number") {
    bar.value = data.percent;
  } else {
    bar.removeAttribute("value");
  }
  bar.hidden = data.phase === "failed";
  box.hidden = false;
}

function fillList(id, items) {
  const list = document.getElementById(id);
  list.textContent = "";
  for (const item of items || []) {
    const li = document.createElement("li");
    li.textContent = String(item);
    list.appendChild(li);
  }
}

function renderUnsupported(data) {
  if (data.headline) {
    document.getElementById("unsupported-headline").textContent = data.headline;
  }
  const checked = document.getElementById("unsupported-checked");
  checked.textContent = data.checked_utc
    ? `Found when START-HERE last ran (${data.checked_utc}).` : "";
  checked.hidden = !data.checked_utc;
  fillList("unsupported-have", data.have);
  fillList("unsupported-need", data.need);
  fillList("unsupported-alternatives", data.alternatives);
}

function hideDownload() {
  document.getElementById("download").hidden = true;
  document.getElementById("download-text").textContent = "";
}

async function bootstrap() {
  show("locating");
  let info;
  try {
    info = await invoke("bootstrap");
  } catch (err) {
    state.lastFailure = { headline: "Horus could not start.", detail: String(err) };
    renderFailure();
    return;
  }
  state.info = info;
  footer(info.root ? `${info.root}   ${info.version || ""}`.trim() : "");

  if (info.state === "not-found") {
    const input = document.getElementById("root-input");
    if (info.root) input.value = info.root;
    show("not-found");
    return;
  }
  if (info.state === "no-python") {
    show("no-python");
    return;
  }
  if (info.state === "not-installed") {
    if (info.refused) {
      await startStack();
      return;
    }
    show("not-installed");
    return;
  }
  await startStack();
}

const PHASES = {
  "starting": ["Starting Horus", "starting"],
  "restarting": ["Restarting Horus", "starting"],
  "stopping": ["Stopping Horus", "stopping"],
};

function beginPhase(phase) {
  const [label, view] = PHASES[phase] || ["Working", "starting"];
  state.phase = phase || null;
  state.output = [];
  state.services = {};
  state.ready = false;
  const table = document.getElementById("services");
  table.hidden = true;
  table.querySelector("tbody").textContent = "";
  hideDownload();
  for (const id of ["output", "stopping-output"]) {
    const pre = document.getElementById(id);
    if (pre) pre.textContent = "";
  }
  document.getElementById("starting-step").textContent = label;
  show(view);
  startTicker();
}

async function run(command, args, failure) {
  try {
    await invoke(command, args);
  } catch (err) {
    state.lastFailure = { headline: failure, detail: String(err) };
    renderFailure();
  }
}

const startStack = () => run("start_stack", undefined, "Horus could not be started.");
const restartStack = () => run("restart_stack", undefined, "Horus could not be restarted.");
const stopStack = (thenQuit) =>
  run("stop_stack", { thenQuit: !!thenQuit }, "Horus could not be stopped.");

function renderFailure() {
  stopTicker();
  const failure = state.lastFailure || {};
  document.getElementById("failed-headline").textContent =
    failure.headline || "Horus did not start.";
  document.getElementById("failed-detail").textContent = failure.detail || "";
  document.getElementById("failed-output").textContent =
    state.output.slice(-40).join("\n");
  show("failed");
}

const AI_MODE_TEXT = {
  mock: "AI: Mock - no AI model runs. Answers and search are simulated from the words of your documents.",
  local: "AI: Local",
};

function renderAiMode(mode) {
  const line = document.getElementById("ai-mode");
  line.textContent = AI_MODE_TEXT[mode] || "";
  line.hidden = !AI_MODE_TEXT[mode];
  line.classList.toggle("mock", mode === "mock");
}

function handleInstallerEvent(data) {
  switch (data.event) {
    case "step":
      if (data.text) {
        document.getElementById("starting-step").textContent = data.text;
        appendOutput("");
        appendOutput(data.text);
      }
      break;
    case "services":
      renderServices(data);
      break;
    case "download":
      renderDownload(data);
      break;
    case "unsupported":
      renderUnsupported(data);
      break;
    case "ready":
      stopTicker();
      state.ready = true;
      renderAiMode(data.ai);
      break;
    case "ai":
      renderAiMode(data.mode);
      break;
    case "say":
      if (data.text && data.text.trim()) appendOutput(data.text);
      break;
    case "ok":
      appendOutput(`[ok]   ${data.text || ""}`);
      break;
    case "warn":
      appendOutput(`[warn] ${data.text || ""}`);
      break;
    case "fail":
      appendOutput(`[FAIL] ${data.text || ""}`);
      break;
    case "located":
      footer(`${data.repo || ""}   ${data.version || ""}`.trim());
      break;
    case "exit":
      state.lastExit = { code: data.code, name: data.name || "" };
      break;
    default:
      break;
  }
}

function handleFinished(payload) {
  stopTicker();
  const code = typeof payload.code === "number" ? payload.code : -1;
  const wasStopping = (payload.phase || state.phase) === "stopping";
  state.phase = null;

  if (code === 0) {
    if (wasStopping) {
      show("stopped");
    } else {
      state.ready = true;
      show("running");
    }
    return;
  }

  const view = EXIT_VIEWS[code];
  if (view) {
    if (view === "docker-down") {
      document.getElementById("docker-detail").textContent =
        state.output.slice(-6).join("\n");
    }
    if (view === "not-found" && state.info && state.info.root) {
      document.getElementById("root-input").value = state.info.root;
    }
    show(view);
    return;
  }

  const named = state.lastExit && state.lastExit.code === code
    ? state.lastExit.name : "";
  state.lastFailure = {
    headline: wasStopping ? "Horus could not be stopped." : "Horus did not start.",
    detail: `The installer stopped with exit code ${code}`
            + (named ? ` (${named}).` : ".")
            + " The full transcript is in install-log.txt - send us that file"
            + " and horus-profile.json and we can see exactly what happened.",
  };
  renderFailure();
}

async function subscribe() {
  await listen("horus://event", (message) => {
    const payload = message.payload || {};
    switch (payload.kind) {
      case "phase":
        beginPhase(payload.phase);
        break;
      case "installer":
        handleInstallerEvent(payload.data || {});
        break;
      case "output":
        appendOutput(payload.text || "");
        break;
      case "internal":
        appendOutput(`[shell] ${payload.text || ""}`);
        break;
      case "error":
        stopTicker();
        state.lastFailure = { headline: "Horus hit a problem.", detail: payload.text || "" };
        renderFailure();
        break;
      case "finished":
        handleFinished(payload);
        break;
      case "close-requested":
        show("close-prompt");
        break;
      default:
        break;
    }
  });
}

function wire() {
  on("root-save", async () => {
    const input = document.getElementById("root-input");
    const error = document.getElementById("root-error");
    error.hidden = true;
    const path = input.value.trim();
    if (!path) {
      error.textContent = "Type the full path to the folder you unzipped.";
      error.hidden = false;
      return;
    }
    try {
      await invoke("set_root", { path });
    } catch (err) {
      error.textContent = String(err);
      error.hidden = false;
      return;
    }
    await bootstrap();
  });

  on("root-quit", () => invoke("quit_app"));
  on("python-quit", () => invoke("quit_app"));
  on("docker-quit", () => invoke("quit_app"));
  on("installed-quit", () => invoke("quit_app"));
  on("failed-quit", () => invoke("quit_app"));
  on("unsupported-quit", () => invoke("quit_app"));
  on("stopped-quit", () => invoke("quit_app"));

  on("python-retry", () => bootstrap());
  on("docker-retry", () => startStack());
  on("installed-retry", () => bootstrap());
  on("unsupported-retry", () => bootstrap());
  on("failed-retry", () => startStack());
  on("stopped-start", () => startStack());

  on("installed-open", () => invoke("open_path", { which: "bundle" }));
  on("unsupported-open", () => invoke("open_path", { which: "bundle" }));
  on("starting-log", () => invoke("open_path", { which: "log" }));
  on("failed-log", () => invoke("open_path", { which: "log" }));
  on("failed-profile", () => invoke("open_path", { which: "profile" }));
  on("unsupported-profile", () => invoke("open_path", { which: "profile" }));
  on("unsupported-log", () => invoke("open_path", { which: "log" }));
  on("running-log", () => invoke("open_path", { which: "log" }));
  on("running-profile", () => invoke("open_path", { which: "profile" }));
  on("running-browser", () => invoke("open_path", { which: "web" }));

  on("starting-cancel", () => invoke("cancel_and_quit"));
  on("running-show", () => invoke("show_app_window"));
  on("running-restart", () => restartStack());
  on("running-stop", () => stopStack(false));

  on("close-leave", () => {
    const remember = document.getElementById("close-remember").checked;
    invoke("close_decision", { shutdown: false, remember });
  });
  on("close-shutdown", () => {
    const remember = document.getElementById("close-remember").checked;
    invoke("close_decision", { shutdown: true, remember });
    show("stopping");
  });
  on("close-cancel", () => {
    invoke("close_decision_cancel");
    show(state.ready ? "running" : "starting");
  });

  document.addEventListener("contextmenu", (event) => event.preventDefault());
}

window.addEventListener("DOMContentLoaded", async () => {
  wire();
  await subscribe();
  await bootstrap();
});
