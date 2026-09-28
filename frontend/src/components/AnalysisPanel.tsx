/**
 * AI 分析面板。
 *
 * 三件事：
 *   1. 让用户决定"喂什么"（上下文开关、分析侧重、补充问题）
 *   2. 流式展示输出，随时可停
 *   3. 把"实际注入了什么"摊开给用户核对（上下文预览）
 *
 * 免责声明是常驻的，不藏在折叠里 —— 这是文化性解读，不是投资建议。
 */

import { useState } from 'react'
import { fetchContextPreview } from '../api'
import type { AnalysisFocus, ContextPreview as ContextPreviewData } from '../api/types'
import { describeError } from '../api/client'
import type { TranslateFn } from '../i18n'
import { useStock } from '../store/useStock'
import { fmtNum } from '../utils/format'
import ContextPreview from './ContextPreview'
import Markdown from './Markdown'
import { Badge, Button, Spinner, Toggle } from './ui'

const FOCUS: { value: AnalysisFocus; key: string }[] = [
  { value: 'technical', key: 'analysis.focus.technical' },
  { value: 'fundamental', key: 'analysis.focus.fundamental' },
  { value: 'news', key: 'analysis.focus.news' },
  { value: 'valuation', key: 'analysis.focus.valuation' },
  { value: 'risk', key: 'analysis.focus.risk' },
]

const SECTION_KEY: Record<string, string> = {
  quote: 'analysis.section.quote',
  indicators: 'analysis.section.indicators',
  summary: 'analysis.section.summary',
  candles: 'analysis.section.candles',
  profile: 'analysis.section.profile',
  financials: 'analysis.section.financials',
  earnings: 'analysis.section.earnings',
  analyst: 'analysis.section.analyst',
  news: 'analysis.section.news',
}

interface Props {
  t: TranslateFn
  language: 'zh' | 'en'
}

const AnalysisPanel: React.FC<Props> = ({ t, language }) => {
  const {
    symbol,
    market,
    question,
    focus,
    useContext,
    analyzing,
    analysisText,
    analysisMeta,
    analysisModel,
    analysisProvider,
    analysisElapsed,
    analysisError,
    detail,
    setQuestion,
    toggleFocus,
    setUseContext,
    runAnalysis,
    stopAnalysis,
    clearAnalysis,
  } = useStock()

  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewData, setPreviewData] = useState<ContextPreviewData | null>(null)
  const [copied, setCopied] = useState(false)

  const loadPreview = async () => {
    setPreviewLoading(true)
    setPreviewError(null)
    try {
      const data = await fetchContextPreview(symbol.trim().toUpperCase(), market, {
        days: 180,
        news_limit: 10,
      })
      setPreviewData(data)
    } catch (error) {
      setPreviewError(describeError(error))
    } finally {
      setPreviewLoading(false)
    }
  }

  const openPreview = () => {
    setPreviewOpen(true)
    if (!previewData) void loadPreview()
  }

  const copyResult = async () => {
    if (!analysisText) return
    try {
      await navigator.clipboard.writeText(analysisText)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  const started = analyzing || analysisText.length > 0

  return (
    <section className="rounded-xl border border-slate-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium text-slate-800">{t('analysis.title')}</h2>
          {analysisModel ? (
            <span className="text-[11px] text-slate-400">
              {analysisProvider ? `${analysisProvider} · ` : ''}
              {analysisModel}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {analysisElapsed !== null ? (
            <span className="text-[11px] tabular-nums text-slate-400">
              {t('analysis.elapsed')} {(analysisElapsed / 1000).toFixed(1)}s
            </span>
          ) : null}
          {started ? (
            <Button size="sm" variant="ghost" onClick={clearAnalysis} disabled={analyzing}>
              {t('common.clear')}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={copyResult} disabled={!analysisText}>
            {copied ? t('common.copied') : t('common.copy')}
          </Button>
        </div>
      </header>

      <div className="space-y-3 px-4 py-3">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={2}
          placeholder={t('analysis.ask.placeholder')}
          className="w-full resize-none rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs leading-relaxed text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
        />

        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-[11px] text-slate-400">{t('analysis.focus')}</span>
          <div className="flex flex-wrap items-center gap-1">
            {FOCUS.map((item) => {
              const active = focus.includes(item.value)
              return (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => toggleFocus(item.value)}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] transition ${
                    active
                      ? 'border-blue-300 bg-blue-50 text-blue-700'
                      : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700'
                  }`}
                >
                  {t(item.key)}
                </button>
              )
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Toggle checked={useContext} onChange={setUseContext} label={t('analysis.useContext')} />
            <button
              type="button"
              onClick={openPreview}
              className="text-[11px] text-blue-600 hover:underline"
            >
              {t('analysis.context')} ↗
            </button>
          </div>

          <div className="flex items-center gap-2">
            {analyzing ? (
              <Button variant="danger" onClick={stopAnalysis}>
                <span className="h-2.5 w-2.5 rounded-sm bg-red-500" />
                {t('analysis.stop')}
              </Button>
            ) : (
              <Button variant="primary" onClick={() => void runAnalysis(language)}>
                {t('analysis.action')}
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="border-t border-slate-100 px-4 py-3">
        {analysisError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-700">
            {analysisError}
          </div>
        ) : null}

        {!analysisError && !started ? (
          <p className="py-6 text-center text-xs leading-relaxed text-slate-400">
            {t('analysis.empty')}
          </p>
        ) : null}

        {analyzing && analysisText.length === 0 && !analysisError ? (
          <div className="flex items-center gap-2 py-6 text-xs text-slate-400">
            <Spinner className="h-3.5 w-3.5" />
            {t('analysis.thinking')}
          </div>
        ) : null}

        {analysisText ? (
          <div className="max-h-[560px] overflow-auto">
            <Markdown text={analysisText} streaming={analyzing} />
          </div>
        ) : null}

        {analysisMeta ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <Badge tone={useContext ? 'info' : 'neutral'}>
              {useContext ? t('analysis.usedContext') : t('analysis.noContext')}
            </Badge>
            <span className="text-[11px] text-slate-400">
              {t('analysis.context.size')} {fmtNum(analysisMeta.context_chars, 0)} /{' '}
              {fmtNum(analysisMeta.budget_chars, 0)}
            </span>
            {analysisMeta.included.map((name) => (
              <span
                key={name}
                className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500"
              >
                {SECTION_KEY[name] ? t(SECTION_KEY[name]) : name}
              </span>
            ))}
            {analysisMeta.missing.map((name) => (
              <span
                key={name}
                className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-600"
                title={t('analysis.context.missing')}
              >
                {SECTION_KEY[name] ? t(SECTION_KEY[name]) : name}
              </span>
            ))}
            {analysisMeta.trimmed.length > 0 ? (
              <span className="text-[11px] text-amber-600">
                {t('analysis.context.trimmed')}: {analysisMeta.trimmed.join('; ')}
              </span>
            ) : null}
          </div>
        ) : null}

        {detail?.warnings?.length ? (
          <ul className="mt-2 space-y-0.5">
            {detail.warnings.map((warning) => (
              <li key={warning} className="text-[11px] text-amber-600">
                {warning}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <p className="border-t border-slate-100 px-4 py-2 text-[11px] leading-relaxed text-slate-400">
        {t('analysis.disclaimer')}
      </p>

      <ContextPreview
        open={previewOpen}
        loading={previewLoading}
        error={previewError}
        data={previewData}
        t={t}
        onClose={() => setPreviewOpen(false)}
        onReload={() => void loadPreview()}
      />
    </section>
  )
}

export default AnalysisPanel
