import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import {
  createBashTool,
  type BashOperations,
} from "@earendil-works/pi-coding-agent";

const brokerUrl = process.env.APEX_SANDBOX_BROKER_URL || "http://127.0.0.1:8790";
const remoteWorkspace = process.env.APEX_REMOTE_WORKSPACE || "/workspace";

interface SandboxExecResponse {
  ok: boolean;
  sandbox_id?: string;
  stdout?: string;
  stderr?: string;
  exit_code?: number | null;
  error?: string;
}

let lastSandboxId: string | null = null;

function reportSandbox(
  ctx: ExtensionContext,
  status: string,
  extra: Record<string, unknown> = {},
): void {
  ctx.ui.setStatus(
    "apex-modal-sandbox",
    JSON.stringify({
      backend: "modal",
      status,
      sandbox_id: lastSandboxId,
      ...extra,
    }),
  );
}

async function brokerRequest(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<SandboxExecResponse> {
  const response = await fetch(`${brokerUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const result = (await response.json()) as SandboxExecResponse;
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `Modal Sandbox broker returned HTTP ${response.status}`);
  }
  if (result.sandbox_id) lastSandboxId = result.sandbox_id;
  return result;
}

function createModalBashOperations(ctx: ExtensionContext): BashOperations {
  return {
    exec: async (command, cwd, { onData, signal, timeout, env }) => {
      reportSandbox(ctx, "running", { command });
      const result = await brokerRequest(
        "/v1/sandbox/exec",
        {
          command,
          cwd: cwd || remoteWorkspace,
          timeout: timeout || 120,
          env: Object.fromEntries(
            Object.entries(env || {}).filter((entry): entry is [string, string] => {
              const [key, value] = entry;
              return (
                typeof value === "string" &&
                !/(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)/i.test(key)
              );
            }),
          ),
        },
        signal,
      );
      if (result.stdout) onData(Buffer.from(result.stdout));
      if (result.stderr) onData(Buffer.from(result.stderr));
      reportSandbox(ctx, "ready", { exit_code: result.exit_code });
      return { exitCode: result.exit_code ?? null };
    },
  };
}

export default function modalSandbox(pi: ExtensionAPI): void {
  const localDefinition = createBashTool(remoteWorkspace);

  pi.registerTool({
    ...localDefinition,
    async execute(id, params, signal, onUpdate, ctx) {
      const remoteTool = createBashTool(remoteWorkspace, {
        operations: createModalBashOperations(ctx),
        exposeSessionEnvironment: false,
      });
      const result = await remoteTool.execute(id, params, signal, onUpdate);
      return {
        ...result,
        details: {
          ...(result.details || {}),
          sandbox: {
            backend: "modal",
            sandbox_id: lastSandboxId,
            workspace: remoteWorkspace,
          },
        },
      };
    },
  });

  pi.on("user_bash", async (_event, ctx) => {
    return {
      operations: createModalBashOperations(ctx),
    };
  });

  pi.on("before_agent_start", (event) => {
    const note =
      `Command execution is isolated in a Modal Sandbox at ${remoteWorkspace}. ` +
      "Use the bash tool for FFmpeg, Python, Node.js, Git, downloads, and other command work.";
    return {
      systemPrompt: `${event.systemPrompt}\n\n${note}`,
    };
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (!lastSandboxId) return;
    reportSandbox(ctx, "stopping");
    try {
      await brokerRequest("/v1/sandbox/destroy", {});
    } finally {
      lastSandboxId = null;
      ctx.ui.setStatus("apex-modal-sandbox", undefined);
    }
  });
}
