'use client'

import * as React from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { versionStatusConfig } from '@/components/review/version-switcher'
import type { AssetVersion } from '@/types'

// Matches the delivered filename's version token (e.g. "v002" in
// "zd_111_reviewAnimation_v002_h264.mp4") so it can be visually
// distinguished from the rest of the name - the point is to make it obvious
// at a glance that two versions are the *same* shot (identical surrounding
// text) differing only in that token, not just a bare "v1"/"v2" with no
// name context to compare against.
const VERSION_TOKEN_RE = /v\d{2,}/i

function splitVersionToken(name: string): [string, string, string] | null {
  const m = VERSION_TOKEN_RE.exec(name)
  if (!m) return null
  return [name.slice(0, m.index), m[0], name.slice(m.index + m[0].length)]
}

interface CompareVersionSelectProps {
  versions: AssetVersion[]
  value: string | null
  onChange: (v: AssetVersion) => void
  /** Pane accent (e.g. "text-sky-400" / "text-emerald-400") keying badge + markers. */
  accentClass: string
  /** Version shown on the OTHER pane — disabled here so both sides can't show the same version. */
  excludeId?: string | null
  testId?: string
}

/** Controlled version dropdown for the compare overlay — never touches the review store. */
export function CompareVersionSelect({ versions, value, onChange, accentClass, excludeId, testId }: CompareVersionSelectProps) {
  const [open, setOpen] = React.useState(false)
  const rootRef = React.useRef<HTMLDivElement>(null)
  const sorted = React.useMemo(
    () => [...versions].sort((a, b) => a.version_number - b.version_number),
    [versions],
  )
  const selected = sorted.find((v) => v.id === value) ?? null

  React.useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  return (
    <div className="relative" ref={rootRef} data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className={cn(
          'flex items-center gap-1.5 rounded-md border border-border bg-bg-secondary px-2.5 py-1.5 text-[13px] font-medium hover:bg-bg-hover transition-colors',
          accentClass,
        )}
      >
        v{selected?.version_number ?? '—'}
        <ChevronDown className="h-3.5 w-3.5 text-text-tertiary" />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute left-0 top-full z-[100] mt-1 min-w-[280px] max-w-[420px] rounded-lg border border-border bg-bg-elevated p-1 shadow-xl"
        >
          {sorted.map((v) => {
            const status = versionStatusConfig[v.processing_status]
            const ready = v.processing_status === 'ready'
            // The version already shown on the other pane is disabled so the two
            // sides can't collapse onto the same version.
            const onOtherSide = v.id === excludeId
            const blocked = !ready || onOtherSide
            const filename = v.files?.[0]?.original_filename
            const parts = filename ? splitVersionToken(filename) : null
            return (
              <button
                key={v.id}
                type="button"
                role="option"
                aria-selected={v.id === value}
                disabled={blocked}
                title={onOtherSide ? 'Shown on the other side' : filename}
                onClick={() => {
                  if (blocked) return
                  onChange(v)
                  setOpen(false)
                }}
                className={cn(
                  'flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors',
                  v.id === value ? 'bg-bg-hover text-text-primary' : 'text-text-secondary hover:bg-bg-hover',
                  blocked && 'opacity-50 cursor-not-allowed',
                )}
              >
                {parts ? (
                  <span className="truncate text-left">
                    <span className="text-text-tertiary">{parts[0]}</span>
                    <span className={cn('font-semibold', accentClass)}>{parts[1]}</span>
                    <span className="text-text-tertiary">{parts[2]}</span>
                  </span>
                ) : (
                  <span>v{v.version_number}</span>
                )}
                {onOtherSide ? (
                  <span className="shrink-0 text-[11px] text-text-tertiary">in use</span>
                ) : status && !ready ? (
                  <span
                    className={cn('shrink-0 inline-flex items-center gap-1 text-[11px]', status.className)}
                    title={status.label}
                  >
                    {status.icon}
                    {status.label}
                  </span>
                ) : null}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
