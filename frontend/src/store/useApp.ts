/** 应用级状态：页面路由与界面语言。 */

import { create } from 'zustand'
import type { Lang } from '../i18n'

export type Page = 'home' | 'movers' | 'upcoming' | 'settings'

const LANG_KEY = 'smp.language'

function isLang(value: unknown): value is Lang {
  return value === 'zh' || value === 'en'
}

/** 浏览器语言推断：中文环境给 zh，其余给 en。
 *
 *  这里曾经写成 `startsWith('zh') ? 'zh' : 'zh'` —— 两个分支一样，
 *  等于浏览器语言检测完全没生效，英文系统上打开也是中文界面。
 */
function fromBrowser(): Lang {
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

/** 用户是否在本机明确选过语言。选过就以本机选择为准。 */
export function hasStoredLanguage(): boolean {
  return isLang(localStorage.getItem(LANG_KEY))
}

function initialLanguage(): Lang {
  const stored = localStorage.getItem(LANG_KEY)
  return isLang(stored) ? stored : fromBrowser()
}

interface AppState {
  page: Page
  language: Lang
  /** 从涨跌榜/财报日历跳转过来时带上的标的 */
  pendingSymbol: { symbol: string; market: 'US' | 'HK' | 'CN' } | null
  setPage: (page: Page) => void
  setLanguage: (language: Lang) => void
  /**
   * 采纳后端配置里的界面语言。
   *
   * 只在**本机没有明确选择过**时才生效：否则用户在设置页选了英文、后端配置却还
   * 停留在旧值（或换台机器后 localStorage 为空），就会被服务端配置悄悄改回去。
   */
  adoptConfigLanguage: (language: unknown) => void
  openSymbol: (symbol: string, market: 'US' | 'HK' | 'CN') => void
  consumePendingSymbol: () => { symbol: string; market: 'US' | 'HK' | 'CN' } | null
}

export const useApp = create<AppState>((set, get) => ({
  page: 'home',
  language: initialLanguage(),
  pendingSymbol: null,
  setPage: (page) => set({ page }),
  setLanguage: (language) => {
    localStorage.setItem(LANG_KEY, language)
    set({ language })
  },
  adoptConfigLanguage: (language) => {
    if (!isLang(language)) return
    if (hasStoredLanguage()) return
    set({ language })
  },
  openSymbol: (symbol, market) => set({ pendingSymbol: { symbol, market }, page: 'home' }),
  consumePendingSymbol: () => {
    const pending = get().pendingSymbol
    if (pending) set({ pendingSymbol: null })
    return pending
  },
}))
