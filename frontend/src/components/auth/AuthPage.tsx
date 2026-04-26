import { useState } from "react";
import { useNavigate, Link, useLocation } from "react-router-dom";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { useStore } from "../../store";
import { getJSONOrNull, postJSON } from "../../lib/api";
import type { FinancialProfile, User } from "../../types";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const location = useLocation() as { state?: { from?: { pathname?: string } } };
  const from = location.state?.from?.pathname;
  const setUser = useStore((s) => s.setUser);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      const path = mode === "login" ? "/auth/login" : "/auth/register";
      const user = await postJSON<User>(path, { username, password });
      setUser(user);
      if (from) {
        navigate(from, { replace: true });
        return;
      }
      if (mode === "register") {
        navigate("/dashboard", { replace: true });
        return;
      }
      const profile = await getJSONOrNull<FinancialProfile>("/wealth/profile");
      navigate(profile ? "/dashboard" : "/onboarding", { replace: true });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Auth failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 border border-border rounded-lg p-6"
      >
        <h1 className="text-xl font-semibold">
          {mode === "login" ? "Log in to Leverin.ai" : "Create your Leverin.ai account"}
        </h1>
        <div className="space-y-2">
          <label className="text-sm font-medium">Username</label>
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">Password</label>
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            minLength={8}
            required
          />
          {mode === "register" && (
            <p className="text-xs text-muted-foreground">Minimum 8 characters.</p>
          )}
        </div>
        {err && <p className="text-sm text-destructive">{err}</p>}
        <Button className="w-full" disabled={submitting}>
          {submitting ? "…" : mode === "login" ? "Log in" : "Register"}
        </Button>
        <p className="text-sm text-muted-foreground text-center">
          {mode === "login" ? (
            <>No account? <Link to="/register" className="underline">Register</Link></>
          ) : (
            <>Have an account? <Link to="/login" className="underline">Log in</Link></>
          )}
        </p>
      </form>
    </div>
  );
}
