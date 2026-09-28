import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Tauri 的 devUrl 写死了 5173，端口被占时宁可失败也不要悄悄换端口，
    // 否则壳窗口会加载到一个空白页。
    strictPort: true,
  },
  build: {
    // ECharts 占了产物的绝大部分体积。单独成块后主包小很多，
    // 升级业务代码时 ECharts 那一块还能命中缓存。
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'],
          vendor: ['react', 'react-dom', 'zustand', 'axios'],
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
})
