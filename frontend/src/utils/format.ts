/** 数字格式化。与后端 `analysis/context.py` 的口径保持一致，避免同一数字两处显示不同。 */

export function isNil(value: unknown): boolean {
  return value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))
}

/** 普通数字，带千分位。 */
export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (isNil(value)) return '—'
  const n = value as number
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** 按中文习惯用 万亿 / 亿 / 万 表示大额数字。 */
export function fmtAmount(value: number | null | undefined, currency?: string | null): string {
  if (isNil(value)) return '—'
  const n = value as number
  const sign = n < 0 ? '-' : ''
  const magnitude = Math.abs(n)
  let text: string
  if (magnitude >= 1e12) text = `${sign}${(magnitude / 1e12).toFixed(2)}万亿`
  else if (magnitude >= 1e8) text = `${sign}${(magnitude / 1e8).toFixed(2)}亿`
  else if (magnitude >= 1e4) text = `${sign}${(magnitude / 1e4).toFixed(2)}万`
  else text = `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
  return currency ? `${text}${currency}` : text
}

/** 成交量：股 / 手。 */
export function fmtVolume(value: number | null | undefined): string {
  if (isNil(value)) return '—'
  const n = value as number
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

/** 已经是百分数的值，例如 1.54 → "1.54%"。 */
export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (isNil(value)) return '—'
  return `${(value as number).toFixed(digits)}%`
}

/** 比率值，例如 0.1234 → "12.34%"。 */
export function fmtRatioPct(value: number | null | undefined, digits = 2): string {
  if (isNil(value)) return '—'
  return `${((value as number) * 100).toFixed(digits)}%`
}

/** 价格：根据量级决定小数位。 */
export function fmtPrice(value: number | null | undefined): string {
  if (isNil(value)) return '—'
  const n = Math.abs(value as number)
  const digits = n >= 1000 ? 2 : n >= 1 ? 2 : 4
  return (value as number).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** ISO 时间 → 本地可读。 */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 16).replace('T', ' ')
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** ISO 时间 → 相对时间（"3 小时前"）。 */
export function fmtRelative(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const diff = Date.now() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return date.toLocaleDateString()
}

/** 财报期标签：0q / +1q / 0y / +1y → 中文。 */
export function periodLabel(period: string, language: 'zh' | 'en'): string {
  const zh: Record<string, string> = {
    '0q': '本季',
    '+1q': '下季',
    '0y': '本年度',
    '+1y': '下一年度',
    LTG: '长期',
  }
  const en: Record<string, string> = {
    '0q': 'Current Q',
    '+1q': 'Next Q',
    '0y': 'Current Y',
    '+1y': 'Next Y',
    LTG: 'Long term',
  }
  return (language === 'zh' ? zh : en)[period] ?? period
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
