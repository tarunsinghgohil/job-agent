"use client";

import { useEffect, useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card, CardGrid } from "../../components/Card";
import { FieldRow, Input } from "../../components/Field";
import { FormActions } from "../../components/FormActions";
import { PageHeader } from "../../components/PageHeader";
import { AsyncBoundary, EmptyState } from "../../components/States";
import { Toggle } from "../../components/Toggle";
import { useToast } from "../../components/Toast";
import { api } from "../../lib/api";
import { formatDateTime, titleize } from "../../lib/format";
import { usePending, useResource } from "../../lib/hooks";
import type { NotificationChannel, NotificationEvent, NotificationPreferences, TestResult } from "../../lib/types";

export function NotificationsView() {
  const toast = useToast();
  const { isPending, run } = usePending();
  const channels = useResource<NotificationChannel[]>((signal) => api.get<NotificationChannel[]>("/api/v1/notifications/channels", undefined, signal));
  const preferences = useResource<NotificationPreferences>((signal) =>
    api.get<NotificationPreferences>("/api/v1/notifications/preferences", undefined, signal),
  );
  const events = useResource<NotificationEvent[]>((signal) => api.get<NotificationEvent[]>("/api/v1/notifications/events", { limit: 30 }, signal));

  const [draftCreds, setDraftCreds] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [prefsForm, setPrefsForm] = useState<NotificationPreferences | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (preferences.data && !prefsForm) setPrefsForm(preferences.data);
  }, [preferences.data, prefsForm]);

  async function toggleChannel(channel: NotificationChannel) {
    await run(`toggle-${channel.channel_type}`, async () => {
      await api.put(`/api/v1/notifications/channels/${channel.channel_type}`, {
        enabled: !channel.enabled,
        config: channel.config,
      });
      channels.reload();
    });
  }

  async function saveCredential(channel: NotificationChannel) {
    const credential = draftCreds[channel.channel_type]?.trim();
    if (!credential) return;
    await run(`cred-${channel.channel_type}`, async () => {
      await toast.withToast(
        () => api.put(`/api/v1/notifications/channels/${channel.channel_type}`, { enabled: channel.enabled, config: channel.config, credential }),
        "Credential saved.",
      );
      setDraftCreds((d) => ({ ...d, [channel.channel_type]: "" }));
      channels.reload();
    });
  }

  async function saveConfigField(channel: NotificationChannel, key: string, value: string) {
    await api.put(`/api/v1/notifications/channels/${channel.channel_type}`, {
      enabled: channel.enabled,
      config: { ...channel.config, [key]: value },
    });
    channels.reload();
  }

  async function testChannel(channelType: string) {
    await run(`test-${channelType}`, async () => {
      const result = await toast.withToast(() => api.post<TestResult>(`/api/v1/notifications/channels/${channelType}/test`), "Test sent.");
      if (result) setTestResults((current) => ({ ...current, [channelType]: result }));
    });
  }

  async function savePreferences() {
    if (!prefsForm) return;
    await run("save-prefs", async () => {
      await toast.withToast(() => api.put("/api/v1/notifications/preferences", prefsForm), "Preferences saved.");
      setDirty(false);
      preferences.reload();
    });
  }

  return (
    <>
      <PageHeader title="Notifications" description="Channels, routing, and quiet hours." />

      <AsyncBoundary loading={channels.loading} error={channels.error} data={channels.data} onRetry={channels.reload}>
        {(items) => (
          <CardGrid columns={2}>
            {items.map((channel) => (
              <Card
                key={channel.channel_type}
                title={channel.display_name || titleize(channel.channel_type)}
                actions={<Toggle checked={channel.enabled} onChange={() => void toggleChannel(channel)} label="Enabled" />}
              >
                {channel.config_schema.map((field) => (
                  <Input
                    key={field.key}
                    label={field.label ?? field.key}
                    defaultValue={String(channel.config[field.key] ?? "")}
                    onBlur={(e) => void saveConfigField(channel, field.key, e.target.value)}
                  />
                ))}
                {channel.requires_credential && (
                  <div className="toolbar">
                    <Input
                      type="password"
                      placeholder={channel.has_credential ? "Rotate credential" : "Enter credential"}
                      value={draftCreds[channel.channel_type] ?? ""}
                      onChange={(e) => setDraftCreds((d) => ({ ...d, [channel.channel_type]: e.target.value }))}
                    />
                    <Button size="sm" loading={isPending(`cred-${channel.channel_type}`)} onClick={() => void saveCredential(channel)}>
                      Save
                    </Button>
                  </div>
                )}
                {channel.last_error && <p className="inline-error">{channel.last_error}</p>}
                {testResults[channel.channel_type] && (
                  <p className={testResults[channel.channel_type].ok ? "muted" : "inline-error"}>
                    {testResults[channel.channel_type].message}
                  </p>
                )}
                <Button size="sm" loading={isPending(`test-${channel.channel_type}`)} onClick={() => void testChannel(channel.channel_type)}>
                  Send test
                </Button>
              </Card>
            ))}
          </CardGrid>
        )}
      </AsyncBoundary>

      <AsyncBoundary loading={preferences.loading} error={preferences.error} data={prefsForm} onRetry={preferences.reload}>
        {(data) => (
          <Card title="Routing and quiet hours">
            <FieldRow>
              <Input
                label="Quiet hours start"
                type="time"
                value={data.quiet_hours_start}
                onChange={(e) => {
                  setPrefsForm({ ...data, quiet_hours_start: e.target.value });
                  setDirty(true);
                }}
              />
              <Input
                label="Quiet hours end"
                type="time"
                value={data.quiet_hours_end}
                onChange={(e) => {
                  setPrefsForm({ ...data, quiet_hours_end: e.target.value });
                  setDirty(true);
                }}
              />
            </FieldRow>
            <FieldRow>
              <Toggle
                label="Daily digest"
                checked={data.daily_digest_enabled}
                onChange={(v) => {
                  setPrefsForm({ ...data, daily_digest_enabled: v });
                  setDirty(true);
                }}
              />
              <Toggle
                label="Weekly summary"
                checked={data.weekly_summary_enabled}
                onChange={(v) => {
                  setPrefsForm({ ...data, weekly_summary_enabled: v });
                  setDirty(true);
                }}
              />
            </FieldRow>
            <FieldRow>
              <Toggle
                label="Instant alerts"
                checked={data.instant_alerts_enabled}
                onChange={(v) => {
                  setPrefsForm({ ...data, instant_alerts_enabled: v });
                  setDirty(true);
                }}
              />
              <Toggle
                label="Failures only"
                checked={data.failures_only}
                onChange={(v) => {
                  setPrefsForm({ ...data, failures_only: v });
                  setDirty(true);
                }}
              />
            </FieldRow>
            <FormActions onSave={savePreferences} saving={isPending("save-prefs")} dirty={dirty} />
          </Card>
        )}
      </AsyncBoundary>

      <AsyncBoundary
        loading={events.loading}
        error={events.error}
        data={events.data}
        onRetry={events.reload}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No notifications sent yet" />}
      >
        {(items) => (
          <Card title="Recent notification events">
            <ul className="timeline">
              {items.map((event) => (
                <li key={event.id}>
                  <div>
                    <p className="timeline-title">
                      {titleize(event.event_type)} <Badge tone={event.status === "sent" ? "success" : event.status === "failed" ? "danger" : "neutral"}>{event.status}</Badge>
                    </p>
                    <p className="timeline-meta">
                      {formatDateTime(event.created_at)} · {event.channel_type}
                    </p>
                    {event.error && <p className="timeline-body">{event.error}</p>}
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </AsyncBoundary>
    </>
  );
}
