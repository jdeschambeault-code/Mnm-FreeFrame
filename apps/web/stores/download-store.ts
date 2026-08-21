import { create } from 'zustand'
import { getAccessToken } from '@/lib/auth'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export type DownloadStatus = 'zipping' | 'downloading' | 'complete' | 'error'

export interface DownloadJob {
  id: string
  folderName: string
  status: DownloadStatus
  receivedBytes: number
  totalBytes: number | null // null = server didn't send Content-Length, show indeterminate
  error?: string
  createdAt: number
}

const abortControllers: Record<string, AbortController> = {}

interface DownloadStore {
  jobs: DownloadJob[]
  minimized: boolean
  setMinimized: (minimized: boolean) => void
  toggleMinimized: () => void
  startDownload: (folderId: string, folderName: string) => string
  cancelDownload: (jobId: string) => void
  dismiss: (jobId: string) => void
  clearFinished: () => void
}

export const useDownloadStore = create<DownloadStore>()((set, get) => ({
  jobs: [],
  minimized: false,

  setMinimized: (minimized) => set({ minimized }),
  toggleMinimized: () => set((s) => ({ minimized: !s.minimized })),

  startDownload: (folderId, folderName) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`

    const entry: DownloadJob = {
      id,
      folderName,
      status: 'zipping',
      receivedBytes: 0,
      totalBytes: null,
      createdAt: Date.now(),
    }
    set((s) => ({ jobs: [entry, ...s.jobs], minimized: false }))

    const updateJob = (jobId: string, patch: Partial<DownloadJob>) => {
      set((s) => ({ jobs: s.jobs.map((j) => (j.id === jobId ? { ...j, ...patch } : j)) }))
    }

    ;(async () => {
      const controller = new AbortController()
      abortControllers[id] = controller

      try {
        // While this request is in flight and headers haven't arrived yet,
        // the server is still walking the delivery folder and writing the
        // zip - there's no byte progress to report for that phase, so the
        // job just sits in "zipping" (indeterminate) until headers land.
        const res = await fetch(`${API_URL}/folders/${folderId}/download`, {
          headers: { Authorization: `Bearer ${getAccessToken()}` },
          signal: controller.signal,
        })

        if (!res.ok) {
          const body = await res.json().catch(() => null)
          throw new Error(typeof body?.detail === 'string' ? body.detail : `Download failed (${res.status})`)
        }

        const contentLength = res.headers.get('content-length')
        const totalBytes = contentLength ? parseInt(contentLength, 10) : null
        const match = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')
        const filename = match?.[1] || `${folderName}.zip`

        updateJob(id, { status: 'downloading', totalBytes })

        // Stream the body so we can report real byte progress instead of
        // blocking on res.blob() with no feedback until the whole zip lands.
        const reader = res.body?.getReader()
        const chunks: Uint8Array[] = []
        let received = 0

        if (reader) {
          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            if (value) {
              chunks.push(value)
              received += value.byteLength
              updateJob(id, { receivedBytes: received })
            }
          }
        }

        const blob = chunks.length ? new Blob(chunks as BlobPart[]) : await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.style.display = 'none'
        document.body.appendChild(a)
        a.click()
        setTimeout(() => {
          a.remove()
          URL.revokeObjectURL(url)
        }, 1000)

        updateJob(id, { status: 'complete', receivedBytes: blob.size, totalBytes: blob.size })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          set((s) => ({ jobs: s.jobs.filter((j) => j.id !== id) }))
        } else {
          updateJob(id, { status: 'error', error: err instanceof Error ? err.message : 'Download failed' })
        }
      } finally {
        delete abortControllers[id]
      }
    })()

    return id
  },

  cancelDownload: (jobId) => {
    abortControllers[jobId]?.abort()
  },

  dismiss: (jobId) => {
    set((s) => ({ jobs: s.jobs.filter((j) => j.id !== jobId) }))
  },

  clearFinished: () => {
    set((s) => ({ jobs: s.jobs.filter((j) => j.status !== 'complete' && j.status !== 'error') }))
  },
}))
