import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { getJSON, getJSONOrNull, postJSON } from "../lib/api";
import { buildWealthPrompt } from "../lib/wealthPrompt";
import type { ChecklistItemState, FinancialProfile, Session } from "../types";
import { TopBar } from "../components/TopBar";

export function HomePage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [profile, setProfile] = useState<FinancialProfile | null>(null);
  const [checklist, setChecklist] = useState<ChecklistItemState[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState<"chat" | "review" | null>(null);
  const navigate = useNavigate();

  async function refresh() {
    const [nextSessions, nextProfile] = await Promise.all([
      getJSON<Session[]>("/sessions"),
      getJSONOrNull<FinancialProfile>("/wealth/profile"),
    ]);
    const nextChecklist = nextProfile
      ? await getJSON<{ items: ChecklistItemState[] }>("/wealth/checklist")
      : { items: [] };
    setSessions(nextSessions);
    setProfile(nextProfile);
    setChecklist(nextChecklist.items);
    setLoading(false);
  }
  useEffect(() => { void refresh(); }, []);

  async function newSession() {
    setCreating("chat");
    try {
      const s = await postJSON<Session>("/sessions", { model: "deepseek/deepseek-chat" });
      navigate(`/session/${s.id}`);
    } finally {
      setCreating(null);
    }
  }

  async function startReview() {
    setCreating("review");
    try {
      const s = await postJSON<Session>("/sessions", { model: "deepseek/deepseek-chat" });
      if (!profile) {
        await postJSON(`/sessions/${s.id}/turns`, {
          user_input: "I want help deciding what to do with my money.",
        });
        navigate(`/session/${s.id}`);
        return;
      }
      await postJSON(`/sessions/${s.id}/turns`, {
        user_input: buildWealthPrompt(profile),
      });
      navigate(`/session/${s.id}`);
    } finally {
      setCreating(null);
    }
  }

  async function editProfile() {
    setCreating("review");
    try {
      const s = await postJSON<Session>("/sessions", { model: "deepseek/deepseek-chat" });
      await postJSON(`/sessions/${s.id}/turns`, {
        user_input: "I want to update my financial details and review my plan.",
      });
      navigate(`/session/${s.id}`);
    } finally {
      setCreating(null);
    }
  }

  const snapshot = useMemo(() => {
    if (!profile) return [];
    return [
      { label: "Income", value: formatMoney(profile.income) },
      { label: "Cash", value: formatMoney(profile.cash) },
      { label: "Monthly expenses", value: formatMoney(profile.monthly_expenses) },
      { label: "Goals", value: String(profile.goals.length || 0) },
    ];
  }, [profile]);
  const checklistSummary = useMemo(() => {
    const completed = checklist.filter((item) => item.completed).length;
    return {
      total: checklist.length,
      completed,
      preview: checklist.slice(0, 4),
    };
  }, [checklist]);

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />
      <div className="flex-1 max-w-5xl mx-auto w-full p-8">
        <div className="rounded-[28px] border border-border bg-secondary/15 p-8">
          <div className="inline-flex rounded-full border border-border bg-background/80 px-3 py-1 text-xs uppercase tracking-[0.16em] text-muted-foreground">
            Leverin.ai
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight">
            Know what to do with your money.
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground">
            Build a structured wealth snapshot, compare a short list of reasonable paths,
            and turn the path you choose into a practical checklist.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button onClick={startReview} disabled={creating !== null}>
              {creating === "review" ? "Starting…" : profile ? "Run wealth review" : "Start onboarding"}
            </Button>
            <Button variant="outline" onClick={newSession} disabled={creating !== null}>
              {creating === "chat" ? "Creating…" : "Open empty session"}
            </Button>
            <Button variant="ghost" onClick={editProfile} disabled={creating !== null}>
              {profile ? "Edit profile in chat" : "Set up profile in chat"}
            </Button>
          </div>
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <section className="rounded-3xl border border-border bg-background/60 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Wealth profile</h2>
              {!profile && !loading && (
                <span className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  Not set up
                </span>
              )}
            </div>
            {loading ? (
              <p className="mt-4 text-sm text-muted-foreground">Loading…</p>
            ) : profile ? (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {snapshot.map((item) => (
                  <div key={item.label} className="rounded-2xl border border-border bg-secondary/20 p-4">
                    <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{item.label}</div>
                    <div className="mt-2 text-sm leading-6">{item.value}</div>
                  </div>
                ))}
                <div className="rounded-2xl border border-border bg-secondary/20 p-4 sm:col-span-2">
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Goals</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {profile.goals.length > 0 ? profile.goals.map((goal) => (
                      <span key={goal} className="rounded-full border border-border bg-background/70 px-3 py-1 text-xs">
                        {goal}
                      </span>
                    )) : (
                      <span className="text-sm text-muted-foreground">No goals saved yet.</span>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-border p-5 text-sm text-muted-foreground">
                Add your profile first so Leverin can compare the right paths for your situation.
              </div>
            )}
          </section>

          <section className="rounded-3xl border border-border bg-background/60 p-6">
            <div className="rounded-2xl border border-border bg-secondary/15 p-4 mb-5">
              <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Active plan</div>
              {checklistSummary.total > 0 ? (
                <>
                  <div className="mt-2 text-sm leading-6">
                    This week&apos;s actions: {checklistSummary.completed} of {checklistSummary.total} done
                  </div>
                  <div className="mt-3 space-y-2">
                    {checklistSummary.preview.map((item) => (
                      <div key={`${item.artifact_id}:${item.item_index}`} className="flex items-start gap-2 text-sm">
                        <span className={item.completed ? "text-emerald-400" : "text-muted-foreground"}>
                          {item.completed ? "✓" : "○"}
                        </span>
                        <span className={item.completed ? "text-foreground/70 line-through" : ""}>{item.text}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="mt-2 text-sm text-muted-foreground">
                  Select a path in a session to generate your action checklist.
                </div>
              )}
            </div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Recent sessions</h2>
            </div>
            {sessions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No sessions yet. Run your first review or open an empty session.
              </p>
            ) : (
              <ul className="space-y-3">
                {sessions.map((s) => (
                  <li
                    key={s.id}
                    className="cursor-pointer rounded-2xl border border-border p-4 transition-colors hover:bg-secondary/20"
                    onClick={() => navigate(`/session/${s.id}`)}
                  >
                    <div className="font-mono text-sm">{s.id.slice(0, 8)}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {s.model} · {s.state} · {new Date(s.created_at * 1000).toLocaleString()}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function formatMoney(value: number): string {
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}
