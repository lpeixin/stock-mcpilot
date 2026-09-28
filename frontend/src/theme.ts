/**
 * 视觉与配色约定。
 *
 * **红涨绿跌**：这是 A 股 / 港股用户的既定习惯，与欧美市场相反。整个应用统一
 * 从这里取色，避免各组件各写一套导致方向弄反（改造前 Movers 页面就用了
 * "绿涨红跌"，对中文用户是反的）。
 */

export const UP = '#d93f4c' // 涨：红
export const DOWN = '#1f9d63' // 跌：绿
export const FLAT = '#6b7280' // 平：灰

export const UP_SOFT = 'rgba(217, 63, 76, 0.12)'
export const DOWN_SOFT = 'rgba(31, 157, 99, 0.12)'

/** 成交量柱：比 K 线本体浅一档，避免抢视觉重心。 */
export const UP_BAR = 'rgba(217, 63, 76, 0.55)'
export const DOWN_BAR = 'rgba(31, 157, 99, 0.55)'

export const SERIES = {
  close: '#2563eb',
  ma5: '#f59e0b',
  ma10: '#8b5cf6',
  ma20: '#0ea5e9',
  ma60: '#64748b',
  boll: '#94a3b8',
  dif: '#f59e0b',
  dea: '#2563eb',
  rsi: '#8b5cf6',
  k: '#f59e0b',
  d: '#2563eb',
  j: '#d946ef',
  grid: '#eef2f6',
  axis: '#94a3b8',
}

/** 依据数值正负返回颜色。0 或缺失按"平"处理。 */
export function trendColor(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return FLAT
  if (value > 0) return UP
  if (value < 0) return DOWN
  return FLAT
}

/** 依据数值正负返回 Tailwind 文本类。 */
export function trendClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-gray-500'
  if (value > 0) return 'text-[#d93f4c]'
  if (value < 0) return 'text-[#1f9d63]'
  return 'text-gray-500'
}

/** 涨跌幅带符号显示，例如 +1.54% / -0.41%。 */
export function signedPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}%`
}

export function signedNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(digits)}`
}
