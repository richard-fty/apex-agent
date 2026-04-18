import { useStore } from "../../store";
import { Search, Globe, Wrench, Loader2, CheckCircle2, XCircle, ChevronRight } from "lucide-react";

/** Map tool names to an icon + friendly label. Falls back to Wrench. */
function iconFor(name: string) {
  const lower = name.toLowerCase();
  if (lower.includes("search") || lower.includes("web")) return <Search className="h-4 w-4" />;
  if (lower.includes("fetch") || lower.includes("browse")) return <Globe className="h-4 w-4" />;
  return <Wrench className="h-4 w-4" />;
}

function prettyLabel(name: string) {
  return name
    .split(/[_-]/)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(" ");
}

function shortArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return "";
  // Prefer a query/path/url field if present.
  const preferred = ["query", "q", "path", "url"];
  for (const key of preferred) {
    if (key in args && typeof args[key] === "string") {
      return String(args[key]);
    }
  }
  // Fallback: first stringy value, truncated.
  const firstStr = entries.find(([, v]) => typeof v === "string");
  if (firstStr) return String(firstStr[1]);
  return JSON.stringify(args).slice(0, 80);
}

export function ToolChip({
  sessionId,
  toolCallId,
}: {
  sessionId: string;
  toolCallId: string;
}) {
  const tc = useStore((s) => s.sessions[sessionId]?.toolCalls[toolCallId]);
  const openTool = useStore((s) => s.openTool);
  const active = useStore(
    (s) => s.ui.panel.kind === "tool" && s.ui.panel.toolCallId === toolCallId,
  );

  if (!tc) return null;

  const statusIcon =
    tc.status === "running" ? (
      <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
    ) : tc.status === "completed" ? (
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
    ) : (
      <XCircle className="h-3.5 w-3.5 text-destructive" />
    );

  return (
    <button
      onClick={() => openTool(toolCallId)}
      className={`w-full text-left rounded-lg border transition-colors
        ${active ? "border-primary/50 bg-secondary/70" : "border-border bg-secondary/40 hover:bg-secondary/70"}
        px-3 py-2 flex items-center gap-3 text-sm`}
    >
      <span className="text-muted-foreground">{iconFor(tc.name)}</span>
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-xs text-muted-foreground shrink-0">Using Tool</span>
        <span className="text-muted-foreground">·</span>
        <span className="font-medium shrink-0">{prettyLabel(tc.name)}</span>
        <span className="text-muted-foreground truncate">{shortArgs(tc.arguments)}</span>
      </div>
      <span className="shrink-0">{statusIcon}</span>
      <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
    </button>
  );
}
