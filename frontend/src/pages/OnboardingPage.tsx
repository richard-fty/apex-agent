import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { postJSON } from "../lib/api";
import type { Session } from "../types";

export function OnboardingPage() {
  const navigate = useNavigate();

  useEffect(() => {
    void postJSON<Session>("/sessions", {
      model: "deepseek/deepseek-chat",
    }).then((session) => {
      navigate(`/session/${session.id}`, { replace: true });
    }).catch(() => {
      navigate("/dashboard", { replace: true });
    });
  }, [navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center p-6 text-sm text-muted-foreground">
      Opening a new session…
    </div>
  );
}
