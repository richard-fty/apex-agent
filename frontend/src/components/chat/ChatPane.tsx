import { useEffect, useRef } from "react";
import { useStore } from "../../store";
import { MessageBubble } from "./MessageBubble";
import { ToolChip } from "./ToolChip";
import { ArtifactCard } from "./ArtifactCard";
import { PlanCard } from "./PlanCard";
import { ActivityBar } from "./ActivityBar";

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
        {session.disclaimer && (
          <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100/90">
            {session.disclaimer}
          </div>
        )}
        {session.items.length === 0 && (
          <div className="text-center text-muted-foreground text-sm py-20">
            Ask anything, create anything.
          </div>
        )}
        {session.items.map((item, idx) => {
          switch (item.kind) {
            case "user":
              if (isInternalWealthPrompt(item.text)) {
                return (
                  <MessageBubble
                    key={idx}
                    role="user"
                    content={summarizeInternalWealthPrompt(item.text)}
                  />
                );
              }
              return <MessageBubble key={idx} role="user" content={item.text} />;
            case "assistant":
              if (
                session.loadedSkills.includes("wealth_guide") &&
                asksForMinimumWealthInput(item.content)
              ) {
                return null;
              }
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
        <ActivityBar sessionId={sessionId} />
      </div>
    </div>
  );
}

function isInternalWealthPrompt(content: string): boolean {
  return content.startsWith("Here is my financial situation:");
}

function summarizeInternalWealthPrompt(content: string): string {
  const income = content.match(/Annual income:\s*([0-9,.]+)/i)?.[1];
  const deposit = content.match(/Deposit[^:]*:\s*([0-9,.]+)/i)?.[1];
  if (income && deposit) {
    return `Shared annual income $${income} and deposit $${deposit}`;
  }
  return "Shared income and deposit";
}

function asksForMinimumWealthInput(content: string): boolean {
  const lower = content.toLowerCase();
  const asksIncome =
    lower.includes("annual income") ||
    lower.includes("your income") ||
    lower.includes("income and");
  const asksDeposit =
    lower.includes("deposit") ||
    lower.includes("liquid cash") ||
    lower.includes("cash / savings") ||
    lower.includes("cash needs") ||
    lower.includes("cash available") ||
    lower.includes("savings");
  return asksIncome && asksDeposit;
}
