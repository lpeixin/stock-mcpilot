/** 后端接口封装。所有函数在失败时抛出带中文说明的 Error。 */

import { http } from './client'
import type {
  AnalysisConfig,
  AnalysisRequest,
  AnalysisResponse,
  AnalystData,
  AppConfig,
  CandlesResponse,
  CompanyProfile,
  ContextPreview,
  EarningsData,
  Financials,
  LLMConfig,
  Market,
  ModelListResult,
  MoversResponse,
  MoversType,
  NewsResponse,
  Quote,
  SearchResponse,
  StockDetail,
  TestResult,
  UpcomingEarningsResponse,
} from './types'

// ---------------- 配置 ----------------

export async function fetchConfig(): Promise<AppConfig> {
  const { data } = await http.get<AppConfig>('/config')
  return data
}

export async function updateConfig(patch: {
  llm?: Partial<LLMConfig>
  analysis?: Partial<AnalysisConfig>
  ui?: Record<string, unknown>
}): Promise<AppConfig> {
  const { data } = await http.post<AppConfig>('/config', patch)
  return data
}

export async function fetchPresets(): Promise<AppConfig['presets']> {
  const { data } = await http.get<{ presets: AppConfig['presets'] }>('/llm/presets')
  return data.presets
}

/** 探测模型列表。可带上尚未保存的配置做试连。 */
export async function fetchModels(override?: Partial<LLMConfig>): Promise<ModelListResult> {
  const { data } = await http.post<ModelListResult>('/llm/models', override ?? {}, { timeout: 30000 })
  return data
}

export async function testConnection(override?: Partial<LLMConfig>, deep = true): Promise<TestResult> {
  const { data } = await http.post<TestResult>(
    '/llm/test',
    override ?? {},
    { params: { deep }, timeout: 180000 },
  )
  return data
}

// ---------------- 行情 ----------------

export async function fetchStockDetail(
  symbol: string,
  market: Market,
  options: { period?: string; interval?: string; days?: number } = {},
): Promise<StockDetail> {
  const { data } = await http.get<StockDetail>(`/stocks/${encodeURIComponent(symbol)}`, {
    params: { market, period: options.period ?? '6mo', interval: options.interval ?? '1d', days: options.days ?? 180 },
    timeout: 120000,
  })
  return data
}

export async function fetchCandles(
  symbol: string,
  market: Market,
  period: string,
  interval: string,
): Promise<CandlesResponse> {
  const { data } = await http.get<CandlesResponse>(`/stocks/${encodeURIComponent(symbol)}/candles`, {
    params: { market, period, interval },
    timeout: 120000,
  })
  return data
}

export async function fetchQuote(symbol: string, market: Market): Promise<Quote> {
  const { data } = await http.get<Quote>(`/stocks/${encodeURIComponent(symbol)}/quote`, {
    params: { market },
  })
  return data
}

export async function fetchProfile(symbol: string, market: Market): Promise<CompanyProfile> {
  const { data } = await http.get<CompanyProfile>(`/stocks/${encodeURIComponent(symbol)}/profile`, {
    params: { market },
    timeout: 60000,
  })
  return data
}

export async function fetchFinancials(symbol: string, market: Market): Promise<Financials> {
  const { data } = await http.get<Financials>(`/stocks/${encodeURIComponent(symbol)}/financials`, {
    params: { market },
    timeout: 60000,
  })
  return data
}

export async function fetchEarnings(symbol: string, market: Market): Promise<EarningsData> {
  const { data } = await http.get<EarningsData>(`/stocks/${encodeURIComponent(symbol)}/earnings`, {
    params: { market },
    timeout: 60000,
  })
  return data
}

export async function fetchAnalyst(symbol: string, market: Market): Promise<AnalystData> {
  const { data } = await http.get<AnalystData>(`/stocks/${encodeURIComponent(symbol)}/analyst`, {
    params: { market },
    timeout: 60000,
  })
  return data
}

export async function fetchNews(symbol: string, market: Market, limit = 12): Promise<NewsResponse> {
  const { data } = await http.get<NewsResponse>(`/stocks/${encodeURIComponent(symbol)}/news`, {
    params: { market, limit },
    timeout: 60000,
  })
  return data
}

export async function searchSymbols(query: string, limit = 10): Promise<SearchResponse> {
  const { data } = await http.get<SearchResponse>('/stocks/search', {
    params: { q: query, limit },
    timeout: 30000,
  })
  return data
}

export async function fetchMovers(
  market: Market,
  type: MoversType,
  count = 10,
): Promise<MoversResponse> {
  const { data } = await http.get<MoversResponse>('/stocks/movers', {
    params: { market, type, count },
    timeout: 60000,
  })
  return data
}

export async function fetchUpcomingEarnings(
  market: Market,
  days = 14,
  limit = 50,
): Promise<UpcomingEarningsResponse> {
  const { data } = await http.get<UpcomingEarningsResponse>('/stocks/upcoming_earnings', {
    params: { market, days, limit },
    timeout: 120000,
  })
  return data
}

// ---------------- AI 分析 ----------------

export async function analyzeOnce(payload: AnalysisRequest): Promise<AnalysisResponse> {
  const { data } = await http.post<AnalysisResponse>('/analysis', payload, { timeout: 600000 })
  return data
}

export async function fetchContextPreview(
  symbol: string,
  market: Market,
  options: { days?: number; news_limit?: number } = {},
): Promise<ContextPreview> {
  const { data } = await http.get<ContextPreview>('/analysis/context', {
    params: { symbol, market, days: options.days ?? 180, news_limit: options.news_limit },
    timeout: 120000,
  })
  return data
}
