import { useStore, type SessionState, type ToolCallRecord } from "../../store";
import { Button } from "../ui/button";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { X, Loader2, CheckCircle2, XCircle } from "lucide-react";

export function ArtifactPanel({ sessionId }: { sessionId: string }) {
  const session = useStore((s) => s.sessions[sessionId]);
  const ui = useStore((s) => s.ui);
  const closePanel = useStore((s) => s.closePanel);

  if (ui.panel.kind === "closed" || !session) return null;

  return (
    <div
      className="h-full flex flex-col border-l border-border bg-background"
      style={{ width: `${ui.panelWidthPct}%`, minWidth: 400 }}
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        {ui.panel.kind === "artifact" ? (
          <ArtifactHeader sessionId={sessionId} artifactId={ui.panel.artifactId} />
        ) : (
          <ToolHeader session={session} toolCallId={ui.panel.toolCallId} />
        )}
        <Button variant="ghost" size="icon" onClick={closePanel} aria-label="Close">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-auto">
        {ui.panel.kind === "artifact" ? (
          <ArtifactBody sessionId={sessionId} artifactId={ui.panel.artifactId} />
        ) : (
          <ToolBody session={session} toolCallId={ui.panel.toolCallId} />
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Artifact view
 * -------------------------------------------------------------------------- */

function ArtifactHeader({
  sessionId,
  artifactId,
}: {
  sessionId: string;
  artifactId: string;
}) {
  const session = useStore((s) => s.sessions[sessionId]);
  const openArtifact = useStore((s) => s.openArtifact);
  const ui = useStore((s) => s.ui);
  const setArtifactView = useStore((s) => s.setArtifactView);
  if (!session) return null;

  const artifact = session.artifacts[artifactId];
  const order = session.artifactOrder;

  return (
    <div className="flex items-center gap-2 min-w-0">
      <select
        value={artifactId}
        onChange={(e) => openArtifact(e.target.value)}
        className="bg-transparent border border-input rounded-md px-2 py-1 text-sm max-w-[240px] truncate"
      >
        {order.map((id) => (
          <option key={id} value={id}>
            {session.artifacts[id]?.name ?? id.slice(0, 8)}
          </option>
        ))}
      </select>
      {artifact && (
        <div className="flex rounded-md border border-border overflow-hidden">
          <button
            className={`px-2 py-1 text-xs ${ui.artifactView === "preview" ? "bg-secondary" : ""}`}
            onClick={() => setArtifactView("preview")}
          >
            Preview
          </button>
          <button
            className={`px-2 py-1 text-xs ${ui.artifactView === "source" ? "bg-secondary" : ""}`}
            onClick={() => setArtifactView("source")}
          >
            Source
          </button>
        </div>
      )}
      {artifact && !artifact.finalized && (
        <span className="text-xs text-muted-foreground animate-pulse">Streaming…</span>
      )}
    </div>
  );
}

function ArtifactBody({
  sessionId,
  artifactId,
}: {
  sessionId: string;
  artifactId: string;
}) {
  const session = useStore((s) => s.sessions[sessionId]);
  const view = useStore((s) => s.ui.artifactView);
  if (!session) return null;
  const artifact = session.artifacts[artifactId];
  if (!artifact) {
    return <div className="p-4 text-muted-foreground text-sm">Artifact missing.</div>;
  }

  const content = artifact.content;

  if (view === "source") {
    return (
      <SyntaxHighlighter
        language={artifact.language ?? "text"}
        style={oneDark}
        customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
      >
        {content || " "}
      </SyntaxHighlighter>
    );
  }

  switch (artifact.kind) {
    case "markdown":
      return (
        <div className="prose prose-sm prose-invert max-w-none px-6 py-6
                        prose-headings:mt-5 prose-headings:mb-2
                        prose-pre:bg-transparent prose-pre:p-0
                        prose-a:text-sky-400 hover:prose-a:text-sky-300">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {healMarkdown(content) || " "}
          </ReactMarkdown>
        </div>
      );
    case "code":
    case "json":
    case "text":
    case "terminal_log":
      return (
        <SyntaxHighlighter
          language={
            artifact.language ??
            (artifact.kind === "json" ? "json" : artifact.kind === "terminal_log" ? "bash" : "text")
          }
          style={oneDark}
          customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
        >
          {content || " "}
        </SyntaxHighlighter>
      );
    default:
      return (
        <div className="p-4 text-sm text-muted-foreground">
          Artifact kind "{artifact.kind}" has no preview yet. Switch to Source.
        </div>
      );
  }
}

/* --------------------------------------------------------------------------
 * Tool view
 * -------------------------------------------------------------------------- */

function ToolHeader({ session, toolCallId }: { session: SessionState; toolCallId: string }) {
  const toolView = useStore((s) => s.ui.toolView);
  const setToolView = useStore((s) => s.setToolView);
  const tc = session.toolCalls[toolCallId];
  if (!tc) return null;

  return (
    <div className="flex items-center gap-2 min-w-0">
      <ToolStatusIcon tc={tc} />
      <span className="font-medium truncate">{tc.name}</span>
      <div className="flex rounded-md border border-border overflow-hidden ml-2">
        <button
          className={`px-2 py-1 text-xs ${toolView === "result" ? "bg-secondary" : ""}`}
          onClick={() => setToolView("result")}
        >
          Result
        </button>
        <button
          className={`px-2 py-1 text-xs ${toolView === "arguments" ? "bg-secondary" : ""}`}
          onClick={() => setToolView("arguments")}
        >
          Arguments
        </button>
      </div>
      {typeof tc.duration_ms === "number" && (
        <span className="text-xs text-muted-foreground ml-2">
          {Math.round(tc.duration_ms)}ms
        </span>
      )}
    </div>
  );
}

function ToolBody({ session, toolCallId }: { session: SessionState; toolCallId: string }) {
  const view = useStore((s) => s.ui.toolView);
  const tc = session.toolCalls[toolCallId];
  if (!tc) return null;

  if (view === "arguments") {
    return (
      <SyntaxHighlighter
        language="json"
        style={oneDark}
        customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
      >
        {JSON.stringify(tc.arguments, null, 2)}
      </SyntaxHighlighter>
    );
  }

  if (tc.status === "running") {
    return (
      <div className="p-6 text-sm text-muted-foreground flex items-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Running…
      </div>
    );
  }

  if (tc.status === "denied") {
    return (
      <div className="p-6 text-sm text-destructive">
        Denied: {tc.reason ?? "no reason given"}
      </div>
    );
  }

  return (
    <SyntaxHighlighter
      language="text"
      style={oneDark}
      customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
      wrapLongLines
    >
      {tc.content || " "}
    </SyntaxHighlighter>
  );
}

function ToolStatusIcon({ tc }: { tc: ToolCallRecord }) {
  if (tc.status === "running") {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }
  if (tc.status === "completed") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  }
  return <XCircle className="h-4 w-4 text-destructive" />;
}

function healMarkdown(src: string): string {
  const fenceCount = (src.match(/^```/gm) ?? []).length;
  if (fenceCount % 2 === 1) return src + "\n```";
  return src;
}
