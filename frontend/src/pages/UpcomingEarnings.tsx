/**
 * 财报日历：未来若干天内将要披露财报的标的。
 *
 * 覆盖范围是各市场的权重股标的池（后端注释里已说明），不是全市场 ——
 * 这一点必须在界面上讲清楚，否则用户会以为"没有就是没有"。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchUpcomingEarnings } from '../api'
import type { Market, UpcomingEarningsItem } from '../api/types'
import { describeError } from '../api/client'
import { Badge, Card, EmptyState, ErrorBanner, Segmented, Spinner } from '../components/ui'
import { makeTranslator } from '../i18n'
import { useApp } from '../store/useApp'
import { fmtAmount, fmtNum } from '../utils/format'

const MARKETS: Market[] = ['US', 'HK', 'CN']
const MARKET_KEY: Record<Market, string> = {
  US: 'market.US',
  HK: 'market.HK',
  CN: 'market.CN',
}
const WINDOWS = [7, 14, 30, 60, 90]

const UpcomingEarnings: React.FC = () => {
  const { language, openSymbol } = useApp()
  const t = useMemo(() => makeTranslator(language), [language])

  const [market, setMarket] = useState<Market>('US')
  // 默认 30 天：财报季之间的窗口里 14 天经常一条都没有，用户会误以为功能坏了
  const [days, setDays] = useState(30)
  const [items, setItems] = useState<UpcomingEarningsItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchUpcomingEarnings(market, days, 100)
      setItems(result.items)
    } catch (caught) {
      setItems([])
      setError(describeError(caught))
    } finally {
      setLoading(false)
    }
  }, [market, days])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-base font-semibold text-slate-900">{t('upcoming.title')}</h1>

        <Segmented<Market>
          value={market}
          onChange={setMarket}
          options={MARKETS.map((item) => ({ value: item, label: t(MARKET_KEY[item]) }))}
        />

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-400">{t('upcoming.days')}</span>
          <Segmented<string>
            value={String(days)}
            onChange={(value) => setDays(Number(value))}
            options={WINDOWS.map((item) => ({ value: String(item), label: String(item) }))}
          />
        </div>

        <span className="ml-auto text-[11px] text-slate-400">{t('upcoming.note')}</span>
      </div>

      {error ? (
        <ErrorBanner message={error} onRetry={() => void load()} retryText={t('common.retry')} />
      ) : null}

      <Card flush>
        {loading ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-xs text-slate-400">
            <span className="flex items-center gap-2">
              <Spinner className="h-3.5 w-3.5" />
              {t('common.loading')}
            </span>
            <span className="text-[11px] text-slate-300">{t('upcoming.firstLoad')}</span>
          </div>
        ) : items.length === 0 ? (
          <EmptyState text={t('upcoming.empty')} hint={t('upcoming.note')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-100 text-[11px] text-slate-400">
                  <th className="px-3 py-2 text-left font-normal">{t('table.symbol')}</th>
                  <th className="px-3 py-2 text-left font-normal">{t('table.name')}</th>
                  <th className="px-3 py-2 text-left font-normal">{t('upcoming.date')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('upcoming.daysUntil')}</th>
                  <th className="px-3 py-2 text-right font-normal">EPS</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.marketCap')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => {
                  const remaining = item.days_until
                  const tone =
                    remaining === null || remaining === undefined
                      ? 'neutral'
                      : remaining <= 3
                        ? 'up'
                        : remaining <= 7
                          ? 'warn'
                          : 'neutral'
                  return (
                    <tr
                      key={`${item.symbol}-${index}`}
                      onClick={() => openSymbol(item.symbol, market)}
                      className="cursor-pointer border-b border-slate-50 transition last:border-0 hover:bg-slate-50"
                    >
                      <td className="px-3 py-2 font-medium text-slate-800">{item.symbol}</td>
                      <td className="max-w-[240px] truncate px-3 py-2 text-slate-500">
                        {item.name || '—'}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-slate-600">
                        {item.earnings_date}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {remaining === null || remaining === undefined ? (
                          '—'
                        ) : (
                          <Badge tone={tone}>
                            {remaining} {t('earnings.daysUntil')}
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-600">
                        {fmtNum(item.eps_estimate, 2)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        {fmtAmount(item.market_cap, item.currency ?? '')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

export default UpcomingEarnings
