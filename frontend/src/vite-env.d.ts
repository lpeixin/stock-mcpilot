/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}

/**
 * 桌面壳注入的全局对象（`app.withGlobalTauri: true`）。
 *
 * 这里只声明实际用到的两个能力。刻意不引 `@tauri-apps/api` 的类型包：
 * 前端要能独立跑在浏览器里，为一个可选依赖拉一整套类型不划算。
 */
interface Window {
  __TAURI__?: {
    core?: {
      invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>
    }
    opener?: {
      openUrl?: (url: string) => Promise<void>
    }
  }
}
