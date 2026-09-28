/**
 * 上下文预览抽屉。
 *
 * 存在的意义是"可核对"：用户能亲眼看到发给模型的是什么，而不是只能相信
 * 一句"已注入行情上下文"。缺失段与裁剪情况也一并列出，避免模型因为拿不到
 * 数据而给出空泛结论却没人发现。
 */

import { useEffect, useState } from 'react'
import type { ContextPreview as ContextPreviewData } from '../api/types'
import type { TranslateFn } from '../i18n'
import { fmtNum } from '../utils/format'
import { Button, EmptyState, Spinner } from './ui'

type Tab = 'system' | 'user' | 'payload'

interface Props {
  open: boolean
  loading: boolean
  error: string | null
  data: ContextPreviewData | null
  t: TranslateFn
  onClose: () => void
  onReload: () => void
}

const ContextPreview: React.FC<Props> = ({
  open,
  loading,
  error,
  data,
  t,
  onClose,
  onReload,
}) => {
  const [tab, setTab] = useState<Tab>('payload')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(timer)
  }, [copied])

  if (!open) return null

  const meta = data?.meta
  const content =
    tab === 'system'
      ? (data?.structured?.system_prompt ?? '')
      : tab === 'user'
        ? (data?.structured?.user_prompt ?? '')
        : (data?.text ?? '')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'payload', label: t('analysis.context.rendered') },
    { key: 'user', label: t('analysis.context.userPrompt') },
    { key: 'system', label: t('analysis.context.systemPrompt') },
  ]

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-slate-900">{t('analysis.context.title')}</h2>
            <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">
              {t('analysis.context.desc')}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" onClick={onReload} disabled={loading}>
              {loading ? <Spinner className="h-3 w-3" /> : null}
              {t('common.refresh')}
            </Button>
            <Button size="sm" onClick={copy} disabled={!content}>
              {copied ? t('common.copied') : t('common.copy')}
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose}>
              {t('common.close')}
            </Button>
          </div>
        </header>

        {meta ? (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 border-b border-slate-100 px-4 py-2.5 sm:grid-cols-4">
            <div>
              <div className="text-[11px] text-slate-400">{t('analysis.context.size')}</div>
              <div className="text-xs tabular-nums text-slate-800">
                {fmtNum(meta.context_chars, 0)} / {fmtNum(meta.budget_chars, 0)}
              </div>
            </div>
            <div className="min-w-0">
              <div className="text-[11px] text-slate-400">{t('analysis.context.included')}</div>
              <div className="truncate text-xs text-slate-800">
                {meta.included.length ? meta.included.join(', ') : '—'}
              </div>
            </div>
            <div className="min-w-0">
              <div className="text-[11px] text-slate-400">{t('analysis.context.missing')}</div>
              <div className="truncate text-xs text-amber-600">
                {meta.missing.length ? meta.missing.join(', ') : '—'}
              </div>
            </div>
            <div className="min-w-0">
              <div className="text-[11px] text-slate-400">{t('analysis.context.trimmed')}</div>
              <div className="truncate text-xs text-amber-600">
                {meta.trimmed.length ? meta.trimmed.join('; ') : '—'}
              </div>
            </div>
          </div>
        ) : null}

        <div className="flex items-center gap-1 border-b border-slate-100 px-4 py-2">
          {tabs.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              className={`rounded px-2 py-0.5 text-xs transition ${
                tab === item.key
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-auto bg-slate-50 px-4 py-3">
          {error ? (
            <p className="text-xs text-red-600">{error}</p>
          ) : loading && !data ? (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Spinner className="h-3.5 w-3.5" />
              {t('common.loading')}
            </div>
          ) : content ? (
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-700">
              {content}
            </pre>
          ) : (
            <EmptyState text={t('common.empty')} compact />
          )}
        </div>
      </div>
    </div>
  )
}

export default ContextPreview
