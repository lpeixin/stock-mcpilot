/**
 * 分析师观点：目标价区间 + 评级分布 + 持股结构。
 *
 * 目标价区间条上会标出现价，让"上行空间"是看出来的而不是只读一个百分比。
 */

import type { AnalystData, RecommendationRow } from '../api/types'
import type { TranslateFn } from '../i18n'
import { DOWN, UP } from '../theme'
import { clamp, fmtNum, fmtPrice } from '../utils/format'
import { Badge, Card, EmptyState, Stat } from './ui'

interface Props {
  analyst: AnalystData | null
  price?: number | null
  t: TranslateFn
}

const RATING_KEYS: { key: keyof RecommendationRow; labelKey: string; color: string }[] = [
  { key: 'strong_buy', labelKey: 'analyst.strongBuy', color: '#b91c1c' },
  { key: 'buy', labelKey: 'analyst.buy', color: '#d93f4c' },
  { key: 'hold', labelKey: 'analyst.hold', color: '#94a3b8' },
  { key: 'sell', labelKey: 'analyst.sell', color: '#4ade80' },
  { key: 'strong_sell', labelKey: 'analyst.strongSell', color: '#1f9d63' },
]

function holderLabel(key: string, t: TranslateFn): string {
  const lower = key.toLowerCase()
  if (lower.includes('institution') && lower.includes('float')) return t('profile.institutionsFloat')
  if (lower.includes('institution') && lower.includes('count')) return t('profile.institutionsCount')
  if (lower.includes('institution')) return t('profile.institutions')
  if (lower.includes('insider') && lower.includes('count')) return t('profile.insidersCount')
  if (lower.includes('insider')) return t('profile.insiders')
  return key
}

function holderValue(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value > 0 && value <= 1.0001) return `${(value * 100).toFixed(2)}%`
  return fmtNum(value, 0)
}

const AnalystCard: React.FC<Props> = ({ analyst, price, t }) => {
  if (!analyst) {
    return (
      <Card title={t('analyst.title')}>
        <EmptyState text={t('analyst.empty')} compact />
      </Card>
    )
  }

  const current = price ?? analyst.target_current ?? null
  const mean = analyst.target_mean ?? null
  const upside =
    current !== null && current > 0 && mean !== null ? ((mean - current) / current) * 100 : null

  const low = analyst.target_low ?? null
  const high = analyst.target_high ?? null
  const span = low !== null && high !== null && high > low ? high - low : null
  const position =
    span !== null && current !== null ? clamp(((current - low!) / span) * 100, 0, 100) : null
  const meanPosition = span !== null && mean !== null ? clamp(((mean - low!) / span) * 100, 0, 100) : null

  const latest = (analyst.recommendations ?? [])[0]
  const total = latest
    ? RATING_KEYS.reduce((sum, entry) => sum + (Number(latest[entry.key]) || 0), 0)
    : 0

  const holderEntries = Object.entries(analyst.holders ?? {})

  const ratingTone = (key: string | null | undefined): 'up' | 'down' | 'neutral' => {
    if (!key) return 'neutral'
    if (key.includes('buy')) return 'up'
    if (key.includes('sell') || key.includes('underperform')) return 'down'
    return 'neutral'
  }

  return (
    <Card
      title={t('analyst.title')}
      actions={
        analyst.recommendation_key ? (
          <Badge tone={ratingTone(analyst.recommendation_key)}>
            {t(`analyst.rating.${analyst.recommendation_key}`)}
          </Badge>
        ) : undefined
      }
    >
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <Stat
          label={t('analyst.target')}
          value={fmtPrice(mean)}
          hint={
            upside === null
              ? undefined
              : `${t('analyst.upside')} ${upside > 0 ? '+' : ''}${upside.toFixed(1)}%`
          }
          valueClass={upside === null ? 'text-slate-900' : upside > 0 ? 'text-[#d93f4c]' : 'text-[#1f9d63]'}
        />
        <Stat label={t('analyst.median')} value={fmtPrice(analyst.target_median)} />
        <Stat label={t('earnings.low')} value={fmtPrice(low)} />
        <Stat label={t('earnings.high')} value={fmtPrice(high)} />
      </div>

      {position !== null && meanPosition !== null ? (
        <div className="mt-4">
          <div className="relative h-1.5 rounded-full bg-slate-100">
            <div
              className="absolute inset-y-0 left-0 rounded-full"
              style={{
                width: `${meanPosition}%`,
                background: `linear-gradient(90deg, ${DOWN}55, ${UP}55)`,
              }}
            />
            <span
              className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-sm bg-slate-800"
              style={{ left: `${position}%` }}
              title={`${t('table.price')} ${fmtPrice(current)}`}
            />
            <span
              className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-[#d93f4c] shadow"
              style={{ left: `${meanPosition}%` }}
              title={`${t('analyst.mean')} ${fmtPrice(mean)}`}
            />
          </div>
          <div className="mt-1.5 flex items-center justify-between text-[11px] tabular-nums text-slate-400">
            <span>{fmtPrice(low)}</span>
            <span>
              {t('table.price')} {fmtPrice(current)}
            </span>
            <span>{fmtPrice(high)}</span>
          </div>
        </div>
      ) : null}

      {latest && total > 0 ? (
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-medium text-slate-400">
              {t('analyst.distribution')}
            </span>
            <span className="text-[11px] text-slate-400">
              {latest.period ? `(${latest.period})` : ''}
            </span>
          </div>
          <div className="flex h-2 overflow-hidden rounded-full bg-slate-100">
            {RATING_KEYS.map((entry) => {
              const count = Number(latest[entry.key]) || 0
              if (count === 0) return null
              return (
                <div
                  key={entry.key}
                  style={{ width: `${(count / total) * 100}%`, background: entry.color }}
                  title={`${t(entry.labelKey)} ${count}`}
                />
              )
            })}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {RATING_KEYS.map((entry) => {
              const count = Number(latest[entry.key]) || 0
              return (
                <span key={entry.key} className="flex items-center gap-1.5 text-[11px] text-slate-500">
                  <span
                    className="h-2 w-2 rounded-sm"
                    style={{ background: entry.color }}
                  />
                  {t(entry.labelKey)}
                  <span className="tabular-nums text-slate-800">{count}</span>
                </span>
              )
            })}
          </div>
        </div>
      ) : null}

      {holderEntries.length > 0 ? (
        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-slate-100 pt-3 sm:grid-cols-3">
          {holderEntries.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <div className="truncate text-[11px] text-slate-400">{holderLabel(key, t)}</div>
              <div className="mt-0.5 text-xs tabular-nums text-slate-800">
                {holderValue(value)}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {analyst.analyst_count ? (
        <p className="mt-3 text-[11px] text-slate-400">
          {t('earnings.analysts')}: {analyst.analyst_count}
        </p>
      ) : null}
    </Card>
  )
}

export default AnalystCard
