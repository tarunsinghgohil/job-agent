"use client";

import { useTheme } from "../lib/theme";

/**
 * Two-state light/dark switch. Before the client has read localStorage the
 * label is suppressed (`ready` is false) so server and client markup agree.
 */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, toggleTheme, ready } = useTheme();
  const next = theme === "dark" ? "light" : "dark";

  return (
    <button
      type="button"
      className={`theme-toggle ${className}`.trim()}
      onClick={toggleTheme}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      data-theme-state={theme}
    >
      <span className="theme-toggle-icon" aria-hidden="true">
        {theme === "dark" ? "☾" : "☀"}
      </span>
      <span className="theme-toggle-text">{ready ? (theme === "dark" ? "Dark" : "Light") : ""}</span>
    </button>
  );
}
