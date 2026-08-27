"use client";

import * as React from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { InstanceSettings } from "@/types";

/** Settings > Admin > Client Sharing: default+lock rules applied to share
 * links created by non-staff (client) users - see routers/share.py's
 * _apply_client_sharing_rules / _strip_client_sharing_locks. "Enforced"
 * means the value is forced at creation AND the client can't change it
 * later; unenforced still seeds the default but leaves it editable. */
export function ClientSharingTab() {
  const { data, mutate } = useSWR<InstanceSettings>(
    "/instance/settings",
    () => api.get<InstanceSettings>("/instance/settings"),
  );

  const [days, setDays] = React.useState<string>("");
  const [expiryEnforced, setExpiryEnforced] = React.useState(true);
  const [watermarkEnforced, setWatermarkEnforced] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!data) return;
    setDays(String(data.client_share_expiry_days));
    setExpiryEnforced(data.client_share_expiry_enforced);
    setWatermarkEnforced(data.client_share_watermark_enforced);
  }, [data?.client_share_expiry_days, data?.client_share_expiry_enforced, data?.client_share_watermark_enforced]);

  const handleSave = async () => {
    const parsedDays = Number(days);
    if (!Number.isFinite(parsedDays) || parsedDays < 1) {
      setError("Expiration must be at least 1 day.");
      return;
    }
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      await api.put("/instance/settings", {
        client_share_expiry_days: parsedDays,
        client_share_expiry_enforced: expiryEnforced,
        client_share_watermark_enforced: watermarkEnforced,
      });
      mutate();
      setSaved(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-6 max-w-lg">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">Client Sharing</h2>
        <p className="text-xs text-text-tertiary mt-0.5">
          Default and enforced rules for share links created by client accounts (any email domain
          not on the Staff email domains allowlist below). Staff/admin-created links are never
          affected. "Enforced" means the client can neither set a different value when creating
          the link nor change it afterward — clear the toggle to keep it as a default only.
        </p>
      </div>

      {/* Expiration */}
      <div className="p-4 rounded-lg border border-border bg-bg-secondary space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-text-primary">Expiration</p>
            <p className="text-xs text-text-tertiary mt-0.5">
              Client share links expire this many days after creation.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={1}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            className="w-24"
          />
          <span className="text-sm text-text-secondary">days from the moment it's shared</span>
        </div>
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={expiryEnforced}
            onChange={(e) => setExpiryEnforced(e.target.checked)}
            className="rounded border-border"
          />
          Enforced — client can't remove or change the expiration date
        </label>
      </div>

      {/* Watermark */}
      <div className="p-4 rounded-lg border border-border bg-bg-secondary space-y-3">
        <div>
          <p className="text-sm font-medium text-text-primary">Watermark</p>
          <p className="text-xs text-text-tertiary mt-0.5">
            Client share links always show a watermark on video/image content.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={watermarkEnforced}
            onChange={(e) => setWatermarkEnforced(e.target.checked)}
            className="rounded border-border"
          />
          Enforced — watermark is always on and can't be turned off by a client
        </label>
      </div>

      {error && <p className="text-xs text-status-error">{error}</p>}
      {saved && <p className="text-xs text-status-success">Saved.</p>}
      <Button size="sm" onClick={handleSave} loading={saving} disabled={!data}>
        Save
      </Button>
    </section>
  );
}
