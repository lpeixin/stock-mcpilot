import React from 'react'
import { EarningsResponse } from '../api/api'
import { t } from '../i18n'

interface Props { data?: EarningsResponse }

const number = (v: number | null | undefined, digits = 2) =>
  (v === null || v === undefined || Number.isNaN(v as any)) ? '-' : Number(v).toFixed(digits)

const EarningsCard: React.FC<Props> = ({ data }) => {
  const events = data?.events || []
  const nextDate = data?.next_earnings_date
  const [expanded, setExpanded] = React.useState(false)
  const visible = expanded ? events : events.slice(-6) // 默认仅显示近 6 条，避免过长
  return (
    <div className="bg-white border rounded shadow-sm flex flex-col max-h-[400px]">
      <div className="px-4 py-2 border-b flex items-center justify-between gap-2">
        <div className="font-medium text-gray-800 truncate">{t('earnings.title') || 'Earnings'}</div>
        <div className="flex items-center gap-3">
          {nextDate && <div className="text-xs text-gray-500 whitespace-nowrap">{t('earnings.next') || 'Next Earnings'}: {nextDate}</div>}
          {events.length > 6 && (
            <button onClick={()=>setExpanded(v=>!v)} className="text-xs text-blue-600 hover:underline">
              {expanded ? (t('collapse') || 'Collapse') : (t('expand') || 'Expand')}
            </button>
          )}
        </div>
      </div>
  <div className="overflow-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr className="text-gray-600">
              <th className="px-3 py-2 text-left">{t('label.date') || 'Date'}</th>
              <th className="px-3 py-2 text-right">EPS Est.</th>
              <th className="px-3 py-2 text-right">EPS Act.</th>
              <th className="px-3 py-2 text-right">Surprise</th>
              <th className="px-3 py-2 text-right">Surprise %</th>
            </tr>
          </thead>
          <tbody>
    {events.length === 0 && (
              <tr><td className="px-3 py-4 text-center text-gray-400" colSpan={5}>{t('earnings.empty') || 'No earnings available'}</td></tr>
            )}
            {visible.map((e, idx)=> (
              <tr key={idx} className={idx % 2 ? 'bg-white' : 'bg-gray-50'}>
                <td className="px-3 py-2">{e.date}</td>
                <td className="px-3 py-2 text-right">{number(e.eps_estimate)}</td>
                <td className="px-3 py-2 text-right">{number(e.eps_actual)}</td>
                <td className="px-3 py-2 text-right">{number(e.eps_surprise)}</td>
                <td className="px-3 py-2 text-right">{number(e.surprise_percent)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default EarningsCard
