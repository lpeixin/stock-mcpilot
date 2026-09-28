/**
 * 极简 Markdown 渲染。
 *
 * 只覆盖模型实际会输出的那几种结构：标题、无序/有序列表、粗体、行内代码、
 * 分隔线、段落。不引第三方库 —— 为一个只读展示面板装一个 markdown 解析器
 * 不划算，而且流式输出下每次增量重解析整个文档，越轻越好。
 */

import type { ReactNode } from 'react'

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = []
  const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g
  let cursor = 0
  let index = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) parts.push(text.slice(cursor, match.index))
    const token = match[0]
    const key = `${keyPrefix}-i${index++}`
    if (token.startsWith('**')) {
      parts.push(
        <strong key={key} className="font-semibold text-slate-900">
          {token.slice(2, -2)}
        </strong>,
      )
    } else {
      parts.push(
        <code key={key} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px]">
          {token.slice(1, -1)}
        </code>,
      )
    }
    cursor = match.index + token.length
  }
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts
}

interface Props {
  text: string
  /** 流式输出时在末尾显示光标。 */
  streaming?: boolean
}

const Markdown: React.FC<Props> = ({ text, streaming = false }) => {
  // 把光标字符直接拼进正文，它就会落在最后一段的行内；否则会另起一行。
  const lines = (streaming && text ? `${text} ▍` : text).split('\n')
  const blocks: ReactNode[] = []
  let listBuffer: string[] = []
  let listOrdered = false
  let key = 0

  const flushList = () => {
    if (listBuffer.length === 0) return
    const items = listBuffer
    listBuffer = []
    const Tag = listOrdered ? 'ol' : 'ul'
    blocks.push(
      <Tag
        key={`l${key++}`}
        className={`my-2 space-y-1 pl-5 text-sm leading-relaxed text-slate-700 ${
          listOrdered ? 'list-decimal' : 'list-disc'
        }`}
      >
        {items.map((item, index) => (
          <li key={index}>{renderInline(item, `l${key}-${index}`)}</li>
        ))}
      </Tag>,
    )
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line)
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line)

    if (bullet || ordered) {
      if (listBuffer.length > 0 && listOrdered !== Boolean(ordered)) flushList()
      listOrdered = Boolean(ordered)
      listBuffer.push((bullet?.[1] ?? ordered?.[1] ?? '').trim())
      continue
    }

    flushList()

    if (!line.trim()) continue

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push(<hr key={`h${key++}`} className="my-3 border-slate-100" />)
      continue
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const size =
        level <= 2 ? 'text-sm font-semibold' : level === 3 ? 'text-xs font-semibold' : 'text-xs font-medium'
      blocks.push(
        <p key={`t${key++}`} className={`mb-1 mt-3 first:mt-0 ${size} text-slate-900`}>
          {renderInline(heading[2], `t${key}`)}
        </p>,
      )
      continue
    }

    blocks.push(
      <p key={`p${key++}`} className="my-1.5 text-sm leading-relaxed text-slate-700">
        {renderInline(line, `p${key}`)}
      </p>,
    )
  }

  flushList()

  return (
    <div className="[&>*:first-child]:mt-0 [&>*:last-child]:mb-0">{blocks}</div>
  )
}

export default Markdown
