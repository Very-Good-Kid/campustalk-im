/**
 * 加群申请状态：收到的（我作为群主 / 管理员待处理）与我发出的申请。
 *
 * 与好友申请（friends store）同构：联系人侧边栏的「群通知」角标与
 * 群通知页共用这份数据，处理完申请后调用 loadAll 刷新。
 */
import { defineStore } from 'pinia'

import { listGroupRequests } from '@/api/conversations'

export const useGroupRequestsStore = defineStore('groupRequests', {
  state: () => ({
    received: [],
    sent: [],
    loaded: false,
  }),
  getters: {
    /** 待我审批的加群申请数（角标只反映它，已拒绝的不会让红点消不掉） */
    pendingReceivedCount: (s) => s.received.filter((r) => r.status === 'pending').length,
  },
  actions: {
    async loadAll() {
      const [received, sent] = await Promise.all([
        listGroupRequests('received'),
        listGroupRequests('sent'),
      ])
      this.received = received
      this.sent = sent
      this.loaded = true
    },
  },
})
