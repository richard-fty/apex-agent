import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useStore } from "../../store";
import { getJSON } from "../../lib/api";
import type { User } from "../../types";

/** Gate protected routes. On mount, check /auth/me; redirect to /login on 401. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const [checking, setChecking] = useState(user === null);
  const location = useLocation();

  useEffect(() => {
    if (user) { setChecking(false); return; }
    let cancelled = false;
    (async () => {
      try {
        const me = await getJSON<User>("/auth/me");
        if (!cancelled) setUser(me);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => { cancelled = true; };
  }, [user, setUser]);

  if (checking) return <div className="p-6 text-muted-foreground">Checking session…</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}
