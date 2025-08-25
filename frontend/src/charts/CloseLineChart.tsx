import React, { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
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
  const [yMin, yMax] = useMemo(()=>{
    if (!data.length) return [0,1]
    let min = data[0].close, max = data[0].close
    for (const d of data){ if (d.close < min) min = d.close; if (d.close > max) max = d.close }
    if (min === max){
      const pad = Math.abs(min || 1) * 0.05 || 0.5
      return [min - pad, max + pad]
    }
    const pad = (max - min) * 0.05
    return [min - pad, max + pad]
  }, [data])
  // Market -> currency abbreviation mapping
  const currency = useMemo(() => {
    switch ((market || '').toUpperCase()) {
      case 'US': return 'USD'
      case 'HK': return 'HKD'
      case 'CN': return 'CNY'
      default: return ''
    }
  }, [market])
  return (
    <div className="h-64 border rounded bg-white p-2 shadow-sm flex flex-col overflow-hidden">
      <h3 className="text-xs text-gray-500 mb-1 shrink-0">{t('chart.close') || 'Close Price'}{currency ? ` (${currency})` : ''} - {symbol}</h3>
      <div className="flex-1 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 12, left: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis dataKey="date" hide={data.length > 40} tick={{ fontSize: 10 }} interval={Math.ceil(data.length/8)} />
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
            <Line type="monotone" dataKey="close" stroke="#2563eb" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
export default CloseLineChart
