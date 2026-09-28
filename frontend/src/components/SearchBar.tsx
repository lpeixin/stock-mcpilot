/**
 * 代码搜索框：市场切换 + 联想下拉。
 *
 * 联想是**防抖 250ms** 的，且用 token 丢弃过期响应 —— 否则快速输入时
 * 先发的慢请求后到，会把下拉列表覆盖成上一次的搜索结果。
 */

import { useEffect, useRef, useState } from 'react'
import { searchSymbols } from '../api'
import type { Market, SearchResultItem } from '../api/types'
import type { TranslateFn } from '../i18n'
import { Spinner } from './ui'

const MARKETS: Market[] = ['US', 'HK', 'CN']
const MARKET_KEY: Record<Market, string> = {
  US: 'market.US',
  HK: 'market.HK',
  CN: 'market.CN',
}

interface Props {
  value: string
  market: Market
  loading?: boolean
  t: TranslateFn
  onValueChange: (value: string) => void
  onMarketChange: (market: Market) => void
  onSubmit: (symbol: string, market: Market) => void
}

const SearchBar: React.FC<Props> = ({
  value,
  market,
  loading = false,
  t,
  onValueChange,
  onMarketChange,
  onSubmit,
}) => {
  const [items, setItems] = useState<SearchResultItem[]>([])
  const [open, setOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const [active, setActive] = useState(-1)
  const boxRef = useRef<HTMLDivElement>(null)
  const tokenRef = useRef(0)

  useEffect(() => {
    const query = value.trim()
    if (query.length < 1) {
      setItems([])
      setSearching(false)
      return
    }
    const token = ++tokenRef.current
    setSearching(true)
    const timer = setTimeout(async () => {
      try {
        const result = await searchSymbols(query, 8)
        if (token !== tokenRef.current) return
        setItems(result.items)
        setActive(-1)
      } catch {
        if (token !== tokenRef.current) return
        setItems([])
      } finally {
        if (token === tokenRef.current) setSearching(false)
      }
    }, 250)
    return () => clearTimeout(timer)
  }, [value])

  // 点击外部收起
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const choose = (item: SearchResultItem) => {
    setOpen(false)
    onMarketChange(item.market)
    onValueChange(item.symbol)
    onSubmit(item.symbol, item.market)
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      if (open && active >= 0 && items[active]) {
        choose(items[active])
      } else {
        setOpen(false)
        onSubmit(value.trim(), market)
      }
      return
    }
    if (event.key === 'Escape') {
      setOpen(false)
      return
    }
    if (!open || items.length === 0) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((index) => (index + 1) % items.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => (index <= 0 ? items.length - 1 : index - 1))
    }
  }

  const showDropdown = open && value.trim().length > 0

  return (
    <div ref={boxRef} className="relative">
      <div className="flex items-stretch gap-2">
        <div className="flex shrink-0 items-center gap-0.5 rounded-lg border border-slate-300 bg-white p-0.5">
          {MARKETS.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onMarketChange(item)}
              className={`rounded px-2.5 py-1 text-xs transition ${
                market === item ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'
              }`}
            >
              {t(MARKET_KEY[item])}
            </button>
          ))}
        </div>

        <div className="relative flex-1">
          <input
            value={value}
            onChange={(event) => {
              onValueChange(event.target.value)
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={handleKeyDown}
            placeholder={t('search.placeholder')}
            spellCheck={false}
            autoComplete="off"
            className="h-full w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
          {searching ? (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-300">
              <Spinner className="h-3.5 w-3.5" />
            </span>
          ) : null}
        </div>

        <button
          type="button"
          disabled={loading || !value.trim()}
          onClick={() => onSubmit(value.trim(), market)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-blue-600 px-4 text-sm text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? <Spinner className="h-3.5 w-3.5" /> : null}
          {t('search.action')}
        </button>
      </div>

      {showDropdown ? (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          {items.length === 0 ? (
            <p className="px-3 py-2.5 text-xs text-slate-400">
              {searching ? t('common.loading') : t('search.noResult')}
            </p>
          ) : (
            <ul className="max-h-72 overflow-auto py-1">
              {items.map((item, index) => (
                <li key={`${item.symbol}-${item.market}-${index}`}>
                  <button
                    type="button"
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(item)}
                    className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left transition ${
                      active === index ? 'bg-slate-50' : ''
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="text-xs font-medium text-slate-800">{item.symbol}</span>
                      <span className="ml-2 truncate text-xs text-slate-400">{item.name ?? ''}</span>
                    </span>
                    <span className="shrink-0 text-[11px] text-slate-400">
                      {t(MARKET_KEY[item.market])}
                      {item.exchange ? ` · ${item.exchange}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}

export default SearchBar
