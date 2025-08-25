import React from 'react'
import { StockDailyResponse, AnalysisResponse } from '../api/api'
import { setLang, t } from '../i18n'
import { useSettings } from '../store/useSettings'

interface Props { data?: StockDailyResponse; analysis?: AnalysisResponse; loading: boolean }

const formatNumber = (n: number | undefined, opts: { digits?: number; pct?: boolean } = {}) => {
  if (n === undefined || n === null || Number.isNaN(n)) return '-'
  const digits = opts.digits ?? 2
  let v = n
  if (opts.pct) return `${v.toFixed(digits)}%`
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: digits })
  return v.toFixed(digits)
}

const MetricItem: React.FC<{ label: string; value: React.ReactNode; hint?: string; tone?: 'pos' | 'neg' | 'neutral' }> = ({ label, value, hint, tone='neutral' }) => {
  const color = tone === 'pos' ? 'text-emerald-600' : tone === 'neg' ? 'text-rose-600' : 'text-gray-800'
  return (
    <div className="flex flex-col gap-0.5 p-3 rounded border bg-white shadow-sm">
      <span className="text-[11px] tracking-wide uppercase text-gray-500">{label}</span>
      <span className={`font-semibold text-sm ${color}`}>{value}</span>
      {hint && <span className="text-[11px] text-gray-400 leading-snug">{hint}</span>}
    </div>
  )
}

const StockResult: React.FC<Props> = ({ data, analysis, loading }) => {
  const { language } = useSettings(); setLang(language as any)
  if (loading) return <div className="text-sm text-gray-500">{t('loading')}</div>
  if (!data) return <div className="text-sm text-gray-400">{t('empty.prompt')}</div>

  const s = data.summary
  const returnTone = s.return_pct >= 0 ? 'pos' : 'neg'
  const ddTone = s.max_drawdown_pct <= -10 ? 'neg' : 'neutral'
  const volTone = s.volatility_pct > 5 ? 'neg' : 'neutral'

  return (
    <div className="space-y-4 mt-4">
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="font-medium text-base">{t('summary.title')}</h2>
          <span className="text-xs text-gray-400">{t('summary.range')}: {data.start} ~ {data.end}</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          <MetricItem label={t('metric.count')} value={s.count} hint={t('metric.count.hint')} />
          <MetricItem label={t('metric.mean_close')} value={formatNumber(s.mean_close)} hint={t('metric.mean_close')} />
          <MetricItem label={t('metric.vol_mean')} value={formatNumber(s.vol_mean, { digits: 0 })} hint={t('metric.vol_mean')} />
          <MetricItem label={t('metric.return_pct')} value={formatNumber(s.return_pct, { pct: true })} tone={returnTone} hint={t('metric.return_pct.hint')} />
          <MetricItem label={t('metric.max_drawdown_pct')} value={formatNumber(s.max_drawdown_pct, { pct: true })} tone={ddTone} hint={t('metric.max_drawdown_pct.hint')} />
          <MetricItem label={t('metric.volatility_pct')} value={formatNumber(s.volatility_pct, { pct: true })} tone={volTone} hint={t('metric.volatility_pct.hint')} />
        </div>
      </div>
      {analysis && (
        <div className="p-4 border rounded bg-white shadow-sm">
          <h2 className="font-medium mb-2">{t('analysis.title')}</h2>
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{analysis.analysis}</p>
        </div>
      )}
    </div>
  )
}

export default StockResult
