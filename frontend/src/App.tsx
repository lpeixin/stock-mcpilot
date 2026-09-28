/**
 * 应用外壳：顶栏导航 + 后端连通性提示 + 页面路由。
 *
 * 语言由 `useApp` 驱动（不是模块级变量），所以切换后整个界面会真正重渲染 ——
 * 改造前把语言存在模块变量里、在渲染过程中改它，React 根本不知道要更新。
 */

import { useEffect, useMemo, useState } from 'react'
import { http, resolveApiBase } from './api/client'
import { makeTranslator } from './i18n'
import type { Lang } from './i18n'
import Home from './pages/Home'
import Movers from './pages/Movers'
import Settings from './pages/Settings'
import UpcomingEarnings from './pages/UpcomingEarnings'
import { useApp } from './store/useApp'
import type { Page } from './store/useApp'
import { useConfig } from './store/useConfig'

const NAV: { page: Page; key: string }[] = [
  { page: 'home', key: 'nav.home' },
  { page: 'movers', key: 'nav.movers' },
  { page: 'upcoming', key: 'nav.upcoming' },
  { page: 'settings', key: 'nav.settings' },
]

const App: React.FC = () => {
  const { page, setPage, language, setLanguage } = useApp()
  const t = useMemo(() => makeTranslator(language), [language])
  const [backendOk, setBackendOk] = useState<boolean | null>(null)
  // 在外壳层就把配置读进来：界面语言存在配置里，如果等到用户点进设置页才加载，
  // 首次打开（以及每次刷新）都会先用错误的语言渲染一遍 —— 英文用户会看到中文界面。
  const loadConfig = useConfig((state) => state.load)

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const tick = async () => {
      let ok = false
      try {
        await http.get('/health', { timeout: 4000 })
        ok = true
      } catch {
        ok = false
      }
      if (cancelled) return

      if (!ok) {
        // 离线时重新问一次壳。两件事都靠它兜住：
        //   1. 桌面壳冷启动要十几秒（import pandas / yfinance），第一次问
        //      通常还没就绪；
        //   2. 8000 被别的服务占用时后端会顺延到 8001、8002……
        await resolveApiBase()
        if (cancelled) return
      }

      setBackendOk(ok)
      // 在线时不必频繁打扰后端；离线时短间隔重试，用户不用盯着"离线"干等。
      timer = setTimeout(tick, ok ? 20000 : 2000)
    }

    void resolveApiBase().then(() => {
      if (!cancelled) void tick()
    })

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[1600px] items-center gap-4 px-5 py-2.5">
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight text-slate-900">
              {t('app.name')}
            </span>
            <span className="hidden text-[11px] text-slate-400 sm:inline">{t('app.tagline')}</span>
          </div>

          <nav className="flex items-center gap-0.5">
            {NAV.map((item) => (
              <button
                key={item.page}
                type="button"
                onClick={() => setPage(item.page)}
                className={`rounded-md px-3 py-1 text-xs transition ${
                  page === item.page
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
                }`}
              >
                {t(item.key)}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {backendOk === false ? (
              <span className="flex items-center gap-1.5 text-[11px] text-red-600">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                {t('error.backend')}
              </span>
            ) : backendOk === true ? (
              <span className="flex items-center gap-1.5 text-[11px] text-emerald-600">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {t('app.online')}
              </span>
            ) : null}

            <div className="flex items-center gap-0.5 rounded-md bg-slate-100 p-0.5">
              {(['zh', 'en'] as Lang[]).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setLanguage(item)}
                  className={`rounded px-1.5 py-0.5 text-[11px] transition ${
                    language === item
                      ? 'bg-white text-slate-900 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {item === 'zh' ? '中' : 'EN'}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      {backendOk === false ? (
        <div className="border-b border-amber-200 bg-amber-50 px-5 py-2">
          <p className="mx-auto w-full max-w-[1600px] text-[11px] leading-relaxed text-amber-800">
            {t('error.backendHint')}
          </p>
        </div>
      ) : null}

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-5 py-4">
        {page === 'home' ? <Home /> : null}
        {page === 'movers' ? <Movers /> : null}
        {page === 'upcoming' ? <UpcomingEarnings /> : null}
        {page === 'settings' ? <Settings /> : null}
      </main>

      <footer className="border-t border-slate-200 px-5 py-3">
        <p className="mx-auto w-full max-w-[1600px] text-[11px] text-slate-400">
          {t('footer.disclaimer')}
        </p>
      </footer>
    </div>
  )
}

export default App
