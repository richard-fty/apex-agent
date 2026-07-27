const CREATIVE_SKILL = "apex-anime-mv";
const APEX_TOOL_PREFIX = "apex_";
const CREATIVE_PATTERN =
  /动漫|动画|二次元|分镜|镜头|生图|图像|视频|音乐|角色|风格|创作|\banime\b|\bmv\b|music video|storyboard|shot list|image generation|video generation|music generation/i;

function nowFrom(message) {
  return message?.bridge_timestamp || new Date().toISOString();
}

function idPart(value) {
  return String(value ?? "unknown").replace(/[^a-zA-Z0-9_-]/g, "-");
}

function resultText(result) {
  if (!result || !Array.isArray(result.content)) return "";
  return result.content
    .filter((item) => item?.type === "text" && typeof item.text === "string")
    .map((item) => item.text)
    .join("\n");
}

function assetType(path = "", mimeType = "") {
  if (mimeType.startsWith("image/") || /\.(avif|gif|jpe?g|png|svg|webp)$/i.test(path)) return "image";
  if (mimeType.startsWith("video/") || /\.(mp4|webm|mov)$/i.test(path)) return "video";
  if (mimeType.startsWith("audio/") || /\.(mp3|ogg|wav|m4a)$/i.test(path)) return "audio";
  return "file";
}

function createRun(message, timestamp, sequence) {
  return {
    id: message?.id || `run-${sequence || Date.now()}`,
    prompt: message?.message || "Agent run",
    status: "queued",
    startedAt: timestamp,
    endedAt: null,
    turn: 0,
    skills: [],
    nodes: [
      {
        id: `prompt-${sequence || Date.now()}`,
        type: "prompt",
        status: "complete",
        title: "User prompt",
        content: message?.message || "",
        timestamp,
        turn: 0,
      },
    ],
    outputs: [],
  };
}

function ensureNode(run, type, contentIndex, timestamp) {
  const key = `${type}-${run.turn}-${contentIndex ?? 0}`;
  let node = run.nodes.find((item) => item.id === key);
  if (!node) {
    node = {
      id: key,
      type,
      status: "running",
      title: type === "thinking" ? "Model thinking" : "Assistant response",
      content: "",
      timestamp,
      turn: run.turn,
    };
    run.nodes.push(node);
  }
  return node;
}

function addSkill(run, skill) {
  if (!skill?.name) return;
  const normalized = String(skill.name).replace(/^skill:/, "");
  const current = run.skills.find((item) => item.name === normalized);
  if (!current) {
    run.skills.push({
      name: normalized,
      status: skill.status || "matched",
      reason: skill.reason || "Matched by skill router",
    });
    return;
  }
  if (skill.status === "activated") current.status = "activated";
  if (skill.reason) current.reason = skill.reason;
}

function inferSkills(run) {
  const explicit = run.prompt.match(/^\/skill:([a-z0-9-]+)/i);
  if (explicit) {
    addSkill(run, {
      name: explicit[1],
      status: "activated",
      reason: "Explicit /skill command",
    });
  } else if (CREATIVE_PATTERN.test(run.prompt)) {
    addSkill(run, {
      name: CREATIVE_SKILL,
      status: "matched",
      reason: "Apex creative router matched the prompt",
    });
  }
}

function addOutput(run, tool, result, timestamp) {
  const details = result?.details || {};
  const job = details.job;
  const project = details.project;
  const manifestPath = details.manifestPath;
  const base = job || project;

  if (base || manifestPath) {
    const paths = Array.isArray(job?.outputs) ? job.outputs : [];
    const output = {
      id: `${tool.id}-manifest`,
      kind: job?.kind || (project ? "project" : "manifest"),
      title: job?.job_id || project?.title || tool.title,
      status: job?.status || project?.stage || (tool.status === "error" ? "error" : "ready"),
      provider: job?.provider || null,
      prompt: job?.prompt || project?.concept || "",
      manifestPath: manifestPath || null,
      paths,
      timestamp,
    };
    if (!run.outputs.some((item) => item.id === output.id)) run.outputs.push(output);
  }

  for (const [index, block] of (result?.content || []).entries()) {
    if (block?.type !== "image" || !block.data) continue;
    const id = `${tool.id}-inline-${index}`;
    if (run.outputs.some((item) => item.id === id)) continue;
    run.outputs.push({
      id,
      kind: "image",
      title: `${tool.title} image`,
      status: "ready",
      provider: null,
      prompt: "",
      manifestPath: null,
      paths: [`data:${block.mimeType || "image/png"};base64,${block.data}`],
      timestamp,
    });
  }
}

export class DebuggerStore {
  constructor() {
    this.reset();
  }

  reset() {
    this.rawEvents = [];
    this.runs = [];
    this.activeRunId = null;
    this.selectedRunId = null;
    this.selectedNodeId = null;
    this.availableSkills = [];
    this.runtime = {
      bridgeStatus: "connecting",
      pid: null,
      model: null,
      thinkingLevel: null,
      sessionId: null,
      isStreaming: false,
      stats: null,
    };
  }

  get activeRun() {
    return this.runs.find((run) => run.id === this.activeRunId) || null;
  }

  get selectedRun() {
    return (
      this.runs.find((run) => run.id === this.selectedRunId) ||
      this.runs[this.runs.length - 1] ||
      null
    );
  }

  ingest(message) {
    if (!message || typeof message !== "object") return;
    if (message.kind === "bridge_snapshot") {
      for (const event of message.events || []) this.ingest(event);
      return;
    }
    if (message.kind === "bridge_history_cleared") {
      this.reset();
      this.runtime.bridgeStatus = "running";
      return;
    }

    this.rawEvents.push(message);
    if (this.rawEvents.length > 1200) this.rawEvents.shift();
    const timestamp = nowFrom(message);

    if (message.kind === "bridge_status") {
      this.runtime.bridgeStatus = message.status || "unknown";
      this.runtime.pid = message.pid || null;
      return;
    }

    if (message.kind === "bridge_command" && message.command?.type === "prompt") {
      const run = createRun(message.command, timestamp, message.bridge_seq);
      inferSkills(run);
      this.runs.push(run);
      this.activeRunId = run.id;
      this.selectedRunId = run.id;
      this.selectedNodeId = run.nodes[0].id;
      return;
    }

    if (message.kind === "bridge_error" || message.kind === "pi_stderr") {
      const run = this.ensureRun(timestamp, message.bridge_seq);
      run.status = "error";
      run.nodes.push({
        id: `error-${message.bridge_seq || Date.now()}`,
        type: "error",
        status: "error",
        title: message.kind === "pi_stderr" ? "Pi stderr" : "Bridge error",
        content: message.message || message.text || "Unknown error",
        timestamp,
        turn: run.turn,
      });
      return;
    }

    if (message.kind !== "pi_event") return;
    this.ingestPiEvent(message.event || {}, timestamp, message.bridge_seq);
  }

  ensureRun(timestamp, sequence) {
    let run = this.activeRun;
    if (!run) {
      run = createRun({ id: `run-${sequence || Date.now()}`, message: "Recovered agent run" }, timestamp, sequence);
      this.runs.push(run);
      this.activeRunId = run.id;
      this.selectedRunId ||= run.id;
    }
    return run;
  }

  ingestPiEvent(event, timestamp, sequence) {
    if (event.type === "response") {
      if (!event.success) {
        const run = this.activeRun;
        if (run) {
          run.status = "error";
          run.nodes.push({
            id: `rpc-error-${sequence}`,
            type: "error",
            status: "error",
            title: `${event.command || "RPC"} rejected`,
            content: event.error || event.message || JSON.stringify(event),
            timestamp,
            turn: run.turn,
          });
        }
        return;
      }
      if (event.command === "get_state") {
        const state = event.data || {};
        this.runtime.model = state.model || null;
        this.runtime.thinkingLevel = state.thinkingLevel || null;
        this.runtime.sessionId = state.sessionId || null;
        this.runtime.isStreaming = Boolean(state.isStreaming);
      } else if (event.command === "get_commands") {
        this.availableSkills = (event.data?.commands || [])
          .filter((command) => command.source === "skill")
          .map((command) => ({
            name: String(command.name).replace(/^skill:/, ""),
            description: command.description || "",
            path: command.path || "",
            location: command.location || "",
          }));
      } else if (event.command === "get_session_stats") {
        this.runtime.stats = event.data || null;
      }
      return;
    }

    if (event.type === "extension_ui_request" && event.method === "setStatus") {
      if (event.statusKey !== "apex-skill-routing") return;
      try {
        const payload = JSON.parse(event.statusText || "{}");
        const run = this.ensureRun(timestamp, sequence);
        for (const skill of payload.skills || []) addSkill(run, skill);
      } catch {
        // A malformed extension status should never break the event debugger.
      }
      return;
    }

    const run = this.ensureRun(timestamp, sequence);

    if (event.type === "agent_start") {
      run.status = "running";
      this.runtime.isStreaming = true;
      return;
    }
    if (event.type === "agent_settled") {
      run.status = run.status === "error" ? "error" : "complete";
      run.endedAt = timestamp;
      this.runtime.isStreaming = false;
      for (const node of run.nodes) {
        if (node.status === "running") node.status = "complete";
      }
      this.activeRunId = null;
      return;
    }
    if (event.type === "turn_start") {
      run.turn += 1;
      return;
    }
    if (event.type === "message_update") {
      const update = event.assistantMessageEvent || {};
      if (update.type === "thinking_start") ensureNode(run, "thinking", update.contentIndex, timestamp);
      if (update.type === "thinking_delta") {
        ensureNode(run, "thinking", update.contentIndex, timestamp).content += update.delta || "";
      }
      if (update.type === "thinking_end") {
        const node = ensureNode(run, "thinking", update.contentIndex, timestamp);
        if (typeof update.content === "string") node.content = update.content;
        node.status = "complete";
      }
      if (update.type === "text_start") ensureNode(run, "response", update.contentIndex, timestamp);
      if (update.type === "text_delta") {
        ensureNode(run, "response", update.contentIndex, timestamp).content += update.delta || "";
      }
      if (update.type === "text_end") {
        const node = ensureNode(run, "response", update.contentIndex, timestamp);
        if (typeof update.content === "string") node.content = update.content;
        node.status = "complete";
      }
      if (update.type === "error") {
        run.status = "error";
        run.nodes.push({
          id: `model-error-${sequence}`,
          type: "error",
          status: "error",
          title: "Model stream error",
          content: update.error?.message || update.reason || JSON.stringify(update),
          timestamp,
          turn: run.turn,
        });
      }
      return;
    }

    if (event.type === "tool_execution_start") {
      const tool = {
        id: `tool-${idPart(event.toolCallId)}`,
        toolCallId: event.toolCallId,
        type: "tool",
        status: "running",
        title: event.toolName || "tool",
        content: "",
        args: event.args || {},
        result: null,
        startedAt: timestamp,
        timestamp,
        turn: run.turn,
      };
      const existingIndex = run.nodes.findIndex((node) => node.id === tool.id);
      if (existingIndex === -1) run.nodes.push(tool);
      else run.nodes[existingIndex] = { ...run.nodes[existingIndex], ...tool };

      if (String(event.toolName).startsWith(APEX_TOOL_PREFIX)) {
        addSkill(run, {
          name: CREATIVE_SKILL,
          status: "activated",
          reason: `Activated by ${event.toolName}`,
        });
      }
      const readPath = event.toolName === "read" ? event.args?.path || event.args?.file_path : "";
      const skillMatch = String(readPath).match(/[/\\]skills[/\\]([^/\\]+)[/\\]SKILL\.md$/i);
      if (skillMatch) {
        addSkill(run, {
          name: skillMatch[1],
          status: "activated",
          reason: "Agent read the skill instructions",
        });
      }
      return;
    }

    if (event.type === "tool_execution_update") {
      const tool = run.nodes.find((node) => node.id === `tool-${idPart(event.toolCallId)}`);
      if (tool) {
        tool.args = event.args || tool.args;
        tool.partialResult = event.partialResult || null;
        tool.content = resultText(event.partialResult);
      }
      return;
    }

    if (event.type === "tool_execution_end") {
      let tool = run.nodes.find((node) => node.id === `tool-${idPart(event.toolCallId)}`);
      if (!tool) {
        tool = {
          id: `tool-${idPart(event.toolCallId)}`,
          toolCallId: event.toolCallId,
          type: "tool",
          status: "running",
          title: event.toolName || "tool",
          args: {},
          startedAt: timestamp,
          timestamp,
          turn: run.turn,
        };
        run.nodes.push(tool);
      }
      tool.status = event.isError ? "error" : "complete";
      tool.result = event.result || null;
      tool.content = resultText(event.result);
      tool.endedAt = timestamp;
      tool.durationMs = Math.max(0, Date.parse(timestamp) - Date.parse(tool.startedAt));
      addOutput(run, tool, event.result, timestamp);
      if (event.isError) run.status = "error";
      return;
    }

    if (event.type === "auto_retry_start" || event.type === "compaction_start") {
      run.nodes.push({
        id: `${event.type}-${sequence}`,
        type: event.type.startsWith("auto_retry") ? "retry" : "compaction",
        status: "running",
        title: event.type === "auto_retry_start" ? "Automatic retry" : "Context compaction",
        content: event.error?.message || event.reason || "",
        timestamp,
        turn: run.turn,
      });
    }
  }
}

export function summarizeRun(run) {
  const tools = run?.nodes.filter((node) => node.type === "tool") || [];
  const thinking = run?.nodes.filter((node) => node.type === "thinking") || [];
  const durationMs = run?.endedAt
    ? Math.max(0, Date.parse(run.endedAt) - Date.parse(run.startedAt))
    : Math.max(0, Date.now() - Date.parse(run?.startedAt || new Date().toISOString()));
  return {
    tools: tools.length,
    thinkingBlocks: thinking.length,
    durationMs,
    outputs: run?.outputs.length || 0,
  };
}

export function mediaForOutput(output) {
  return (output?.paths || []).map((path) => ({
    path,
    type: assetType(path),
    source:
      /^(https?:|data:|blob:)/i.test(path)
        ? path
        : `/asset?path=${encodeURIComponent(path)}`,
  }));
}
