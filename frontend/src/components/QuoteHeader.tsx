/**
 * 报价头部：价格、涨跌、日内与区间指标。
 *
 * 涨跌颜色一律走 `theme.trendClass`（红涨绿跌），不在这里自己判断。
 */

import type { MarketSession, Quote } from '../api/types'
import type { TranslateFn } from '../i18n'
import { signedPct, trendClass } from '../theme'
import { clamp, fmtAmount, fmtPrice, fmtVolume } from '../utils/format'
import { Badge } from './ui'

const SESSION_KEY: Record<MarketSession['status'], string> = {
  pre: 'session.pre',
  open: 'session.open',
  lunch: 'session.lunch',
  closed: 'session.closed',
}

const SESSION_TONE: Record<MarketSession['status'], 'up' | 'info' | 'neutral' | 'warn'> = {
  pre: 'warn',
  open: 'up',
  lunch: 'info',
  closed: 'neutral',
}

interface Props {
  quote: Quote | null
  session?: MarketSession | null
  symbol: string
  t: TranslateFn
}

const QuoteHeader: React.FC<Props> = ({ quote, session, symbol, t }) => {
  const changeClass = trendClass(quote?.change_pct ?? quote?.change)
  const displayName = quote?.name_zh || quote?.long_name || quote?.name || ''
  const currency = quote?.currency ?? ''

  const items: { label: string; value: string; valueClass?: string }[] = [
    { label: t('quote.open'), value: fmtPrice(quote?.open) },
    { label: t('quote.high'), value: fmtPrice(quote?.day_high) },
    { label: t('quote.low'), value: fmtPrice(quote?.day_low) },
    { label: t('quote.prevClose'), value: fmtPrice(quote?.previous_close) },
    { label: t('quote.volume'), value: fmtVolume(quote?.volume) },
    { label: t('quote.avgVolume'), value: fmtVolume(quote?.avg_volume) },
    { label: t('quote.marketCap'), value: fmtAmount(quote?.market_cap, currency) },
    { label: t('quote.ma50'), value: fmtPrice(quote?.ma50) },
    { label: t('quote.ma200'), value: fmtPrice(quote?.ma200) },
  ]

  const low = quote?.week52_low ?? null
  const high = quote?.week52_high ?? null
  const price = quote?.price ?? null
  const position =
    low !== null && high !== null && price !== null && high > low
      ? clamp(((price - low) / (high - low)) * 100, 0, 100)
      : null

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold tracking-tight text-slate-900">{symbol}</h1>
            {displayName ? (
              <span className="truncate text-sm text-slate-500">{displayName}</span>
            ) : null}
            {quote?.exchange ? (
              <span className="text-[11px] text-slate-400">{quote.exchange}</span>
            ) : null}
            {session ? (
              <Badge tone={SESSION_TONE[session.status]}>{t(SESSION_KEY[session.status])}</Badge>
            ) : null}
          </div>

          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={`text-3xl font-semibold tabular-nums ${changeClass}`}>
              {fmtPrice(price)}
            </span>
            <span className={`text-sm tabular-nums ${changeClass}`}>
              {quote?.change !== null && quote?.change !== undefined
                ? `${quote.change > 0 ? '+' : ''}${quote.change.toFixed(2)}`
                : '—'}
            </span>
            <span className={`text-sm tabular-nums ${changeClass}`}>
              {signedPct(quote?.change_pct)}
            </span>
            {currency ? <span className="text-[11px] text-slate-400">{currency}</span> : null}
          </div>

          {quote?.quote_type ? (
            <p className="mt-1 text-[11px] uppercase tracking-wide text-slate-300">
              {quote.quote_type}
            </p>
          ) : null}
        </div>

        {position !== null ? (
          <div className="w-full max-w-[220px] shrink-0">
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span>{t('quote.week52')}</span>
              <span className="tabular-nums">{position.toFixed(0)}%</span>
            </div>
            <div className="relative mt-1.5 h-1.5 rounded-full bg-slate-100">
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[#1f9d63] via-slate-300 to-[#d93f4c]"
                style={{ width: '100%' }}
              />
              <span
                className="absolute top-1/2 h-3 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-slate-800"
                style={{ left: `${position}%` }}
              />
            </div>
            <div className="mt-1 flex items-center justify-between text-[11px] tabular-nums text-slate-400">
              <span>{fmtPrice(low)}</span>
              <span>{fmtPrice(high)}</span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-3.5 grid grid-cols-3 gap-x-4 gap-y-2.5 border-t border-slate-100 pt-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-9">
        {items.map((item) => (
          <div key={item.label} className="min-w-0">
            <div className="truncate text-[11px] text-slate-400">{item.label}</div>
            <div
              className={`mt-0.5 truncate text-xs tabular-nums ${
                item.valueClass ?? 'text-slate-800'
              }`}
            >
              {item.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default QuoteHeader
