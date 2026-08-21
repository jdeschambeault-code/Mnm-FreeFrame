'use client'

import * as React from 'react'
import useSWR, { mutate } from 'swr'
import { FolderKanban, EyeOff, Eye } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/shared/empty-state'
import type { MyProjectVisibilityItem } from '@/types'

export default function MyAyonProjectsPage() {
  const { data, error, isLoading } = useSWR<MyProjectVisibilityItem[]>(
    '/projects/me/all',
    () => api.get<MyProjectVisibilityItem[]>('/projects/me/all'),
  )
  const [busyId, setBusyId] = React.useState<string | null>(null)

  const handleToggle = async (item: MyProjectVisibilityItem) => {
    setBusyId(item.project_id)
    try {
      await api.post(`/projects/${item.project_id}/${item.hidden ? 'unhide' : 'hide'}`, {})
      mutate('/projects/me/all')
      mutate('/projects')
    } finally {
      setBusyId(null)
    }
  }

  const isForbidden =
    error instanceof Error && error.message.toLowerCase().includes('only staff accounts')

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-text-primary">My Ayon Projects</h1>
        <p className="text-sm text-text-secondary mt-1">
          Staff accounts see every project by default. Hide the ones you don&apos;t need
          cluttering your own project list - this only affects your view, nobody else&apos;s.
        </p>
      </div>

      {isForbidden ? (
        <div className="rounded-lg border border-border bg-bg-secondary">
          <EmptyState
            icon={FolderKanban}
            title="Not applicable to this account"
            description="Only staff accounts (mnm.local / methodnmadness.com) see every project by default, so there's nothing to hide here. Ask an admin if you need access to a specific project."
          />
        </div>
      ) : isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-bg-tertiary" />
          ))}
        </div>
      ) : error ? (
        <p className="text-sm text-status-error">
          {error instanceof Error ? error.message : 'Failed to load projects'}
        </p>
      ) : !data || data.length === 0 ? (
        <div className="rounded-lg border border-border bg-bg-secondary">
          <EmptyState icon={FolderKanban} title="No projects yet" description="Nothing to show here yet." />
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-bg-secondary overflow-hidden divide-y divide-border">
          {data.map((item) => (
            <div key={item.project_id} className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-sm font-medium text-text-primary">{item.project_name}</p>
                {item.ayon_project_name && (
                  <p className="text-xs text-text-tertiary">{item.ayon_project_name}</p>
                )}
              </div>
              <Button
                variant="ghost"
                size="sm"
                loading={busyId === item.project_id}
                onClick={() => handleToggle(item)}
              >
                {item.hidden ? (
                  <>
                    <Eye className="h-3.5 w-3.5" /> Show
                  </>
                ) : (
                  <>
                    <EyeOff className="h-3.5 w-3.5" /> Hide
                  </>
                )}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
