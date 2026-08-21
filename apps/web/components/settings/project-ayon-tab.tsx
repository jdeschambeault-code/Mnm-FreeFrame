"use client";

import * as React from "react";
import Link from "next/link";
import useSWR from "swr";
import { Folder, ChevronRight, ChevronDown, Link2, HardDrive } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { AyonHierarchyNode, AyonTreeResponse, Project } from "@/types";

function TreeNode({ node, depth = 0 }: { node: AyonHierarchyNode; depth?: number }) {
  const [open, setOpen] = React.useState(depth < 1);
  const hasChildren = node.children && node.children.length > 0;

  return (
    <div>
      <button
        onClick={() => hasChildren && setOpen((o) => !o)}
        title={node.physical_path ?? undefined}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-md py-1 px-1.5 text-left text-sm hover:bg-bg-tertiary transition-colors",
          !hasChildren && "cursor-default",
        )}
        style={{ paddingLeft: `${depth * 16 + 4}px` }}
      >
        {hasChildren ? (
          open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
          )
        ) : (
          <span className="w-3.5 shrink-0" />
        )}
        <Folder className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
        <span className="text-text-primary truncate">{node.name}</span>
        {node.tasks.length > 0 && (
          <span className="ml-1 flex flex-wrap gap-1">
            {node.tasks.map((t) => (
              <span
                key={t.id}
                title={[t.status, t.assignees.join(", ")].filter(Boolean).join(" — ") || undefined}
                className="rounded-full bg-accent/10 px-1.5 py-0 text-[10px] font-medium text-accent"
              >
                {t.name}
              </span>
            ))}
          </span>
        )}
      </button>
      {open && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNode key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ProjectAyonTab({ projectId }: { projectId: string }) {
  const { data: project } = useSWR<Project>(`/projects/${projectId}`, () =>
    api.get<Project>(`/projects/${projectId}`),
  );

  const linked = !!project?.ayon_project_name;

  const {
    data: tree,
    error,
    isLoading,
  } = useSWR<AyonTreeResponse>(linked ? `/projects/${projectId}/ayon-tree` : null, () =>
    api.get(`/projects/${projectId}/ayon-tree`),
  );

  if (!project) return null;

  if (!linked) {
    return (
      <section className="space-y-3 max-w-md">
        <h2 className="text-sm font-semibold text-text-primary">Ayon</h2>
        <p className="text-sm text-text-secondary">
          This project isn&apos;t linked to an Ayon project yet.
        </p>
        <Link
          href="/settings/admin"
          className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
        >
          <Link2 className="h-3.5 w-3.5" />
          Link it from Admin → Ayon Projects
        </Link>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-text-primary">Ayon folder &amp; task tree</h2>
        <p className="text-xs text-text-secondary mt-0.5">
          Live from Ayon project <span className="font-medium">{project.ayon_project_name}</span> —
          fetched fresh on every load, nothing is stored in FreeFrame.
        </p>
        {tree?.disk_path && (
          <p className="mt-1.5 flex items-center gap-1.5 text-xs text-text-tertiary font-mono">
            <HardDrive className="h-3.5 w-3.5 shrink-0" />
            {tree.disk_path}
          </p>
        )}
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-7 animate-pulse rounded-md bg-bg-tertiary" />
          ))}
        </div>
      ) : error ? (
        <p className="text-sm text-status-error">
          {error instanceof Error ? error.message : "Couldn't load the Ayon tree"}
        </p>
      ) : !tree || tree.hierarchy.length === 0 ? (
        <p className="text-sm text-text-tertiary">No folders in this Ayon project.</p>
      ) : (
        <div className="rounded-lg border border-border bg-bg-secondary p-2">
          {tree.hierarchy.map((node) => (
            <TreeNode key={node.id} node={node} />
          ))}
        </div>
      )}
    </section>
  );
}
