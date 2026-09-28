/**
 * 外部链接处理。
 *
 * 桌面壳（Tauri）的 webview 会拦下 `window.open` / `target="_blank"`，
 * 用户点新闻原文会**毫无反应**。所以壳里必须走 opener 插件
 * （权限见 `src-tauri/capabilities/default.json` 的 `opener:default`）。
 *
 * 浏览器里则原样交给 `<a target="_blank">`，不要插一手 —— 自己
 * `preventDefault` + `window.open` 会破坏中键、Ctrl+点击这些原生行为。
 */

import { isDesktop, tauriGlobal } from '../api/client'

/** 在系统默认浏览器里打开链接；壳里失败时退回浏览器行为。 */
export function openExternal(url: string): void {
  const opener = tauriGlobal()?.opener
  if (opener?.openUrl) {
    void opener.openUrl(url).catch(() => {
      window.open(url, '_blank', 'noopener,noreferrer')
    })
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

/**
 * 给外部链接的 `onClick` 用。
 *
 * 只在桌面壳里接管；浏览器里什么都不做，让链接保持原生语义。
 */
export function interceptExternalClick(
  event: React.MouseEvent<HTMLAnchorElement>,
  url: string,
): void {
  if (!isDesktop()) return
  // 让用户仍能用中键 / 修饰键走自己的习惯
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
  event.preventDefault()
  openExternal(url)
}
