import { create } from 'zustand'
import { SettingsState, getSettings, updateSettings } from '../api/api'

interface Store extends SettingsState {
  initialized: boolean
  init: () => Promise<void>
  save: (p: Partial<SettingsState>) => Promise<void>
}

export const useSettings = create<Store>((set, get) => ({
  mode: 'local',
  api_key: undefined,
  local_model: 'llama3',
  language: 'en',
  initialized: false,
  init: async () => {
    if (get().initialized) return
  try { const data = await getSettings(); set({ ...data, initialized: true }) } catch {}
  },
  save: async (p) => {
    const data = await updateSettings(p)
    set(data)
  }
}))
