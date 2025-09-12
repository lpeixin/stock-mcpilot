import React from 'react'
import { NewsResponse } from '../api/api'
import { t } from '../i18n'

interface Props { data?: NewsResponse }

const NewsList: React.FC<Props> = ({ data }) => {
  const items = data?.items || []
  return (
    <div className="bg-white border rounded shadow-sm flex flex-col max-h-[240px]">
      <div className="px-4 py-2 border-b flex items-center justify-between">
        <div className="font-medium text-gray-800 truncate">{t('news.title') || 'Recent News'}</div>
        {items.length > 0 && <div className="text-xs text-gray-500">{t('news.count') || 'Count'}: {items.length}</div>}
      </div>
  <div className="flex-1 overflow-auto">
        {items.length === 0 && (
          <div className="px-3 py-4 text-gray-400 text-sm">{t('news.empty') || 'No recent news available'}</div>
        )}
        <ul className="divide-y">
          {items.map((it, idx)=> (
            <li key={idx} className="px-3 py-2 text-sm">
              <div className="text-xs text-gray-500 mb-1">{new Date(it.published_at).toLocaleString()}</div>
              <div className="text-gray-800 leading-snug">{it.text}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default NewsList
