import React from 'react'
import SearchBar from '../components/SearchBar'
import StockResult from '../components/StockResult'
import CloseLineChart from '../charts/CloseLineChart'
import EarningsCard from '../components/EarningsCard'
import NewsList from '../components/NewsList'
import { useSettings } from '../store/useSettings'
import { setLang, t } from '../i18n'
import { useHome } from '../store/useHome'

const Home: React.FC = () => {
  const { language } = useSettings(); setLang(language as any)
  const { data, earnings, news, analysis, loading, symbol, market, question, setQuestion, setSymbol, setMarket, search, runAnalysis } = useHome()
  const doSearch = async () => { await search() }
  const doAnalyze = async () => { await runAnalysis(language) }
  return (
    <div>
      <SearchBar onSearch={()=>doSearch()} />
      {data && (
        <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4 items-stretch">
          <div className="lg:col-span-2 flex flex-col gap-4">
            <CloseLineChart rows={data.rows} symbol={data.symbol} market={data.market} />
            <NewsList data={news} />
          </div>
          <div className="lg:col-span-1 flex">
            <EarningsCard data={earnings} />
          </div>
        </div>
      )}
      <div className="mt-4 flex gap-2 items-start">
        <input value={question} onChange={e=>setQuestion(e.target.value)} placeholder={t('analysis.ask.placeholder')} className="border rounded px-3 py-2 flex-1" />
        <button disabled={!data} onClick={doAnalyze} className="bg-emerald-600 disabled:bg-gray-300 text-white rounded px-4 py-2 text-sm">{t('analysis.action')}</button>
      </div>
      <StockResult data={data} analysis={analysis} loading={loading} />
    </div>
  )
}
export default Home
