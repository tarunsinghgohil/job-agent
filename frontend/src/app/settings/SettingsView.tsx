"use client";

import { useState } from "react";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { Input } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { useToast } from "../../components/Toast";
import { apiFetch, errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatDateTime } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { UserSession } from "../../lib/types";
import { api } from "../../lib/api";

export function SettingsView() {
  const toast = useToast();
  const { logout } = useAuth();
  const { isPending, run } = usePending();
  const sessions = useResource<UserSession[]>((signal) => api.get<UserSession[]>("/api/v1/auth/sessions", undefined, signal));

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  async function revoke(id: string) {
    await run(`revoke-${id}`, async () => {
      await toast.withToast(() => api.del(`/api/v1/auth/sessions/${id}`), "Session revoked.");
      sessions.reload();
    });
  }

  async function changePassword() {
    if (!currentPassword || newPassword.length < 12) {
      toast.error("Enter your current password and a new one at least 12 characters long.");
      return;
    }
    await run("change-password", async () => {
      try {
        await api.post("/api/v1/auth/change-password", { current_password: currentPassword, new_password: newPassword });
        toast.success("Password changed. Signing you out everywhere else.");
        setCurrentPassword("");
        setNewPassword("");
      } catch (error) {
        toast.error(errorMessage(error));
      }
    });
  }

  async function exportData() {
    await run("export", async () => {
      try {
        const response = await apiFetch("/api/v1/system/export");
        if (!response.ok) throw new Error("Export failed.");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `job-agent-export-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        toast.success("Export downloaded.");
      } catch (error) {
        toast.error(errorMessage(error));
      }
    });
  }

  return (
    <>
      <PageHeader title="Settings" description="Security, sessions, and data control." />

      <CardGrid columns={2}>
        <Card title="Change password">
          <Input
            label="Current password"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
          />
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            hint="At least 12 characters, with a letter and a digit."
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <Button variant="primary" loading={isPending("change-password")} onClick={() => void changePassword()}>
            Change password
          </Button>
        </Card>

        <Card title="Data control" description="Export everything the product stores about you. Credentials are never included.">
          <Button loading={isPending("export")} onClick={() => void exportData()}>
            Export all data
          </Button>
          <div style={{ marginTop: 16 }}>
            <Button variant="danger" onClick={() => void logout()}>
              Sign out
            </Button>
          </div>
        </Card>
      </CardGrid>

      <AsyncBoundary
        loading={sessions.loading}
        error={sessions.error}
        data={sessions.data}
        onRetry={sessions.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No other active sessions" />}
      >
        {(items) => (
          <Card title="Active sessions">
            <ul className="list-rows">
              {items.map((session) => (
                <li className="list-row" key={session.id}>
                  <div className="list-row-main">
                    <strong>{session.user_agent || "Unknown device"}</strong>
                    <span>
                      {session.ip_address || "Unknown IP"} · signed in {formatDateTime(session.created_at)} · expires{" "}
                      {formatDateTime(session.expires_at)}
                    </span>
                  </div>
                  <Button size="sm" variant="danger" loading={isPending(`revoke-${session.id}`)} onClick={() => void revoke(session.id)}>
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </AsyncBoundary>
    </>
  );
}
