import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { useStore } from "../store";
import { useSSE } from "../hooks/useSSE";
import { ChatPane } from "../components/chat/ChatPane";
import { Composer } from "../components/chat/Composer";
import { ActivityBar } from "../components/chat/ActivityBar";
import { ArtifactPanel } from "../components/artifacts/ArtifactPanel";
import { TopBar } from "../components/TopBar";
import { SkillsStrip } from "../components/skills/SkillsStrip";

export function SessionPage() {
  const { sessionId } = useParams();
  const resetSession = useStore((s) => s.resetSession);
  const setActiveSessionId = useStore((s) => s.setActiveSessionId);
  const session = useStore((s) => (sessionId ? s.sessions[sessionId] : undefined));
  const panelKind = useStore((s) => s.ui.panel.kind);

  useEffect(() => {
    if (sessionId && !session) resetSession(sessionId);
    if (sessionId) setActiveSessionId(sessionId);
    return () => setActiveSessionId(null);
  }, [sessionId, session, resetSession, setActiveSessionId]);

  useSSE(sessionId ?? null);

  if (!sessionId) return null;

  // Empty state: no items sent yet in this session.
  const isEmpty = !session || session.items.length === 0;

  return (
    <div className="h-screen flex flex-col bg-background">
      <TopBar />
      <div className="flex-1 flex overflow-hidden">
        <LayoutGroup id="session-layout">
          <div className="flex-1 flex flex-col min-w-0 relative">
            <AnimatePresence mode="wait">
              {isEmpty ? (
                <EmptyHero key="empty" sessionId={sessionId} />
              ) : (
                <ChatSurface key="chat" sessionId={sessionId} />
              )}
            </AnimatePresence>
          </div>
        </LayoutGroup>
        {panelKind !== "closed" && <ArtifactPanel sessionId={sessionId} />}
      </div>
    </div>
  );
}

/**
 * Empty-session hero: headline + composer centered vertically. The composer
 * is wrapped in a <motion.div layoutId="composer-shell"> so that when the
 * user sends their first message, Framer animates it from the center of the
 * screen to its docked bottom position in ChatSurface.
 */
function EmptyHero({ sessionId }: { sessionId: string }) {
  return (
    <motion.div
      className="flex-1 flex flex-col items-center justify-center px-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.2 }}
    >
      <motion.div
        className="max-w-3xl w-full text-center mb-6"
        initial={{ y: 10, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
      >
        <h1 className="text-3xl font-semibold tracking-tight bg-gradient-to-r from-foreground via-foreground/90 to-muted-foreground bg-clip-text text-transparent">
          What can I help with?
        </h1>
        <p className="text-sm text-muted-foreground mt-2">
          Ask anything, create anything. Attach skills to specialize me for a domain.
        </p>
      </motion.div>
      <motion.div layoutId="composer-shell" className="w-full max-w-3xl" transition={SPRING}>
        <div className="rounded-2xl border border-border bg-secondary/20 overflow-hidden">
          <Composer sessionId={sessionId} />
        </div>
      </motion.div>
      <motion.div
        className="w-full max-w-3xl mt-3"
        initial={{ y: 10, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.25, delay: 0.1 }}
      >
        <SkillsStrip sessionId={sessionId} />
      </motion.div>
    </motion.div>
  );
}

/** Docked-composer state: chat fills most of the screen, composer at bottom. */
function ChatSurface({ sessionId }: { sessionId: string }) {
  return (
    <motion.div
      key="chat"
      className="flex-1 flex flex-col min-h-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
    >
      <ChatPane sessionId={sessionId} />
      <ActivityBar sessionId={sessionId} />
      <SkillsStrip sessionId={sessionId} />
      <motion.div layoutId="composer-shell" transition={SPRING}>
        <Composer sessionId={sessionId} />
      </motion.div>
    </motion.div>
  );
}

const SPRING = { type: "spring" as const, stiffness: 320, damping: 34, mass: 0.8 };
