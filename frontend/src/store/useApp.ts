import { create } from 'zustand'

type Page = 'home' | 'settings' | 'movers' | 'upcoming'

interface AppState {
  page: Page
  setPage: (p: Page) => void
}

export const useApp = create<AppState>((set)=>({
  page: 'home',
  setPage: (p)=> set({ page: p })
}))
