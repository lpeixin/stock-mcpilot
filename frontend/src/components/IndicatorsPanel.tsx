/**
 * 技术指标面板 + 客观形态判读。
 *
 * 判读文字来自后端的机器可读编码（`signals_structured`），在这里按语言组句。
 * chip 的颜色只是"读数偏高/偏低"的视觉提示，不是买卖信号。
 */

import type { IndicatorSnapshot } from '../api/types'
import type { TranslateFn } from '../i18n'
import { DOWN, UP } from '../theme'
import { clamp, fmtNum, fmtPrice, fmtPct } from '../utils/format'
import { localizeSignals, signalTone } from '../utils/signals'
import { Card, EmptyState } from './ui'

interface Props {
  indicators: IndicatorSnapshot | null
  t: TranslateFn
}

const RsiGauge: React.FC<{ value: number }> = ({ value }) => (
  <div className="relative mt-1 h-1 w-full rounded-full bg-slate-100">
    <div
      className="absolute inset-y-0 rounded-full"
      style={{
        left: '30%',
        width: '40%',
        background: 'rgba(148,163,184,0.18)',
      }}
    />
    <span
      className="absolute top-1/2 h-2.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm"
      style={{ left: `${clamp(value, 0, 100)}%`, background: value >= 70 ? UP : value <= 30 ? DOWN : '#64748b' }}
    />
  </div>
)

const Block: React.FC<{
  title: string
  children: React.ReactNode
  className?: string
}> = ({ title, children, className = '' }) => (
  <div className={className}>
    <div className="mb-1.5 text-[11px] font-medium text-slate-400">{title}</div>
    {children}
  </div>
)

const Row: React.FC<{ label: string; value: string; valueClass?: string }> = ({
  label,
  value,
  valueClass = 'text-slate-800',
}) => (
  <div className="flex items-baseline justify-between gap-2 leading-relaxed">
    <span className="text-[11px] text-slate-400">{label}</span>
    <span className={`text-xs tabular-nums ${valueClass}`}>{value}</span>
  </div>
)

const IndicatorsPanel: React.FC<Props> = ({ indicators, t }) => {
  if (!indicators) {
    return (
      <Card title={t('indicators.title')}>
        <EmptyState text={t('common.empty')} compact />
      </Card>
    )
  }

  const ma = indicators.ma ?? {}
  const macd = indicators.macd ?? {}
  const boll = indicators.boll ?? {}
  const kdj = indicators.kdj ?? {}
  const close = indicators.close ?? null

  const maRow = (key: string) => {
    const value = ma[key]
    const relation =
      value !== null && value !== undefined && close !== null
        ? close > value
          ? UP
          : close < value
            ? DOWN
            : undefined
        : undefined
    return (
      <Row
        key={key}
        label={key.toUpperCase()}
        value={fmtPrice(value)}
        valueClass={relation === UP ? 'text-[#d93f4c]' : relation === DOWN ? 'text-[#1f9d63]' : 'text-slate-800'}
      />
    )
  }

  const signals = localizeSignals(indicators.signals_structured, indicators.signals ?? [], t)

  const toneClass: Record<string, string> = {
    up: 'bg-red-50 text-[#d93f4c]',
    down: 'bg-emerald-50 text-[#1f9d63]',
    neutral: 'bg-slate-100 text-slate-600',
  }

  return (
    <Card title={t('indicators.title')}>
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-4">
        <Block title={t('indicators.ma')}>
          {['ma5', 'ma10', 'ma20', 'ma60'].map(maRow)}
        </Block>

        <Block title={t('indicators.rsi')}>
          <Row
            label={t('table.price')}
            value={fmtNum(indicators.rsi14, 2)}
            valueClass={
              (indicators.rsi14 ?? 50) >= 70
                ? 'text-[#d93f4c]'
                : (indicators.rsi14 ?? 50) <= 30
                  ? 'text-[#1f9d63]'
                  : 'text-slate-800'
            }
          />
          <div className="mt-1.5">
            <RsiGauge value={indicators.rsi14 ?? 50} />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-slate-300">
            <span>0</span>
            <span>30</span>
            <span>70</span>
            <span>100</span>
          </div>
        </Block>

        <Block title={t('indicators.macd')}>
          <Row label="DIF" value={fmtNum(macd.dif, 3)} />
          <Row label="DEA" value={fmtNum(macd.dea, 3)} />
          <Row
            label="HIST"
            value={fmtNum(macd.hist, 3)}
            valueClass={(macd.hist ?? 0) >= 0 ? 'text-[#d93f4c]' : 'text-[#1f9d63]'}
          />
        </Block>

        <Block title={t('indicators.boll')}>
          <Row label="UP" value={fmtPrice(boll.upper)} />
          <Row label="MID" value={fmtPrice(boll.mid)} />
          <Row label="LOW" value={fmtPrice(boll.lower)} />
          <Row label="%B" value={fmtNum(boll.pct_b, 2)} />
        </Block>

        <Block title={t('indicators.kdj')}>
          <Row label="K" value={fmtNum(kdj.k, 2)} />
          <Row label="D" value={fmtNum(kdj.d, 2)} />
          <Row label="J" value={fmtNum(kdj.j, 2)} />
        </Block>

        <Block title={t('indicators.atr')}>
          <Row label="ATR" value={fmtNum(indicators.atr14, 3)} />
          <Row label="ATR%" value={fmtPct(indicators.atr_pct)} />
        </Block>

        <Block title={t('indicators.volumeRatio')}>
          <Row
            label={t('indicators.volumeRatio')}
            value={fmtNum(indicators.volume_ratio, 2)}
            valueClass={
              (indicators.volume_ratio ?? 1) >= 1.5
                ? 'text-[#d93f4c]'
                : (indicators.volume_ratio ?? 1) <= 0.6
                  ? 'text-[#1f9d63]'
                  : 'text-slate-800'
            }
          />
          <Row label={t('metrics.volatility')} value={fmtPct(indicators.amplitude)} />
        </Block>
      </div>

      {signals.length > 0 ? (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <div className="mb-2 text-[11px] font-medium text-slate-400">
            {t('indicators.signals')}
          </div>
          <ul className="flex flex-wrap gap-1.5">
            {signals.map((text, index) => {
              const structured = indicators.signals_structured?.[index]
              const tone = structured
                ? signalTone(structured.code, structured.params)
                : 'neutral'
              return (
                <li
                  key={`${text}-${index}`}
                  className={`rounded px-2 py-1 text-[11px] leading-tight ${toneClass[tone]}`}
                >
                  {text}
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}

      <p className="mt-3 text-[11px] leading-relaxed text-slate-300">
        {t('indicators.footnote')}
      </p>
    </Card>
  )
}

export default IndicatorsPanel
