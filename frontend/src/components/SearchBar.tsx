import React, { useState } from 'react'
import { useSettings } from '../store/useSettings'
import { setLang, t } from '../i18n'

interface Props { onSearch: (symbol: string, market: string) => void }

const SearchBar: React.FC<Props> = ({ onSearch }) => {
  const [symbol, setSymbol] = useState('AAPL')
  const [market, setMarket] = useState<'US'|'HK'|'CN'>('US')
  const { language } = useSettings()
  setLang(language as any)
  const [msg, setMsg] = useState('')
  return (
    <div className="flex flex-col gap-2 md:flex-row md:items-center">
      <input value={symbol} onChange={e=>setSymbol(e.target.value)} placeholder={t('search.placeholder')} className="border rounded px-3 py-2 w-40" />
      <select value={market} onChange={e=>setMarket(e.target.value as any)} className="border rounded px-2 py-2">
        <option value="US">{t('search.market.us')}</option>
        <option value="HK">{t('search.market.hk')}</option>
        <option value="CN">{t('search.market.cn')}</option>
      </select>
      <button onClick={()=>{
        const s = symbol.trim()
        if (!s){ setMsg(t('search.empty')); return }
        setMsg('')
        onSearch(s, market)
      }} className="bg-blue-600 text-white rounded px-4 py-2 text-sm">{t('search.action')}</button>
      {msg && <span className="text-xs text-rose-500 mt-1 md:mt-0">{msg}</span>}
    </div>
  )
}
export default SearchBar
