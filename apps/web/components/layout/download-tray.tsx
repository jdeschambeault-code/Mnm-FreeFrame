'use client'

import * as React from 'react'
import { X, Minus, FolderArchive, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import { cn, formatBytes } from '@/lib/utils'
import { useDownloadStore, type DownloadJob } from '@/stores/download-store'

function JobRow({ job }: { job: DownloadJob }) {
  const { cancelDownload, dismiss } = useDownloadStore()
  const pct =
    job.status === 'downloading' && job.totalBytes
      ? Math.min(100, Math.round((job.receivedBytes / job.totalBytes) * 100))
      : job.status === 'complete'
        ? 100
        : null

  return (
    <div className="flex items-start gap-3 px-3 py-2.5">
      <div className="h-8 w-8 shrink-0 rounded-md bg-bg-tertiary flex items-center justify-center text-text-tertiary">
        {job.status === 'complete' ? (
          <CheckCircle className="h-4 w-4 text-status-success" />
        ) : job.status === 'error' ? (
          <AlertCircle className="h-4 w-4 text-status-error" />
        ) : (
          <FolderArchive className="h-4 w-4" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-text-primary truncate">{job.folderName}</p>

        {(job.status === 'zipping' || job.status === 'downloading') && (
          <div className="mt-1.5 h-1.5 w-full rounded-full bg-bg-tertiary overflow-hidden">
            {pct === null ? (
              <div className="h-full w-1/3 rounded-full bg-accent animate-indeterminate" />
            ) : (
              <div className="h-full rounded-full bg-accent transition-all duration-200" style={{ width: `${pct}%` }} />
            )}
          </div>
        )}

        <p className="text-[11px] text-text-tertiary mt-1">
          {job.status === 'zipping' && 'Preparing zip on the server…'}
          {job.status === 'downloading' &&
            (job.totalBytes
              ? `${formatBytes(job.receivedBytes)} / ${formatBytes(job.totalBytes)} (${pct}%)`
              : `Downloading… ${formatBytes(job.receivedBytes)}`)}
          {job.status === 'complete' && 'Saved to your Downloads folder'}
          {job.status === 'error' && <span className="text-status-error">{job.error}</span>}
        </p>
      </div>

      <div className="shrink-0 flex items-center">
        {(job.status === 'zipping' || job.status === 'downloading') && (
          <button
            onClick={() => cancelDownload(job.id)}
            className="h-6 w-6 flex items-center justify-center rounded text-text-tertiary hover:text-text-primary hover:bg-bg-hover transition-colors"
            title="Cancel"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
        {(job.status === 'complete' || job.status === 'error') && (
          <button
            onClick={() => dismiss(job.id)}
            className="h-6 w-6 flex items-center justify-center rounded text-text-tertiary hover:text-text-primary hover:bg-bg-hover transition-colors"
            title="Dismiss"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

export function DownloadTray() {
  const { jobs, minimized, setMinimized, clearFinished } = useDownloadStore()

  if (jobs.length === 0) return null

  const activeCount = jobs.filter((j) => j.status === 'zipping' || j.status === 'downloading').length

  // Minimized: a small pill in the corner - the app underneath stays fully
  // interactive since this tray never renders a backdrop.
  if (minimized) {
    return (
      <button
        onClick={() => setMinimized(false)}
        className="fixed bottom-4 right-4 z-50 flex items-center gap-2 rounded-full border border-border bg-bg-elevated shadow-xl px-4 py-2.5 hover:bg-bg-hover transition-colors"
      >
        {activeCount > 0 ? (
          <Loader2 className="h-3.5 w-3.5 text-accent animate-spin" />
        ) : (
          <FolderArchive className="h-3.5 w-3.5 text-text-tertiary" />
        )}
        <span className="text-xs font-medium text-text-primary">
          {activeCount > 0 ? `Downloading ${activeCount}…` : `${jobs.length} download${jobs.length > 1 ? 's' : ''}`}
        </span>
      </button>
    )
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[320px] rounded-xl border border-border bg-bg-elevated shadow-2xl overflow-hidden animate-in slide-in-from-bottom-4 fade-in duration-150">
      {/* Header */}
      <div className="flex items-center justify-between px-3 h-10 border-b border-border shrink-0">
        <h2 className="text-xs font-semibold text-text-primary">
          Downloads
          {activeCount > 0 && <span className="ml-1.5 text-[11px] font-normal text-accent">{activeCount} active</span>}
        </h2>
        <div className="flex items-center gap-0.5">
          {jobs.some((j) => j.status === 'complete' || j.status === 'error') && (
            <button
              onClick={clearFinished}
              className="text-[11px] text-text-tertiary hover:text-text-secondary transition-colors px-1.5 py-0.5 rounded hover:bg-bg-hover"
            >
              Clear
            </button>
          )}
          <button
            onClick={() => setMinimized(true)}
            className="h-6 w-6 flex items-center justify-center rounded text-text-tertiary hover:text-text-primary hover:bg-bg-hover transition-colors"
            title="Minimize"
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Job list */}
      <div className={cn('divide-y divide-border overflow-y-auto', jobs.length > 4 && 'max-h-[320px]')}>
        {jobs.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </div>
    </div>
  )
}
