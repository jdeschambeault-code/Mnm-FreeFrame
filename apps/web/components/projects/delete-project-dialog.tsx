"use client";

import * as React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ProjectPurgePreview } from "@/types";

interface DeleteProjectDialogProps {
  projectId: string;
  projectName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}

// Admin-only (see require_admin on POST /admin/projects/{id}/purge-now) -
// permanently deletes a project (DB + object storage, via the same cascade
// the retention GC uses) and best-effort trash-moves its NAS delivery
// folder. Shared between the main Projects page's "..." menu and Settings >
// Admin > Ayon Projects, so "Delete" always does this instead of the plain
// soft-delete (see routers/projects.py delete_project), which never touches
// the NAS and leaves the project purge-able-later rather than gone now.
export function DeleteProjectDialog({
  projectId,
  projectName,
  open,
  onOpenChange,
  onDeleted,
}: DeleteProjectDialogProps) {
  const [preview, setPreview] = React.useState<ProjectPurgePreview | null>(null);
  const [loadingPreview, setLoadingPreview] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState("");
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState("");

  // Both call sites mount this dialog already open (open={true} from the
  // first render, no Dialog.Trigger) rather than opening it via a click
  // Radix itself observes - so onOpenChange(true) never fires for that
  // transition and a fetch triggered only from there would never run,
  // leaving preview permanently null and the confirm button permanently
  // disabled. Watching `open` directly here fires regardless of how it
  // became true.
  React.useEffect(() => {
    if (!open) return;
    setError("");
    setConfirmText("");
    setLoadingPreview(true);
    setPreview(null);
    api
      .get<ProjectPurgePreview>(`/admin/projects/${projectId}/purge-preview`)
      .then(setPreview)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load purge preview"))
      .finally(() => setLoadingPreview(false));
  }, [open, projectId]);

  const handleDelete = async () => {
    if (!preview || confirmText !== preview.project_name) return;
    setDeleting(true);
    setError("");
    try {
      await api.post(`/admin/projects/${projectId}/purge-now`, { confirm_name: confirmText });
      onOpenChange(false);
      onDeleted?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete project");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-bg-secondary p-6 shadow-xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95">
          <Dialog.Close className="absolute right-4 top-4 text-text-tertiary hover:text-text-primary transition-colors">
            <X className="h-4 w-4" />
          </Dialog.Close>

          <div className="flex items-center gap-2">
            <TriangleAlert className="h-4 w-4 text-status-error" />
            <Dialog.Title className="text-base font-semibold text-text-primary">
              Delete project permanently
            </Dialog.Title>
          </div>
          <Dialog.Description className="mt-1 text-sm text-text-secondary">
            This permanently deletes &quot;{projectName}&quot; - every asset, comment, folder, and
            share link, in both the database and object storage. This cannot be undone.
          </Dialog.Description>

          <div className="mt-4 space-y-4">
            {loadingPreview ? (
              <p className="text-sm text-text-tertiary">Loading what will be deleted…</p>
            ) : preview ? (
              <>
                <ul className="text-sm text-text-secondary space-y-1 rounded-md border border-border bg-bg-tertiary p-3">
                  <li>{preview.counts.assets ?? 0} asset(s)</li>
                  <li>{preview.counts.folders ?? 0} folder(s)</li>
                  <li>{preview.counts.comments ?? 0} comment(s)</li>
                  <li>{preview.counts.share_links ?? 0} share link(s)</li>
                  <li>{preview.counts.members ?? 0} member(s)</li>
                </ul>
                {preview.nas_delivery_path ? (
                  <p className="text-xs text-text-tertiary">
                    Its NAS delivery folder (<span className="text-text-secondary">{preview.nas_delivery_path}</span>)
                    will be moved to a <span className="text-text-secondary">_deleted</span> folder next to it,
                    not permanently erased.
                  </p>
                ) : (
                  <p className="text-xs text-text-tertiary">No NAS delivery folder was found for it.</p>
                )}

                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium text-text-secondary">
                    Type <span className="text-text-primary font-semibold">{preview.project_name}</span> to confirm
                  </label>
                  <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
                </div>
              </>
            ) : null}

            {error && <p className="text-xs text-status-error">{error}</p>}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                loading={deleting}
                disabled={!preview || confirmText !== preview.project_name}
                onClick={handleDelete}
                className="bg-status-error hover:bg-status-error/90 text-white"
              >
                Delete permanently
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
