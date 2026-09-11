"use client";

import * as React from "react";
import useSWR from "swr";
import * as Dialog from "@radix-ui/react-dialog";
import { FolderKanban, X } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { UserProjectAccessItem } from "@/types";

export function UserProjectAccessModal({
  userId,
  userName,
}: {
  userId: string;
  userName: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [selected, setSelected] = React.useState<Set<string> | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");

  const { data, isLoading } = useSWR<UserProjectAccessItem[]>(
    open ? `/admin/users/${userId}/projects` : null,
    () => api.get<UserProjectAccessItem[]>(`/admin/users/${userId}/projects`),
  );

  React.useEffect(() => {
    if (data && selected === null) {
      setSelected(new Set(data.filter((p) => p.is_member).map((p) => p.project_id)));
    }
  }, [data, selected]);

  React.useEffect(() => {
    if (!open) setSelected(null);
  }, [open]);

  const toggle = (projectId: string) => {
    setSelected((prev) => {
      const next = new Set(prev ?? []);
      if (next.has(projectId)) next.delete(projectId);
      else next.add(projectId);
      return next;
    });
  };

  const handleSave = async () => {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await api.put(`/admin/users/${userId}/projects`, { project_ids: Array.from(selected) });
      setOpen(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save project access");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="ghost" size="sm">
          <FolderKanban className="h-3.5 w-3.5" />
          Ayon Project
        </Button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-bg-secondary p-6 shadow-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <Dialog.Close className="absolute right-4 top-4 text-text-tertiary hover:text-text-primary transition-colors">
            <X className="h-4 w-4" />
          </Dialog.Close>

          <Dialog.Title className="text-base font-semibold text-text-primary">
            Project access — {userName}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            Pick which projects this account can see. Staff accounts (madness.com /
            methodnmadness.com) already see every project by default and manage
            exceptions themselves from Settings → My Ayon Projects — this only matters
            for everyone else.
          </Dialog.Description>

          <div className="mt-4 max-h-80 overflow-y-auto space-y-1">
            {isLoading || !data ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-8 animate-pulse rounded-lg bg-bg-tertiary" />
                ))}
              </div>
            ) : data.length === 0 ? (
              <p className="text-xs text-text-tertiary">No projects yet.</p>
            ) : (
              data.map((p) => (
                <label
                  key={p.project_id}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm text-text-secondary hover:bg-bg-hover cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selected?.has(p.project_id) ?? false}
                    onChange={() => toggle(p.project_id)}
                    className="h-3.5 w-3.5 rounded border-border accent-accent"
                  />
                  <span className="text-text-primary">{p.project_name}</span>
                  {p.ayon_project_name && (
                    <span className="text-xs text-text-tertiary">({p.ayon_project_name})</span>
                  )}
                </label>
              ))
            )}
          </div>

          {error && <p className="mt-2 text-xs text-status-error">{error}</p>}

          <div className="mt-4 flex justify-end gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="button" size="sm" loading={saving} onClick={handleSave} disabled={!selected}>
              Save
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
