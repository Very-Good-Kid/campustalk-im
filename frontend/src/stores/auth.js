/**
 * 身份状态：令牌 + 当前用户。
 *
 * 退出登录 = 无状态 JWT 的本地失效：清除令牌、断开 WebSocket、
 * 回到登录页。服务端不维护会话白名单（设计 2.2.4 约定）。
 */
import { defineStore } from 'pinia'

import * as adminApi from '@/api/admin'
import * as authApi from '@/api/auth'
import { clearToken, getToken, setToken } from '@/api/token'
import { useWebsocketStore } from './websocket'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    /** 当前用户（/api/auth/me 的 UserOut 结构），未加载时为 null。 */
    user: null,
  }),

  getters: {
    isLoggedIn: (s) => Boolean(s.token),
    isAdmin: (s) => Boolean(s.user?.is_admin),
  },

  actions: {
    async login(username, password) {
      const data = await authApi.login(username, password)
      setToken(data.access_token)
      this.token = data.access_token
      // 登录响应只带基础字段，完整资料进布局后拉取
      this.user = { id: data.user_id, nickname: data.nickname, is_admin: data.is_admin }
      return data
    },

    /** 管理端登录：独立入口，服务端会拒绝非管理员且不签发令牌。 */
    async adminLogin(username, password) {
      const data = await adminApi.adminLogin(username, password)
      setToken(data.access_token)
      this.token = data.access_token
      this.user = { id: data.user_id, nickname: data.nickname, is_admin: data.is_admin }
      return data
    },

    async register(payload) {
      return authApi.register(payload)
    },

    /** 拉取完整资料（进入布局时与修改资料后调用）。 */
    async fetchMe() {
      this.user = await authApi.getMe()
      return this.user
    },

    async updateProfile(payload) {
      this.user = await authApi.updateMe(payload)
      return this.user
    },

    logout() {
      // 先通知后端记录最后在线时间；不等待、失败也不阻塞退出
      authApi.logout().catch(() => {})
      useWebsocketStore().disconnect()
      clearToken()
      this.token = ''
      this.user = null
    },
  },
})
