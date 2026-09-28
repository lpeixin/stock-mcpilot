/**
 * 个股页。
 *
 * 数据流：SearchBar → `useStock.load()`（详情 + K 线）→ `loadSecondary()` 并发拉
 * 概况/财报/盈利/分析师/新闻。所有下游组件都从这里取数据，自己不请求。
 *
 * 从涨跌榜或财报日历跳转过来时，`useApp.pendingSymbol` 里带着标的，
 * 挂载时消费掉并立即加载。
 */

import { useEffect, useMemo } from 'react'
import type { CandleInterval, CandlePeriod, Market } from '../api/types'
import CandlestickChart from '../charts/CandlestickChart'
import AnalysisPanel from '../components/AnalysisPanel'
import AnalystCard from '../components/AnalystCard'
import EarningsCard from '../components/EarningsCard'
import FinancialsCard from '../components/FinancialsCard'
import IndicatorsPanel from '../components/IndicatorsPanel'
import MetricsPanel from '../components/MetricsPanel'
import NewsList from '../components/NewsList'
import ProfileCard from '../components/ProfileCard'
import QuoteHeader from '../components/QuoteHeader'
import SearchBar from '../components/SearchBar'
import { Card, ErrorBanner, Skeleton } from '../components/ui'
import { makeTranslator } from '../i18n'
import { useApp } from '../store/useApp'
import { useStock } from '../store/useStock'

/**
 * 切换周期时顺手把区间调到能看出趋势的长度。
 * 只放大不缩小 —— 用户手动选的范围不该被系统悄悄改小。
 */
function smartPeriod(period: CandlePeriod, interval: CandleInterval): CandlePeriod {
  if (interval === '1wk' && ['1mo', '3mo', '6mo'].includes(period)) return '2y'
  if (interval === '1mo' && ['1mo', '3mo', '6mo', '1y', '2y'].includes(period)) return '5y'
  return period
}

const Home: React.FC = () => {
  const { language, consumePendingSymbol } = useApp()
  const t = useMemo(() => makeTranslator(language), [language])

  const symbol = useStock((state) => state.symbol)
  const market = useStock((state) => state.market)
  const period = useStock((state) => state.period)
  const interval = useStock((state) => state.interval)
  const subIndicator = useStock((state) => state.subIndicator)
  const detail = useStock((state) => state.detail)
  const candles = useStock((state) => state.candles)
  const profile = useStock((state) => state.profile)
  const financials = useStock((state) => state.financials)
  const earnings = useStock((state) => state.earnings)
  const analyst = useStock((state) => state.analyst)
  const news = useStock((state) => state.news)
  const loading = useStock((state) => state.loading)
  const loadingSecondary = useStock((state) => state.loadingSecondary)
  const reloadingCandles = useStock((state) => state.reloadingCandles)
  const error = useStock((state) => state.error)

  // 首次挂载：优先消费从其它页面带过来的标的
  useEffect(() => {
    const pending = consumePendingSymbol()
    if (pending) {
      useStock.setState({ symbol: pending.symbol, market: pending.market })
      void useStock.getState().load()
      return
    }
    if (!useStock.getState().detail) void useStock.getState().load()
  }, [consumePendingSymbol])

  const submit = (next: string, nextMarket: Market) => {
    useStock.setState({ symbol: next, market: nextMarket })
    void useStock.getState().load()
  }

  const handleMarketChange = (next: Market) => {
    // 只改选择，不立即查询 —— 用户可能还要改代码
    useStock.setState({ market: next })
  }

  const handlePeriod = (next: CandlePeriod) => {
    if (next === period) return
    useStock.setState({ period: next })
    void useStock.getState().reloadCandles()
  }

  const handleInterval = (next: CandleInterval) => {
    if (next === interval) return
    useStock.setState({ interval: next, period: smartPeriod(period, next) })
    void useStock.getState().reloadCandles()
  }

  const currency = detail?.quote?.currency ?? ''

  return (
    <div className="space-y-4">
      <SearchBar
        value={symbol}
        market={market}
        loading={loading}
        t={t}
        onValueChange={(value) => useStock.setState({ symbol: value })}
        onMarketChange={handleMarketChange}
        onSubmit={submit}
      />

      {error ? (
        <ErrorBanner
          message={error}
          onRetry={() => void useStock.getState().load()}
          retryText={t('common.retry')}
        />
      ) : null}

      {loading && !detail ? (
        <div className="space-y-4">
          <Card>
            <Skeleton className="h-6 w-40" />
            <div className="mt-3 grid grid-cols-4 gap-3">
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-8" />
              ))}
            </div>
          </Card>
          <Card>
            <Skeleton className="h-[300px]" />
          </Card>
        </div>
      ) : null}

      {!loading && !detail && !error ? (
        <Card>
          <p className="py-10 text-center text-xs text-slate-400">{t('search.empty')}</p>
        </Card>
      ) : null}

      {detail ? (
        <>
          <QuoteHeader
            quote={detail.quote ?? null}
            session={detail.session ?? null}
            symbol={detail.symbol}
            t={t}
          />

          <CandlestickChart
            candles={candles}
            period={period}
            interval={interval}
            subIndicator={subIndicator}
            loading={reloadingCandles}
            symbol={detail.symbol}
            t={t}
            onPeriodChange={handlePeriod}
            onIntervalChange={handleInterval}
            onSubChange={(value) => useStock.setState({ subIndicator: value })}
          />

          <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              <IndicatorsPanel indicators={detail.indicators ?? null} t={t} />
              <MetricsPanel summary={detail.summary ?? null} t={t} />
              <FinancialsCard
                financials={financials}
                currency={currency}
                t={t}
              />
              <ProfileCard profile={profile} currency={currency} t={t} />
            </div>

            <div className="space-y-4">
              <div className="xl:sticky xl:top-4">
                <AnalysisPanel t={t} language={language} />
              </div>
              <AnalystCard analyst={analyst} price={detail.quote?.price ?? null} t={t} />
              <EarningsCard earnings={earnings} currency={currency} t={t} language={language} />
              <NewsList items={news} loading={loadingSecondary} t={t} />
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

export default Home
