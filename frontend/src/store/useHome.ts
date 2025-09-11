import { create } from 'zustand'
import { analyze, fetchStock, StockDailyResponse, AnalysisResponse, fetchEarnings, EarningsResponse } from '../api/api'

interface HomeState {
  symbol: string
  market: 'US' | 'HK' | 'CN'
  question: string
  data?: StockDailyResponse
  analysis?: AnalysisResponse
  earnings?: EarningsResponse
  loading: boolean
  setSymbol: (s: string) => void
  setMarket: (m: 'US' | 'HK' | 'CN') => void
  setQuestion: (q: string) => void
  clearAnalysis: () => void
  search: () => Promise<void>
  runAnalysis: (language?: string) => Promise<void>
}

export const useHome = create<HomeState>((set, get) => ({
  symbol: 'AAPL',
  market: 'US',
  question: '',
  data: undefined,
  analysis: undefined,
  earnings: undefined,
  loading: false,
  setSymbol: (s) => set({ symbol: s }),
  setMarket: (m) => set({ market: m }),
  setQuestion: (q) => set({ question: q }),
  clearAnalysis: () => set({ analysis: undefined }),
  search: async () => {
    const { symbol, market } = get()
    if (!symbol.trim()) return
    set({ loading: true, analysis: undefined })
    try {
      const [d, e] = await Promise.all([
        fetchStock(symbol.trim().toUpperCase(), market),
        fetchEarnings(symbol.trim().toUpperCase(), market).catch(()=>undefined)
      ])
      set({ data: d, earnings: e })
    } catch (e) {
      // swallow; UI can decide to show message later
    } finally { set({ loading: false }) }
  },
  runAnalysis: async (language?: string) => {
    const { data, question } = get()
    if (!data) return
    set({ loading: true })
    try {
      const a = await analyze(data.symbol, data.market, question || undefined, language)
      set({ analysis: a })
    } finally { set({ loading: false }) }
  }
}))
