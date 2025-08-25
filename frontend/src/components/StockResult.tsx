import React from 'react'
import { StockDailyResponse, AnalysisResponse } from '../api/api'

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
  if (loading) return <div className="text-sm text-gray-500">加载中...</div>
  if (!data) return <div className="text-sm text-gray-400">请输入股票代码查询。</div>

  const s = data.summary
  const returnTone = s.return_pct >= 0 ? 'pos' : 'neg'
  const ddTone = s.max_drawdown_pct <= -10 ? 'neg' : 'neutral'
  const volTone = s.volatility_pct > 5 ? 'neg' : 'neutral'

  return (
    <div className="space-y-4 mt-4">
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="font-medium text-base">基础统计摘要</h2>
          <span className="text-xs text-gray-400">区间: {data.start} ~ {data.end}</span>
        </div>
        <div className="grid gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          <MetricItem label="样本天数" value={s.count} hint="交易日数量" />
          <MetricItem label="均价" value={formatNumber(s.mean_close)} hint="收盘价均值" />
          <MetricItem label="均量" value={formatNumber(s.vol_mean, { digits: 0 })} hint="平均成交量" />
          <MetricItem label="区间收益" value={formatNumber(s.return_pct, { pct: true })} tone={returnTone} hint="最新价 / 起始价 - 1" />
          <MetricItem label="最大回撤" value={formatNumber(s.max_drawdown_pct, { pct: true })} tone={ddTone} hint="峰值至谷底最大跌幅" />
          <MetricItem label="波动率" value={formatNumber(s.volatility_pct, { pct: true })} tone={volTone} hint="日收益标准差" />
        </div>
      </div>
      {analysis && (
        <div className="p-4 border rounded bg-white shadow-sm">
          <h2 className="font-medium mb-2">模型分析</h2>
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{analysis.analysis}</p>
        </div>
      )}
    </div>
  )
}

export default StockResult
