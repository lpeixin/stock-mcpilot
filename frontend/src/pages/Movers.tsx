/**
 * 涨跌榜。
 *
 * 颜色走 `trendClass`（红涨绿跌）。改造前这里用的是绿涨红跌，对中文用户是反的。
 * 点击任意一行跳到个股页。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchMovers } from '../api'
import type { Market, MoverItem, MoversType } from '../api/types'
import { describeError } from '../api/client'
import { Card, EmptyState, ErrorBanner, Segmented, Spinner } from '../components/ui'
import { makeTranslator } from '../i18n'
import { useApp } from '../store/useApp'
import { signedPct, trendClass } from '../theme'
import { fmtAmount, fmtPrice, fmtVolume } from '../utils/format'

const MARKETS: Market[] = ['US', 'HK', 'CN']
const MARKET_KEY: Record<Market, string> = {
  US: 'market.US',
  HK: 'market.HK',
  CN: 'market.CN',
}
const COUNTS = [10, 20, 30, 50]

const Movers: React.FC = () => {
  const { language, openSymbol } = useApp()
  const t = useMemo(() => makeTranslator(language), [language])

  const [market, setMarket] = useState<Market>('US')
  const [type, setType] = useState<MoversType>('gainers')
  const [count, setCount] = useState(10)
  const [items, setItems] = useState<MoverItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchMovers(market, type, count)
      setItems(result.items)
    } catch (caught) {
      setItems([])
      setError(describeError(caught))
    } finally {
      setLoading(false)
    }
  }, [market, type, count])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-base font-semibold text-slate-900">{t('movers.title')}</h1>

        <Segmented<Market>
          value={market}
          onChange={setMarket}
          options={MARKETS.map((item) => ({ value: item, label: t(MARKET_KEY[item]) }))}
        />

        <Segmented<MoversType>
          value={type}
          onChange={setType}
          options={[
            { value: 'gainers', label: t('movers.gainers') },
            { value: 'losers', label: t('movers.losers') },
          ]}
        />

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-400">{t('movers.count')}</span>
          <Segmented<string>
            value={String(count)}
            onChange={(value) => setCount(Number(value))}
            options={COUNTS.map((item) => ({ value: String(item), label: String(item) }))}
          />
        </div>

        <span className="ml-auto text-[11px] text-slate-400">{t('movers.clickHint')}</span>
      </div>

      {error ? <ErrorBanner message={error} onRetry={() => void load()} retryText={t('common.retry')} /> : null}

      <Card flush>
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-12 text-xs text-slate-400">
            <Spinner className="h-3.5 w-3.5" />
            {t('common.loading')}
          </div>
        ) : items.length === 0 ? (
          <EmptyState text={t('movers.empty')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-100 text-[11px] text-slate-400">
                  <th className="px-3 py-2 text-left font-normal">#</th>
                  <th className="px-3 py-2 text-left font-normal">{t('table.symbol')}</th>
                  <th className="px-3 py-2 text-left font-normal">{t('table.name')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.price')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.change')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.changePct')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.volume')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.marketCap')}</th>
                  <th className="px-3 py-2 text-right font-normal">{t('table.exchange')}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => {
                  const cls = trendClass(item.change_pct)
                  return (
                    <tr
                      key={`${item.symbol}-${index}`}
                      onClick={() => openSymbol(item.symbol, item.market as Market)}
                      className="cursor-pointer border-b border-slate-50 transition last:border-0 hover:bg-slate-50"
                    >
                      <td className="px-3 py-2 tabular-nums text-slate-300">{index + 1}</td>
                      <td className="px-3 py-2 font-medium text-slate-800">{item.symbol}</td>
                      <td className="max-w-[220px] truncate px-3 py-2 text-slate-500">
                        {item.name_zh || item.name || '—'}
                      </td>
                      <td className={`px-3 py-2 text-right tabular-nums ${cls}`}>
                        {fmtPrice(item.price)}
                      </td>
                      <td className={`px-3 py-2 text-right tabular-nums ${cls}`}>
                        {item.change === null || item.change === undefined
                          ? '—'
                          : `${item.change > 0 ? '+' : ''}${item.change.toFixed(2)}`}
                      </td>
                      <td className={`px-3 py-2 text-right tabular-nums ${cls}`}>
                        {signedPct(item.change_pct)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        {fmtVolume(item.volume)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                        {fmtAmount(item.market_cap, item.currency ?? '')}
                      </td>
                      <td className="px-3 py-2 text-right text-slate-400">{item.exchange ?? '—'}</td>
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

export default Movers
