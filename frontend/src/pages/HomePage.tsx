import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { getJSON, postJSON } from "../lib/api";
import type { Session } from "../types";
import { TopBar } from "../components/TopBar";

export function HomePage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  async function refresh() {
    setSessions(await getJSON<Session[]>("/sessions"));
  }
  useEffect(() => { refresh(); }, []);

  async function newSession() {
    setCreating(true);
    try {
      const s = await postJSON<Session>("/sessions", { model: "deepseek/deepseek-chat" });
      navigate(`/session/${s.id}`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <TopBar />
      <div className="flex-1 max-w-3xl mx-auto w-full p-8">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold">Your sessions</h1>
          <Button onClick={newSession} disabled={creating}>
            {creating ? "Creating…" : "New session"}
          </Button>
        </div>
        {sessions.length === 0 && (
          <p className="text-muted-foreground">
            No sessions yet. Start one to begin talking to the agent.
          </p>
        )}
        <ul className="space-y-2">
          {sessions.map((s) => (
            <li
              key={s.id}
              className="border border-border rounded-md p-3 hover:bg-accent/50 cursor-pointer"
              onClick={() => navigate(`/session/${s.id}`)}
            >
              <div className="font-mono text-sm">{s.id.slice(0, 8)}</div>
              <div className="text-xs text-muted-foreground">
                {s.model} · {s.state} ·{" "}
                {new Date(s.created_at * 1000).toLocaleString()}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
