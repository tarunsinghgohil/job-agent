import type { Metadata } from "next";
import "./styles.css";
import { AuthProvider } from "../lib/auth";
import { ThemeProvider, THEME_BOOT_SCRIPT } from "../lib/theme";
import { ToastProvider } from "../components/Toast";
import { AppShell } from "../components/AppShell";

export const metadata: Metadata = {
  title: {
    default: "Job Agent",
    template: "%s · Job Agent",
  },
  description: "Personal AI job application agent — discovery, scoring, and application tracking.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* Applies the stored theme before first paint, so there is no flash. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        <ThemeProvider>
          <AuthProvider>
            <ToastProvider>
              <AppShell>{children}</AppShell>
            </ToastProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
