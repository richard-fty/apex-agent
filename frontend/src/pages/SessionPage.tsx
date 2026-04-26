import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { useStore } from "../store";
import { useSSE } from "../hooks/useSSE";
import { ChatPane } from "../components/chat/ChatPane";
import { Composer } from "../components/chat/Composer";
import { ArtifactPanel } from "../components/artifacts/ArtifactPanel";
import { TopBar } from "../components/TopBar";
import { SkillsStrip } from "../components/skills/SkillsStrip";
import { FinancialProfileForm } from "../components/onboarding/FinancialProfileForm";
import { Button } from "../components/ui/button";
import { getJSONOrNull, postJSON } from "../lib/api";
import { buildWealthPrompt } from "../lib/wealthPrompt";
import type { FinancialProfile } from "../types";

export function SessionPage() {
  const { sessionId } = useParams();
  const resetSession = useStore((s) => s.resetSession);
  const setActiveSessionId = useStore((s) => s.setActiveSessionId);
  const session = useStore((s) => (sessionId ? s.sessions[sessionId] : undefined));
  const panelKind = useStore((s) => s.ui.panel.kind);
  const [profile, setProfile] = useState<FinancialProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSubmitting, setProfileSubmitting] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  useEffect(() => {
    if (sessionId && !session) resetSession(sessionId);
    if (sessionId) setActiveSessionId(sessionId);
    return () => setActiveSessionId(null);
  }, [sessionId, session, resetSession, setActiveSessionId]);

  useEffect(() => {
    let cancelled = false;
    setProfileLoading(true);
    (async () => {
      try {
        const existing = await getJSONOrNull<FinancialProfile>("/wealth/profile");
        if (!cancelled) setProfile(existing);
      } catch {
        if (!cancelled) setProfile(null);
      } finally {
        if (!cancelled) setProfileLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    setProfileError(null);
  }, [sessionId]);

  useSSE(sessionId ?? null);

  // Empty state: no items sent yet in this session.
  const isEmpty = !session || session.items.length === 0;
  const latestAssistantMessage = useMemo(() => {
    if (!session) return null;
    for (let i = session.items.length - 1; i >= 0; i--) {
      const item = session.items[i];
      if (item.kind === "assistant" && item.content.trim()) return item.content;
    }
    return null;
  }, [session]);
  const needsMinimumWealthInput =
    !hasMinimumWealthInput(profile) || asksForMinimumWealthInput(latestAssistantMessage);
  const showWealthIntake =
    !!session &&
    session.loadedSkills.includes("wealth_guide") &&
    !session.pending &&
    !profileLoading &&
    session.status !== "running" &&
    needsMinimumWealthInput;
  const pathChoice = useMemo(
    () => extractPathChoice(latestAssistantMessage),
    [latestAssistantMessage]
  );
  const showPathChoice =
    !!session &&
    session.loadedSkills.includes("wealth_guide") &&
    !session.pending &&
    session.status !== "running" &&
    !showWealthIntake &&
    !!pathChoice;
  const latestUserRequest = useMemo(() => {
    if (!session) return null;
    for (let i = session.items.length - 1; i >= 0; i--) {
      const item = session.items[i];
      if (item.kind === "user") return item.text;
    }
    return null;
  }, [session]);

  if (!sessionId) return null;

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
                <ChatSurface
                  key="chat"
                  sessionId={sessionId}
                  composerOverride={
                    showWealthIntake ? (
                      <WealthIntakeComposer
                        initialValue={profile}
                        loading={profileLoading}
                        submitting={profileSubmitting}
                        error={profileError}
                        onSubmit={async (nextProfile) => {
                          setProfileSubmitting(true);
                          setProfileError(null);
                          try {
                            await postJSON<void>("/wealth/profile", nextProfile);
                            setProfile(nextProfile);
                            const prompt = buildWealthPrompt(nextProfile);
                            const userInput = latestUserRequest
                              ? `${prompt}\n\nMy original request: ${latestUserRequest}`
                              : prompt;
                            await postJSON(`/sessions/${sessionId}/turns`, {
                              user_input: userInput,
                            });
                          } catch (err) {
                            setProfileError(
                              err instanceof Error ? err.message : "Failed to continue the wealth guide"
                            );
                          } finally {
                            setProfileSubmitting(false);
                          }
                        }}
                      />
                    ) : showPathChoice ? (
                      <PathChoiceComposer
                        choices={pathChoice}
                        onChoose={async (choice) => {
                          await postJSON(`/sessions/${sessionId}/turns`, {
                            user_input: `I choose ${choice.label}${
                              choice.name ? ` (${choice.name})` : ""
                            }. Please generate the action checklist.`,
                          });
                        }}
                      />
                    ) : undefined
                  }
                />
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

type PathChoice = {
  label: string;
  name: string;
};

function PathChoiceComposer({
  choices,
  onChoose,
}: {
  choices: PathChoice[];
  onChoose: (choice: PathChoice) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState<string | null>(null);

  return (
    <div className="border-t border-border bg-background/95 backdrop-blur">
      <div className="mx-auto max-w-3xl px-6 py-4">
        <div className="rounded-xl border border-border bg-gradient-to-b from-secondary/35 to-secondary/10 p-4 shadow-lg shadow-black/10">
          <div className="mb-3">
            <div className="text-sm font-semibold">Choose a path</div>
            <p className="mt-1 text-xs text-muted-foreground">
              Pick one and Leverin will turn it into an action checklist.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {choices.map((choice) => (
              <Button
                key={choice.label}
                type="button"
                variant="outline"
                disabled={!!submitting}
                className="h-auto justify-start rounded-lg px-4 py-3 text-left"
                onClick={async () => {
                  setSubmitting(choice.label);
                  try {
                    await onChoose(choice);
                  } finally {
                    setSubmitting(null);
                  }
                }}
              >
                <span className="mr-2 rounded-md bg-secondary px-2 py-1 text-xs">
                  {choice.label}
                </span>
                <span className="whitespace-normal text-sm">
                  {submitting === choice.label ? "Choosing..." : choice.name}
                </span>
              </Button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function WealthIntakeComposer({
  initialValue,
  loading,
  submitting,
  error,
  onSubmit,
}: {
  initialValue: FinancialProfile | null;
  loading: boolean;
  submitting: boolean;
  error: string | null;
  onSubmit: (profile: FinancialProfile) => Promise<void>;
}) {
  return (
    <div className="border-t border-border bg-background/95 backdrop-blur">
      <div className="mx-auto max-w-3xl px-6 py-4">
        {loading ? (
          <div className="text-sm text-muted-foreground">Loading your saved profile…</div>
        ) : (
          <div className="rounded-xl border border-border bg-gradient-to-b from-secondary/35 to-secondary/10 p-4 shadow-lg shadow-black/10">
            <FinancialProfileForm
              initialValue={initialValue}
              title="Share annual income and deposit"
              description="That is enough for Leverin to create a first-pass strategy. It will assume the rest."
              submitting={submitting}
              onSubmit={onSubmit}
            />
            {error && <p className="mt-4 text-sm text-destructive">{error}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

/** Docked-composer state: chat fills most of the screen, composer at bottom. */
function ChatSurface({
  sessionId,
  composerOverride,
}: {
  sessionId: string;
  composerOverride?: React.ReactNode;
}) {
  return (
    <motion.div
      key="chat"
      className="flex-1 flex flex-col min-h-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
    >
      <ChatPane sessionId={sessionId} />
      <SkillsStrip sessionId={sessionId} />
      <motion.div layoutId="composer-shell" transition={SPRING}>
        {composerOverride ?? <Composer sessionId={sessionId} />}
      </motion.div>
    </motion.div>
  );
}

const SPRING = { type: "spring" as const, stiffness: 320, damping: 34, mass: 0.8 };

function hasMinimumWealthInput(profile: FinancialProfile | null): boolean {
  return !!profile && profile.income > 0 && profile.cash > 0;
}

function asksForMinimumWealthInput(message: string | null): boolean {
  if (!message) return false;
  const lower = message.toLowerCase();
  const asksIncome =
    lower.includes("annual income") ||
    lower.includes("your income") ||
    lower.includes("income and");
  const asksCash =
    lower.includes("deposit") ||
    lower.includes("liquid cash") ||
    lower.includes("cash / savings") ||
    lower.includes("cash needs") ||
    lower.includes("cash available") ||
    lower.includes("savings");
  return asksIncome && asksCash;
}

function extractPathChoice(message: string | null): PathChoice[] | null {
  if (!message) return null;
  const lower = message.toLowerCase();
  if (!lower.includes("which path") && !lower.includes("choose a path")) return null;

  const choices = ["A", "B", "C"].map((label) => {
    const match = message.match(new RegExp(`${label}\\s*\\(([^)]+)\\)`, "i"));
    return {
      label,
      name: match?.[1] ?? `Path ${label}`,
    };
  });
  return choices;
}
