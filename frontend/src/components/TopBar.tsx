import { Link, useNavigate } from "react-router-dom";
import { Button } from "./ui/button";
import { useStore } from "../store";
import { postJSON } from "../lib/api";
import { Bot } from "lucide-react";

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
    <div className="px-4 py-2 flex items-center justify-between">
      <Link
        to={user ? "/chat" : "/"}
        className="font-semibold tracking-tight inline-flex items-center gap-1"
      >
        <Bot className="h-4 w-4" />
        Apex
      </Link>
      {user && (
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">{user.username}</span>
          <Button size="sm" variant="outline" onClick={logout}>Log out</Button>
        </div>
      )}
    </div>
  );
}
