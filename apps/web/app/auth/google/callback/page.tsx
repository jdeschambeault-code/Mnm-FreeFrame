'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { setTokens } from '@/lib/auth'
import { useAuthStore } from '@/stores/auth-store'

// Lands here after /auth/google/callback (the backend route) redirects with
// tokens in the URL *fragment* (not a query string - fragments never reach
// any server, so this is the one place they're read, client-side only).
export default function GoogleCallbackPage() {
  const router = useRouter()
  const [error, setError] = useState('')

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')

    if (!accessToken || !refreshToken) {
      setError('Google sign-in did not complete. Please try again.')
      return
    }

    setTokens(accessToken, refreshToken)
    useAuthStore.getState().fetchUser().finally(() => {
      router.replace('/projects')
    })
  }, [router])

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-text-secondary">
        {error || 'Finishing sign-in…'}
      </p>
    </div>
  )
}
