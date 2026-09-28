/**
 * 形态判读的本地化。
 *
 * 后端返回 `[{code, params}]`，这里按 code 组句。这样英文界面不会混入中文，
 * 而判断逻辑仍然只有后端一份。旧版后端不返回 `signals_structured`，
 * 此时回退到它给的中文句子。
 */

import type { IndicatorSignal } from '../api/types'
import type { TranslateFn } from '../i18n'
import { fmtNum } from './format'

const str = (value: string | number | undefined): string => String(value ?? '')
const num = (value: string | number | undefined, digits = 2): string =>
  typeof value === 'number' ? fmtNum(value, digits) : str(value)

export function renderSignal(item: IndicatorSignal, t: TranslateFn): string {
  const p = item.params ?? {}
  switch (item.code) {
    case 'ma_relation':
      return t(`signal.ma_relation.${p.side === 'above' ? 'above' : 'below'}`, {
        ma: str(p.ma),
        close: num(p.close),
        ma_value: num(p.ma_value),
      })
    case 'ma_alignment':
      return t(`signal.ma_alignment.${str(p.mode)}`)
    case 'rsi_zone':
      return t(`signal.rsi_zone.${str(p.zone)}`, { value: num(p.value, 1) })
    case 'macd_cross':
      return t(`signal.macd_cross.${p.mode === 'golden' ? 'golden' : 'dead'}`)
    case 'macd_axis':
      return t(`signal.macd_axis.${p.side === 'above' ? 'above' : 'below'}`)
    case 'boll_zone':
      return t(`signal.boll_zone.${str(p.mode)}`)
    case 'kdj_cross':
      return t(`signal.kdj_cross.${p.mode === 'golden' ? 'golden' : 'dead'}`, {
        k: num(p.k, 1),
        d: num(p.d, 1),
      })
    case 'volume_ratio':
      return t(`signal.volume_ratio.${str(p.mode)}`, { value: num(p.value, 2) })
    case 'atr_scale':
      return t('signal.atr_scale', { value: num(p.value, 2) })
    default:
      return ''
  }
}

export function localizeSignals(
  structured: IndicatorSignal[] | undefined,
  fallback: string[],
  t: TranslateFn,
): string[] {
  if (!structured || structured.length === 0) return fallback
  return structured.map((item) => renderSignal(item, t)).filter(Boolean)
}

/** 判读的倾向：用于给 chip 上色。只做机械映射，不构成建议。 */
export function signalTone(code: string, params: Record<string, string | number>): 'up' | 'down' | 'neutral' {
  const mode = String(params.mode ?? params.zone ?? params.side ?? '')
  if (
    mode === 'bull' ||
    mode === 'golden' ||
    mode === 'oversold' ||
    mode === 'above_upper' ||
    mode === 'above' ||
    mode === 'heavy'
  ) {
    return 'up'
  }
  if (mode === 'bear' || mode === 'dead' || mode === 'overbought' || mode === 'below_lower' || mode === 'below' || mode === 'light') {
    return 'down'
  }
  return 'neutral'
}
