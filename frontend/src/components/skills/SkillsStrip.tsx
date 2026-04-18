import { useEffect, useState } from "react";
import { Plus, Sparkles, Loader2 } from "lucide-react";
import { getJSON } from "../../lib/api";
import type { Skill } from "../../types";
import { SkillsModal } from "./SkillsModal";

/** Compact strip rendered just above the composer.
 *
 * Shows currently-loaded skills as chips + an "Add skills" button that
 * opens the full SkillsModal. Polls /skills on mount and whenever the modal
 * closes so the chip list reflects server-side state.
 */
export function SkillsStrip({ sessionId }: { sessionId: string }) {
  const [loaded, setLoaded] = useState<Skill[] | null>(null);
  const [open, setOpen] = useState(false);

  async function refresh() {
    try {
      const res = await getJSON<{ skills: Skill[] }>(`/sessions/${sessionId}/skills`);
      setLoaded(res.skills.filter((s) => s.loaded));
    } catch {
      // Ignore; strip is best-effort.
    }
  }

  useEffect(() => {
    refresh();
  }, [sessionId]);

  function handleClose() {
    setOpen(false);
    refresh();
  }

  return (
    <>
      <div className="mx-auto max-w-3xl px-6 pt-2 flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary/40 hover:bg-secondary/70 px-3 py-1 text-xs text-muted-foreground transition-colors"
        >
          <Plus className="h-3 w-3" /> Skills
        </button>
        {loaded === null ? (
          <span className="text-xs text-muted-foreground flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
          </span>
        ) : (
          loaded.map((s) => (
            <span
              key={s.name}
              className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/30 px-2.5 py-0.5 text-xs"
              title={s.description}
            >
              <Sparkles className="h-3 w-3" />
              {s.name}
            </span>
          ))
        )}
      </div>
      <SkillsModal sessionId={sessionId} open={open} onClose={handleClose} />
    </>
  );
}
