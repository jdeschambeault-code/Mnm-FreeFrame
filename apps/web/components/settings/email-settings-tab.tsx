"use client";

import * as React from "react";
import useSWR from "swr";
import { CheckCircle, XCircle, Send, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { EmailStatus } from "@/types";

export function EmailSettingsTab() {
  const { data, mutate: mutateStatus } = useSWR<EmailStatus>(
    "/admin/email/status",
    () => api.get<EmailStatus>("/admin/email/status"),
  );

  const [testEmail, setTestEmail] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [result, setResult] = React.useState<{ ok: boolean; message: string } | null>(null);

  const handleSendTest = async () => {
    if (!testEmail.trim()) return;
    setSending(true);
    setResult(null);
    try {
      await api.post("/admin/email/test", { to_email: testEmail.trim() });
      setResult({ ok: true, message: `Sent to ${testEmail.trim()}. Check the inbox (and spam folder).` });
    } catch (err: unknown) {
      setResult({ ok: false, message: err instanceof Error ? err.message : "Send failed" });
    } finally {
      setSending(false);
      mutateStatus();
    }
  };

  return (
    <section className="space-y-4 max-w-md">
      <h2 className="text-sm font-semibold text-text-primary">Email configuration</h2>

      {/* Status card */}
      <div className="p-4 rounded-lg border border-border bg-bg-secondary space-y-2">
        {!data ? (
          <p className="text-sm text-text-tertiary">Loading…</p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              {data.configured ? (
                <CheckCircle className="h-4 w-4 text-status-success" />
              ) : (
                <XCircle className="h-4 w-4 text-status-error" />
              )}
              <span className={cn("text-sm font-medium", data.configured ? "text-status-success" : "text-status-error")}>
                {data.configured ? "Configured" : "Not configured"}
              </span>
              <span className="text-xs text-text-tertiary uppercase tracking-wide ml-auto">
                {data.provider}
              </span>
            </div>
            <dl className="text-xs text-text-tertiary space-y-1 pt-1">
              <div className="flex justify-between gap-4">
                <dt>From</dt>
                <dd className="text-text-secondary truncate">{data.from_name} &lt;{data.from_address}&gt;</dd>
              </div>
              {data.provider === "smtp" && (
                <>
                  <div className="flex justify-between gap-4">
                    <dt>SMTP host</dt>
                    <dd className="text-text-secondary truncate">{data.smtp_host || "—"}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt>SMTP port</dt>
                    <dd className="text-text-secondary">{data.smtp_port ?? "—"}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt>TLS</dt>
                    <dd className="text-text-secondary">{data.smtp_use_tls ? "Enabled" : "Disabled"}</dd>
                  </div>
                </>
              )}
            </dl>
            {!data.configured && (
              <p className="text-xs text-status-error pt-1">
                Magic-code login, invites, and notifications will silently fail to send until this is set up
                (SMTP_HOST / AWS SES credentials — deployment config, not editable here).
              </p>
            )}
          </>
        )}
      </div>

      {/* Send test email */}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="test-email" className="text-sm font-medium text-text-secondary">
          Send a test email
        </label>
        <div className="flex items-center gap-2">
          <Input
            id="test-email"
            type="email"
            value={testEmail}
            onChange={(e) => setTestEmail(e.target.value)}
            placeholder="you@example.com"
            onKeyDown={(e) => e.key === "Enter" && handleSendTest()}
          />
          <Button size="sm" onClick={handleSendTest} loading={sending} disabled={!testEmail.trim()}>
            {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Send
          </Button>
        </div>
        <p className="text-xs text-text-tertiary">
          Sends immediately (not queued) so you get a real pass/fail here.
        </p>
        {result && (
          <p className={cn("text-xs", result.ok ? "text-status-success" : "text-status-error")}>
            {result.message}
          </p>
        )}
      </div>
    </section>
  );
}
