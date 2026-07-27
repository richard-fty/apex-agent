import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocket, WebSocketServer } from "ws";

const bridgeDir = dirname(fileURLToPath(import.meta.url));
const piDir = resolve(bridgeDir, "..");
const projectDir = resolve(piDir, "..");
const publicDir = join(bridgeDir, "public");
try {
  process.loadEnvFile(resolve(projectDir, ".env"));
} catch {
  // A repository .env is optional; normal process environment variables still work.
}
const port = Number.parseInt(process.env.APEX_PI_BRIDGE_PORT || "8788", 10);
const cliPath = join(piDir, "node_modules", ".bin", "pi");
const extensionPath = join(piDir, "extensions", "apex-creative.ts");
const apexAssetsRoot = resolve(projectDir, ".apex");
const historyLimit = 1200;
const debugSessionLifetimeMs = 12 * 60 * 60 * 1000;
const debugAdmin = process.env.APEX_DEBUG_ADMIN || "admin";
const isProduction = process.env.NODE_ENV === "production";
const debugPassword = process.env.APEX_DEBUG_PASSWORD || (isProduction ? null : "apex-local");
const piRuntimeMode = (process.env.APEX_PI_RUNTIME || "local").toLowerCase();
const modalPiUrl = process.env.APEX_MODAL_PI_URL || "";
const modalPiIdleMs = Number.parseInt(process.env.APEX_MODAL_PI_IDLE_MS || "60000", 10);

interface DebugClientCommand {
  kind: "rpc" | "restart" | "clear_history";
  payload?: Record<string, unknown>;
}

interface StudioClientCommand {
  kind: "studio_prompt" | "studio_abort";
  message?: string;
}

type BridgeMessage = Record<string, unknown>;

let child: ChildProcessWithoutNullStreams | null = null;
let stdoutBuffer = "";
let remoteSocket: WebSocket | null = null;
let remoteConnecting: Promise<WebSocket> | null = null;
let remoteIdleTimer: NodeJS.Timeout | null = null;
let remoteStatus = piRuntimeMode === "modal" ? "idle" : "stopped";
let remotePid: number | null = null;
let bridgeSequence = 0;
const debugHistory: BridgeMessage[] = [];
const studioHistory: BridgeMessage[] = [];
const debugSessions = new Map<string, number>();
const debugWebsocketServer = new WebSocketServer({ noServer: true });
const studioWebsocketServer = new WebSocketServer({ noServer: true });

function stamp(value: BridgeMessage): BridgeMessage {
  return {
    ...value,
    bridge_seq: ++bridgeSequence,
    bridge_timestamp: new Date().toISOString(),
  };
}

function trimHistory(history: BridgeMessage[]): void {
  if (history.length > historyLimit) {
    history.splice(0, history.length - historyLimit);
  }
}

function sendToClients(websocketServer: WebSocketServer, value: BridgeMessage): void {
  const encoded = JSON.stringify(value);
  for (const client of websocketServer.clients) {
    if (client.readyState === WebSocket.OPEN) client.send(encoded);
  }
}

function friendlyActivity(toolName: string): { label: string; stage: string } {
  const exact: Record<string, { label: string; stage: string }> = {
    apex_create_project: { label: "正在建立创作项目", stage: "idea" },
    apex_generate_image: { label: "正在制作视觉画面", stage: "visual" },
    apex_generate_video: { label: "正在制作动态镜头", stage: "motion" },
    apex_generate_music: { label: "正在设计音乐与声音", stage: "music" },
    apex_render_mv: { label: "正在合成最终作品", stage: "render" },
  };
  if (exact[toolName]) return exact[toolName];
  const lower = toolName.toLowerCase();
  if (lower.includes("read") || lower.includes("search") || lower.includes("find")) {
    return { label: "正在整理创作素材", stage: "research" };
  }
  if (lower.includes("write") || lower.includes("edit")) {
    return { label: "正在完善创作方案", stage: "plan" };
  }
  return { label: "Apex 正在推进创作", stage: "create" };
}

function publicOutput(event: Record<string, unknown>): BridgeMessage | null {
  const result = event.result as Record<string, unknown> | undefined;
  const details = result?.details as Record<string, unknown> | undefined;
  const job = details?.job as Record<string, unknown> | undefined;
  const project = details?.project as Record<string, unknown> | undefined;
  if (!job && !project) return null;
  return {
    id:
      (job?.job_id as string | undefined) ||
      (project?.project_id as string | undefined) ||
      (event.toolCallId as string | undefined),
    kind: (job?.kind as string | undefined) || (project ? "project" : "creation"),
    title:
      (job?.job_id as string | undefined) ||
      (project?.title as string | undefined) ||
      "Apex creation",
    status:
      (job?.status as string | undefined) ||
      (project?.stage as string | undefined) ||
      (event.isError ? "error" : "ready"),
    provider: (job?.provider as string | undefined) || null,
    prompt:
      (job?.prompt as string | undefined) ||
      (project?.concept as string | undefined) ||
      "",
    paths: Array.isArray(job?.outputs) ? job.outputs : [],
  };
}

function sanitizeForStudio(message: BridgeMessage): BridgeMessage | null {
  const base = {
    bridge_seq: message.bridge_seq,
    bridge_timestamp: message.bridge_timestamp,
  };
  if (message.kind === "bridge_status") {
    return { ...base, kind: "studio_status", status: message.status };
  }
  if (message.kind === "bridge_history_cleared") {
    return { ...base, kind: "studio_history_cleared" };
  }
  if (message.kind === "bridge_error" || message.kind === "pi_stderr") {
    return {
      ...base,
      kind: "studio_error",
      message:
        message.kind === "bridge_error"
          ? message.message
          : "Apex 的创作服务暂时遇到问题，请稍后再试。",
    };
  }
  if (message.kind === "bridge_command") {
    const command = message.command as Record<string, unknown> | undefined;
    if (command?.type === "prompt") {
      return {
        ...base,
        kind: "studio_run",
        id: command.id,
        prompt: command.message,
      };
    }
    if (command?.type === "abort") return { ...base, kind: "studio_abort" };
    return null;
  }
  if (message.kind !== "pi_event") return null;

  const event = (message.event || {}) as Record<string, unknown>;
  if (event.type === "agent_start") return { ...base, kind: "studio_lifecycle", status: "running" };
  if (event.type === "agent_settled") {
    return { ...base, kind: "studio_lifecycle", status: "complete" };
  }
  if (event.type === "message_update") {
    const update = (event.assistantMessageEvent || {}) as Record<string, unknown>;
    if (update.type === "text_delta" || update.type === "text_end") {
      return {
        ...base,
        kind: "studio_response",
        mode: update.type === "text_delta" ? "delta" : "final",
        text: update.type === "text_delta" ? update.delta : update.content,
      };
    }
    if (update.type === "error") {
      return {
        ...base,
        kind: "studio_error",
        message: "Apex 没能完成这次创作，请调整描述后重试。",
      };
    }
    return null;
  }
  if (event.type === "message_end") {
    const message = (event.message || {}) as Record<string, unknown>;
    if (message.role === "assistant" && message.stopReason === "error") {
      return {
        ...base,
        kind: "studio_error",
        message: "Apex 暂时无法连接创作模型，请管理员检查模型配置。",
      };
    }
  }
  if (event.type === "tool_execution_start") {
    const activity = friendlyActivity(String(event.toolName || ""));
    return {
      ...base,
      kind: "studio_activity",
      id: event.toolCallId,
      status: "running",
      label: activity.label,
      stage: activity.stage,
    };
  }
  if (event.type === "tool_execution_end") {
    const activity = friendlyActivity(String(event.toolName || ""));
    return {
      ...base,
      kind: "studio_activity",
      id: event.toolCallId,
      status: event.isError ? "error" : "complete",
      label: activity.label.replace(/^正在/, ""),
      stage: activity.stage,
      output: publicOutput(event),
    };
  }
  if (event.type === "response" && event.command === "prompt" && event.success === false) {
    return {
      ...base,
      kind: "studio_error",
      message: "Apex 当前正在创作，请等待完成后再发送新的想法。",
    };
  }
  return null;
}

function broadcast(value: BridgeMessage, record = true): void {
  const debugMessage = stamp(value);
  if (record) {
    debugHistory.push(debugMessage);
    trimHistory(debugHistory);
  }
  sendToClients(debugWebsocketServer, debugMessage);

  const studioMessage = sanitizeForStudio(debugMessage);
  if (!studioMessage) return;
  if (record) {
    studioHistory.push(studioMessage);
    trimHistory(studioHistory);
  }
  sendToClients(studioWebsocketServer, studioMessage);
}

function runtimeStatus(): string {
  if (piRuntimeMode === "modal") return remoteStatus;
  return child ? "running" : "stopped";
}

function runtimePid(): number | null {
  return piRuntimeMode === "modal" ? remotePid : child?.pid || null;
}

function startLocalPi(): void {
  if (child) return;
  stdoutBuffer = "";
  child = spawn(
    cliPath,
    ["--mode", "rpc", "--no-session", "--extension", extensionPath],
    {
      cwd: projectDir,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  broadcast({ kind: "bridge_status", status: "starting", pid: child.pid });

  child.stdout.on("data", (chunk: Buffer) => {
    stdoutBuffer += chunk.toString("utf8");
    while (true) {
      const newline = stdoutBuffer.indexOf("\n");
      if (newline === -1) break;
      const line = stdoutBuffer.slice(0, newline).replace(/\r$/, "");
      stdoutBuffer = stdoutBuffer.slice(newline + 1);
      if (!line) continue;
      try {
        broadcast({ kind: "pi_event", event: JSON.parse(line) as unknown });
      } catch {
        broadcast({ kind: "pi_stdout", text: line });
      }
    }
  });

  child.stderr.on("data", (chunk: Buffer) => {
    broadcast({ kind: "pi_stderr", text: chunk.toString("utf8") });
  });

  child.on("spawn", () => {
    broadcast({ kind: "bridge_status", status: "running", pid: child?.pid });
  });

  child.on("exit", (code, signal) => {
    child = null;
    broadcast({ kind: "bridge_status", status: "stopped", code, signal });
  });

  child.on("error", (error) => {
    broadcast({ kind: "bridge_error", message: error.message });
  });
}

function modalWebsocketUrl(): string {
  const parsed = new URL(modalPiUrl);
  if (parsed.protocol === "https:") parsed.protocol = "wss:";
  if (parsed.protocol === "http:") parsed.protocol = "ws:";
  if (parsed.pathname === "/" || !parsed.pathname) parsed.pathname = "/runtime";
  return parsed.toString();
}

async function resolveModalRuntimeToken(): Promise<string> {
  if (process.env.APEX_MODAL_PI_TOKEN) return process.env.APEX_MODAL_PI_TOKEN;
  const config = await readFile(join(homedir(), ".modal.toml"), "utf8");
  const profileName = process.env.MODAL_PROFILE || "richardye980718";
  const escapedProfile = profileName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const profile = config.match(
    new RegExp(`\\[${escapedProfile}\\]([\\s\\S]*?)(?=\\n\\[|$)`),
  );
  const secret = profile?.[1].match(/^token_secret\s*=\s*["']([^"']+)["']/m);
  if (!secret) {
    throw new Error(
      `APEX_MODAL_PI_TOKEN is missing and Modal profile ${profileName} has no token_secret`,
    );
  }
  return createHash("sha256")
    .update(`apex-pi-runtime-v1:${secret[1]}`)
    .digest("hex");
}

function clearRemoteIdleTimer(): void {
  if (!remoteIdleTimer) return;
  clearTimeout(remoteIdleTimer);
  remoteIdleTimer = null;
}

function scheduleRemoteDisconnect(): void {
  if (piRuntimeMode !== "modal") return;
  clearRemoteIdleTimer();
  remoteIdleTimer = setTimeout(() => {
    remoteIdleTimer = null;
    if (remoteSocket?.readyState === WebSocket.OPEN) {
      remoteSocket.close(1000, "Apex creative session idle");
    }
  }, Math.max(2_000, modalPiIdleMs));
}

function handleRemoteMessage(raw: WebSocket.RawData): void {
  try {
    const message = JSON.parse(Buffer.from(raw as ArrayBuffer).toString("utf8")) as BridgeMessage;
    if (message.kind === "runtime_status") {
      remoteStatus = String(message.status || "unknown");
      remotePid = typeof message.pid === "number" ? message.pid : null;
      broadcast({
        kind: "bridge_status",
        status: remoteStatus,
        pid: remotePid,
        runtime: "modal",
        runtime_seq: message.runtime_seq,
        runtime_timestamp: message.runtime_timestamp,
      });
      return;
    }
    if (message.kind === "runtime_error") {
      broadcast({
        kind: "bridge_error",
        message: message.message || "Modal Pi runtime error",
        runtime: "modal",
      });
      return;
    }
    broadcast({ ...message, runtime: "modal" });
    if (message.kind === "pi_event") {
      const event = (message.event || {}) as Record<string, unknown>;
      if (event.type === "agent_start") clearRemoteIdleTimer();
      if (event.type === "agent_settled") scheduleRemoteDisconnect();
    }
  } catch (error) {
    broadcast({
      kind: "bridge_error",
      message: error instanceof Error ? error.message : "Invalid Modal runtime event",
      runtime: "modal",
    });
  }
}

async function connectRemotePi(): Promise<WebSocket> {
  if (remoteSocket?.readyState === WebSocket.OPEN) return remoteSocket;
  if (remoteConnecting) return remoteConnecting;
  if (!modalPiUrl) throw new Error("APEX_MODAL_PI_URL is required when APEX_PI_RUNTIME=modal");
  remoteStatus = "starting";
  broadcast({ kind: "bridge_status", status: "starting", runtime: "modal" });
  remoteConnecting = (async () => {
    const token = await resolveModalRuntimeToken();
    return new Promise<WebSocket>((resolveSocket, rejectSocket) => {
      const socket = new WebSocket(modalWebsocketUrl(), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const timeout = setTimeout(() => {
        socket.terminate();
        rejectSocket(new Error("Timed out connecting to Modal Pi runtime"));
      }, 60_000);
      socket.on("message", handleRemoteMessage);
      socket.once("open", () => {
        clearTimeout(timeout);
        remoteSocket = socket;
        remoteStatus = "running";
        broadcast({ kind: "bridge_status", status: "running", runtime: "modal" });
        resolveSocket(socket);
      });
      socket.once("error", (error) => {
        clearTimeout(timeout);
        if (socket.readyState !== WebSocket.OPEN) rejectSocket(error);
      });
      socket.once("close", (code, reason) => {
        clearTimeout(timeout);
        if (remoteSocket === socket) remoteSocket = null;
        remoteStatus = "idle";
        remotePid = null;
        broadcast({
          kind: "bridge_status",
          status: "idle",
          runtime: "modal",
          code,
          reason: reason.toString("utf8"),
        });
      });
    });
  })().finally(() => {
    remoteConnecting = null;
  });
  return remoteConnecting;
}

async function sendPiPayload(payload: Record<string, unknown>): Promise<void> {
  clearRemoteIdleTimer();
  if (piRuntimeMode === "modal") {
    const socket = await connectRemotePi();
    socket.send(JSON.stringify({ kind: "rpc", payload }));
  } else {
    if (!child) throw new Error("Pi RPC is not running");
    child.stdin.write(`${JSON.stringify(payload)}\n`);
  }
  broadcast({ kind: "bridge_command", command: payload, runtime: piRuntimeMode });
}

function stopPi(): void {
  clearRemoteIdleTimer();
  if (piRuntimeMode === "modal") {
    remoteSocket?.close(1000, "Local Apex bridge stopped");
    remoteSocket = null;
    remoteStatus = "idle";
    remotePid = null;
    return;
  }
  child?.kill("SIGTERM");
}

async function restartPi(): Promise<void> {
  if (piRuntimeMode === "modal") {
    const socket = await connectRemotePi();
    socket.send(JSON.stringify({ kind: "restart" }));
    return;
  }
  const running = child;
  if (!running) {
    startLocalPi();
    return;
  }
  running.once("exit", () => setTimeout(startLocalPi, 50));
  running.kill("SIGTERM");
}

function parseDebugCommand(raw: Buffer): DebugClientCommand | null {
  try {
    const value = JSON.parse(raw.toString("utf8")) as unknown;
    if (!value || typeof value !== "object") return null;
    const candidate = value as Record<string, unknown>;
    if (candidate.kind === "restart") return { kind: "restart" };
    if (candidate.kind === "clear_history") return { kind: "clear_history" };
    if (
      candidate.kind === "rpc" &&
      candidate.payload &&
      typeof candidate.payload === "object" &&
      !Array.isArray(candidate.payload)
    ) {
      return {
        kind: "rpc",
        payload: candidate.payload as Record<string, unknown>,
      };
    }
    return null;
  } catch {
    return null;
  }
}

function parseStudioCommand(raw: Buffer): StudioClientCommand | null {
  try {
    const value = JSON.parse(raw.toString("utf8")) as Record<string, unknown>;
    if (value?.kind === "studio_abort") return { kind: "studio_abort" };
    if (
      value?.kind === "studio_prompt" &&
      typeof value.message === "string" &&
      value.message.trim() &&
      value.message.length <= 50_000
    ) {
      return { kind: "studio_prompt", message: value.message.trim() };
    }
    return null;
  } catch {
    return null;
  }
}

function parseCookies(request: IncomingMessage): Record<string, string> {
  const result: Record<string, string> = {};
  for (const item of (request.headers.cookie || "").split(";")) {
    const separator = item.indexOf("=");
    if (separator === -1) continue;
    const key = item.slice(0, separator).trim();
    const value = item.slice(separator + 1).trim();
    if (key) result[key] = decodeURIComponent(value);
  }
  return result;
}

function isDebugAuthenticated(request: IncomingMessage): boolean {
  const token = parseCookies(request).apex_debug_session;
  if (!token) return false;
  const expiresAt = debugSessions.get(token);
  if (!expiresAt) return false;
  if (expiresAt <= Date.now()) {
    debugSessions.delete(token);
    return false;
  }
  return true;
}

function safeEqual(candidate: string, expected: string): boolean {
  const left = Buffer.from(candidate);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

async function readRequestBody(request: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.from(chunk);
    size += buffer.length;
    if (size > 16_384) throw new Error("Request body too large");
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function wantsSecureCookie(request: IncomingMessage): boolean {
  return request.headers["x-forwarded-proto"] === "https";
}

async function sendStatic(
  response: ServerResponse,
  file: string,
  contentType: string,
  status = 200,
): Promise<void> {
  try {
    const body = await readFile(join(publicDir, file));
    response.writeHead(status, {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    });
    response.end(body);
  } catch (error) {
    response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    response.end(error instanceof Error ? error.message : "Unable to load page");
  }
}

const studioStatic = new Map<string, { file: string; contentType: string }>([
  ["/", { file: "index.html", contentType: "text/html; charset=utf-8" }],
  ["/index.html", { file: "index.html", contentType: "text/html; charset=utf-8" }],
  ["/studio.css", { file: "studio.css", contentType: "text/css; charset=utf-8" }],
  ["/studio.js", { file: "studio.js", contentType: "text/javascript; charset=utf-8" }],
  ["/apex-cat.png", { file: "apex-cat.png", contentType: "image/png" }],
  ["/apex-cat-logo.png", { file: "apex-cat-logo.png", contentType: "image/png" }],
]);

const debugStatic = new Map<string, { file: string; contentType: string }>([
  ["/debug", { file: "debug.html", contentType: "text/html; charset=utf-8" }],
  ["/debug/", { file: "debug.html", contentType: "text/html; charset=utf-8" }],
  ["/debug/styles.css", { file: "styles.css", contentType: "text/css; charset=utf-8" }],
  ["/debug/app.js", { file: "app.js", contentType: "text/javascript; charset=utf-8" }],
]);

const sharedStatic = new Map<string, { file: string; contentType: string }>([
  [
    "/debugger-state.js",
    { file: "debugger-state.js", contentType: "text/javascript; charset=utf-8" },
  ],
]);

const mediaTypes: Record<string, string> = {
  ".avif": "image/avif",
  ".gif": "image/gif",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".mp3": "audio/mpeg",
  ".mp4": "video/mp4",
  ".ogg": "audio/ogg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".wav": "audio/wav",
  ".webm": "video/webm",
  ".webp": "image/webp",
};

const server = createServer(async (request, response) => {
  const requestUrl = new URL(request.url || "/", `http://${request.headers.host || "127.0.0.1"}`);
  const pathname = requestUrl.pathname;

  if (pathname === "/health") {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(
      JSON.stringify({
        ok: true,
        runtime: piRuntimeMode,
        pi: runtimeStatus(),
        pid: runtimePid(),
        bufferedDebugEvents: debugHistory.length,
        bufferedStudioEvents: studioHistory.length,
      }),
    );
    return;
  }

  if (pathname === "/debug/login" && request.method === "GET") {
    if (isDebugAuthenticated(request)) {
      response.writeHead(303, { Location: "/debug" });
      response.end();
      return;
    }
    await sendStatic(response, "debug-login.html", "text/html; charset=utf-8");
    return;
  }

  if (pathname === "/debug/login" && request.method === "POST") {
    if (!debugPassword) {
      response.writeHead(503, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("APEX_DEBUG_PASSWORD must be configured in production");
      return;
    }
    try {
      const form = new URLSearchParams(await readRequestBody(request));
      const username = form.get("username") || "";
      const password = form.get("password") || "";
      if (safeEqual(username, debugAdmin) && safeEqual(password, debugPassword)) {
        const token = randomBytes(32).toString("base64url");
        debugSessions.set(token, Date.now() + debugSessionLifetimeMs);
        const secure = wantsSecureCookie(request) ? "; Secure" : "";
        response.writeHead(303, {
          Location: "/debug",
          "Set-Cookie":
            `apex_debug_session=${encodeURIComponent(token)}; HttpOnly; SameSite=Strict; ` +
            `Path=/debug; Max-Age=${Math.floor(debugSessionLifetimeMs / 1000)}${secure}`,
        });
        response.end();
        return;
      }
      response.writeHead(303, {
        Location: "/debug/login?error=invalid",
        "Set-Cookie": "apex_debug_session=; HttpOnly; SameSite=Strict; Path=/debug; Max-Age=0",
      });
      response.end();
    } catch {
      response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Invalid login request");
    }
    return;
  }

  if (pathname === "/debug/logout" && request.method === "POST") {
    const token = parseCookies(request).apex_debug_session;
    if (token) debugSessions.delete(token);
    response.writeHead(303, {
      Location: "/debug/login",
      "Set-Cookie": "apex_debug_session=; HttpOnly; SameSite=Strict; Path=/debug; Max-Age=0",
    });
    response.end();
    return;
  }

  const debugFile = debugStatic.get(pathname);
  if (debugFile) {
    if (!isDebugAuthenticated(request)) {
      response.writeHead(303, { Location: "/debug/login" });
      response.end();
      return;
    }
    await sendStatic(response, debugFile.file, debugFile.contentType);
    return;
  }

  if (pathname === "/asset") {
    const requestedPath = requestUrl.searchParams.get("path");
    if (!requestedPath) {
      response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Missing asset path");
      return;
    }
    const resolvedPath = resolve(requestedPath);
    const isInsideApex =
      resolvedPath === apexAssetsRoot || resolvedPath.startsWith(`${apexAssetsRoot}${sep}`);
    if (!isInsideApex) {
      response.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Only .apex assets may be previewed");
      return;
    }
    try {
      const asset = await readFile(resolvedPath);
      response.writeHead(200, {
        "Content-Type": mediaTypes[extname(resolvedPath).toLowerCase()] || "application/octet-stream",
        "Cache-Control": "no-store",
      });
      response.end(asset);
    } catch {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Asset not found");
    }
    return;
  }

  const staticFile = studioStatic.get(pathname) || sharedStatic.get(pathname);
  if (staticFile) {
    await sendStatic(response, staticFile.file, staticFile.contentType);
    return;
  }

  response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  response.end("Not found");
});

server.on("upgrade", (request, socket, head) => {
  const pathname = new URL(
    request.url || "/",
    `http://${request.headers.host || "127.0.0.1"}`,
  ).pathname;
  if (pathname === "/debug/ws") {
    if (!isDebugAuthenticated(request)) {
      socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
      socket.destroy();
      return;
    }
    debugWebsocketServer.handleUpgrade(request, socket, head, (websocket) => {
      debugWebsocketServer.emit("connection", websocket, request);
    });
    return;
  }
  if (pathname === "/ws") {
    studioWebsocketServer.handleUpgrade(request, socket, head, (websocket) => {
      studioWebsocketServer.emit("connection", websocket, request);
    });
    return;
  }
  socket.destroy();
});

debugWebsocketServer.on("connection", (socket) => {
  socket.send(
    JSON.stringify({
      kind: "bridge_snapshot",
      events: debugHistory,
      bridge_seq: bridgeSequence,
      bridge_timestamp: new Date().toISOString(),
    }),
  );
  socket.send(
    JSON.stringify({
      kind: "bridge_status",
      status: runtimeStatus(),
      pid: runtimePid(),
      runtime: piRuntimeMode,
      bridge_seq: bridgeSequence,
      bridge_timestamp: new Date().toISOString(),
    }),
  );
  socket.on("message", (raw) => {
    const command = parseDebugCommand(Buffer.from(raw as ArrayBuffer));
    if (!command) {
      socket.send(JSON.stringify(stamp({ kind: "bridge_error", message: "Invalid bridge command" })));
      return;
    }
    if (command.kind === "restart") {
      void restartPi().catch((error) => {
        socket.send(
          JSON.stringify(
            stamp({
              kind: "bridge_error",
              message: error instanceof Error ? error.message : "Unable to restart Pi",
            }),
          ),
        );
      });
      return;
    }
    if (command.kind === "clear_history") {
      debugHistory.length = 0;
      studioHistory.length = 0;
      broadcast({ kind: "bridge_history_cleared" }, false);
      return;
    }
    if (!command.payload) {
      socket.send(JSON.stringify(stamp({ kind: "bridge_error", message: "Pi RPC is not running" })));
      return;
    }
    void sendPiPayload(command.payload).catch((error) => {
      socket.send(
        JSON.stringify(
          stamp({
            kind: "bridge_error",
            message: error instanceof Error ? error.message : "Unable to reach Pi runtime",
          }),
        ),
      );
    });
  });
});

studioWebsocketServer.on("connection", (socket) => {
  socket.send(
    JSON.stringify({
      kind: "studio_snapshot",
      events: studioHistory,
      bridge_seq: bridgeSequence,
      bridge_timestamp: new Date().toISOString(),
    }),
  );
  socket.send(
    JSON.stringify({
      kind: "studio_status",
      status: runtimeStatus(),
      runtime: piRuntimeMode,
      bridge_seq: bridgeSequence,
      bridge_timestamp: new Date().toISOString(),
    }),
  );
  socket.on("message", (raw) => {
    const command = parseStudioCommand(Buffer.from(raw as ArrayBuffer));
    if (!command) {
      socket.send(
        JSON.stringify(
          stamp({ kind: "studio_error", message: "这条创作指令无法识别，请重新描述。" }),
        ),
      );
      return;
    }
    if (piRuntimeMode === "local" && !child) {
      socket.send(
        JSON.stringify(
          stamp({ kind: "studio_error", message: "Apex 创作服务尚未准备好，请稍后重试。" }),
        ),
      );
      return;
    }
    const payload =
      command.kind === "studio_abort"
        ? { id: randomBytes(12).toString("hex"), type: "abort" }
        : {
            id: randomBytes(12).toString("hex"),
            type: "prompt",
            message: command.message,
          };
    void sendPiPayload(payload).catch((error) => {
      socket.send(
        JSON.stringify(
          stamp({
            kind: "studio_error",
            message:
              error instanceof Error
                ? `Apex 无法连接创作服务：${error.message}`
                : "Apex 无法连接创作服务。",
          }),
        ),
      );
    });
  });
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Apex Studio: http://127.0.0.1:${port}`);
  console.log(`Apex Debug:  http://127.0.0.1:${port}/debug`);
  if (!process.env.APEX_DEBUG_PASSWORD && !isProduction) {
    console.log("Local debug login: admin / apex-local");
  }
  if (piRuntimeMode === "local") {
    startLocalPi();
  } else {
    broadcast({ kind: "bridge_status", status: "idle", runtime: "modal" });
    console.log(`Pi runtime: Modal (${modalPiUrl || "APEX_MODAL_PI_URL missing"})`);
  }
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    stopPi();
    server.close(() => process.exit(0));
  });
}
