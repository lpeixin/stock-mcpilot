/**
 * 财报日历与盈利预期。
 *
 * 历史 EPS 意外用「预期 / 实际 / 意外」三列，意外为正标红（超预期 = 利好）。
 */

import type { EarningsData, EstimateRow } from '../api/types'
import type { TranslateFn } from '../i18n'
import { signedPct, trendClass } from '../theme'
import { fmtAmount, fmtNum, periodLabel } from '../utils/format'
import { Badge, Card, EmptyState } from './ui'

interface Props {
  earnings: EarningsData | null
  currency?: string
  t: TranslateFn
  language: 'zh' | 'en'
}

function daysUntil(date: string): number | null {
  const target = new Date(`${date}T00:00:00`)
  if (Number.isNaN(target.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((target.getTime() - today.getTime()) / 86400000)
}

const EstimateTable: React.FC<{
  title: string
  rows: Record<string, EstimateRow>
  t: TranslateFn
  language: 'zh' | 'en'
  /** EPS 是每股数值，营收是金额 —— 两者格式完全不同，不能靠猜。 */
  kind: 'eps' | 'revenue'
  currency?: string
}> = ({ title, rows, t, language, kind, currency = '' }) => {
  const periods = Object.keys(rows ?? {})
  if (periods.length === 0) return null
  const render = (value: number | null | undefined) =>
    kind === 'eps' ? fmtNum(value, 2) : fmtAmount(value, currency)
  return (
    <div className="min-w-0">
      <div className="mb-1.5 text-[11px] font-medium text-slate-400">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="text-[11px] text-slate-400">
              <th className="py-1 pr-3 text-left font-normal">{t('earnings.period')}</th>
              <th className="px-2 py-1 text-right font-normal">{t('earnings.avg')}</th>
              <th className="px-2 py-1 text-right font-normal">{t('earnings.low')}</th>
              <th className="px-2 py-1 text-right font-normal">{t('earnings.high')}</th>
              <th className="px-2 py-1 text-right font-normal">{t('earnings.analysts')}</th>
              <th className="py-1 pl-3 text-right font-normal">{t('financials.yoy')}</th>
            </tr>
          </thead>
          <tbody>
            {periods.map((period) => {
              const row = rows[period] ?? {}
              return (
                <tr key={period} className="border-t border-slate-50">
                  <td className="py-1 pr-3 text-slate-600">{periodLabel(period, language)}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-800">
                    {render(row.avg)}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-500">
                    {render(row.low)}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-500">
                    {render(row.high)}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-slate-500">
                    {row.analysts ?? '—'}
                  </td>
                  <td className={`py-1 pl-3 text-right tabular-nums ${trendClass(row.growth)}`}>
                    {row.growth === null || row.growth === undefined
                      ? '—'
                      : signedPct(row.growth * 100)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const EarningsCard: React.FC<Props> = ({ earnings, currency = '', t, language }) => {
  if (!earnings) {
    return (
      <Card title={t('earnings.title')}>
        <EmptyState text={t('earnings.empty')} compact />
      </Card>
    )
  }

  const upcoming = earnings.next_earnings_date
  const days = upcoming ? daysUntil(upcoming) : null
  const history = (earnings.events ?? []).slice(0, 8)
  const revisions = earnings.eps_revisions ?? {}
  const revisionPeriods = Object.keys(revisions)

  const subtitle =
    upcoming && days !== null && days >= 0
      ? `${t('earnings.next')} ${upcoming} · ${days} ${t('earnings.daysUntil')}`
      : undefined

  const hasAnything =
    history.length > 0 ||
    Object.keys(earnings.eps_estimate ?? {}).length > 0 ||
    Object.keys(earnings.revenue_estimate ?? {}).length > 0

  return (
    <Card
      title={t('earnings.title')}
      subtitle={subtitle}
      actions={
        earnings.earnings_average !== null && earnings.earnings_average !== undefined ? (
          <Badge tone="info">
            EPS {t('earnings.avg')} {fmtNum(earnings.earnings_average, 2)}
          </Badge>
        ) : undefined
      }
    >
      {!hasAnything ? (
        <EmptyState text={t('earnings.empty')} compact />
      ) : (
        <div className="space-y-4">
          {history.length > 0 ? (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-slate-400">
                {t('earnings.history')}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="text-[11px] text-slate-400">
                      <th className="py-1 pr-3 text-left font-normal">{t('upcoming.date')}</th>
                      <th className="px-2 py-1 text-right font-normal">{t('earnings.est')}</th>
                      <th className="px-2 py-1 text-right font-normal">{t('earnings.act')}</th>
                      <th className="py-1 pl-3 text-right font-normal">
                        {t('earnings.surprise')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((event) => (
                      <tr key={event.date} className="border-t border-slate-50">
                        <td className="py-1 pr-3 tabular-nums text-slate-600">{event.date}</td>
                        <td className="px-2 py-1 text-right tabular-nums text-slate-500">
                          {fmtNum(event.eps_estimate, 2)}
                        </td>
                        <td className="px-2 py-1 text-right tabular-nums text-slate-800">
                          {fmtNum(event.eps_actual, 2)}
                        </td>
                        <td
                          className={`py-1 pl-3 text-right tabular-nums ${trendClass(event.surprise_pct)}`}
                        >
                          {signedPct(event.surprise_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
            <EstimateTable
              title={t('earnings.estimate')}
              rows={earnings.eps_estimate ?? {}}
              t={t}
              language={language}
              kind="eps"
            />
            <EstimateTable
              title={t('earnings.revenueEstimate')}
              rows={earnings.revenue_estimate ?? {}}
              t={t}
              language={language}
              kind="revenue"
              currency={currency}
            />
          </div>

          {revisionPeriods.length > 0 ? (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-slate-400">
                {t('earnings.revisions')}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="text-[11px] text-slate-400">
                      <th className="py-1 pr-3 text-left font-normal">{t('earnings.period')}</th>
                      <th className="px-2 py-1 text-right font-normal">{t('earnings.up')} 7D</th>
                      <th className="px-2 py-1 text-right font-normal">{t('earnings.down')} 7D</th>
                      <th className="px-2 py-1 text-right font-normal">{t('earnings.up')} 30D</th>
                      <th className="py-1 pl-3 text-right font-normal">
                        {t('earnings.down')} 30D
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {revisionPeriods.map((period) => {
                      const row = revisions[period] ?? {}
                      return (
                        <tr key={period} className="border-t border-slate-50">
                          <td className="py-1 pr-3 text-slate-600">
                            {periodLabel(period, language)}
                          </td>
                          <td className="px-2 py-1 text-right tabular-nums text-[#d93f4c]">
                            {row.up_7d ?? 0}
                          </td>
                          <td className="px-2 py-1 text-right tabular-nums text-[#1f9d63]">
                            {row.down_7d ?? 0}
                          </td>
                          <td className="px-2 py-1 text-right tabular-nums text-[#d93f4c]">
                            {row.up_30d ?? 0}
                          </td>
                          <td className="py-1 pl-3 text-right tabular-nums text-[#1f9d63]">
                            {row.down_30d ?? 0}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {earnings.revenue_average !== null && earnings.revenue_average !== undefined ? (
            <p className="text-[11px] text-slate-400">
              {t('earnings.revenueEstimate')} {t('earnings.avg')}：
              {fmtAmount(earnings.revenue_average, currency)}
            </p>
          ) : null}
        </div>
      )}
    </Card>
  )
}

export default EarningsCard
