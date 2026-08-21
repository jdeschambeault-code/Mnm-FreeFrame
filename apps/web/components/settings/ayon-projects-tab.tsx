"use client";

import * as React from "react";
import useSWR, { mutate } from "swr";
import Link from "next/link";
import { Link2, Check, ExternalLink, Save, RotateCcw } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/shared/empty-state";
import { DeleteProjectDialog } from "@/components/projects/delete-project-dialog";
import type { AyonConnection, AyonProjectSummary } from "@/types";

function AyonConnectionCard() {
  const { data, mutate: mutateConnection } = useSWR<AyonConnection>(
    "/admin/ayon/connection",
    () => api.get<AyonConnection>("/admin/ayon/connection"),
  );

  const [url, setUrl] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");

  // Only seed the URL field from the loaded connection once, on first load -
  // otherwise every background revalidation would clobber whatever the admin
  // is mid-typing. The API key is never returned raw, so its field always
  // starts blank ("leave blank to keep the current key").
  const seeded = React.useRef(false);
  React.useEffect(() => {
    if (data && !seeded.current) {
      setUrl(data.ayon_url ?? "");
      seeded.current = true;
    }
  }, [data]);

  const save = async (body: { ayon_url?: string; ayon_api_key?: string }) => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const updated = await api.put<AyonConnection>("/admin/ayon/connection", body);
      mutateConnection(updated, false);
      setApiKey("");
      setSuccess("Saved.");
      mutate("/admin/ayon/projects");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save Ayon connection");
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => {
    const body: { ayon_url?: string; ayon_api_key?: string } = { ayon_url: url.trim() };
    if (apiKey.trim()) body.ayon_api_key = apiKey.trim();
    save(body);
  };

  const handleResetToLauncher = () => {
    if (!confirm("Clear the override and fall back to the Pinokio launcher's AYON_URL / AYON_API_KEY?")) return;
    seeded.current = false;
    save({ ayon_url: "", ayon_api_key: "" });
  };

  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-4 space-y-4 max-w-xl">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-text-primary">Ayon connection</h3>
        {data && (
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
              data.source === "database"
                ? "bg-status-success/15 text-status-success"
                : data.source === "launcher"
                  ? "bg-bg-tertiary text-text-tertiary"
                  : "bg-status-error/15 text-status-error",
            )}
          >
            {data.source === "database"
              ? "Overridden here"
              : data.source === "launcher"
                ? "From Pinokio launcher"
                : "Not configured"}
          </span>
        )}
      </div>

      <div className="space-y-3">
        <Input
          label="Ayon URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="http://ayon.example.local"
        />
        <Input
          label="Ayon API key"
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={data?.api_key_masked ? `Current: ${data.api_key_masked}` : "Not set"}
        />
      </div>

      {error && <p className="text-xs text-status-error">{error}</p>}
      {success && <p className="text-xs text-status-success">{success}</p>}

      <div className="flex items-center gap-2">
        <Button size="sm" onClick={handleSave} loading={saving} disabled={!url.trim()}>
          <Save className="h-3.5 w-3.5" /> Save
        </Button>
        {data?.source === "database" && (
          <Button variant="ghost" size="sm" onClick={handleResetToLauncher} disabled={saving}>
            <RotateCcw className="h-3.5 w-3.5" /> Reset to launcher default
          </Button>
        )}
      </div>
      <p className="text-xs text-text-tertiary">
        Overrides the Ayon URL / API key set in the Pinokio launcher's Settings, without needing a restart.
        Leave the API key blank to keep the current one.
      </p>
    </div>
  );
}

export function AyonProjectsTab() {
  const { data, error, isLoading } = useSWR<AyonProjectSummary[]>(
    "/admin/ayon/projects",
    () => api.get<AyonProjectSummary[]>("/admin/ayon/projects"),
  );
  const [activating, setActivating] = React.useState<string | null>(null);
  const [deactivating, setDeactivating] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState("");
  const [deletingProject, setDeletingProject] = React.useState<{ id: string; name: string } | null>(null);

  const handleActivate = async (name: string) => {
    setActivating(name);
    setActionError("");
    try {
      await api.post(`/admin/ayon/projects/${encodeURIComponent(name)}/activate`, {});
      mutate("/admin/ayon/projects");
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : `Failed to activate ${name}`);
    } finally {
      setActivating(null);
    }
  };

  const handleDeactivate = async (name: string) => {
    if (!confirm(`Unlink "${name}" from its FreeFrame project? The FreeFrame project and its assets/comments are kept - only the Ayon link is removed, so the delivery watcher and comment relay stop touching it.`)) {
      return;
    }
    setDeactivating(name);
    setActionError("");
    try {
      await api.post(`/admin/ayon/projects/${encodeURIComponent(name)}/deactivate`, {});
      mutate("/admin/ayon/projects");
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : `Failed to deactivate ${name}`);
    } finally {
      setDeactivating(null);
    }
  };

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">Ayon Projects</h2>
        <p className="text-xs text-text-secondary mt-0.5">
          Live from your Ayon server — nothing here is cached. Activate a project to create a
          matching FreeFrame project you can review in.
        </p>
      </div>

      <AyonConnectionCard />

      {actionError && <p className="text-xs text-status-error">{actionError}</p>}

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-bg-tertiary" />
          ))}
        </div>
      ) : error ? (
        <div className="rounded-lg border border-border bg-bg-secondary p-4">
          <p className="text-sm text-status-error">
            {error instanceof Error ? error.message : "Couldn't reach Ayon"}
          </p>
          <p className="text-xs text-text-tertiary mt-1">
            Check the Ayon connection settings above (or the Pinokio launcher's Settings, which they fall back to).
          </p>
        </div>
      ) : !data || data.length === 0 ? (
        <div className="rounded-lg border border-border bg-bg-secondary">
          <EmptyState
            icon={Link2}
            title="No Ayon projects found"
            description="Nothing came back from the Ayon server."
          />
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-bg-secondary overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-bg-tertiary">
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">
                  Ayon project
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">
                  Code
                </th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-text-tertiary">
                  Status
                </th>
                <th className="px-4 py-2.5 text-right text-xs font-medium text-text-tertiary">
                  FreeFrame
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr
                  key={p.name}
                  className="border-b border-border last:border-0 hover:bg-bg-tertiary transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-text-primary">{p.name}</td>
                  <td className="px-4 py-3 text-text-tertiary">{p.code}</td>
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                        p.active
                          ? "bg-status-success/15 text-status-success"
                          : "bg-bg-tertiary text-text-tertiary",
                      )}
                    >
                      {p.active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {p.linked && p.freeframe_project_id ? (
                      <div className="inline-flex items-center gap-3">
                        <Link
                          href={`/projects/${p.freeframe_project_id}`}
                          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
                        >
                          <Check className="h-3.5 w-3.5" /> Linked
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={deactivating === p.name}
                          onClick={() => handleDeactivate(p.name)}
                        >
                          Deactivate
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-status-error hover:text-status-error"
                          onClick={() => setDeletingProject({ id: p.freeframe_project_id!, name: p.name })}
                        >
                          Delete permanently
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={activating === p.name}
                        onClick={() => handleActivate(p.name)}
                      >
                        Activate
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deletingProject && (
        <DeleteProjectDialog
          projectId={deletingProject.id}
          projectName={deletingProject.name}
          open={!!deletingProject}
          onOpenChange={(o) => !o && setDeletingProject(null)}
          onDeleted={() => mutate("/admin/ayon/projects")}
        />
      )}
    </section>
  );
}
