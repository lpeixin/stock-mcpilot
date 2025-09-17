import React, { useEffect, useState } from 'react'
import { Market, fetchUpcomingEarnings, UpcomingEarningsResponse } from '../api/api'
import { t, setLang } from '../i18n'
import { useSettings } from '../store/useSettings'
import { useApp } from '../store/useApp'
import { useHome } from '../store/useHome'

const UpcomingEarnings: React.FC = () => {
  const [market, setMarket] = useState<Market>('US')
  const [days, setDays] = useState(14)
  const [data, setData] = useState<UpcomingEarningsResponse | undefined>()
  const [loading, setLoading] = useState(false)
  const { setPage } = useApp()
  const { language } = useSettings(); setLang(language as any)
  const { setMarket: setHomeMarket, setSymbol, search } = useHome()

  const load = async () => {
    setLoading(true)
    try {
      const d = await fetchUpcomingEarnings(market, days)
      setData(d)
    } finally { setLoading(false) }
  }
  useEffect(()=>{ load() }, [market, days])

  const onClickSymbol = (sym: string) => {
    setHomeMarket(market)
    setSymbol(sym.replace('.HK','').replace('.SS','').replace('.SZ',''))
    setPage('home')
    setTimeout(()=>search(), 0)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <select className="border rounded px-2 py-1" value={market} onChange={e=>setMarket(e.target.value as Market)}>
          <option value="US">{t('search.market.us') || 'US'}</option>
          <option value="HK">{t('search.market.hk') || 'HK'}</option>
          <option value="CN">{t('search.market.cn') || 'CN'}</option>
        </select>
        <select className="border rounded px-2 py-1" value={days} onChange={e=>setDays(Number(e.target.value))}>
          <option value={7}>7d</option>
          <option value={14}>14d</option>
          <option value={30}>30d</option>
        </select>
      </div>
      <div className="bg-white border rounded shadow-sm overflow-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-gray-600">
            <tr>
              <th className="px-3 py-2 text-left">{t('table.symbol') || 'Symbol'}</th>
              <th className="px-3 py-2 text-left">{t('table.name') || 'Name'}</th>
              <th className="px-3 py-2 text-left">{t('upcoming.earnings_date') || 'Earnings Date'}</th>
              <th className="px-3 py-2 text-left">{t('upcoming.session') || 'Session'}</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td className="px-3 py-4 text-center text-gray-400" colSpan={4}>{t('loading') || 'Loading...'}</td></tr>}
            {!loading && (!data || data.items.length===0) && <tr><td className="px-3 py-4 text-center text-gray-400" colSpan={4}>{t('empty.prompt') || 'No data'}</td></tr>}
            {!loading && data && data.items.map((it, idx)=>(
              <tr key={idx} className={idx%2? 'bg-white':'bg-gray-50'}>
                <td className="px-3 py-2 text-blue-600 cursor-pointer" onClick={()=>onClickSymbol(it.symbol)}>{it.symbol}</td>
                <td className="px-3 py-2">{it.name || '-'}</td>
                <td className="px-3 py-2">{it.earnings_date || '-'}</td>
                <td className="px-3 py-2">{it.session ? (it.session==='pre'? (t('upcoming.pre')||'Pre') : (t('upcoming.post')||'Post')) : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default UpcomingEarnings
