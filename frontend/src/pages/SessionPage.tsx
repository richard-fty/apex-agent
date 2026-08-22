import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { Bot, FolderOpen, Globe, Lightbulb, Sparkles } from "lucide-react";
import { useStore, type SessionState } from "../store";
import { useSSE } from "../hooks/useSSE";
import { ChatPane } from "../components/chat/ChatPane";
import { Composer } from "../components/chat/Composer";
import { TurnNavigator } from "../components/chat/TurnNavigator";
import { ArtifactPanel } from "../components/artifacts/ArtifactPanel";
import { TopBar } from "../components/TopBar";
import { FinancialProfileForm } from "../components/onboarding/FinancialProfileForm";
import { Button } from "../components/ui/button";
import { getJSONOrNull, postJSON } from "../lib/api";
import { buildWealthPrompt } from "../lib/wealthPrompt";
import type { FinancialProfile } from "../types";

const ENABLE_WEALTH_GUIDE = false;

export function SessionPage() {
  const { sessionId } = useParams();
  const resetSession = useStore((s) => s.resetSession);
  const setActiveSessionId = useStore((s) => s.setActiveSessionId);
  const session = useStore((s) => (sessionId ? s.sessions[sessionId] : undefined));
  const panelKind = useStore((s) => s.ui.panel.kind);
  const openHistory = useStore((s) => s.openHistory);
  const openSocial = useStore((s) => s.openSocial);
  const [profile, setProfile] = useState<FinancialProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileSubmitting, setProfileSubmitting] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const lastAutoSocialUrl = useRef<string | null>(null);

  useEffect(() => {
    if (sessionId && !session) resetSession(sessionId);
    if (sessionId) setActiveSessionId(sessionId);
    return () => setActiveSessionId(null);
  }, [sessionId, session, resetSession, setActiveSessionId]);

  useEffect(() => {
    if (!ENABLE_WEALTH_GUIDE) {
      setProfileLoading(false);
      return;
    }
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
    ENABLE_WEALTH_GUIDE &&
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
    ENABLE_WEALTH_GUIDE &&
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

  const autoSocialUrl = detectAutoSocialUrl(session);
  useEffect(() => {
    if (!autoSocialUrl) return;
    if (lastAutoSocialUrl.current === autoSocialUrl) return;
    lastAutoSocialUrl.current = autoSocialUrl;
    openSocial(autoSocialUrl);
  }, [autoSocialUrl, openSocial]);

  if (!sessionId || !session) return null;

  return (
    <div className="h-screen flex flex-col bg-background">
      <TopBar />
      <ConversationToolbar onOpenHistory={openHistory} onOpenSocial={openSocial} />
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

function ConversationToolbar({
  onOpenHistory,
  onOpenSocial,
}: {
  onOpenHistory: () => void;
  onOpenSocial: (url: string) => void;
}) {
  const [socialUrl, setSocialUrl] = useState("https://x.com/home");

  return (
    <div className="border-b border-border bg-secondary/20 px-4 py-2">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Bot className="h-4 w-4 text-sky-400" />
          <span>Apex 是有灵魂的创作伙伴，支持长期陪伴式创作和日常闲聊。</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onOpenHistory}>
            <FolderOpen className="mr-2 h-4 w-4" />
            创作历史
          </Button>
          <div className="flex items-center gap-2">
            <input
              value={socialUrl}
              onChange={(event) => setSocialUrl(event.target.value)}
              className="h-8 rounded-md border border-border bg-background px-2 text-xs w-56"
              aria-label="社媒 webview 链接"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={() => onOpenSocial(ensureAbsoluteUrl(socialUrl))}
              className="whitespace-nowrap"
            >
              <Globe className="mr-2 h-4 w-4" />
              打开社媒
            </Button>
          </div>
        </div>
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
        <h1 className="text-3xl font-semibold tracking-tight flex items-center justify-center gap-2">
          <Sparkles className="h-6 w-6 text-sky-400" />
          我是 Apex，今天想做什么创作？
        </h1>
        <p className="text-sm text-muted-foreground mt-2">
          你可以直接聊想法、发文件、让它做视频、音频、插画、运营文案，Apex 会持续记住我们现在的创作脉络。
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
        <div className="rounded-xl border border-border bg-secondary/30 px-4 py-3 text-xs text-muted-foreground">
          <p className="flex items-center">
            <Lightbulb className="mr-2 h-3.5 w-3.5" />
            创作入口优先：发一句「给我做一个王家卫风格90年代都市动漫MV脚本」就能直接开干。
          </p>
        </div>
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
              Pick one and Apex will turn it into an action checklist.
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
              description="That is enough for Apex to create a first-pass strategy. It will assume the rest."
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
  composerOverride?: ReactNode;
}) {
  return (
    <motion.div
      key="chat"
      className="flex-1 flex flex-col min-h-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
    >
      <div className="relative flex-1 min-h-0 overflow-hidden">
        <ChatPane sessionId={sessionId} />
        <TurnNavigator sessionId={sessionId} />
      </div>
      <div className="shrink-0 bg-background">
        <motion.div layoutId="composer-shell" transition={SPRING}>
          {composerOverride ?? <Composer sessionId={sessionId} />}
        </motion.div>
      </div>
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

function ensureAbsoluteUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "https://x.com/home";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

function detectAutoSocialUrl(session: SessionState | undefined): string | null {
  if (!session) return null;

  for (const item of [...session.items].reverse()) {
    let found: string | null = null;
    if (item.kind === "assistant") {
      found = extractSocialUrlFromText(item.content);
    } else if (item.kind === "tool") {
      const tc = session.toolCalls[item.toolCallId];
      if (tc) found = extractSocialUrlFromArgs(tc.arguments);
    }
    if (found) return found;
  }
  return null;
}

function extractSocialUrlFromArgs(args: Record<string, unknown>): string | null {
  const candidateKeys = ["url", "target", "link", "profile_url", "page", "site"];
  for (const key of candidateKeys) {
    const raw = args[key];
    if (typeof raw === "string") {
      const maybe = extractSocialUrlFromText(raw);
      if (maybe) return maybe;
    }
  }
  return null;
}

function extractSocialUrlFromText(text: string): string | null {
  const urls = text.match(/https?:\/\/[^\s)]+/g) ?? [];
  for (const candidate of urls) {
    const normalized = stripTrailingPunct(candidate);
    if (isApexSocialDomain(normalized)) {
      return normalized;
    }
  }
  return null;
}

function isApexSocialDomain(url: string): boolean {
  const lowered = url.toLowerCase();
  return (
    lowered.includes("x.com") ||
    lowered.includes("twitter.com") ||
    lowered.includes("instagram.com") ||
    lowered.includes("facebook.com") ||
    lowered.includes("threads.net") ||
    lowered.includes("weibo.com") ||
    lowered.includes("xiaohongshu.com") ||
    lowered.includes("bilibili.com") ||
    lowered.includes("tiktok.com") ||
    lowered.includes("youtube.com")
  );
}

function stripTrailingPunct(url: string): string {
  return url.replace(/[)\]}>.,;:'"!?。，；”’]+$/, "");
}
