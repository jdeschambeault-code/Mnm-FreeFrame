"use client";

import * as React from "react";
import useSWR, { mutate } from "swr";
import { Link2, Users, Ban } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";
import type { AdminShareLinkItem } from "@/types";

const TYPE_LABEL: Record<AdminShareLinkItem["share_type"], string> = {
  asset: "Asset",
  folder: "Folder",
  project: "Project",
};

/** Settings > Admin > Share Links: every share link across every project, for
 * instance-wide oversight and cancellation — see routers/admin.py
 * list_all_share_links. Cancel reuses the same DELETE /share/{token} the
 * per-project "All Share Links" panel uses (superadmin already bypasses its
 * project-membership check). */
export function AdminShareLinksTab() {
  const { data, isLoading } = useSWR<AdminShareLinkItem[]>(
    "/admin/share-links",
    () => api.get<AdminShareLinkItem[]>("/admin/share-links"),
  );
  const [cancelling, setCancelling] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");

  const handleCancel = async (link: AdminShareLinkItem) => {
    if (!confirm(`Cancel the share link "${link.title || "(untitled)"}"? Anyone with this link will lose access immediately.`)) {
      return;
    }
    setCancelling(link.token);
    setError("");
    try {
      await api.delete(`/share/${link.token}`);
      mutate("/admin/share-links");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to cancel link");
    } finally {
      setCancelling(null);
    }
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">Share Links</h2>
          <p className="text-xs text-text-tertiary mt-0.5">
            Every active share link across every project. Cancel any link to revoke access
            immediately.
          </p>
        </div>
      </div>

      {error && <p className="text-xs text-status-error">{error}</p>}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-bg-tertiary" />
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <div className="rounded-lg border border-border bg-bg-secondary">
          <EmptyState icon={Link2} title="No share links" description="Nothing has been shared yet." />
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-bg-secondary overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-bg-tertiary">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">Link</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">Project</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">Created by</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">Expires</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">Status</th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-text-tertiary">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.map((link) => (
                <tr key={link.id} className="border-b border-border last:border-0 hover:bg-bg-tertiary transition-colors">
                  <td className="px-4 py-3">
                    <p className="text-sm font-medium text-text-primary truncate max-w-[220px]">
                      {link.title || "(untitled)"}
                    </p>
                    <p className="text-2xs text-text-tertiary">
                      {TYPE_LABEL[link.share_type]} · {link.show_watermark ? "watermarked" : "no watermark"}
                    </p>
                  </td>
                  <td className="px-4 py-3 text-text-secondary">{link.project_name}</td>
                  <td className="px-4 py-3">
                    <p className="text-text-secondary truncate max-w-[180px]">{link.created_by_name}</p>
                    {link.is_client && (
                      <span className="inline-flex items-center gap-1 text-2xs text-accent">
                        <Users className="h-3 w-3" /> Client
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-text-tertiary">
                    {link.expires_at ? new Date(link.expires_at).toLocaleDateString() : "Never"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                        link.is_enabled
                          ? "bg-status-success/15 text-status-success"
                          : "bg-bg-tertiary text-text-tertiary",
                      )}
                    >
                      {link.is_enabled ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={cancelling === link.token}
                      onClick={() => handleCancel(link)}
                      className="text-status-error hover:text-status-error gap-1"
                    >
                      <Ban className="h-3.5 w-3.5" /> Cancel
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
