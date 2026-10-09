/**
 * WebSocket 连接管理：全站唯一的连接点（由 AppLayout 建立）。
 *
 * 职责边界（设计 2.1 铁律"前端不持有业务规则"的对应面）：
 * 本 store 只负责 建连 / 断线重连 / 帧收发与按 type 分发，
 * 帧里的业务数据交给订阅方（chat store 等）处理。
 */
import { defineStore } from 'pinia'

import { getToken } from '@/api/token'
import { useToastStore } from './toast'

export const useWebsocketStore = defineStore('websocket', {
  state: () => ({
    connected: false,
    /** @type {WebSocket|null} */
    socket: null,
    /** @type {Map<string, Set<Function>>} 帧类型 → 订阅回调集合 */
    listeners: new Map(),
    /** 重连退避计数（简单指数退避，上限 30s） */
    retry: 0,
    _timer: null,
  }),

  actions: {
    /** 建立连接（重复调用安全：已连接或已连接中则忽略）。 */
    connect() {
      if (!getToken() || this.connected) return
      if (this.socket && this.socket.readyState === WebSocket.CONNECTING) return

      // 浏览器侧始终同源（开发期由 Vite 代理 /ws），无需关心后端地址
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${proto}://${location.host}/ws?token=${getToken()}`)
      this.socket = socket

      socket.onopen = () => {
        this.connected = true
        this.retry = 0
        // 通知订阅方连接已就绪：断线期间错过的帧由订阅方自行补拉（见 chat store）
        this._dispatch({ type: 'ws_reconnected' })
      }

      socket.onmessage = (event) => {
        let frame
        try {
          frame = JSON.parse(event.data)
        } catch {
          return
        }
        this._dispatch(frame)
      }

      socket.onclose = () => {
        this.connected = false
        this.socket = null
        // 令牌仍在才重连（退出登录后不再恢复连接）
        if (getToken()) this._scheduleReconnect()
      }

      socket.onerror = () => socket.close()
    },

    disconnect() {
      clearTimeout(this._timer)
      this.retry = 0
      if (this.socket) {
        // 主动关闭不触发重连：先摘掉 onclose
        this.socket.onclose = null
        this.socket.close()
        this.socket = null
      }
      this.connected = false
    },

    /** 订阅某类帧，返回取消订阅函数。 */
    on(type, handler) {
      if (!this.listeners.has(type)) this.listeners.set(type, new Set())
      this.listeners.get(type).add(handler)
      return () => this.listeners.get(type)?.delete(handler)
    },

    /** 发送一帧（未连接时静默丢弃：消息已落库的保证来自后端，不依赖在线状态）。 */
    send(frame) {
      if (this.connected && this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify(frame))
      }
    },

    _dispatch(frame) {
      const handlers = this.listeners.get(frame.type)
      if (handlers) for (const fn of handlers) fn(frame.data ?? frame)
      // 后端错误帧统一弹提示，业务层无需各自处理
      if (frame.type === 'error') {
        useToastStore().error(frame.detail)
      }
    },

    _scheduleReconnect() {
      clearTimeout(this._timer)
      const delay = Math.min(1000 * 2 ** this.retry++, 30000)
      this._timer = setTimeout(() => this.connect(), delay)
    },
  },
})
