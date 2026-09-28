/** HTTP 客户端与 SSE 工具。 */

import axios, { AxiosError } from 'axios'
import type {
  SSEEvent,
} from './types'

/**
 * 桌面壳注入的全局对象（`app.withGlobalTauri: true`）。
 *
 * 刻意不用 `@tauri-apps/api` 这个包：前端要能**独立跑在浏览器里**
 * （`vite dev` 调后端是主要开发方式），为两个调用点引一个只在壳里有意义的
 * 依赖不划算。这里用可选的全局对象，缺失时安静降级。
 */
export interface TauriGlobal {
  core?: { invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown> }
  opener?: { openUrl?: (url: string) => Promise<void> }
}

export function tauriGlobal(): TauriGlobal | undefined {
  return (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__
}

export function isDesktop(): boolean {
  return typeof tauriGlobal()?.core?.invoke === 'function'
}

const DEFAULT_API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) || 'http://127.0.0.1:8000'

let apiBase = DEFAULT_API_BASE

/** 当前使用的后端地址（只读）。 */
export function getApiBase(): string {
  return apiBase
}

export const http = axios.create({ baseURL: apiBase, timeout: 60000 })

/**
 * 确定后端地址，桌面壳里问一次壳。
 *
 * 为什么不能硬编码：8000 被别的服务占用时后端会顺延到 8001、8002……
 * （见 `src-tauri/src/backend.rs` 的 `choose_port`）。硬编码的话界面会一直显示
 * "无法连接后端"，而后端其实好好跑着 —— 这种"两边各自都对、合起来不对"的
 * 问题最难查。
 *
 * 后端冷启动要十几秒，所以这个函数会被反复调用：壳里还没就绪时它会安静地
 * 保持原值，下一次轮询再问。
 */
export async function resolveApiBase(): Promise<string> {
  const invoke = tauriGlobal()?.core?.invoke
  if (typeof invoke !== 'function') return apiBase

  try {
    const url = await invoke('backend_base_url')
    if (typeof url === 'string' && url) {
      apiBase = url
      http.defaults.baseURL = url
    }
  } catch {
    /* 壳里还没拿到后端，保持原值 */
  }
  return apiBase
}

/** 把后端返回的错误整理成一句人话。 */
function describeError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<{ detail?: unknown }>
    const detail = axiosError.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    if (Array.isArray(detail)) {
      // FastAPI 的参数校验错误
      const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined
      if (first?.msg) {
        const where = Array.isArray(first.loc) ? first.loc.slice(1).join('.') : ''
        return where ? `${where}: ${first.msg}` : first.msg
      }
    }
    if (axiosError.code === 'ECONNABORTED') return '请求超时，后端可能仍在处理。'
    if (!axiosError.response) {
      return `无法连接后端（${apiBase}）。请确认服务已启动。`
    }
    return `请求失败（HTTP ${axiosError.response.status}）。`
  }
  if (error instanceof Error) return error.message
  return '发生未知错误。'
}

http.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(new Error(describeError(error))),
)

/**
 * 消费 SSE 流。
 *
 * 用 fetch 而不是 axios —— 浏览器端 axios 拿不到增量响应体，只能等流结束。
 */
export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${apiBase}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') return
    throw new Error(`无法连接后端（${apiBase}）。请确认服务已启动。`)
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）。`
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string') detail = payload.detail
    } catch {
      /* 忽略解析失败 */
    }
    throw new Error(detail)
  }
  if (!response.body) throw new Error('后端未返回流式响应体。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (raw: string) => {
    for (const line of raw.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      const payload = trimmed.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload) as SSEEvent)
      } catch {
        /* 忽略坏帧 */
      }
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        dispatch(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer)
  } catch (error) {
    if ((error as Error).name !== 'AbortError') throw error
  } finally {
    reader.releaseLock?.()
  }
}

export { describeError }
