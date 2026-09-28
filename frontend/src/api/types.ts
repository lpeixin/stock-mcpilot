/** 后端接口的类型定义。与 backend/schemas 一一对应。 */

export type Market = 'US' | 'HK' | 'CN'
export type MoversType = 'gainers' | 'losers'
export type CandleInterval = '1d' | '1wk' | '1mo' | '1m' | '5m' | '15m' | '30m' | '60m'
export type CandlePeriod = '1mo' | '3mo' | '6mo' | '1y' | '2y' | '5y' | '10y' | 'ytd' | 'max'
export type AnalysisFocus = 'technical' | 'fundamental' | 'news' | 'valuation' | 'risk'

export interface Quote {
  symbol: string
  market: string
  name?: string | null
  long_name?: string | null
  name_zh?: string | null
  price?: number | null
  previous_close?: number | null
  change?: number | null
  change_pct?: number | null
  open?: number | null
  day_high?: number | null
  day_low?: number | null
  volume?: number | null
  avg_volume?: number | null
  market_cap?: number | null
  currency?: string | null
  exchange?: string | null
  quote_type?: string | null
  week52_high?: number | null
  week52_low?: number | null
  week52_position_pct?: number | null
  ma50?: number | null
  ma200?: number | null
  timezone?: string | null
}

export interface Candle {
  date: string
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  volume?: number | null
  ma5?: number | null
  ma10?: number | null
  ma20?: number | null
  ma60?: number | null
  rsi14?: number | null
  macd_dif?: number | null
  macd_dea?: number | null
  macd_hist?: number | null
  boll_upper?: number | null
  boll_mid?: number | null
  boll_lower?: number | null
  kdj_k?: number | null
  kdj_d?: number | null
  kdj_j?: number | null
  atr14?: number | null
  volume_ratio?: number | null
  pct_change?: number | null
}

export interface IndicatorSignal {
  code: string
  params: Record<string, string | number>
}

export interface IndicatorSnapshot {
  close?: number | null
  pct_change?: number | null
  ma: Record<string, number | null>
  rsi14?: number | null
  macd: Record<string, number | null>
  boll: Record<string, number | null>
  atr14?: number | null
  atr_pct?: number | null
  kdj: Record<string, number | null>
  volume_ratio?: number | null
  amplitude?: number | null
  /** 中文渲染后的句子（后端产出）。 */
  signals: string[]
  /** 机器可读编码，前端据此本地化。旧后端可能不返回。 */
  signals_structured?: IndicatorSignal[]
}

export interface PriceSummary {
  count?: number | null
  start_date?: string | null
  end_date?: string | null
  first_close?: number | null
  last_close?: number | null
  mean_close?: number | null
  high?: number | null
  low?: number | null
  return_pct?: number | null
  max_drawdown_pct?: number | null
  volatility_pct?: number | null
  annualized_volatility_pct?: number | null
  max_single_day_gain_pct?: number | null
  max_single_day_loss_pct?: number | null
  up_days?: number | null
  down_days?: number | null
  vol_mean?: number | null
  vol_last?: number | null
  recent_20d_return_pct?: number | null
  prior_20d_return_pct?: number | null
  momentum_acceleration_pct?: number | null
}

export interface MarketSession {
  status: 'pre' | 'open' | 'lunch' | 'closed'
  date: string
  timezone: string
  now: string
}

export interface StockDetail {
  symbol: string
  market: string
  quote?: Quote | null
  indicators?: IndicatorSnapshot | null
  summary?: PriceSummary | null
  candles: Candle[]
  interval: string
  period: string
  session?: MarketSession | null
  warnings: string[]
}

export interface CandlesResponse {
  symbol: string
  market: string
  period: string
  interval: string
  count: number
  start?: string | null
  end?: string | null
  candles: Candle[]
}

export interface NewsItem {
  title: string
  url?: string | null
  publisher?: string | null
  published_at?: string | null
  summary?: string | null
}

export interface NewsResponse {
  symbol: string
  market: string
  count: number
  items: NewsItem[]
}

export interface CompanyProfile {
  symbol: string
  market: string
  name?: string | null
  name_zh?: string | null
  long_name?: string | null
  sector?: string | null
  industry?: string | null
  country?: string | null
  website?: string | null
  employees?: number | null
  summary?: string | null
  market_cap?: number | null
  enterprise_value?: number | null
  pe_trailing?: number | null
  pe_forward?: number | null
  peg_ratio?: number | null
  pb?: number | null
  ps?: number | null
  ev_to_ebitda?: number | null
  eps_trailing?: number | null
  eps_forward?: number | null
  revenue?: number | null
  ebitda?: number | null
  profit_margin?: number | null
  gross_margin?: number | null
  operating_margin?: number | null
  roe?: number | null
  roa?: number | null
  revenue_growth?: number | null
  earnings_growth?: number | null
  debt_to_equity?: number | null
  current_ratio?: number | null
  quick_ratio?: number | null
  free_cashflow?: number | null
  total_cash?: number | null
  total_debt?: number | null
  dividend_yield?: number | null
  dividend_rate?: number | null
  payout_ratio?: number | null
  beta?: number | null
  target_mean?: number | null
  target_high?: number | null
  target_low?: number | null
  target_median?: number | null
  recommendation?: string | null
  recommendation_mean?: number | null
  analyst_count?: number | null
  earnings_date?: string | null
  ex_dividend_date?: string | null
  shares_outstanding?: number | null
  float_shares?: number | null
  held_by_insiders?: number | null
  held_by_institutions?: number | null
  short_ratio?: number | null
  short_pct_of_float?: number | null
}

export type FinancialPeriod = Record<string, number | null>

export interface Financials {
  symbol: string
  market: string
  annual: Record<string, FinancialPeriod>
  quarterly: Record<string, FinancialPeriod>
}

export interface EarningsEvent {
  date: string
  eps_estimate?: number | null
  eps_actual?: number | null
  surprise_pct?: number | null
}

export interface EstimateRow {
  avg?: number | null
  low?: number | null
  high?: number | null
  analysts?: number | null
  growth?: number | null
  year_ago?: number | null
}

export interface EarningsData {
  symbol: string
  market: string
  next_earnings_date?: string | null
  events: EarningsEvent[]
  eps_estimate: Record<string, EstimateRow>
  revenue_estimate: Record<string, EstimateRow>
  eps_trend: Record<string, Record<string, number | null>>
  eps_revisions: Record<string, Record<string, number | null>>
  earnings_high?: number | null
  earnings_low?: number | null
  earnings_average?: number | null
  revenue_average?: number | null
}

export interface RecommendationRow {
  period?: string | null
  strong_buy?: number | null
  buy?: number | null
  hold?: number | null
  sell?: number | null
  strong_sell?: number | null
}

export interface AnalystData {
  symbol: string
  market: string
  target_current?: number | null
  target_high?: number | null
  target_low?: number | null
  target_mean?: number | null
  target_median?: number | null
  recommendation_key?: string | null
  recommendation_mean?: number | null
  analyst_count?: number | null
  recommendations: RecommendationRow[]
  holders: Record<string, number | null>
}

export interface MoverItem {
  symbol: string
  market: string
  name?: string | null
  name_zh?: string | null
  price?: number | null
  change?: number | null
  change_pct?: number | null
  volume?: number | null
  market_cap?: number | null
  currency?: string | null
  exchange?: string | null
}

export interface MoversResponse {
  market: Market
  type: MoversType
  count: number
  items: MoverItem[]
}

export interface UpcomingEarningsItem {
  symbol: string
  name?: string | null
  earnings_date: string
  days_until?: number | null
  eps_estimate?: number | null
  market_cap?: number | null
  currency?: string | null
}

export interface UpcomingEarningsResponse {
  market: Market
  count: number
  days: number
  items: UpcomingEarningsItem[]
}

export interface SearchResultItem {
  symbol: string
  market: Market
  name?: string | null
  exchange?: string | null
  type?: string | null
}

export interface SearchResponse {
  query: string
  count: number
  items: SearchResultItem[]
}

// ---------------- 配置与 LLM ----------------

export type ProviderGroup = 'remote' | 'local'

export interface ProviderPreset {
  label: string
  /** 分组：远程服务商排在本地模型之前。 */
  group: ProviderGroup
  kind: 'ollama' | 'openai_compat' | 'anthropic'
  base_url: string
  requires_key: boolean
  default_model: string
  hint: string
}

export interface PresetGroup {
  key: string
  label: string
}

export interface LLMConfig {
  preset: string
  kind: string
  base_url: string
  /** 掩码形式，例如 sk-1****cdef；空串表示未设置 */
  api_key: string
  api_key_set: boolean
  model: string
  temperature: number
  max_tokens: number
  timeout: number
  system_prompt: string
}

export interface AnalysisConfig {
  language: 'en' | 'zh'
  news_limit: number
  candle_days: number
  max_context_chars: number
  include: Record<string, boolean>
}

export interface AppConfig {
  llm: LLMConfig
  analysis: AnalysisConfig
  ui: { language?: 'en' | 'zh' }
  presets: Record<string, ProviderPreset>
  /** 服务端下发的分组顺序与标题，前端不硬编码。 */
  preset_groups: PresetGroup[]
  /** 被环境变量锁定的字段路径，例如 ["llm.api_key"] */
  locked_by_env: string[]
  config_path: string
}

export interface ModelListResult {
  ok: boolean
  models: string[]
  kind?: string | null
  message?: string
}

export interface ProbeResult {
  ok: boolean
  message: string
  latency_ms: number
  models: string[]
  model_ready: boolean
  kind?: string | null
}

export interface TestResult {
  ok: boolean
  message: string
  kind?: string | null
  probe?: ProbeResult | null
  generation?: { ok: boolean; latency_ms: number; sample?: string | null } | null
}

// ---------------- AI 分析 ----------------

export interface ContextMeta {
  included: string[]
  missing: string[]
  trimmed: string[]
  errors: Record<string, string>
  prompt_chars: number
  context_chars: number
  budget_chars: number
  generated_at?: string | null
}

export interface AnalysisRequest {
  symbol: string
  market: Market
  question?: string
  days?: number
  language?: 'en' | 'zh'
  focus?: AnalysisFocus[]
  include?: Record<string, boolean>
  news_limit?: number
  use_context?: boolean
  temperature?: number
  max_tokens?: number
}

export interface AnalysisResponse {
  symbol: string
  market: string
  analysis: string
  provider?: string | null
  model?: string | null
  elapsed_ms?: number | null
  context_meta?: ContextMeta | null
}

export interface ContextPreview {
  symbol: string
  market: string
  meta: ContextMeta
  text: string
  structured: {
    system_prompt: string
    user_prompt: string
    sections: string[]
  }
}

// ---------------- SSE 事件 ----------------

export type SSEEvent =
  | { type: 'meta'; provider?: string; model?: string; symbol?: string; market?: string; context_meta?: ContextMeta | null; scope?: string }
  | { type: 'delta'; text: string }
  | { type: 'error'; kind?: string; message: string; status?: number | null }
  | { type: 'done'; elapsed_ms: number }
