/**
 * 新闻列表。
 *
 * 每条都带原文链接（后端已保证 URL 存在）。浏览器里靠 `target="_blank"` 打开；
 * 桌面壳里 webview 会拦下它，得交给 opener 插件 —— 见 `interceptExternalClick`。
 */

import type { NewsItem } from '../api/types'
import type { TranslateFn } from '../i18n'
import { interceptExternalClick } from '../utils/external'
import { fmtDateTime, fmtRelative } from '../utils/format'
import { Card, EmptyState } from './ui'

interface Props {
  items: NewsItem[]
  loading?: boolean
  t: TranslateFn
}

const NewsList: React.FC<Props> = ({ items, loading = false, t }) => (
  <Card
    title={t('news.title')}
    subtitle={items.length > 0 ? t('news.count', { n: items.length }) : undefined}
    flush
  >
    {items.length === 0 ? (
      <EmptyState text={loading ? t('common.loading') : t('news.empty')} compact />
    ) : (
      <ul className="divide-y divide-slate-50">
        {items.map((item, index) => {
          const meta = [item.publisher, fmtRelative(item.published_at) || fmtDateTime(item.published_at)]
            .filter(Boolean)
            .join(' · ')
          const body = (
            <>
              <p className="text-xs leading-relaxed text-slate-800 group-hover:text-blue-700">
                {item.title}
              </p>
              {item.summary ? (
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-400">
                  {item.summary}
                </p>
              ) : null}
              <p className="mt-1 text-[11px] text-slate-400">{meta}</p>
            </>
          )
          return (
            <li key={`${item.url ?? item.title}-${index}`}>
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(event) => interceptExternalClick(event, item.url as string)}
                  className="group block px-4 py-2.5 transition hover:bg-slate-50"
                >
                  {body}
                </a>
              ) : (
                <div className="px-4 py-2.5">{body}</div>
              )}
            </li>
          )
        })}
      </ul>
    )}
  </Card>
)

export default NewsList
