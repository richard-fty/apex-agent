import { useEffect, useRef } from "react";
import { useStore } from "../../store";
import { MessageBubble } from "./MessageBubble";
import { ToolChip } from "./ToolChip";
import { ArtifactCard } from "./ArtifactCard";
import { PlanCard } from "./PlanCard";

export function ChatPane({ sessionId }: { sessionId: string }) {
  const session = useStore((s) => s.sessions[sessionId]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Follow-the-tail unless the user scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [session?.items.length]);

  if (!session) {
    return <div className="p-6 text-muted-foreground">Loading…</div>;
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-auto">
      <PlanCard sessionId={sessionId} />
      <div className="mx-auto max-w-3xl px-6 py-8 space-y-4">
        {session.items.length === 0 && (
          <div className="text-center text-muted-foreground text-sm py-20">
            Ask anything, create anything.
          </div>
        )}
        {session.items.map((item, idx) => {
          switch (item.kind) {
            case "user":
              return <MessageBubble key={idx} role="user" content={item.text} />;
            case "assistant":
              return (
                <MessageBubble
                  key={idx}
                  role="assistant"
                  content={item.content}
                  streaming={item.streaming}
                />
              );
            case "tool":
              return (
                <ToolChip
                  key={idx}
                  sessionId={sessionId}
                  toolCallId={item.toolCallId}
                />
              );
            case "artifact":
              return (
                <ArtifactCard
                  key={idx}
                  sessionId={sessionId}
                  artifactId={item.artifactId}
                />
              );
          }
        })}
      </div>
    </div>
  );
}
