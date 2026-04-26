import { useEffect } from "react";
import { useStore } from "../store";
import type { AgentEvent } from "../types";

/** Subscribe to the agent server's SSE event stream for a session.
 *
 * The browser's EventSource auto-reconnects; we use `Last-Event-ID` implicitly
 * (EventSource sends the last `id: N` header on reconnect) so the server
 * replays events after that seq from the in-memory bus buffer.
 */
export function useSSE(sessionId: string | null) {
  const ingest = useStore((s) => s.ingest);
  useEffect(() => {
    if (!sessionId) return;
    const url = `/sessions/${encodeURIComponent(sessionId)}/events`;
    const es = new EventSource(url, { withCredentials: true });

    const handlers: string[] = [
      "session_created", "turn_started", "turn_finished", "stream_end", "error",
      "assistant_token", "assistant_message", "assistant_note",
      "education_disclaimer",
      "skill_auto_loaded", "plan_updated",
      "tool_started", "tool_finished", "tool_denied",
      "approval_requested", "approval_resolved",
      "artifact_created", "artifact_patch", "artifact_finalized", "artifact_deleted",
      "sandbox_exec_started", "sandbox_exec_output", "sandbox_exec_finished",
      "usage",
    ];
    handlers.forEach((name) => {
      es.addEventListener(name, (ev: MessageEvent) => {
        try {
          const parsed = JSON.parse(ev.data) as AgentEvent;
          ingest(sessionId, parsed);
        } catch (e) {
          console.error("SSE parse error", name, e);
        }
      });
    });

    es.onerror = (e) => console.warn("SSE disconnected, browser will retry", e);
    return () => es.close();
  }, [sessionId, ingest]);
}
