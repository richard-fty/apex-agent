import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { WebSocket, WebSocketServer } from "ws";

const port = Number.parseInt(process.env.APEX_REMOTE_RUNTIME_PORT || "8788", 10);
const runtimeToken = process.env.APEX_RUNTIME_TOKEN || "";
const piRoot = "/app/.pi";
const workspace = process.env.APEX_REMOTE_WORKSPACE || "/workspace";
const cliPath = join(piRoot, "node_modules", ".bin", "pi");
const creativeExtensionPath = join(piRoot, "extensions", "apex-creative.ts");
const sandboxExtensionPath = join(piRoot, "extensions", "modal-sandbox.ts");
const skillPath = join(piRoot, "skills", "apex-anime-mv", "SKILL.md");
const systemPromptPath = join(piRoot, "SYSTEM.md");
const websocketServer = new WebSocketServer({ noServer: true });

let child: ChildProcessWithoutNullStreams | null = null;
let stdoutBuffer = "";
let runtimeSequence = 0;
let disconnectTimer: NodeJS.Timeout | null = null;

type RuntimeMessage = Record<string, unknown>;

function stamp(message: RuntimeMessage): RuntimeMessage {
  return {
    ...message,
    runtime: "modal",
    runtime_seq: ++runtimeSequence,
    runtime_timestamp: new Date().toISOString(),
  };
}

function broadcast(message: RuntimeMessage): void {
  const encoded = JSON.stringify(stamp(message));
  for (const socket of websocketServer.clients) {
    if (socket.readyState === WebSocket.OPEN) socket.send(encoded);
  }
}

function send(socket: WebSocket, message: RuntimeMessage): void {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(stamp(message)));
  }
}

function safeEqual(candidate: string, expected: string): boolean {
  const left = Buffer.from(candidate);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

function isAuthorized(header: string | undefined): boolean {
  if (!runtimeToken) return false;
  const expected = `Bearer ${runtimeToken}`;
  return safeEqual(header || "", expected);
}

async function installPiConfiguration(): Promise<void> {
  const agentDir = join(homedir(), ".pi", "agent");
  await mkdir(agentDir, { recursive: true });
  const authJson = process.env.APEX_PI_AUTH_JSON;
  const modelsJson = process.env.APEX_PI_MODELS_JSON;
  if (authJson) {
    await writeFile(join(agentDir, "auth.json"), `${authJson.trim()}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
  }
  if (modelsJson) {
    await writeFile(join(agentDir, "models.json"), `${modelsJson.trim()}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
  }
}

function piEnvironment(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  delete env.APEX_RUNTIME_TOKEN;
  delete env.APEX_PI_AUTH_JSON;
  delete env.APEX_PI_MODELS_JSON;
  return env;
}

async function startPi(): Promise<void> {
  if (child) return;
  if (disconnectTimer) {
    clearTimeout(disconnectTimer);
    disconnectTimer = null;
  }
  await installPiConfiguration();
  const systemPrompt = await readFile(systemPromptPath, "utf8");
  stdoutBuffer = "";
  child = spawn(
    cliPath,
    [
      "--mode",
      "rpc",
      "--no-session",
      "--approve",
      "--extension",
      creativeExtensionPath,
      "--extension",
      sandboxExtensionPath,
      "--skill",
      skillPath,
      "--append-system-prompt",
      systemPrompt,
    ],
    {
      cwd: workspace,
      env: piEnvironment(),
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  broadcast({ kind: "runtime_status", status: "starting", pid: child.pid });

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
    broadcast({ kind: "runtime_status", status: "running", pid: child?.pid });
  });

  child.on("exit", (code, signal) => {
    child = null;
    broadcast({ kind: "runtime_status", status: "stopped", code, signal });
  });

  child.on("error", (error) => {
    broadcast({ kind: "runtime_error", message: error.message });
  });
}

function stopPi(): void {
  child?.kill("SIGTERM");
}

async function restartPi(): Promise<void> {
  const running = child;
  if (!running) {
    await startPi();
    return;
  }
  running.once("exit", () => {
    void startPi();
  });
  running.kill("SIGTERM");
}

function scheduleStopAfterDisconnect(): void {
  if (websocketServer.clients.size > 0 || disconnectTimer) return;
  disconnectTimer = setTimeout(() => {
    disconnectTimer = null;
    if (websocketServer.clients.size === 0) stopPi();
  }, 10_000);
}

async function runSandboxDiagnostic(socket: WebSocket): Promise<void> {
  try {
    const baseUrl = process.env.APEX_SANDBOX_BROKER_URL || "http://127.0.0.1:8790";
    const response = await fetch(`${baseUrl}/v1/sandbox/exec`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        command: "printf 'apex-modal-sandbox-ok\\n'; node --version; python3 --version",
        timeout: 60,
      }),
    });
    const result = (await response.json()) as RuntimeMessage;
    send(socket, {
      kind: "sandbox_diagnostic",
      ok: response.ok,
      result,
    });
  } catch (error) {
    send(socket, {
      kind: "sandbox_diagnostic",
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

const server = createServer((request, response) => {
  const requestUrl = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  if (requestUrl.pathname === "/health") {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(
      JSON.stringify({
        ok: true,
        runtime: "modal",
        pi: child ? "running" : "stopped",
        clients: websocketServer.clients.size,
      }),
    );
    return;
  }
  response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  response.end("Not found");
});

server.on("upgrade", (request, socket, head) => {
  const requestUrl = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  if (requestUrl.pathname !== "/runtime") {
    socket.destroy();
    return;
  }
  if (!isAuthorized(request.headers.authorization)) {
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
    return;
  }
  websocketServer.handleUpgrade(request, socket, head, (websocket) => {
    websocketServer.emit("connection", websocket, request);
  });
});

websocketServer.on("connection", (socket) => {
  if (disconnectTimer) {
    clearTimeout(disconnectTimer);
    disconnectTimer = null;
  }
  void startPi()
    .then(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify(
            stamp({
              kind: "runtime_status",
              status: child ? "running" : "starting",
              pid: child?.pid,
            }),
          ),
        );
      }
    })
    .catch((error) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify(
            stamp({
              kind: "runtime_error",
              message: error instanceof Error ? error.message : String(error),
            }),
          ),
        );
      }
    });

  socket.on("message", (raw) => {
    try {
      const command = JSON.parse(Buffer.from(raw as ArrayBuffer).toString("utf8")) as {
        kind?: string;
        payload?: Record<string, unknown>;
      };
      if (command.kind === "restart") {
        void restartPi();
        return;
      }
      if (command.kind === "sandbox_diagnostic") {
        void runSandboxDiagnostic(socket);
        return;
      }
      if (command.kind !== "rpc" || !command.payload) {
        socket.send(
          JSON.stringify(stamp({ kind: "runtime_error", message: "Invalid runtime command" })),
        );
        return;
      }
      if (!child) {
        socket.send(
          JSON.stringify(stamp({ kind: "runtime_error", message: "Pi RPC is not running" })),
        );
        return;
      }
      child.stdin.write(`${JSON.stringify(command.payload)}\n`);
    } catch (error) {
      socket.send(
        JSON.stringify(
          stamp({
            kind: "runtime_error",
            message: error instanceof Error ? error.message : "Invalid JSON",
          }),
        ),
      );
    }
  });

  socket.on("close", scheduleStopAfterDisconnect);
});

server.listen(port, "0.0.0.0", () => {
  console.log(`Apex Modal Pi Runtime listening on 0.0.0.0:${port}`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    if (disconnectTimer) clearTimeout(disconnectTimer);
    stopPi();
    server.close(() => process.exit(0));
  });
}
