import { useStore } from "../../store";
import { Loader2 } from "lucide-react";

/**
 * Live activity strip: shows what the agent is doing RIGHT NOW.
 *
 * - "Thinking…"                    while running but no tool active yet
 * - "Searching the web…"           while a web_search tool is running
 * - "Running code…" etc.           while a matching tool is running
 *
 * Hidden when status is idle / completed / failed. Only one at a time —
 * picks the most recent running tool.
 */
export function ActivityBar({ sessionId }: { sessionId: string }) {
  const session = useStore((s) => s.sessions[sessionId]);
  if (!session) return null;
  if (session.status !== "running") return null;

  // Find the most recent running tool (reverse scan of items).
  let label = "Thinking…";
  for (let i = session.items.length - 1; i >= 0; i--) {
    const it = session.items[i];
    if (it.kind === "tool") {
      const tc = session.toolCalls[it.toolCallId];
      if (tc?.status === "running") {
        label = prettyActivity(tc.name);
        break;
      }
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 pt-1">
      <div className="inline-flex items-center gap-2 rounded-full bg-secondary/50 border border-border/60 px-3 py-1 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        <span className="bg-gradient-to-r from-muted-foreground via-foreground to-muted-foreground bg-[length:200%_100%] bg-clip-text text-transparent animate-shimmer">
          {label}
        </span>
      </div>
    </div>
  );
}

function prettyActivity(name: string): string {
  const lower = name.toLowerCase();
  if (lower.includes("web_search") || lower.includes("search")) return "Searching the web…";
  if (lower.includes("fetch") || lower.includes("browse"))       return "Reading page…";
  if (lower.includes("rag") || lower.includes("recall"))          return "Searching memory…";
  if (lower.includes("write_file") || lower.includes("edit_file")) return "Writing files…";
  if (lower.includes("read_file") || lower.includes("list_dir"))   return "Reading files…";
  if (lower.includes("run_command") || lower.includes("exec"))     return "Running command…";
  if (lower.includes("todo") || lower.includes("plan"))            return "Planning…";
  if (lower.includes("chart") || lower.includes("plot"))           return "Generating chart…";
  // Fallback: humanize the tool name.
  const human = name.split(/[_-]/).map((s) => s.charAt(0).toUpperCase() + s.slice(1)).join(" ");
  return `Running ${human}…`;
}
