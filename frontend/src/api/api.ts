import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const client = axios.create({ baseURL: API_BASE, timeout: 15000 })

client.interceptors.response.use(r=>r, e=>{
  // 简单错误包装
  const msg = e?.response?.data?.detail || e.message || '请求失败'
  return Promise.reject(new Error(msg))
})

export interface StockRow { date: string; open: number; high: number; low: number; close: number; volume: number }
export interface StockSummary { count: number; mean_close: number; vol_mean: number; return_pct: number; max_drawdown_pct: number; volatility_pct: number }
export interface StockDailyResponse { symbol: string; market: string; start: string; end: string; rows: StockRow[]; summary: StockSummary; company_name_en?: string | null; company_name_zh?: string | null }

export async function fetchStock(symbol: string, market: string, days = 60) {
  const { data } = await client.get<StockDailyResponse>(`/stocks/${symbol}`, { params: { market, days } })
  return data
}

export interface AnalysisResponse { symbol: string; market: string; summary: StockSummary; analysis: string }

export async function analyze(symbol: string, market: string, question?: string, language?: string) {
  const { data } = await client.post<AnalysisResponse>('/analysis', { symbol, market, question, language })
  return data
}

export interface SettingsState { mode: 'local' | 'cloud'; api_key?: string; local_model?: string; language?: 'en' | 'zh' }

export async function getSettings() {
  const { data } = await client.get<SettingsState>('/settings')
  return data
}
export async function updateSettings(payload: Partial<SettingsState>) {
  const { data } = await client.post<SettingsState>('/settings', payload)
  return data
}

export interface EarningsEvent { date: string; eps_actual?: number | null; eps_estimate?: number | null; eps_surprise?: number | null; surprise_percent?: number | null }
export interface AnalystEstimates { next_quarter_eps_avg?: number | null; next_quarter_analysts?: number | null; next_year_eps_avg?: number | null; revenue_next_quarter_avg?: number | null; updated_at?: string | null }
export interface EarningsResponse { symbol: string; market: string; next_earnings_date?: string | null; events: EarningsEvent[]; analyst?: AnalystEstimates | null }

export async function fetchEarnings(symbol: string, market: string){
  const { data } = await client.get<EarningsResponse>(`/stocks/${symbol}/earnings`, { params: { market } })
  return data
}
