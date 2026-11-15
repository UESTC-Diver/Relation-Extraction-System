import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // 不再靠抬高阈值把体积警告藏起来；按路由与图表库自然分包后应低于该值。
    // Element Plus 整套注册只在 /app 动态加载（见 main.js），首页不下载它。
    chunkSizeWarningLimit: 600,
  },
})
