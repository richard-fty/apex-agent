import { useStore } from "../../store";
import { FileText, Code2, FileJson, FileBarChart, Terminal, File, Image as ImageIcon } from "lucide-react";
import type { ArtifactKind } from "../../types";

function iconFor(kind: ArtifactKind) {
  switch (kind) {
    case "markdown": return <FileText className="h-5 w-5" />;
    case "code":     return <Code2 className="h-5 w-5" />;
    case "json":     return <FileJson className="h-5 w-5" />;
    case "image":    return <ImageIcon className="h-5 w-5" />;
    case "terminal_log": return <Terminal className="h-5 w-5" />;
    case "plan":     return <FileBarChart className="h-5 w-5" />;
    default:         return <File className="h-5 w-5" />;
  }
}

function humanSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function firstLine(content: string, max = 140): string {
  const stripped = content
    .replace(/^#+\s*/gm, "")      // drop heading hashes
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.length > 0) ?? "";
  return stripped.length > max ? stripped.slice(0, max) + "…" : stripped;
}

export function ArtifactCard({
  sessionId,
  artifactId,
}: {
  sessionId: string;
  artifactId: string;
}) {
  const artifact = useStore((s) => s.sessions[sessionId]?.artifacts[artifactId]);
  const openArtifact = useStore((s) => s.openArtifact);
  const active = useStore(
    (s) => s.ui.panel.kind === "artifact" && s.ui.panel.artifactId === artifactId,
  );

  if (!artifact) return null;

  const size = new Blob([artifact.content]).size;
  const subtitle = artifact.description || firstLine(artifact.content);

  return (
    <button
      onClick={() => openArtifact(artifactId)}
      className={`w-full text-left rounded-xl border transition-colors
        ${active ? "border-primary/50 bg-secondary/70" : "border-border bg-secondary/30 hover:bg-secondary/60"}
        p-4 flex gap-3`}
    >
      <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center shrink-0">
        {iconFor(artifact.kind)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{artifact.name}</span>
          {!artifact.finalized && (
            <span className="text-xs text-muted-foreground animate-pulse">streaming…</span>
          )}
        </div>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{subtitle}</p>
        )}
        <div className="text-xs text-muted-foreground mt-1">
          {artifact.kind} · {humanSize(size)}
          {artifact.language && ` · ${artifact.language}`}
        </div>
      </div>
    </button>
  );
}
