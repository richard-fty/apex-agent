import { Link, useNavigate } from "react-router-dom";
import { Button } from "./ui/button";
import { useStore } from "../store";
import { postJSON } from "../lib/api";

export function TopBar() {
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const navigate = useNavigate();

  async function logout() {
    try { await postJSON("/auth/logout", {}); } catch { /* ignore */ }
    setUser(null);
    navigate("/login", { replace: true });
  }

  return (
    <div className="border-b border-border px-4 py-2 flex items-center justify-between">
      <Link to={user ? "/dashboard" : "/"} className="font-semibold tracking-tight">
        Leverin.ai
      </Link>
      {user && (
        <div className="flex items-center gap-3 text-sm">
          <Link to="/onboarding" className="text-muted-foreground hover:text-foreground">
            Update profile
          </Link>
          <span className="text-muted-foreground">{user.username}</span>
          <Button size="sm" variant="outline" onClick={logout}>Log out</Button>
        </div>
      )}
    </div>
  );
}
