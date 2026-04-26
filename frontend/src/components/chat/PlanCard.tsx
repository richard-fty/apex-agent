import { useState } from "react";
import { useStore } from "../../store";
import { CheckCircle2, Circle, Loader2, XCircle, ChevronDown, ListChecks } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { PlanStep } from "../../types";

/**
 * Claude-Code / Codex-style plan progress card.
 *
 * Sticks to the top of the chat surface, shows each todo step with an
 * icon and text. Completed steps are struck through. Collapses to a
 * compact summary when the user clicks the header.
 */
export function PlanCard({ sessionId }: { sessionId: string }) {
  const plan = useStore((s) => s.sessions[sessionId]?.plan ?? []);
  const [open, setOpen] = useState(true);

  if (plan.length === 0) return null;

  const completed = plan.filter((s) => s.status === "completed").length;
  const total = plan.length;
  const allCompleted = completed === total;

  return (
    <div className="mx-auto max-w-3xl px-6 pt-4">
      <div className="rounded-xl border border-border bg-secondary/30 overflow-hidden">
        <button
          onClick={() => setOpen((v) => !v)}
          className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-secondary/50 transition-colors"
        >
          <ListChecks className="h-4 w-4 text-muted-foreground" />
          <div className="flex-1 text-left">
            <div className="text-sm font-medium">Checklist</div>
            <div className="text-xs text-muted-foreground">
              {completed} of {total} {allCompleted ? "completed" : "complete"}
            </div>
          </div>
          <ProgressRing completed={completed} total={total} />
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.ul
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="border-t border-border/60 divide-y divide-border/60"
            >
              {plan.map((step) => (
                <PlanRow key={step.id} step={step} />
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function PlanRow({ step }: { step: PlanStep }) {
  const { icon, textClass } = statusDetails(step.status);
  return (
    <motion.li
      layout
      className="flex items-start gap-3 px-4 py-2.5"
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className={`text-sm leading-relaxed ${textClass}`}>{step.text}</span>
    </motion.li>
  );
}

function statusDetails(status: PlanStep["status"]) {
  switch (status) {
    case "completed":
      return {
        icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
        textClass: "line-through text-muted-foreground",
      };
    case "in_progress":
      return {
        icon: <Loader2 className="h-4 w-4 animate-spin text-sky-400" />,
        textClass: "text-foreground",
      };
    case "failed":
      return {
        icon: <XCircle className="h-4 w-4 text-destructive" />,
        textClass: "text-destructive",
      };
    default:
      return {
        icon: <Circle className="h-4 w-4 text-muted-foreground/70" />,
        textClass: "text-muted-foreground",
      };
  }
}

function ProgressRing({ completed, total }: { completed: number; total: number }) {
  const size = 20;
  const stroke = 2.5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = total === 0 ? 0 : completed / total;
  const dash = c * pct;
  return (
    <svg width={size} height={size} className="-rotate-90">
      <circle cx={size / 2} cy={size / 2} r={r}
        fill="none" strokeWidth={stroke}
        className="stroke-border" />
      <circle cx={size / 2} cy={size / 2} r={r}
        fill="none" strokeWidth={stroke}
        strokeDasharray={`${dash} ${c - dash}`}
        strokeLinecap="round"
        className="stroke-emerald-500 transition-all" />
    </svg>
  );
}
