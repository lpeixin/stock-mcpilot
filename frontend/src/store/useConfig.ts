/** 后端配置状态（模型服务 / 分析上下文 / 界面）。 */

import { create } from 'zustand'
import { fetchConfig, updateConfig } from '../api'
import type { AnalysisConfig, AppConfig, LLMConfig } from '../api/types'
import { describeError } from '../api/client'
import { useApp } from './useApp'

interface ConfigState {
  config: AppConfig | null
  loading: boolean
  error: string | null
  initialized: boolean
  load: (force?: boolean) => Promise<void>
  save: (patch: { llm?: Partial<LLMConfig>; analysis?: Partial<AnalysisConfig>; ui?: Record<string, unknown> }) => Promise<AppConfig | null>
}

export const useConfig = create<ConfigState>((set, get) => ({
  config: null,
  loading: false,
  error: null,
  initialized: false,

  load: async (force = false) => {
    if (get().loading) return
    if (get().initialized && !force) return
    set({ loading: true, error: null })
    try {
      const config = await fetchConfig()
      set({ config, initialized: true, loading: false })
      // 后端配置是界面语言的来源之一，但**不能**无条件覆盖本机选择：
      // 那样用户在设置页选了英文，只要重新加载配置就会被改回旧值。
      // 优先级见 useApp.adoptConfigLanguage（本机明确选过 > 配置 > 浏览器语言）。
      useApp.getState().adoptConfigLanguage(config.ui?.language || config.analysis?.language)
    } catch (error) {
      set({ loading: false, error: describeError(error) })
    }
  },

  save: async (patch) => {
    set({ loading: true, error: null })
    try {
      const config = await updateConfig(patch)
      set({ config, initialized: true, loading: false })
      return config
    } catch (error) {
      set({ loading: false, error: describeError(error) })
      return null
    }
  },
}))
