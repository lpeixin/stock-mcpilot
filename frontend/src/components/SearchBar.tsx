import React, { useState } from 'react'

interface Props { onSearch: (symbol: string, market: string) => void }

const SearchBar: React.FC<Props> = ({ onSearch }) => {
  const [symbol, setSymbol] = useState('AAPL')
  const [market, setMarket] = useState<'US'|'HK'|'CN'>('US')
  return (
    <div className="flex flex-col gap-2 md:flex-row md:items-center">
      <input value={symbol} onChange={e=>setSymbol(e.target.value)} placeholder="股票代码" className="border rounded px-3 py-2 w-40" />
      <select value={market} onChange={e=>setMarket(e.target.value as any)} className="border rounded px-2 py-2">
        <option value="US">美股</option>
        <option value="HK">港股</option>
        <option value="CN">A股</option>
      </select>
      <button onClick={()=>onSearch(symbol, market)} className="bg-blue-600 text-white rounded px-4 py-2 text-sm">查询</button>
    </div>
  )
}
export default SearchBar
