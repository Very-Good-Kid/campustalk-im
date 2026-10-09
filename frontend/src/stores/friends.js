/**
 * 联系人域状态：好友列表、收到的申请、发出的申请。
 *
 * 联系人侧边栏（分组列表、好友通知角标）与右侧资料面板共用同一份数据；
 * 进入联系人分区时由侧边栏触发 loadAll，处理申请/编辑好友后调用对应刷新。
 */
import { defineStore } from 'pinia'

import { getFriends, getFriendsOnline, listFriendRequests } from '@/api/friends'

export const useFriendsStore = defineStore('friends', {
  state: () => ({
    friends: [],
    received: [],
    sent: [],
    loaded: false,
    /** @type {Object<number, boolean>} 好友 user_id → 是否在线（快照＋presence 帧维护） */
    online: {},
  }),
  getters: {
    /** 待我处理的申请数。红点只反映它——已拒绝的记录不应让红点永远消不掉 */
    pendingReceivedCount: (s) => s.received.filter((r) => r.status === 'pending').length,
  },
  actions: {
    async loadAll() {
      const [f, r, s, o] = await Promise.all([
        getFriends(),
        listFriendRequests('received'),
        listFriendRequests('sent'),
        // 在线快照失败不阻断联系人页：顶多绿点晚一拍，presence 帧会继续修正
        getFriendsOnline().catch(() => ({ online: {} })),
      ])
      this.friends = f
      this.received = r
      this.sent = s
      this.setOnlineMap(o.online)
      this.loaded = true
    },
    /** 快照入口：后端键是字符串（JSON 限制），这里统一成数字键。 */
    setOnlineMap(map) {
      const next = {}
      for (const [uid, flag] of Object.entries(map || {})) next[Number(uid)] = !!flag
      this.online = next
    },
    /** 单点更新：WS presence 帧到达时由 chat store 转发过来。 */
    setOnline(userId, isOnline) {
      this.online[Number(userId)] = !!isOnline
    },
    async loadReceived() {
      this.received = await listFriendRequests('received')
    },
  },
})
