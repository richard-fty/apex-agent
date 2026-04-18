import { useRef, useState } from "react";
import { Button } from "../ui/button";
import { useStore } from "../../store";
import { postJSON } from "../../lib/api";
import { ArrowUp, Loader2 } from "lucide-react";

export function Composer({ sessionId }: { sessionId: string }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const session = useStore((s) => s.sessions[sessionId]);
  const pending = session?.pending ?? null;
  const status = session?.status ?? "idle";

  async function send() {
    const msg = text.trim();
    if (!msg || sending) return;
    setSending(true);
    try {
      await postJSON(`/sessions/${sessionId}/turns`, { user_input: msg });
      setText("");
      if (taRef.current) taRef.current.style.height = "auto";
    } catch (e) {
      console.error(e);
    } finally {
      setSending(false);
    }
  }

  async function resolveApproval(action: "approve_once" | "deny") {
    await postJSON(`/sessions/${sessionId}/approvals`, { action });
  }

  // Approval strip takes over the composer when agent is waiting for input.
  if (pending) {
    return (
      <div className="border-t border-border bg-background">
        <div className="mx-auto max-w-3xl px-6 py-4 space-y-2">
          <div className="text-sm">
            <span className="font-medium">Approval required</span> for{" "}
            <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">
              {pending.tool_name}
            </code>{" "}
            <span className="text-muted-foreground">· {pending.reason}</span>
          </div>
          <div className="flex gap-2">
            <Button onClick={() => resolveApproval("approve_once")}>Approve once</Button>
            <Button variant="outline" onClick={() => resolveApproval("deny")}>Deny</Button>
          </div>
        </div>
      </div>
    );
  }

  const disabled = status === "running" || sending;

  return (
    <div className="border-t border-border bg-background">
      <form
        className="mx-auto max-w-3xl px-6 py-4"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <div className="relative flex items-end rounded-2xl border border-input bg-secondary/30 focus-within:border-ring focus-within:ring-1 focus-within:ring-ring">
          <textarea
            ref={taRef}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              // auto-grow up to ~8 lines
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = Math.min(el.scrollHeight, 240) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={disabled ? "Agent is working…" : "Ask anything, create anything"}
            disabled={disabled}
            rows={1}
            className="flex-1 resize-none bg-transparent px-4 py-3 pr-12 text-sm leading-relaxed placeholder:text-muted-foreground focus:outline-none disabled:opacity-60"
          />
          <Button
            type="submit"
            size="icon"
            disabled={disabled || !text.trim()}
            className="absolute right-2 bottom-2 h-8 w-8 rounded-full"
            aria-label="Send"
          >
            {sending || status === "running" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </Button>
        </div>
        <p className="mt-2 text-center text-[11px] text-muted-foreground">
          Shift + Enter for new line · Enter to send
        </p>
      </form>
    </div>
  );
}
