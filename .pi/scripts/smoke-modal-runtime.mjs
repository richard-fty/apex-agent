import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import WebSocket from "ws";

const endpoint =
  process.env.APEX_MODAL_PI_URL ||
  "https://richardye980718--apex-pi-runtime-pi-runtime.modal.run";
const profileName = process.env.MODAL_PROFILE || "richardye980718";
const modalConfig = readFileSync(join(homedir(), ".modal.toml"), "utf8");
const escapedProfile = profileName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const profileMatch = modalConfig.match(
  new RegExp(`\\[${escapedProfile}\\]([\\s\\S]*?)(?=\\n\\[|$)`),
);
const secretMatch = profileMatch?.[1].match(/^token_secret\s*=\s*["']([^"']+)["']/m);
if (!secretMatch) {
  throw new Error(`Modal profile ${profileName} has no token_secret`);
}
const runtimeToken = createHash("sha256")
  .update(`apex-pi-runtime-v1:${secretMatch[1]}`)
  .digest("hex");
const url = new URL("/runtime", endpoint);
url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

const socket = new WebSocket(url, {
  headers: { Authorization: `Bearer ${runtimeToken}` },
});
let commandsSent = false;
let piRpcOk = false;
let sandboxOk = false;

const timeout = setTimeout(() => {
  console.error("Modal runtime smoke test timed out");
  socket.terminate();
  process.exitCode = 1;
}, 120_000);

function finishIfReady() {
  if (!piRpcOk || !sandboxOk) return;
  clearTimeout(timeout);
  console.log("Modal Pi RPC: ok");
  console.log("Modal Sandbox: ok");
  socket.close(1000);
}

socket.on("message", (raw) => {
  const message = JSON.parse(raw.toString());
  if (
    message.kind === "runtime_status" &&
    message.status === "running" &&
    !commandsSent
  ) {
    commandsSent = true;
    socket.send(
      JSON.stringify({
        kind: "rpc",
        payload: { id: "modal-smoke-state", type: "get_state" },
      }),
    );
    socket.send(JSON.stringify({ kind: "sandbox_diagnostic" }));
    return;
  }
  if (
    message.kind === "pi_event" &&
    message.event?.type === "response" &&
    message.event?.id === "modal-smoke-state"
  ) {
    if (message.event.success === false) {
      throw new Error(`Pi RPC failed: ${message.event.error || "unknown error"}`);
    }
    piRpcOk = true;
    finishIfReady();
    return;
  }
  if (message.kind === "sandbox_diagnostic") {
    const stdout = String(message.result?.stdout || "");
    sandboxOk =
      message.ok === true &&
      stdout.includes("apex-modal-sandbox-ok") &&
      stdout.includes("v24.");
    if (!sandboxOk) {
      throw new Error(`Sandbox diagnostic failed: ${JSON.stringify(message.result)}`);
    }
    finishIfReady();
    return;
  }
  if (message.kind === "runtime_error") {
    throw new Error(`Remote runtime error: ${message.message}`);
  }
});

socket.on("error", (error) => {
  clearTimeout(timeout);
  console.error(error.message);
  process.exitCode = 1;
});

socket.on("close", () => {
  clearTimeout(timeout);
  if (!piRpcOk || !sandboxOk) process.exitCode = 1;
});
