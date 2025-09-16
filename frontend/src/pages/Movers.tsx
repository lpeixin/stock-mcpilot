import React, { useEffect, useMemo, useState } from 'react'
import { fetchMovers, Market, MoversItem, MoversResponse, MoversType } from '../api/api'
import { t } from '../i18n'
import { useApp } from '../store/useApp'
import { useHome } from '../store/useHome'

const fmtNum = (v: any) => v === null || v === undefined ? '-' : Number(v).toLocaleString()
const fmtPct = (v: any) => v === null || v === undefined ? '-' : `${Number(v).toFixed(2)}%`

const Movers: React.FC = () => {
  const [market, setMarket] = useState<Market>('US')
  const [type, setType] = useState<MoversType>('gainers')
  const [count, setCount] = useState(10)
  const [data, setData] = useState<MoversResponse | undefined>()
  const [loading, setLoading] = useState(false)
  const { setPage } = useApp()
  const { setMarket: setHomeMarket, setSymbol, search } = useHome()

  const load = async () => {
    setLoading(true)
    try {
      const d = await fetchMovers(market, type, count)
      setData(d)
    } finally { setLoading(false) }
  }
  useEffect(()=>{ load() }, [market, type, count])

  const onClickSymbol = async (sym: string) => {
    setHomeMarket(market)
    setSymbol(sym.replace('.HK','').replace('.SS','').replace('.SZ',''))
    setPage('home')
    // slight delay to ensure Home renders, then search
    setTimeout(()=>{ search() }, 0)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select className="border rounded px-2 py-1" value={market} onChange={e=>setMarket(e.target.value as Market)}>
          <option value="US">{t('search.market.us') || 'US'}</option>
          <option value="HK">{t('search.market.hk') || 'HK'}</option>
          <option value="CN">{t('search.market.cn') || 'CN'}</option>
        </select>
        <div className="inline-flex rounded border overflow-hidden">
          <button className={`px-3 py-1 text-sm ${type==='gainers'?'bg-blue-50 text-blue-700':'text-gray-600'}`} onClick={()=>setType('gainers')}>{t('movers.gainers') || 'Gainers'}</button>
          <button className={`px-3 py-1 text-sm ${type==='losers'?'bg-blue-50 text-blue-700':'text-gray-600'}`} onClick={()=>setType('losers')}>{t('movers.losers') || 'Losers'}</button>
        </div>
        <select className="border rounded px-2 py-1" value={count} onChange={e=>setCount(Number(e.target.value))}>
          <option value={10}>Top 10</option>
          <option value={20}>Top 20</option>
        </select>
      </div>
      <div className="bg-white border rounded shadow-sm overflow-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              <th className="px-3 py-2 text-left">{t('table.symbol') || 'Symbol'}</th>
              <th className="px-3 py-2 text-left">{t('table.name') || 'Name'}</th>
              <th className="px-3 py-2 text-right">{t('table.price') || 'Price'}</th>
              <th className="px-3 py-2 text-right">{t('table.change') || 'Change'}</th>
              <th className="px-3 py-2 text-right">{t('table.change_pct') || 'Change %'}</th>
              <th className="px-3 py-2 text-right">{t('table.volume') || 'Volume'}</th>
              <th className="px-3 py-2 text-right">{t('table.market_cap') || 'Mkt Cap'}</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td className="px-3 py-4 text-center text-gray-400" colSpan={7}>{t('loading') || 'Loading...'}</td></tr>
            )}
            {!loading && (!data || data.items.length===0) && (
              <tr><td className="px-3 py-4 text-center text-gray-400" colSpan={7}>{t('empty.prompt') || 'No data'}</td></tr>
            )}
            {!loading && data && data.items.map((it, idx)=> (
              <tr key={idx} className={idx%2? 'bg-white':'bg-gray-50'}>
                <td className="px-3 py-2 text-blue-600 cursor-pointer" onClick={()=>onClickSymbol(it.symbol)}>{it.symbol}</td>
                <td className="px-3 py-2">{it.name || '-'}</td>
                <td className="px-3 py-2 text-right">{fmtNum(it.price)}</td>
                <td className={"px-3 py-2 text-right " + ((it.change||0) >= 0 ? 'text-green-600':'text-red-600')}>{fmtNum(it.change)}</td>
                <td className={"px-3 py-2 text-right " + ((it.change_pct||0) >= 0 ? 'text-green-600':'text-red-600')}>{fmtPct(it.change_pct)}</td>
                <td className="px-3 py-2 text-right">{fmtNum(it.volume)}</td>
                <td className="px-3 py-2 text-right">{fmtNum(it.market_cap)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default Movers
