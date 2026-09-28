/**
 * ECharts K 线图。
 *
 * 布局：主图（K 线 + MA）/ 成交量 / 可选副图（MACD / RSI / KDJ）。
 *
 * **缩放**是这个组件的核心诉求（用户明确要求"图表可以根据坐标轴 zoom in/out"）：
 *   - 滚轮 → 横向缩放（`dataZoom.inside`）；纵轴因 `scale: true` 会自动贴合可见区间，
 *     所以缩放实际是"双轴"的，不需要额外操作纵轴。
 *   - 拖拽 → 横向平移。
 *   - 底部滑块 → 粗选区间。
 *   - 放大 / 缩小 / 重置按钮 → 无鼠标滚轮时也能操作。
 *
 * 视窗状态由 `zoomRef` 持有，而不是塞进 option —— 否则每次数据刷新
 * `setOption` 都会把用户刚调好的缩放冲掉。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart as EChartsCandlestick, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import type { Candle, CandleInterval, CandlePeriod } from '../api/types'
import type { SubIndicator } from '../store/useStock'
import { DOWN, DOWN_BAR, SERIES, UP, UP_BAR } from '../theme'
import { fmtPrice, fmtVolume } from '../utils/format'
import type { TranslateFn } from '../i18n'
import { useChart } from './useChart'

echarts.use([
  EChartsCandlestick,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  AxisPointerComponent,
  MarkLineComponent,
  CanvasRenderer,
])

/** 默认只显示最后这么多根，剩下的交给用户自己缩放。 */
const DEFAULT_BARS = 120
const ZOOM_STEP = 1.6
const MIN_SPAN = 0.4

const INTERVALS: { value: CandleInterval; key: string }[] = [
  { value: '1d', key: 'chart.interval.daily' },
  { value: '1wk', key: 'chart.interval.weekly' },
  { value: '1mo', key: 'chart.interval.monthly' },
]

const PERIODS: { value: CandlePeriod; label: string }[] = [
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' },
  { value: '2y', label: '2Y' },
  { value: '5y', label: '5Y' },
  { value: '10y', label: '10Y' },
  { value: 'ytd', label: 'YTD' },
  { value: 'max', label: 'MAX' },
]

const SUBS: { value: SubIndicator; key: string }[] = [
  { value: 'macd', key: 'chart.sub.macd' },
  { value: 'rsi', key: 'chart.sub.rsi' },
  { value: 'kdj', key: 'chart.sub.kdj' },
  { value: 'none', key: 'chart.sub.none' },
]

const AXIS_LINE = '#e2e8f0'
const LABEL_COLOR = '#94a3b8'

interface Props {
  candles: Candle[]
  period: CandlePeriod
  interval: CandleInterval
  subIndicator: SubIndicator
  loading?: boolean
  symbol?: string
  t: TranslateFn
  onPeriodChange: (period: CandlePeriod) => void
  onIntervalChange: (interval: CandleInterval) => void
  onSubChange: (sub: SubIndicator) => void
}

function defaultWindow(count: number): { start: number; end: number } {
  if (count <= DEFAULT_BARS) return { start: 0, end: 100 }
  return { start: ((count - DEFAULT_BARS) / count) * 100, end: 100 }
}

function compactVolume(value: number): string {
  if (value >= 1e8) return `${(value / 1e8).toFixed(1)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(0)}万`
  return String(Math.round(value))
}

function priceAxisLabel(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude >= 1000) return value.toFixed(0)
  if (magnitude >= 10) return value.toFixed(1)
  return value.toFixed(2)
}

const CandlestickChart: React.FC<Props> = ({
  candles,
  period,
  interval,
  subIndicator,
  loading = false,
  symbol,
  t,
  onPeriodChange,
  onIntervalChange,
  onSubChange,
}) => {
  const { containerRef, instance, ready } = useChart()
  const zoomRef = useRef({ start: 0, end: 100 })
  const dataKeyRef = useRef('')
  const shapeRef = useRef('')
  const [visible, setVisible] = useState<{ start: string; end: string } | null>(null)

  const hasSub = subIndicator !== 'none' && candles.length > 0

  // -------------------------------------------------------------- 可见区间
  const candlesRef = useRef(candles)
  candlesRef.current = candles

  const syncVisible = useCallback((start: number, end: number) => {
    const list = candlesRef.current
    if (!list.length) {
      setVisible(null)
      return
    }
    const from = Math.max(0, Math.floor((start / 100) * list.length))
    const to = Math.min(list.length - 1, Math.ceil((end / 100) * list.length) - 1)
    const head = list[from]?.date
    const tail = list[to]?.date
    setVisible(head && tail ? { start: head, end: tail } : null)
  }, [])

  // ------------------------------------------------------ 跟踪用户的缩放动作
  useEffect(() => {
    const chart = instance()
    if (!chart) return

    const handler = (event: unknown) => {
      const payload = event as { batch?: unknown[]; start?: number; end?: number }
      const first = (Array.isArray(payload?.batch) ? payload.batch[0] : payload) as
        | { start?: number; end?: number }
        | undefined
      if (first && typeof first.start === 'number' && typeof first.end === 'number') {
        zoomRef.current = { start: first.start, end: first.end }
        syncVisible(first.start, first.end)
      }
    }
    chart.on('datazoom', handler)
    return () => {
      chart.off('datazoom', handler)
    }
  }, [ready, instance, syncVisible])

  // -------------------------------------------------------------------- option
  const option = useMemo<echarts.EChartsCoreOption>(() => {
    const dates = candles.map((item) => item.date)
    const ohlc = candles.map((item) => [
      item.open ?? null,
      item.close ?? null,
      item.low ?? null,
      item.high ?? null,
    ])
    const volumes = candles.map((item) => ({
      value: item.volume ?? 0,
      itemStyle: { color: (item.close ?? 0) >= (item.open ?? 0) ? UP_BAR : DOWN_BAR },
    }))

    const grids = hasSub
      ? [
          { left: 60, right: 18, top: 30, height: 208 },
          { left: 60, right: 18, top: 256, height: 56 },
          { left: 60, right: 18, top: 328, height: 84 },
        ]
      : [
          { left: 60, right: 18, top: 30, height: 296 },
          { left: 60, right: 18, top: 344, height: 72 },
        ]

    const bottomGrid = hasSub ? 2 : 1
    const xAxisIndexes = hasSub ? [0, 1, 2] : [0, 1]

    const categoryAxis = (gridIndex: number) => ({
      type: 'category' as const,
      gridIndex,
      data: dates,
      boundaryGap: true,
      axisLine: { lineStyle: { color: AXIS_LINE } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel:
        gridIndex === bottomGrid
          ? {
              color: LABEL_COLOR,
              fontSize: 10,
              margin: 8,
              // 显式 rotate:0 + hideOverlap：ECharts 默认在空间不够时会把标签**竖排**，
              // 竖排的日期很难扫读。宁可让重叠的标签被丢掉。
              rotate: 0,
              hideOverlap: true,
              formatter: (value: string) =>
                interval === '1d' ? value.slice(2) : value.slice(0, 7),
            }
          : { show: false },
      axisPointer: {
        label: {
          show: gridIndex === bottomGrid,
          backgroundColor: '#334155',
          fontSize: 10,
        },
      },
    })

    const priceAxis = {
      type: 'value' as const,
      gridIndex: 0,
      scale: true,
      splitNumber: 4,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: SERIES.grid } },
      axisLabel: { color: LABEL_COLOR, fontSize: 10, formatter: priceAxisLabel, margin: 6 },
    }

    const volumeAxis = {
      type: 'value' as const,
      gridIndex: 1,
      splitNumber: 2,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: LABEL_COLOR, fontSize: 10, formatter: compactVolume, margin: 6 },
    }

    const subAxis = {
      type: 'value' as const,
      gridIndex: 2,
      splitNumber: 3,
      ...(subIndicator === 'rsi' ? { min: 0, max: 100 } : { scale: true }),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: {
        color: LABEL_COLOR,
        fontSize: 10,
        formatter: (value: number) =>
          subIndicator === 'rsi' ? value.toFixed(0) : value.toFixed(1),
        margin: 6,
      },
    }

    // ------------------------------------------------------------------ 副图
    const subSeries: Record<string, unknown>[] = []
    const subLegend: string[] = []

    if (hasSub && subIndicator === 'macd') {
      subLegend.push('DIF', 'DEA', 'MACD')
      subSeries.push(
        {
          name: 'DIF',
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: candles.map((item) => item.macd_dif ?? null),
          showSymbol: false,
          symbol: 'none',
          lineStyle: { width: 1.1, color: SERIES.dif },
          itemStyle: { color: SERIES.dif },
          emphasis: { disabled: true },
        },
        {
          name: 'DEA',
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: candles.map((item) => item.macd_dea ?? null),
          showSymbol: false,
          symbol: 'none',
          lineStyle: { width: 1.1, color: SERIES.dea },
          itemStyle: { color: SERIES.dea },
          emphasis: { disabled: true },
        },
        {
          name: 'MACD',
          type: 'bar',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: candles.map((item) => ({
            value: item.macd_hist ?? null,
            itemStyle: { color: (item.macd_hist ?? 0) >= 0 ? UP_BAR : DOWN_BAR },
          })),
          barMaxWidth: 8,
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: false },
            lineStyle: { color: AXIS_LINE, width: 1, type: 'solid' },
            data: [{ yAxis: 0 }],
          },
        },
      )
    } else if (hasSub && subIndicator === 'rsi') {
      subLegend.push('RSI14')
      subSeries.push({
        name: 'RSI14',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: candles.map((item) => item.rsi14 ?? null),
        showSymbol: false,
        symbol: 'none',
        lineStyle: { width: 1.3, color: SERIES.rsi },
        itemStyle: { color: SERIES.rsi },
        emphasis: { disabled: true },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          lineStyle: { color: '#cbd5e1', width: 1, type: 'dashed' },
          data: [{ yAxis: 70 }, { yAxis: 30 }],
        },
      })
    } else if (hasSub && subIndicator === 'kdj') {
      subLegend.push('K', 'D', 'J')
      const lines: [string, string, (item: Candle) => number | null | undefined][] = [
        ['K', SERIES.k, (item) => item.kdj_k],
        ['D', SERIES.d, (item) => item.kdj_d],
        ['J', SERIES.j, (item) => item.kdj_j],
      ]
      for (const [name, color, pick] of lines) {
        subSeries.push({
          name,
          type: 'line',
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: candles.map((item) => pick(item) ?? null),
          showSymbol: false,
          symbol: 'none',
          lineStyle: { width: 1.1, color },
          itemStyle: { color },
          emphasis: { disabled: true },
          ...(name === 'K'
            ? {
                markLine: {
                  silent: true,
                  symbol: 'none',
                  label: { show: false },
                  lineStyle: { color: '#cbd5e1', width: 1, type: 'dashed' },
                  data: [{ yAxis: 80 }, { yAxis: 20 }],
                },
              }
            : {}),
        })
      }
    }

    // ---------------------------------------------------------------- tooltip
    const row = (label: string, value: string, color?: string) =>
      `<div style="display:flex;justify-content:space-between;gap:18px;line-height:1.75">` +
      `<span style="color:#64748b">${label}</span>` +
      `<span style="font-variant-numeric:tabular-nums;color:${color ?? '#0f172a'}">${value}</span>` +
      `</div>`

    const formatter = (raw: unknown): string => {
      const list = Array.isArray(raw) ? raw : [raw]
      const index = (list[0] as { dataIndex?: number } | undefined)?.dataIndex
      if (typeof index !== 'number') return ''
      const item = candles[index]
      if (!item) return ''
      const previous = candles[index - 1]?.close ?? item.open ?? null
      const change =
        item.pct_change !== null && item.pct_change !== undefined
          ? item.pct_change
          : previous && item.close
            ? ((item.close - previous) / previous) * 100
            : null
      const trendColor = (change ?? 0) > 0 ? UP : (change ?? 0) < 0 ? DOWN : '#64748b'
      const sign = (change ?? 0) > 0 ? '+' : ''

      const parts: string[] = [
        `<div style="font-weight:600;margin-bottom:5px;color:#0f172a">${item.date}</div>`,
        row(t('quote.open'), fmtPrice(item.open)),
        row(t('quote.high'), fmtPrice(item.high)),
        row(t('quote.low'), fmtPrice(item.low)),
        row(t('table.price'), fmtPrice(item.close), trendColor),
      ]
      if (change !== null) {
        parts.push(row(t('table.changePct'), `${sign}${change.toFixed(2)}%`, trendColor))
      }
      parts.push(row(t('chart.volume'), fmtVolume(item.volume)))
      if (item.volume_ratio !== null && item.volume_ratio !== undefined) {
        parts.push(row(t('indicators.volumeRatio'), item.volume_ratio.toFixed(2)))
      }
      const maPairs: [string, number | null | undefined][] = [
        ['MA5', item.ma5],
        ['MA10', item.ma10],
        ['MA20', item.ma20],
        ['MA60', item.ma60],
      ]
      for (const [label, value] of maPairs) {
        if (value !== null && value !== undefined) parts.push(row(label, fmtPrice(value)))
      }
      if (subIndicator === 'macd' && item.macd_dif !== null && item.macd_dif !== undefined) {
        parts.push(row('DIF', item.macd_dif.toFixed(3)))
        parts.push(row('DEA', (item.macd_dea ?? 0).toFixed(3)))
        parts.push(row('MACD', (item.macd_hist ?? 0).toFixed(3), (item.macd_hist ?? 0) >= 0 ? UP : DOWN))
      } else if (subIndicator === 'rsi' && item.rsi14 !== null && item.rsi14 !== undefined) {
        parts.push(row('RSI14', item.rsi14.toFixed(2)))
      } else if (subIndicator === 'kdj' && item.kdj_k !== null && item.kdj_k !== undefined) {
        parts.push(row('K', (item.kdj_k ?? 0).toFixed(2)))
        parts.push(row('D', (item.kdj_d ?? 0).toFixed(2)))
        parts.push(row('J', (item.kdj_j ?? 0).toFixed(2)))
      }
      return `<div style="min-width:200px">${parts.join('')}</div>`
    }

    return {
      animation: false,
      backgroundColor: 'transparent',
      textStyle: { fontFamily: 'inherit' },
      grid: grids,
      legend: {
        show: subLegend.length > 0,
        top: 4,
        left: 8,
        itemWidth: 12,
        itemHeight: 8,
        itemGap: 14,
        textStyle: { fontSize: 10, color: '#64748b' },
        data: subLegend,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
          crossStyle: { color: '#cbd5e1', width: 1 },
          lineStyle: { color: '#cbd5e1', type: 'dashed' },
        },
        backgroundColor: 'rgba(255,255,255,0.97)',
        borderColor: '#e2e8f0',
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: '#0f172a', fontSize: 11 },
        extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(15,23,42,0.12);',
        formatter,
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      xAxis: xAxisIndexes.map(categoryAxis),
      yAxis: hasSub ? [priceAxis, volumeAxis, subAxis] : [priceAxis, volumeAxis],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: xAxisIndexes,
          start: 0,
          end: 100,
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          moveOnMouseWheel: false,
          throttle: 30,
        },
        {
          type: 'slider',
          xAxisIndex: xAxisIndexes,
          bottom: 6,
          height: 18,
          start: 0,
          end: 100,
          borderColor: AXIS_LINE,
          backgroundColor: '#f8fafc',
          fillerColor: 'rgba(37,99,235,0.10)',
          handleStyle: { color: '#2563eb', borderColor: '#2563eb' },
          moveHandleStyle: { color: '#cbd5e1' },
          dataBackground: {
            lineStyle: { color: '#cbd5e1', width: 1 },
            areaStyle: { color: '#e2e8f0' },
          },
          selectedDataBackground: {
            lineStyle: { color: '#93c5fd', width: 1 },
            areaStyle: { color: '#dbeafe' },
          },
          textStyle: { fontSize: 10, color: LABEL_COLOR },
          brushSelect: false,
        },
      ],
      series: [
        {
          name: 'K',
          type: 'candlestick',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ohlc,
          barMaxWidth: 14,
          itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
        },
        ...[
          ['MA5', 'ma5'],
          ['MA10', 'ma10'],
          ['MA20', 'ma20'],
          ['MA60', 'ma60'],
        ].map(([name, key]) => ({
          name,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: candles.map(
            (item) => (item as unknown as Record<string, number | null>)[key] ?? null,
          ),
          showSymbol: false,
          symbol: 'none',
          connectNulls: false,
          lineStyle: { width: 1, color: (SERIES as Record<string, string>)[key] },
          itemStyle: { color: (SERIES as Record<string, string>)[key] },
          emphasis: { disabled: true },
          z: 3,
        })),
        {
          name: 'VOL',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          barMaxWidth: 14,
        },
        ...subSeries,
      ],
    }
  }, [candles, hasSub, interval, subIndicator, t])

  // -------------------------------------------------------------- 应用 option
  useEffect(() => {
    const chart = instance()
    if (!chart || !ready) return

    const shape = `${subIndicator}|${hasSub}|${interval}`
    const notMerge = shapeRef.current !== '' && shapeRef.current !== shape
    shapeRef.current = shape

    chart.setOption(option, { notMerge, lazyUpdate: true })

    const key = `${candles.length}|${candles[0]?.date ?? ''}|${candles[candles.length - 1]?.date ?? ''}|${interval}`
    if (key !== dataKeyRef.current) {
      // 换标的 / 换周期 → 回到默认视窗
      dataKeyRef.current = key
      zoomRef.current = defaultWindow(candles.length)
    }
    chart.dispatchAction({
      type: 'dataZoom',
      start: zoomRef.current.start,
      end: zoomRef.current.end,
    })
    syncVisible(zoomRef.current.start, zoomRef.current.end)
  }, [option, ready, instance, candles, interval, subIndicator, hasSub, syncVisible])

  // -------------------------------------------------------------- 缩放操作
  const applyZoom = useCallback(
    (factor: number) => {
      const chart = instance()
      if (!chart) return
      const { start, end } = zoomRef.current
      const span = Math.max(MIN_SPAN, Math.min(100, end - start))
      const next = Math.max(MIN_SPAN, Math.min(100, span / factor))
      const center = (start + end) / 2
      let nextStart = center - next / 2
      let nextEnd = center + next / 2
      if (nextStart < 0) {
        nextEnd -= nextStart
        nextStart = 0
      }
      if (nextEnd > 100) {
        nextStart -= nextEnd - 100
        nextEnd = 100
      }
      zoomRef.current = { start: Math.max(0, nextStart), end: nextEnd }
      chart.dispatchAction({ type: 'dataZoom', ...zoomRef.current })
      syncVisible(zoomRef.current.start, zoomRef.current.end)
    },
    [instance, syncVisible],
  )

  const resetZoom = useCallback(() => {
    const chart = instance()
    if (!chart) return
    zoomRef.current = defaultWindow(candlesRef.current.length)
    chart.dispatchAction({ type: 'dataZoom', ...zoomRef.current })
    syncVisible(zoomRef.current.start, zoomRef.current.end)
  }, [instance, syncVisible])

  const empty = candles.length === 0
  const chartHeight = hasSub ? 460 : 440

  const iconButton =
    'flex h-6 w-6 items-center justify-center rounded text-slate-500 transition hover:bg-slate-100 hover:text-slate-900'

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-800">{t('chart.title')}</span>
          {symbol ? <span className="text-xs text-slate-400">{symbol}</span> : null}
        </div>

        <div className="flex items-center gap-1">
          {INTERVALS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onIntervalChange(item.value)}
              className={`rounded px-2 py-0.5 text-xs transition ${
                interval === item.value
                  ? 'bg-slate-900 text-white'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {t(item.key)}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-0.5 rounded-md bg-slate-100 p-0.5">
          {PERIODS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onPeriodChange(item.value)}
              className={`rounded px-1.5 py-0.5 text-[11px] transition ${
                period === item.value
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          {SUBS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onSubChange(item.value)}
              className={`rounded px-2 py-0.5 text-xs transition ${
                subIndicator === item.value
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {t(item.key)}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2">
          {visible ? (
            <span className="hidden text-[11px] tabular-nums text-slate-400 sm:inline">
              {t('chart.visible')} {visible.start} ~ {visible.end}
            </span>
          ) : null}
          <div className="flex items-center gap-0.5">
            <button type="button" onClick={() => applyZoom(ZOOM_STEP)} title={t('chart.zoomIn')} className={iconButton}>
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
                <circle cx="7" cy="7" r="4.5" />
                <path d="M10.4 10.4 14 14M7 5.2v3.6M5.2 7h3.6" strokeLinecap="round" />
              </svg>
            </button>
            <button type="button" onClick={() => applyZoom(1 / ZOOM_STEP)} title={t('chart.zoomOut')} className={iconButton}>
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
                <circle cx="7" cy="7" r="4.5" />
                <path d="M10.4 10.4 14 14M5.2 7h3.6" strokeLinecap="round" />
              </svg>
            </button>
            <button type="button" onClick={resetZoom} title={t('chart.resetZoom')} className={iconButton}>
              <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M13 8a5 5 0 1 1-1.6-3.7" strokeLinecap="round" />
                <path d="M13 2.5V5h-2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <div className="px-2 pb-1 pt-1">
        <div className="relative">
          <div ref={containerRef} style={{ height: chartHeight, width: '100%' }} />
          {empty && !loading ? (
            <div className="absolute inset-0 flex items-center justify-center text-xs text-slate-400">
              {t('chart.noData')}
            </div>
          ) : null}
          {loading ? (
            <div className="absolute right-3 top-2 rounded bg-white/85 px-2 py-0.5 text-[11px] text-slate-500">
              {t('common.loading')}
            </div>
          ) : null}
        </div>
        <p className="px-2 pb-1 text-[11px] text-slate-400">{t('chart.zoom.hint')}</p>
      </div>
    </div>
  )
}

export default CandlestickChart
