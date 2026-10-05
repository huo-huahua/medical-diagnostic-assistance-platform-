import { create } from 'zustand'

import { authApi, tokenStore } from '@/api'
import type { Disease, DiseaseInfo, User } from '@/types'

interface AuthState {
  user: User | null
  status: 'idle' | 'loading' | 'authenticated' | 'anonymous'
  login: (email: string, password: string) => Promise<void>
  register: (email: string, displayName: string, password: string) => Promise<void>
  logout: () => void
  bootstrap: () => Promise<void>
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  status: 'idle',

  login: async (email, password) => {
    const res = await authApi.login({ email, password })
    tokenStore.set(res.access_token)
    set({ user: res.user, status: 'authenticated' })
  },

  register: async (email, displayName, password) => {
    const res = await authApi.register({
      email,
      display_name: displayName,
      password,
    })
    tokenStore.set(res.access_token)
    set({ user: res.user, status: 'authenticated' })
  },

  logout: () => {
    tokenStore.clear()
    set({ user: null, status: 'anonymous' })
  },

  /** Restore the session from a stored token on app boot. */
  bootstrap: async () => {
    if (!tokenStore.get()) {
      set({ status: 'anonymous' })
      return
    }
    set({ status: 'loading' })
    try {
      const user = await authApi.me()
      set({ user, status: 'authenticated' })
    } catch {
      tokenStore.clear()
      set({ user: null, status: 'anonymous' })
    }
  },
}))

// --------------------------------------------------------------------------- //

interface WorkspaceState {
  /** Disease modules loaded from the registry (public endpoint). */
  diseases: DiseaseInfo[]
  diseasesLoaded: boolean
  activeDisease: Disease
  /** Per-disease selected algorithm; falls back to the champion. */
  selectedAlgo: Record<string, string>
  loadDiseases: () => Promise<DiseaseInfo[]>
  setActiveDisease: (d: Disease) => void
  setAlgo: (disease: Disease, algo: string) => void
}

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  diseases: [],
  diseasesLoaded: false,
  activeDisease: 'breast',
  selectedAlgo: {},

  loadDiseases: async () => {
    if (get().diseasesLoaded && get().diseases.length) return get().diseases
    const { modelApi } = await import('@/api')
    const list = await modelApi.list()
    list.sort((a, b) => (a.disease === 'breast' ? -1 : b.disease === 'breast' ? 1 : 0))
    set({ diseases: list, diseasesLoaded: true })
    return list
  },

  setActiveDisease: (d) => set({ activeDisease: d }),

  setAlgo: (disease, algo) =>
    set((s) => ({ selectedAlgo: { ...s.selectedAlgo, [disease]: algo } })),
}))

/** Resolve the algorithm currently in effect for a disease. */
export function resolveAlgo(
  diseases: DiseaseInfo[],
  disease: Disease,
  selectedAlgo: Record<string, string>,
): string {
  const module = diseases.find((d) => d.disease === disease)
  if (!module) return 'xgb'
  return selectedAlgo[disease] ?? module.champion
}

// --------------------------------------------------------------------------- //

interface UiState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}

export const useUi = create<UiState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}))
