import React, { useMemo, useState, useCallback, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Brush } from 'recharts'
import { StockRow } from '../api/api'
import { useSettings } from '../store/useSettings'
import { setLang, t } from '../i18n'

interface Props { rows: StockRow[]; symbol: string; market: string }
const CloseLineChart: React.FC<Props> = ({ rows, symbol, market }) => {
  const { language } = useSettings(); setLang(language as any)
  const data = useMemo(()=> rows.map(r => ({
    date: r.date.slice(0,10),
    close: Number(r.close?.toFixed ? r.close.toFixed(4) : Number(r.close).toFixed(4))
  })), [rows])
  // Selected range indices (controlled by Brush)
  const [range, setRange] = useState<{ startIndex: number; endIndex: number }>({
    startIndex: 0,
    endIndex: Math.max(0, data.length - 1)
  })

  // Keep range valid when data length changes (e.g., new fetch)
  useEffect(() => {
    if (!data.length) return
    setRange(prev => {
      const end = data.length - 1
      let s = typeof prev.startIndex === 'number' ? prev.startIndex : 0
      let e = typeof prev.endIndex === 'number' ? prev.endIndex : end
      if (e > end) e = end
      if (s < 0) s = 0
      if (s >= e) {
        // default to last window if invalid; choose up to 120 points
        const win = Math.min(120, end + 1)
        s = Math.max(0, (end + 1) - win)
        e = end
      }
      if (s === prev.startIndex && e === prev.endIndex) return prev
      return { startIndex: s, endIndex: e }
    })
  }, [data.length])
  // Market -> currency abbreviation mapping
  const currency = useMemo(() => {
    switch ((market || '').toUpperCase()) {
      case 'US': return 'USD'
      case 'HK': return 'HKD'
      case 'CN': return 'CNY'
      default: return ''
    }
  }, [market])

  // Slice data according to current brush selection
  const visibleData = useMemo(() => {
    if (!data.length) return []
    const { startIndex, endIndex } = range
    return data.slice(startIndex, endIndex + 1)
  }, [data, range])
  // Y domain computed from currently visible window for better scaling
  const [yMin, yMax] = useMemo(()=>{
    if (!visibleData.length) return [0,1]
    let min = visibleData[0].close, max = visibleData[0].close
    for (const d of visibleData){ if (d.close < min) min = d.close; if (d.close > max) max = d.close }
    if (min === max){
      const pad = Math.abs(min || 1) * 0.05 || 0.5
      return [min - pad, max + pad]
    }
    const pad = (max - min) * 0.05
    return [min - pad, max + pad]
  }, [visibleData])

  const onBrushChange = useCallback((r: any) => {
    if (r && typeof r.startIndex === 'number' && typeof r.endIndex === 'number') {
      setRange({ startIndex: r.startIndex, endIndex: r.endIndex })
    }
  }, [])

  // Adaptive tick interval based on visible points
  const xInterval = useMemo(() => {
    const len = visibleData.length
    if (len <= 15) return 0
    if (len <= 60) return Math.ceil(len / 12)
    if (len <= 120) return Math.ceil(len / 16)
    if (len <= 250) return Math.ceil(len / 20)
    return Math.ceil(len / 25)
  }, [visibleData])

  // Date tick formatter
  const tickFormatter = useCallback(() => {
    if (!visibleData.length) return (v: string) => v
    const first = new Date(visibleData[0].date)
    const last = new Date(visibleData[visibleData.length - 1].date)
    const spanDays = (last.getTime() - first.getTime()) / 86400000
    return (value: string) => {
      const d = new Date(value)
      if (spanDays > 800) return d.getFullYear().toString()
      if (spanDays > 180) return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
      return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    }
  }, [visibleData])

  const currentRangeLabel = useMemo(() => {
    if (!visibleData.length) return '-'
    return `${visibleData[0].date} ~ ${visibleData[visibleData.length - 1].date}`
  }, [visibleData])

  return (
    <div className="h-80 border rounded bg-white p-2 shadow-sm flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-1 text-xs text-gray-500">
        <h3>
          {t('chart.close') || 'Close Price'}
          {currency ? ` (${currency})` : ''} - {symbol}
        </h3>
        <span className="truncate">
          {t('chart.visible_range')}: {currentRangeLabel}
        </span>
      </div>
      <div className="flex-1 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 4, right: 12, left: 4, bottom: 4 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10 }}
              interval={xInterval}
              tickFormatter={tickFormatter()}
              minTickGap={12}
            />
            <YAxis
              domain={[yMin, yMax]}
              tick={{ fontSize: 10 }}
              width={70}
              tickFormatter={(v:number)=>{
                const abs = Math.abs(v)
                if (abs >= 1000) return v.toLocaleString(undefined,{ maximumFractionDigits:2 })
                if (abs >= 1) return v.toFixed(2)
                return v.toFixed(4)
              }}
              allowDecimals
            />
            <Tooltip
              formatter={(v:number)=>{
                const abs = Math.abs(v)
                if (abs >= 1000) return v.toLocaleString(undefined,{ maximumFractionDigits:2 })
                if (abs >= 1) return v.toFixed(2)
                return v.toFixed(4)
              }}
              labelFormatter={l=>`${t('label.date') || 'Date'}: ${l}`}
            />
            <Line
              type="monotone"
              dataKey="close"
              stroke="#2563eb"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Brush
              dataKey="date"
              height={24}
              travellerWidth={10}
              stroke="#2563eb"
              startIndex={range.startIndex}
              endIndex={range.endIndex}
              onChange={onBrushChange}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
export default CloseLineChart
