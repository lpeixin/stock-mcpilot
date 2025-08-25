import React from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { StockRow } from '../api/api'

interface Props { rows: StockRow[]; symbol: string }

const CloseLineChart: React.FC<Props> = ({ rows, symbol }) => {
  const data = rows.map(r => ({
    date: r.date.slice(0,10),
    // 限制小数位，避免出现很多二进制浮点尾数
    close: Number(r.close?.toFixed ? r.close.toFixed(4) : Number(r.close).toFixed(4))
  }))
  return (
    <div className="h-64 border rounded bg-white p-2 shadow-sm">
      <h3 className="text-xs text-gray-500 mb-1">收盘价走势 - {symbol}</h3>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
          <XAxis dataKey="date" hide={data.length > 40} tick={{ fontSize: 10 }} interval={Math.ceil(data.length/8)} />
          <YAxis
            domain={['dataMin','dataMax']}
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
            labelFormatter={l=>`日期: ${l}`}
          />
          <Line type="monotone" dataKey="close" stroke="#2563eb" strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
export default CloseLineChart
