import React, { useState } from 'react'
import SearchBar from '../components/SearchBar'
import StockResult from '../components/StockResult'
import { analyze, fetchStock, StockDailyResponse, AnalysisResponse } from '../api/api'
import CloseLineChart from '../charts/CloseLineChart'
import { useSettings } from '../store/useSettings'
import { setLang, t } from '../i18n'

const Home: React.FC = () => {
  const [data, setData] = useState<StockDailyResponse | undefined>()
  const [analysis, setAnalysis] = useState<AnalysisResponse | undefined>()
  const [loading, setLoading] = useState(false)
  const [question, setQuestion] = useState('')
  const { language } = useSettings(); setLang(language as any)

  const doSearch = async (symbol: string, market: string) => {
    setLoading(true)
    setAnalysis(undefined)
    try {
      const d = await fetchStock(symbol, market)
      setData(d)
    } catch (e:any) {
      setData(undefined)
      alert(e.message)
    } finally { setLoading(false) }
  }
  const doAnalyze = async () => {
    if (!data) return
    setLoading(true)
  try { const a = await analyze(data.symbol, data.market, question, language); setAnalysis(a) } finally { setLoading(false) }
  }
  return (
    <div>
      <SearchBar onSearch={doSearch} />
  {data && <div className="mt-4"><CloseLineChart rows={data.rows} symbol={data.symbol} market={data.market} /></div>}
      <div className="mt-4 flex gap-2 items-start">
  <input value={question} onChange={e=>setQuestion(e.target.value)} placeholder={t('analysis.ask.placeholder')} className="border rounded px-3 py-2 flex-1" />
  <button disabled={!data} onClick={doAnalyze} className="bg-emerald-600 disabled:bg-gray-300 text-white rounded px-4 py-2 text-sm">{t('analysis.action')}</button>
      </div>
      <StockResult data={data} analysis={analysis} loading={loading} />
    </div>
  )
}
export default Home
