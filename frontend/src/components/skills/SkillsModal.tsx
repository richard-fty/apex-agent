import { useEffect, useState } from "react";
import { del, getJSON, postJSON } from "../../lib/api";
import { Button } from "../ui/button";
import { X, Check, Loader2 } from "lucide-react";
import type { Skill } from "../../types";

/**
 * Skills manager modal. Opens from the composer — lists every skill pack the
 * agent has discovered, marks which are currently loaded, and lets the user
 * toggle them. Backed by /sessions/{id}/skills (GET/POST/DELETE).
 */
export function SkillsModal({
  sessionId,
  open,
  onClose,
}: {
  sessionId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSkills(null);
    setErr(null);
    (async () => {
      try {
        const res = await getJSON<{ skills: Skill[] }>(`/sessions/${sessionId}/skills`);
        setSkills(res.skills);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Failed to load skills");
      }
    })();
  }, [open, sessionId]);

  async function toggle(skill: Skill) {
    setBusy(skill.name);
    try {
      if (skill.loaded) {
        await del(`/sessions/${sessionId}/skills/${encodeURIComponent(skill.name)}`);
      } else {
        await postJSON(`/sessions/${sessionId}/skills/${encodeURIComponent(skill.name)}`, {});
      }
      setSkills((prev) =>
        prev?.map((s) => (s.name === skill.name ? { ...s, loaded: !s.loaded } : s)) ?? null,
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="bg-background border border-border rounded-2xl w-full max-w-xl max-h-[80vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-base font-semibold">Manage skills</h2>
            <p className="text-xs text-muted-foreground">
              Load a skill to give the agent domain-specific tools and instructions.
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="flex-1 overflow-auto p-3">
          {skills === null && !err && (
            <div className="flex items-center gap-2 p-4 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          )}
          {err && <div className="p-4 text-sm text-destructive">{err}</div>}
          {skills && skills.length === 0 && (
            <div className="p-6 text-center text-muted-foreground text-sm">
              No skills available. Add skill packs under{" "}
              <code className="bg-secondary px-1 py-0.5 rounded">core/src/skill_packs/</code>.
            </div>
          )}
          {skills?.map((s) => (
            <SkillRow
              key={s.name}
              skill={s}
              busy={busy === s.name}
              onToggle={() => toggle(s)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function SkillRow({
  skill,
  busy,
  onToggle,
}: {
  skill: Skill;
  busy: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-transparent hover:border-border hover:bg-secondary/40 p-3 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{skill.name}</span>
          {skill.loaded && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
              <Check className="h-3 w-3" /> loaded
            </span>
          )}
        </div>
        {skill.description && (
          <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{skill.description}</p>
        )}
        {skill.keywords.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {skill.keywords.slice(0, 8).map((kw) => (
              <span
                key={kw}
                className="text-[10px] px-1.5 py-0.5 rounded-full bg-secondary/60 text-muted-foreground"
              >
                {kw}
              </span>
            ))}
          </div>
        )}
      </div>
      <Button
        size="sm"
        variant={skill.loaded ? "outline" : "default"}
        disabled={busy}
        onClick={onToggle}
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : skill.loaded ? "Remove" : "Add"}
      </Button>
    </div>
  );
}
