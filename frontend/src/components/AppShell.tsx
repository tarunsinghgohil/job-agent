"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "../lib/auth";
import { Nav } from "./Nav";
import { LoadingState } from "./States";
import { ThemeToggle } from "./ThemeToggle";

const PUBLIC_ROUTES = new Set(["/login"]);

/**
 * Renders the signed-in chrome, and keeps unauthenticated visitors on /login.
 * The redirect waits for `initializing` so a valid refresh cookie is never
 * mistaken for a signed-out session on a hard reload.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const { user, initializing } = useAuth();
  const isPublic = PUBLIC_ROUTES.has(pathname);

  useEffect(() => {
    if (initializing) return;
    if (!user && !isPublic) router.replace("/login");
    if (user && isPublic) router.replace("/");
  }, [user, initializing, isPublic, router]);

  // The theme switch is reachable on every screen, signed in or not.
  if (isPublic) {
    return (
      <main className="auth-main">
        <div className="floating-theme-toggle">
          <ThemeToggle />
        </div>
        {children}
      </main>
    );
  }

  if (initializing || !user) {
    return (
      <main className="boot-main">
        <div className="floating-theme-toggle">
          <ThemeToggle />
        </div>
        <LoadingState label="Restoring your session…" rows={2} />
      </main>
    );
  }

  return (
    <div className="shell">
      <Nav />
      <div className="shell-main">
        <header className="topbar">
          <ThemeToggle />
        </header>
        <main className="content" id="main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
