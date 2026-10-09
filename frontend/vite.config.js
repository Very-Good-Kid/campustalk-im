import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发期代理：前端 5108，后端 uvicorn 5109。
// /api 与 /uploads 走 HTTP 代理；/ws 走 WebSocket 代理（ws: true）。
// 这样浏览器侧始终同源，无需关心 CORS，生产部署也可用 Nginx 同样的方式反代。
const API_TARGET = 'http://127.0.0.1:5109'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 显式绑定 IPv4 回环：默认的 'localhost' 在部分 Windows 上只监听 ::1，
    // 会导致浏览器用 127.0.0.1 访问时连不上（表现为"服务起了但页面打不开"）。
    host: '127.0.0.1',
    port: 5108,
    // 端口被占用时直接失败、不自动顺延，避免"脚本打开 A 端口、服务实际在 B 端口"
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/uploads': { target: API_TARGET, changeOrigin: true },
      '/ws': { target: API_TARGET, ws: true, changeOrigin: true },
    },
  },
})
