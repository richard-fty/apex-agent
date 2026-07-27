const state = {
  serviceStatus: "connecting",
  runs: [],
  selectedRunId: null,
  activeRunId: null,
};

const elements = {
  abort: document.querySelector("#abort"),
  activityFeed: document.querySelector("#activity-feed"),
  conversation: document.querySelector("#conversation"),
  inlineProgress: document.querySelector("#inline-progress"),
  newProject: document.querySelector("#new-project"),
  outputCount: document.querySelector("#output-count"),
  outputList: document.querySelector("#output-list"),
  outputSection: document.querySelector("#output-section"),
  progressBar: document.querySelector("#progress-bar"),
  progressLabel: document.querySelector("#progress-label"),
  progressValue: document.querySelector("#progress-value"),
  projectList: document.querySelector("#project-list"),
  projectTitle: document.querySelector("#project-title"),
  prompt: document.querySelector("#prompt"),
  responseCaret: document.querySelector("#response-caret"),
  responseCopy: document.querySelector("#response-copy"),
  responseState: document.querySelector("#response-state"),
  runView: document.querySelector("#run-view"),
  send: document.querySelector("#send"),
  shell: document.querySelector("#studio-shell"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  toast: document.querySelector("#toast"),
  userPrompt: document.querySelector("#user-prompt"),
  welcome: document.querySelector("#welcome"),
};

const stageOrder = ["idea", "plan", "visual", "music", "render"];
let socket = null;
let reconnectTimer = null;
let renderFrame = null;
let toastTimer = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 2200);
}

function scheduleRender() {
  if (renderFrame) return;
  renderFrame = requestAnimationFrame(() => {
    renderFrame = null;
    render();
  });
}

function selectedRun() {
  if (!state.selectedRunId) return null;
  return state.runs.find((run) => run.id === state.selectedRunId) || null;
}

function activeRun() {
  return state.runs.find((run) => run.id === state.activeRunId) || null;
}

function ensureRun(message) {
  let run = activeRun();
  if (!run) {
    run = {
      id: `recovered-${message.bridge_seq || Date.now()}`,
      prompt: "继续上一次创作",
      title: "未命名创作",
      status: "running",
      response: "",
      activities: [],
      outputs: [],
      startedAt: message.bridge_timestamp,
    };
    state.runs.push(run);
    state.activeRunId = run.id;
    state.selectedRunId ||= run.id;
  }
  return run;
}

function titleFromPrompt(prompt) {
  const theme = prompt.match(/(?:主题是|关于|讲述)([^。,.，]{2,24})/i)?.[1]?.trim();
  if (theme) return theme;
  const clean = prompt
    .replace(/^(请|帮我|我想|我要|为我|给我)+/g, "")
    .replace(/^(做|创作|制作|设计|生成|一个|一支)+/g, "")
    .trim();
  if (!clean) return "新的创作";
  return clean.length > 20 ? `${clean.slice(0, 20)}…` : clean;
}

function ingest(message) {
  if (!message || typeof message !== "object") return;
  if (message.kind === "studio_snapshot") {
    for (const event of message.events || []) ingest(event);
    return;
  }
  if (message.kind === "studio_history_cleared") {
    state.runs = [];
    state.activeRunId = null;
    state.selectedRunId = null;
    return;
  }
  if (message.kind === "studio_status") {
    state.serviceStatus = message.status || "unknown";
    return;
  }
  if (message.kind === "studio_run") {
    const prompt = String(message.prompt || "");
    const run = {
      id: String(message.id || `run-${message.bridge_seq || Date.now()}`),
      prompt,
      title: titleFromPrompt(prompt),
      status: "queued",
      response: "",
      activities: [],
      outputs: [],
      startedAt: message.bridge_timestamp,
    };
    state.runs.push(run);
    state.activeRunId = run.id;
    state.selectedRunId = run.id;
    return;
  }

  const run = ensureRun(message);
  if (message.kind === "studio_lifecycle") {
    run.status = message.status;
    if (message.status === "complete") {
      run.endedAt = message.bridge_timestamp;
      state.activeRunId = null;
    }
    return;
  }
  if (message.kind === "studio_response") {
    if (message.mode === "delta") run.response += String(message.text || "");
    else if (typeof message.text === "string") run.response = message.text;
    return;
  }
  if (message.kind === "studio_activity") {
    let activity = run.activities.find((item) => item.id === message.id);
    if (!activity) {
      activity = {
        id: String(message.id || `activity-${message.bridge_seq}`),
        label: String(message.label || "Apex 正在创作"),
        stage: String(message.stage || "create"),
        status: String(message.status || "running"),
      };
      run.activities.push(activity);
    } else {
      activity.label = String(message.label || activity.label);
      activity.stage = String(message.stage || activity.stage);
      activity.status = String(message.status || activity.status);
    }
    if (message.output && !run.outputs.some((output) => output.id === message.output.id)) {
      run.outputs.push(message.output);
    }
    if (message.status === "error") run.status = "error";
    return;
  }
  if (message.kind === "studio_error") {
    run.status = "error";
    run.error = String(message.message || "Apex 暂时遇到问题，请稍后重试。");
  }
}

function sendMessage(value) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    showToast("Apex 还在连接，请稍后再试");
    return false;
  }
  socket.send(JSON.stringify(value));
  return true;
}

function connect() {
  clearTimeout(reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/ws`);
  socket.addEventListener("open", () => {
    state.serviceStatus = "running";
    scheduleRender();
  });
  socket.addEventListener("message", (frame) => {
    try {
      ingest(JSON.parse(frame.data));
      scheduleRender();
    } catch {
      showToast("Apex 收到了一条无法识别的创作进度");
    }
  });
  socket.addEventListener("close", () => {
    state.serviceStatus = "disconnected";
    scheduleRender();
    reconnectTimer = setTimeout(connect, 1200);
  });
  socket.addEventListener("error", () => {
    state.serviceStatus = "error";
    scheduleRender();
  });
}

function mediaType(path) {
  if (/\.(png|jpe?g|webp|gif|avif|svg)$/i.test(path) || path.startsWith("data:image/")) return "image";
  if (/\.(mp4|webm|mov)$/i.test(path) || path.startsWith("data:video/")) return "video";
  if (/\.(mp3|wav|ogg|m4a)$/i.test(path) || path.startsWith("data:audio/")) return "audio";
  return "file";
}

function mediaSource(path) {
  return /^(https?:|data:|blob:)/i.test(path)
    ? path
    : `/asset?path=${encodeURIComponent(path)}`;
}

function stageIndexFor(run) {
  let highest = -1;
  for (const activity of run?.activities || []) {
    const normalized = activity.stage === "motion" ? "visual" : activity.stage;
    const index = stageOrder.indexOf(normalized);
    if (index > highest) highest = index;
  }
  return Math.max(highest, run ? 0 : -1);
}

function renderProjects() {
  elements.projectList.replaceChildren();
  if (!state.runs.length) {
    elements.projectList.append(element("p", "sidebar-empty", "你的作品会出现在这里"));
    return;
  }
  [...state.runs].reverse().forEach((run) => {
    const button = element(
      "button",
      `project-item${selectedRun()?.id === run.id ? " active" : ""}`,
    );
    button.append(element("span", "project-thumb", run.status === "complete" ? "✓" : "✦"));
    const copy = element("span", "project-copy");
    copy.append(
      element("strong", "", run.title),
      element(
        "small",
        "",
        run.status === "running"
          ? "正在创作"
          : run.status === "complete"
            ? `${run.outputs.length} 个成果`
            : "创作草稿",
      ),
    );
    button.append(copy);
    button.addEventListener("click", () => {
      state.selectedRunId = run.id;
      scheduleRender();
    });
    elements.projectList.append(button);
  });
}

function renderMarkdownish(text) {
  elements.responseCopy.replaceChildren();
  if (!text) return;
  let list = null;
  let listType = null;

  const flushList = () => {
    if (list) elements.responseCopy.append(list);
    list = null;
    listType = null;
  };

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    const heading = line.match(/^#{1,4}\s+(.+)/);
    if (heading) {
      flushList();
      elements.responseCopy.append(element("h3", "", heading[1].replaceAll("**", "")));
      continue;
    }
    const unordered = line.match(/^[-*]\s+(.+)/);
    const ordered = line.match(/^\d+[.)]\s+(.+)/);
    if (unordered || ordered) {
      const type = ordered ? "ol" : "ul";
      if (!list || listType !== type) {
        flushList();
        list = element(type);
        listType = type;
      }
      list.append(element("li", "", (ordered?.[1] || unordered?.[1] || "").replaceAll("**", "")));
      continue;
    }
    flushList();
    elements.responseCopy.append(element("p", "", line.replaceAll("**", "")));
  }
  flushList();
}

function renderActivities(run) {
  elements.activityFeed.replaceChildren();
  for (const activity of run.activities.slice(-5)) {
    const item = element("div", `activity-item ${activity.status}`);
    item.append(
      element(
        "span",
        "",
        activity.status === "complete" ? "✓" : activity.status === "error" ? "!" : "·",
      ),
      element("b", "", activity.label),
    );
    elements.activityFeed.append(item);
  }
}

function renderProgress(run) {
  const highest = stageIndexFor(run);
  const visible = Boolean(run && (run.status === "running" || run.status === "queued"));
  elements.inlineProgress.hidden = !visible;
  if (!visible) return;
  const progress = highest < 0 ? 8 : Math.min(92, ((highest + 0.55) / stageOrder.length) * 100);
  elements.progressBar.style.width = `${Math.round(progress)}%`;
  elements.progressValue.textContent = `${Math.round(progress)}%`;
  elements.progressLabel.textContent =
    run.activities.at(-1)?.label || (run.status === "queued" ? "正在理解你的想法" : "正在推进创作");
}

function renderOutputs(run) {
  const outputs = run?.outputs || [];
  elements.outputCount.textContent = String(outputs.length);
  elements.outputSection.hidden = outputs.length === 0;
  elements.outputList.replaceChildren();
  if (!outputs.length) return;
  for (const output of [...outputs].reverse()) {
    const card = element("article", "output-card");
    for (const path of output.paths || []) {
      const type = mediaType(String(path));
      let media = null;
      if (type === "image") {
        media = element("img");
        media.alt = output.title || "Apex visual";
        media.loading = "lazy";
      } else if (type === "video") {
        media = element("video");
        media.controls = true;
      } else if (type === "audio") {
        media = element("audio");
        media.controls = true;
      }
      if (media) {
        media.src = mediaSource(String(path));
        card.append(media);
      }
    }
    const copy = element("div", "output-card-copy");
    const top = element("div", "output-card-top");
    top.append(
      element("strong", "", output.title || "Apex creation"),
      element("span", "output-kind", output.kind || "creation"),
    );
    copy.append(top);
    if (output.prompt) copy.append(element("p", "", output.prompt));
    const meta = element("div", "output-meta");
    meta.append(
      element("span", "", output.status || "ready"),
      element("span", "", output.provider || "Apex"),
    );
    copy.append(meta);
    card.append(copy);
    elements.outputList.append(card);
  }
}

function renderRun() {
  const run = selectedRun();
  elements.welcome.hidden = Boolean(run);
  elements.runView.hidden = !run;
  elements.projectTitle.textContent = run?.title || "新的创作";

  if (!run) {
    elements.abort.hidden = true;
    renderProgress(null);
    renderOutputs(null);
    return;
  }

  elements.userPrompt.textContent = run.prompt;
  renderActivities(run);
  renderMarkdownish(run.error || run.response);
  elements.responseCaret.classList.toggle("hidden", run.status !== "running" && run.status !== "queued");
  elements.responseState.textContent =
    run.status === "running"
      ? run.activities.at(-1)?.label || "正在理解你的想法"
      : run.status === "complete"
        ? "这一步已经完成"
        : run.status === "error"
          ? "需要你调整一下"
          : "准备开始创作";
  elements.abort.hidden = run.status !== "running";
  renderProgress(run);
  renderOutputs(run);
}

function render() {
  renderProjects();
  renderRun();
  const working = Boolean(activeRun());
  elements.send.disabled = working;
  elements.prompt.disabled = working;
  elements.prompt.placeholder = working ? "Apex 正在创作这一步…" : "描述你想创作的作品…";
}

function submitPrompt() {
  const message = elements.prompt.value.trim();
  if (!message) {
    showToast("先告诉 Apex 你想创作什么");
    return;
  }
  if (activeRun()) {
    showToast("请等 Apex 完成这一步");
    return;
  }
  if (sendMessage({ kind: "studio_prompt", message })) {
    elements.prompt.value = "";
    elements.prompt.style.height = "auto";
  }
}

elements.send.addEventListener("click", submitPrompt);
elements.prompt.addEventListener("input", (event) => {
  const target = event.currentTarget;
  target.style.height = "auto";
  target.style.height = `${Math.min(target.scrollHeight, 150)}px`;
});
elements.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitPrompt();
  }
});
elements.abort.addEventListener("click", () => {
  if (sendMessage({ kind: "studio_abort" })) showToast("正在停止这次创作");
});
elements.newProject.addEventListener("click", () => {
  if (activeRun()) return showToast("请先完成或停止当前创作");
  state.selectedRunId = null;
  elements.prompt.focus();
  scheduleRender();
});
elements.sidebarToggle.addEventListener("click", () => {
  const collapsed = !elements.shell.classList.contains("sidebar-collapsed");
  elements.shell.classList.toggle("sidebar-collapsed", collapsed);
  elements.sidebarToggle.textContent = collapsed ? "›" : "‹";
  elements.sidebarToggle.title = collapsed ? "展开侧边栏" : "收起侧边栏";
  elements.sidebarToggle.setAttribute("aria-label", elements.sidebarToggle.title);
  try {
    localStorage.setItem("apex-sidebar-collapsed", collapsed ? "1" : "0");
  } catch {
    // Preference persistence is optional.
  }
});
for (const card of document.querySelectorAll("[data-prompt]")) {
  card.addEventListener("click", () => {
    elements.prompt.value = card.dataset.prompt;
    submitPrompt();
  });
}
for (const chip of document.querySelectorAll("[data-chip]")) {
  chip.addEventListener("click", () => {
    const prefix = elements.prompt.value.trim();
    elements.prompt.value = prefix ? `${prefix}\n${chip.dataset.chip}` : chip.dataset.chip;
    elements.prompt.focus();
  });
}
for (const item of document.querySelectorAll("[data-coming-soon]")) {
  item.addEventListener("click", () => showToast("这个功能会在后续版本开放"));
}

try {
  const collapsed = localStorage.getItem("apex-sidebar-collapsed") === "1";
  elements.shell.classList.toggle("sidebar-collapsed", collapsed);
  elements.sidebarToggle.textContent = collapsed ? "›" : "‹";
  elements.sidebarToggle.title = collapsed ? "展开侧边栏" : "收起侧边栏";
  elements.sidebarToggle.setAttribute("aria-label", elements.sidebarToggle.title);
} catch {
  // Preference persistence is optional.
}

connect();
render();
