import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface BrandingState {
  /** Logo for dark theme (shown on dark backgrounds) */
  orgLogoDark: string | null
  /** Logo for light theme (shown on light backgrounds) */
  orgLogoLight: string | null
  setOrgLogoDark: (url: string | null) => void
  setOrgLogoLight: (url: string | null) => void
  resetAll: () => void
}

// Workspace *name* moved server-side (InstanceSettings.workspace_name, via
// /instance/settings) so backend email templates can reference it too - see
// components/settings/branding-name.tsx. Logos stay client-side-only here;
// migrating those wasn't asked for.
export const useBrandingStore = create<BrandingState>()(
  persist(
    (set) => ({
      orgLogoDark: null,
      orgLogoLight: null,
      setOrgLogoDark: (url) => set({ orgLogoDark: url }),
      setOrgLogoLight: (url) => set({ orgLogoLight: url }),
      resetAll: () => set({ orgLogoDark: null, orgLogoLight: null }),
    }),
    {
      name: 'ff-branding',
      version: 3,
      migrate: () => ({
        orgLogoDark: null,
        orgLogoLight: null,
      }),
    },
  ),
)
