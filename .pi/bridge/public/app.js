import { DebuggerStore, mediaForOutput, summarizeRun } from "/debugger-state.js";

const store = new DebuggerStore();
const nodeOpenState = new Map();
const elements = {
  abort: document.querySelector("#abort"),
  artifactList: document.querySelector("#artifact-list"),
  chainView: document.querySelector("#chain-view"),
  clear: document.querySelector("#clear"),
  outputTabCount: document.querySelector("#output-tab-count"),
  outputsView: document.querySelector("#outputs-view"),
  prompt: document.querySelector("#prompt"),
  rawCount: document.querySelector("#raw-count"),
  rawEvents: document.querySelector("#raw-events"),
  rawSearch: document.querySelector("#raw-search"),
  rawView: document.querySelector("#raw-view"),
  restart: document.querySelector("#restart"),
  runCount: document.querySelector("#run-count"),
  runList: document.querySelector("#run-list"),
  runMetrics: document.querySelector("#run-metrics"),
  runStatus: document.querySelector("#run-status"),
  runSummary: document.querySelector("#run-summary"),
  runtimeDot: document.querySelector("#runtime-dot"),
  runtimeMeta: document.querySelector("#runtime-meta"),
  runtimeModel: document.querySelector("#runtime-model"),
  runtimeState: document.querySelector("#runtime-state"),
  sendPrompt: document.querySelector("#send-prompt"),
  skillRouting: document.querySelector("#skill-routing"),
  toast: document.querySelector("#toast"),
  traceTitle: document.querySelector("#trace-title"),
  traceView: document.querySelector("#trace-view"),
};

let socket = null;
let reconnectTimer = null;
let renderFrame = null;
let currentTab = "trace";
let toastTimer = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDuration(ms) {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

function formatTime(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.valueOf())
    ? date.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";
}

function jsonText(value) {
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
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

function send(payload) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    showToast("Debug WebSocket is not connected");
    return false;
  }
  socket.send(JSON.stringify({ kind: "rpc", payload }));
  return true;
}

function sendBridge(kind) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    showToast("Debug WebSocket is not connected");
    return false;
  }
  socket.send(JSON.stringify({ kind }));
  return true;
}

function fetchRuntimeMetadata() {
  for (const type of ["get_state", "get_commands", "get_session_stats"]) {
    send({ id: crypto.randomUUID(), type });
  }
}

function connect() {
  clearTimeout(reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${location.host}/debug/ws`);

  socket.addEventListener("open", () => {
    fetchRuntimeMetadata();
    scheduleRender();
  });
  socket.addEventListener("message", (frame) => {
    try {
      store.ingest(JSON.parse(frame.data));
      scheduleRender();
    } catch (error) {
      showToast(`Invalid debug event: ${error.message}`);
    }
  });
  socket.addEventListener("close", () => {
    store.runtime.bridgeStatus = "disconnected";
    scheduleRender();
    reconnectTimer = setTimeout(connect, 1200);
  });
  socket.addEventListener("error", () => {
    store.runtime.bridgeStatus = "error";
    scheduleRender();
  });
}

function activeAgentRun() {
  return [...store.runs]
    .reverse()
    .find((run) => run.status === "running" || run.status === "queued");
}

function renderRuntime() {
  const runtime = store.runtime;
  const bridgeRunning = runtime.bridgeStatus === "running";
  const activeRun = activeAgentRun();
  const activeTool = activeRun?.nodes
    .filter((node) => node.type === "tool" && node.status === "running")
    .at(-1);

  elements.runtimeDot.className = "runtime-dot";
  if (!bridgeRunning) elements.runtimeDot.classList.add("error");
  else if (activeRun) elements.runtimeDot.classList.add("busy");
  else elements.runtimeDot.classList.add("running");

  elements.runtimeState.textContent = !bridgeRunning
    ? runtime.bridgeStatus || "Disconnected"
    : activeTool
      ? `${activeTool.title} running`
      : activeRun
        ? "Agent thinking"
        : "Agent idle";

  const model = runtime.model;
  elements.runtimeModel.textContent =
    model?.name || model?.id || model?.model || "Pi runtime";

  const stats = runtime.stats || {};
  const totalTokens =
    stats.tokens?.total ||
    stats.totalTokens ||
    stats.total_tokens ||
    stats.usage?.totalTokens ||
    stats.usage?.total_tokens;
  const meta = [];
  if (model?.provider) meta.push(model.provider);
  if (runtime.thinkingLevel) meta.push(`thinking ${runtime.thinkingLevel}`);
  if (totalTokens) meta.push(`${Number(totalTokens).toLocaleString()} tokens`);
  elements.runtimeMeta.textContent = meta.join(" · ") || "state ready";
}

function renderRuns() {
  elements.runCount.textContent = String(store.runs.length);
  elements.runList.replaceChildren();
  if (!store.runs.length) {
    const empty = element("div", "empty small");
    empty.append(
      element("strong", "", "No runs"),
      element("span", "", "Send a prompt to trace Apex."),
    );
    elements.runList.append(empty);
    return;
  }

  [...store.runs].reverse().forEach((run, reverseIndex) => {
    const stats = summarizeRun(run);
    const button = element(
      "button",
      `run-card${store.selectedRun?.id === run.id ? " active" : ""}`,
    );
    const top = element("div", "run-top");
    top.append(
      element(
        "span",
        "run-number",
        `RUN ${String(store.runs.length - reverseIndex).padStart(2, "0")}`,
      ),
      element("span", `status-dot ${run.status}`),
    );
    const prompt = element("p", "run-prompt", run.prompt);
    const metrics = element("div", "run-stats");
    metrics.append(
      element("span", "", formatDuration(stats.durationMs)),
      element("span", "", `${stats.tools} tools`),
      element("span", "", `${stats.outputs} outputs`),
    );
    button.append(top, prompt, metrics);
    button.addEventListener("click", () => {
      store.selectedRunId = run.id;
      scheduleRender();
    });
    elements.runList.append(button);
  });
}

function renderRunSummary(run) {
  elements.runSummary.hidden = !run;
  if (!run) return;
  const stats = summarizeRun(run);
  elements.traceTitle.textContent =
    run.prompt.length > 92 ? `${run.prompt.slice(0, 92)}…` : run.prompt;
  elements.runStatus.className = `status-badge ${run.status}`;
  elements.runStatus.textContent = run.status;

  elements.runMetrics.replaceChildren(
    element("span", "", formatDuration(stats.durationMs)),
    element("span", "", `${stats.tools} tool calls`),
    element("span", "", `${stats.thinkingBlocks} thinking blocks`),
    element("span", "", `${stats.outputs} outputs`),
    element("span", "", `started ${formatTime(run.startedAt)}`),
  );

  elements.skillRouting.replaceChildren();
  for (const skill of run.skills) {
    const chip = element("span", `skill-chip ${skill.status}`);
    chip.title = skill.reason;
    chip.append(
      element("b", "", skill.name),
      element("span", "", skill.status === "activated" ? "active" : "matched"),
    );
    elements.skillRouting.append(chip);
  }
}

function defaultNodeOpen(node) {
  return (
    node.type === "thinking" ||
    node.type === "response" ||
    node.type === "error" ||
    node.status === "running"
  );
}

function appendDetailBlock(parent, title, value) {
  if (value === undefined || value === null || value === "") return;
  const block = element("section", "detail-block");
  block.append(
    element("h3", "", title),
    element("pre", "code-block", jsonText(value)),
  );
  parent.append(block);
}

function nodeTypeLabel(node) {
  return {
    prompt: "INPUT",
    thinking: "THINKING",
    tool: "TOOL",
    response: "RESPONSE",
    error: "ERROR",
    retry: "RETRY",
    compaction: "CONTEXT",
  }[node.type] || String(node.type).toUpperCase();
}

function renderTraceNode(node) {
  const details = element("details", `trace-node ${node.type}`);
  details.open = nodeOpenState.has(node.id)
    ? nodeOpenState.get(node.id)
    : defaultNodeOpen(node);

  const summary = element("summary", "node-summary");
  const title = element("span", "node-title");
  title.append(
    element("span", "node-type", nodeTypeLabel(node)),
    element("strong", "", node.title),
  );
  const meta = element("span", "node-meta");
  if (node.status === "running") meta.append(element("span", "node-spinner"));
  if (node.durationMs !== undefined) {
    meta.append(element("span", "", formatDuration(node.durationMs)));
  }
  meta.append(
    element("span", "", `T${node.turn}`),
    element("span", "", formatTime(node.timestamp)),
    element("span", "node-chevron", "›"),
  );
  summary.append(title, meta);
  details.append(summary);

  const body = element("div", "node-body");
  if (node.type === "tool") {
    const grid = element("div", "detail-grid");
    appendDetailBlock(grid, "Arguments", node.args);
    appendDetailBlock(
      grid,
      node.result
        ? node.status === "error"
          ? "Error result"
          : "Result"
        : "Live partial result",
      node.result || node.partialResult || node.content,
    );
    body.append(grid);
  } else {
    body.append(
      element(
        "pre",
        "node-content",
        node.content ||
          (node.status === "running"
            ? "Waiting for stream…"
            : "No content emitted."),
      ),
    );
  }
  details.append(body);
  details.addEventListener("toggle", () => {
    nodeOpenState.set(node.id, details.open);
  });
  return details;
}

function renderTrace() {
  const run = store.selectedRun;
  renderRunSummary(run);
  elements.chainView.replaceChildren();
  if (!run) {
    const empty = element("div", "empty");
    empty.append(
      element("span", "empty-mark", "⌁"),
      element("strong", "", "No agent trace yet"),
      element("p", "", "Thinking、工具调用和最终回复会按时间顺序显示。"),
    );
    elements.chainView.append(empty);
    return;
  }

  const chain = element("div", "trace-chain");
  for (const node of run.nodes) chain.append(renderTraceNode(node));
  if (!run.nodes.some((node) => node.type === "thinking") && run.status !== "queued") {
    chain.append(
      element(
        "div",
        "thinking-notice",
        run.status === "running"
          ? "Waiting for the model to emit a thinking stream…"
          : "The model/provider emitted no thinking stream. Hidden reasoning is not fabricated.",
      ),
    );
  }
  elements.chainView.append(chain);
}

function renderOutputs() {
  const outputs = store.selectedRun?.outputs || [];
  elements.outputTabCount.textContent = String(outputs.length);
  elements.artifactList.replaceChildren();
  if (!outputs.length) {
    const empty = element("div", "empty");
    empty.append(
      element("span", "empty-mark", "◇"),
      element("strong", "", "No outputs for this run"),
      element("p", "", "Generated media and manifests will appear here."),
    );
    elements.artifactList.append(empty);
    return;
  }

  for (const output of [...outputs].reverse()) {
    const card = element("article", "artifact-card");
    for (const media of mediaForOutput(output)) {
      let preview = null;
      if (media.type === "image") {
        preview = element("img", "artifact-media");
        preview.alt = output.title;
        preview.loading = "lazy";
      } else if (media.type === "video") {
        preview = element("video", "artifact-media");
        preview.controls = true;
      } else if (media.type === "audio") {
        preview = element("audio", "artifact-media");
        preview.controls = true;
      }
      if (preview) {
        preview.src = media.source;
        card.append(preview);
      }
    }
    const copy = element("div", "artifact-copy");
    const top = element("div", "artifact-top");
    top.append(
      element("strong", "", output.title),
      element("span", "artifact-kind", output.kind),
    );
    copy.append(top);
    if (output.prompt) copy.append(element("p", "", output.prompt));
    const meta = element("div", "artifact-meta");
    meta.append(
      element("span", "", output.status),
      element("span", "", output.provider || "local manifest"),
    );
    copy.append(meta);
    if (output.manifestPath) {
      const path = element("p", "manifest-path", output.manifestPath);
      path.title = output.manifestPath;
      copy.append(path);
    }
    card.append(copy);
    elements.artifactList.append(card);
  }
}

function renderRaw() {
  const search = elements.rawSearch.value.trim().toLowerCase();
  const filtered = store.rawEvents.filter((message) => {
    if (!search) return true;
    return JSON.stringify(message).toLowerCase().includes(search);
  });
  elements.rawCount.textContent = `${filtered.length} events`;
  elements.rawEvents.replaceChildren();
  for (const message of [...filtered].reverse()) {
    const type = message.event?.type || message.kind || "unknown";
    const details = element("details", "raw-event");
    details.append(
      element(
        "summary",
        "",
        `#${message.bridge_seq ?? "–"}  ${type}  ${formatTime(message.bridge_timestamp)}`,
      ),
      element("pre", "", JSON.stringify(message.event ?? message, null, 2)),
    );
    elements.rawEvents.append(details);
  }
}

function render() {
  renderRuntime();
  renderRuns();
  renderTrace();
  renderOutputs();
  if (currentTab === "raw") renderRaw();
}

function setTab(tabName) {
  currentTab = tabName;
  elements.traceView.hidden = tabName !== "trace";
  elements.outputsView.hidden = tabName !== "outputs";
  elements.rawView.hidden = tabName !== "raw";
  for (const tab of document.querySelectorAll("[data-tab]")) {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  }
  if (tabName === "raw") renderRaw();
}

elements.sendPrompt.addEventListener("click", () => {
  const message = elements.prompt.value.trim();
  if (!message) return showToast("Write a prompt first");
  if (send({ id: crypto.randomUUID(), type: "prompt", message })) {
    elements.prompt.value = "";
    showToast("Prompt sent to Apex");
  }
});
elements.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    elements.sendPrompt.click();
  }
});
elements.abort.addEventListener("click", () => {
  send({ id: crypto.randomUUID(), type: "abort" });
});
elements.restart.addEventListener("click", () => {
  if (sendBridge("restart")) showToast("Restarting Pi runtime…");
});
elements.clear.addEventListener("click", () => {
  if (sendBridge("clear_history")) {
    store.reset();
    store.runtime.bridgeStatus = "running";
    nodeOpenState.clear();
    fetchRuntimeMetadata();
    scheduleRender();
  }
});
elements.rawSearch.addEventListener("input", scheduleRender);
for (const tab of document.querySelectorAll("[data-tab]")) {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
}

connect();
render();
