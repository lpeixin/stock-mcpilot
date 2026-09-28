/** 个股页面状态：行情数据 + AI 分析。 */

import { create } from 'zustand'
import {
  analyzeOnce,
  fetchAnalyst,
  fetchCandles,
  fetchEarnings,
  fetchFinancials,
  fetchNews,
  fetchProfile,
  fetchStockDetail,
} from '../api'
import { describeError, streamSSE } from '../api/client'
import type {
  AnalysisFocus,
  AnalystData,
  Candle,
  CandleInterval,
  CandlePeriod,
  CompanyProfile,
  ContextMeta,
  EarningsData,
  Financials,
  Market,
  NewsItem,
  StockDetail,
} from '../api/types'

export type SubIndicator = 'none' | 'macd' | 'rsi' | 'kdj'

interface StockState {
  symbol: string
  market: Market
  period: CandlePeriod
  interval: CandleInterval
  subIndicator: SubIndicator

  detail: StockDetail | null
  candles: Candle[]
  profile: CompanyProfile | null
  financials: Financials | null
  earnings: EarningsData | null
  analyst: AnalystData | null
  news: NewsItem[]

  loading: boolean
  loadingSecondary: boolean
  reloadingCandles: boolean
  error: string | null

  question: string
  focus: AnalysisFocus[]
  useContext: boolean
  analyzing: boolean
  analysisText: string
  analysisMeta: ContextMeta | null
  analysisModel: string | null
  analysisProvider: string | null
  analysisElapsed: number | null
  analysisError: string | null

  setSymbol: (symbol: string) => void
  setMarket: (market: Market) => void
  setPeriod: (period: CandlePeriod) => void
  setInterval: (interval: CandleInterval) => void
  setSubIndicator: (indicator: SubIndicator) => void
  setQuestion: (question: string) => void
  toggleFocus: (focus: AnalysisFocus) => void
  setUseContext: (value: boolean) => void

  load: () => Promise<void>
  loadSecondary: () => Promise<void>
  reloadCandles: () => Promise<void>
  runAnalysis: (language: 'zh' | 'en') => Promise<void>
  stopAnalysis: () => void
  clearAnalysis: () => void
}

/** 用于丢弃过期响应：快速切换标的时，旧请求可能后到。 */
let requestToken = 0
let analysisController: AbortController | null = null

export const useStock = create<StockState>((set, get) => ({
  symbol: 'AAPL',
  market: 'US',
  period: '6mo',
  interval: '1d',
  subIndicator: 'macd',

  detail: null,
  candles: [],
  profile: null,
  financials: null,
  earnings: null,
  analyst: null,
  news: [],

  loading: false,
  loadingSecondary: false,
  reloadingCandles: false,
  error: null,

  question: '',
  focus: [],
  useContext: true,
  analyzing: false,
  analysisText: '',
  analysisMeta: null,
  analysisModel: null,
  analysisProvider: null,
  analysisElapsed: null,
  analysisError: null,

  setSymbol: (symbol) => set({ symbol }),
  setMarket: (market) => set({ market }),
  setPeriod: (period) => set({ period }),
  setInterval: (interval) => set({ interval }),
  setSubIndicator: (subIndicator) => set({ subIndicator }),
  setQuestion: (question) => set({ question }),
  toggleFocus: (focus) =>
    set((state) => ({
      focus: state.focus.includes(focus)
        ? state.focus.filter((item) => item !== focus)
        : [...state.focus, focus],
    })),
  setUseContext: (useContext) => set({ useContext }),

  load: async () => {
    const { symbol, market, period, interval } = get()
    const code = symbol.trim().toUpperCase()
    if (!code) {
      set({ error: '请输入股票代码' })
      return
    }

    const token = ++requestToken
    set({
      loading: true,
      error: null,
      // 清空上一只股票的数据，避免新旧混排造成误读
      detail: null,
      candles: [],
      profile: null,
      financials: null,
      earnings: null,
      analyst: null,
      news: [],
      analysisText: '',
      analysisMeta: null,
      analysisError: null,
    })

    try {
      const detail = await fetchStockDetail(code, market, { period, interval })
      if (token !== requestToken) return
      set({ detail, candles: detail.candles, loading: false })
    } catch (error) {
      if (token !== requestToken) return
      set({ loading: false, error: describeError(error) })
      return
    }

    void get().loadSecondary()
  },

  loadSecondary: async () => {
    const { symbol, market } = get()
    const code = symbol.trim().toUpperCase()
    const token = requestToken
    set({ loadingSecondary: true })

    const results = await Promise.allSettled([
      fetchProfile(code, market),
      fetchFinancials(code, market),
      fetchEarnings(code, market),
      fetchAnalyst(code, market),
      fetchNews(code, market, 12),
    ])
    if (token !== requestToken) return

    const [profile, financials, earnings, analyst, news] = results
    set({
      loadingSecondary: false,
      profile: profile.status === 'fulfilled' ? profile.value : null,
      financials: financials.status === 'fulfilled' ? financials.value : null,
      earnings: earnings.status === 'fulfilled' ? earnings.value : null,
      analyst: analyst.status === 'fulfilled' ? analyst.value : null,
      news: news.status === 'fulfilled' ? news.value.items : [],
    })
  },

  reloadCandles: async () => {
    const { symbol, market, period, interval } = get()
    const code = symbol.trim().toUpperCase()
    const token = requestToken
    set({ reloadingCandles: true })
    try {
      const response = await fetchCandles(code, market, period, interval)
      if (token !== requestToken) return
      set({ candles: response.candles, reloadingCandles: false })
    } catch (error) {
      if (token !== requestToken) return
      set({ reloadingCandles: false, error: describeError(error) })
    }
  },

  runAnalysis: async (language) => {
    const { symbol, market, question, focus, useContext, detail } = get()
    const code = symbol.trim().toUpperCase()
    if (!code || get().analyzing) return

    analysisController?.abort()
    analysisController = new AbortController()

    set({
      analyzing: true,
      analysisText: '',
      analysisError: null,
      analysisMeta: null,
      analysisElapsed: null,
      analysisModel: null,
      analysisProvider: null,
    })

    const payload = {
      symbol: code,
      market,
      question: question.trim() || undefined,
      focus: focus.length ? focus : undefined,
      use_context: useContext,
      language,
      days: detail?.summary?.count && detail.summary.count > 0 ? 180 : 180,
    }

    try {
      await streamSSE(
        '/analysis/stream',
        payload,
        (event) => {
          if (event.type === 'meta') {
            set({
              analysisMeta: event.context_meta ?? null,
              analysisModel: event.model ?? null,
              analysisProvider: event.provider ?? null,
            })
          } else if (event.type === 'delta') {
            set((state) => ({ analysisText: state.analysisText + event.text }))
          } else if (event.type === 'error') {
            set({ analysisError: event.message })
          } else if (event.type === 'done') {
            set({ analysisElapsed: event.elapsed_ms })
          }
        },
        analysisController.signal,
      )
    } catch (error) {
      set({ analysisError: describeError(error) })
    } finally {
      set({ analyzing: false })
      analysisController = null
    }
  },

  stopAnalysis: () => {
    analysisController?.abort()
    analysisController = null
    set({ analyzing: false })
  },

  clearAnalysis: () =>
    set({
      analysisText: '',
      analysisMeta: null,
      analysisError: null,
      analysisElapsed: null,
      analysisModel: null,
      analysisProvider: null,
    }),
}))

/** 非流式分析（备用，设置页的"试用"也可复用）。 */
export async function runAnalysisOnce(symbol: string, market: Market, question?: string) {
  return analyzeOnce({ symbol, market, question })
}
