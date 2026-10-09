/**
 * 会话与消息状态：会话列表（含未读）、各会话历史消息、成员列表。
 *
 * 关键约定：
 * 1. 消息以"收到 WS 回显"为准追加（后端推送覆盖会话内全部成员，含发送者
 *    本人），本地不做乐观插入，天然避免重复；
 * 2. 消息不丢的保证在后端"先落库再推送"——WS 断开时刷新页面即可补齐历史，
 *    因此发送失败不需要本地补偿队列；
 * 3. 未读红点在打开会话 / 收到新消息（会话处于打开状态）时调用已读接口归零。
 */
import { defineStore } from 'pinia'

import * as convApi from '@/api/conversations'
import { useAuthStore } from './auth'
import { useFriendsStore } from './friends'
import { useSettingsStore } from './settings'
import { useToastStore } from './toast'
import { useWebsocketStore } from './websocket'

export const useChatStore = defineStore('chat', {
  state: () => ({
    /** @type {Array} 会话列表（后端已按最后消息时间倒序） */
    conversations: [],
    /** @type {Object<number, Array>} conversationId → 消息数组（时间正序） */
    messages: {},
    /** @type {Object<number, boolean>} 是否还有更早的历史可加载 */
    hasMore: {},
    /** @type {Object<number, Array>} conversationId → 成员列表 */
    members: {},
    activeId: null,
    loading: false,
    loadingMore: false,
    /** @type {Object<string, boolean>} `${会话id}:${用户id}` → 该成员正在输入（4s 自动过期） */
    typing: {},
    /** @type {Object<string, number>} 会话id → 上次发 typing 帧的时间戳（3s 节流） */
    lastTypingSent: {},
    /** @type {Object<string, any>} typing 过期定时器（不进响应式语义，仅存句柄） */
    _typingTimers: {},
    _wsBound: false,
  }),

  getters: {
    activeConversation: (s) => s.conversations.find((c) => c.conversation_id === s.activeId) || null,
    activeMessages: (s) => (s.activeId != null ? s.messages[s.activeId] || [] : []),
    activeMembers: (s) => (s.activeId != null ? s.members[s.activeId] || [] : []),
    /** 频道置顶话题帖：从已加载消息中取 is_pinned 的一条（后端保证唯一）。 */
    activePinnedMessage(s) {
      const list = s.activeId != null ? s.messages[s.activeId] || [] : []
      return list.find((m) => m.is_pinned && !m.recalled_at) || null
    },
    totalUnread: (s) => s.conversations.reduce((sum, c) => sum + (c.unread || 0), 0),
    /** 当前打开会话里"正在输入"的成员 id（过期键值为 false，直接过滤） */
    activeTypingUids: (s) => {
      if (s.activeId == null) return []
      const prefix = s.activeId + ':'
      return Object.keys(s.typing)
        .filter((k) => k.startsWith(prefix) && s.typing[k])
        .map((k) => Number(k.slice(prefix.length)))
    },
  },

  actions: {
    /** 绑定 WS 帧订阅（AppLayout 挂载时调用一次）。 */
    bindWebsocket() {
      if (this._wsBound) return
      this._wsBound = true
      useWebsocketStore().on('receive_message', (msg) => this._onReceive(msg))
      // 系统通知：撤回 / 置顶变更，让其他在线端即时同步（无需刷新）
      useWebsocketStore().on('system_notice', (data) => this._onSystemNotice(data))
      // 好友上下线：写进 friends store 的在线表，联系人列表绿点随之刷新
      useWebsocketStore().on('presence', (data) =>
        useFriendsStore().setOnline(data.user_id, data.online)
      )
      // 输入中提示：纯展示状态，不落库不补拉
      useWebsocketStore().on('typing', (data) => this._onTyping(data))
      // 重连就绪：补断线窗口里错过的帧（消息已落库，这里只补展示层）
      useWebsocketStore().on('ws_reconnected', () => this._backfill())
    },

    async loadConversations() {
      this.conversations = await convApi.getConversations()
    },

    /** 打开会话：载入历史与成员，标记已读。 */
    async openConversation(id) {
      this.activeId = id
      this.loading = true
      try {
        const tasks = [this._ensureHistory(id), this._ensureMembers(id)]
        await Promise.all(tasks)
        await this.markRead(id)
      } finally {
        this.loading = false
      }
    },

    closeConversation() {
      this.activeId = null
    },

    /** 上滑加载更早的历史（游标 = 当前最早一条的 created_at）。 */
    async loadMore(id) {
      const list = this.messages[id]
      if (!list?.length || this.hasMore[id] === false || this.loadingMore) return
      this.loadingMore = true
      try {
        const older = await convApi.getHistory(id, list[0].created_at)
        this.messages[id] = [...older, ...list]
        this.hasMore[id] = older.length >= 20
      } finally {
        this.loadingMore = false
      }
    },

    /** 发送消息（统一出口，文本 / 表情 / 图片 / 文件 / 名片共用）。
     *  replyToId 为引用回复的目标消息 id（右键菜单的 引用 / 回复表情包）。 */
    sendMessage({ conversationId, msgType, content, fileName = null, fileSize = null, replyToId = null }) {
      useWebsocketStore().send({
        type: 'send_message',
        conversation_id: conversationId,
        msg_type: msgType,
        content,
        file_name: fileName,
        file_size: fileSize,
        reply_to_id: replyToId,
      })
    },

    async markRead(id) {
      await convApi.markRead(id)
      const conv = this.conversations.find((c) => c.conversation_id === id)
      if (conv) {
        conv.unread = 0
        conv.mention = false
      }
    },

    /** 强制刷新成员列表（邀请 / 移除成员后调用）。 */
    async loadMembers(id) {
      this.members[id] = await convApi.getMembers(id)
    },

    async recall(messageId) {
      await convApi.recallMessage(messageId)
      // 本地乐观更新；后端同时广播 system_notice，其他在线端收到后幂等更新
      for (const list of Object.values(this.messages)) {
        const msg = list.find((m) => m.id === messageId)
        if (msg) {
          msg.recalled_at = new Date().toISOString()
          msg.content = ''
        }
      }
    },

    /** 置顶 / 取消置顶：本地乐观更新（后端同时广播 system_notice）。 */
    async setPinned(conversationId, messageId, pinned) {
      if (pinned) await convApi.pinMessage(conversationId, messageId)
      else await convApi.unpinMessage(conversationId, messageId)
      for (const msg of this.messages[conversationId] || []) {
        if (msg.is_pinned && msg.id !== messageId) msg.is_pinned = false
        if (msg.id === messageId) msg.is_pinned = pinned
      }
    },

    /** 资料卡拿到最新资料后回写：把所有名片消息里该用户的头像刷新为最新。
     *
     * 头像变更是低频操作，不做 WS 广播；点开一次资料卡（此时拉到的就是最新资料）
     * 即可让已加载的名片消息无需刷新页面就更新。 */
    syncCardAvatar(userId, avatarUrl) {
      if (!userId) return
      for (const list of Object.values(this.messages)) {
        for (const m of list) {
          if (m.card_user && m.card_user.id === userId) {
            m.card_user.avatar_url = avatarUrl
          }
        }
      }
    },

    /** 本地移除会话（退群 / 退频道后调用；私聊通过删好友在列表消失）。 */
    removeConversationLocally(id) {
      this.conversations = this.conversations.filter((c) => c.conversation_id !== id)
      if (this.activeId === id) this.activeId = null
    },

    async _ensureHistory(id) {
      if (this.messages[id]) return
      const list = await convApi.getHistory(id)
      this.messages[id] = list
      this.hasMore[id] = list.length >= 20
    },

    async _ensureMembers(id) {
      if (this.members[id]) return
      this.members[id] = await convApi.getMembers(id)
    },

    /** WS（重）连成功后的回填：列表刷新未读/摘要，当前会话重拉历史与成员。
     *
     * 断线期间发出的消息已经落库，只是帧没收到——重拉一遍即补齐，
     * 不需要本地队列重发；首次连接也会走一次，重复拉取无害。
     * 失败静默：回填是锦上添花，不能因为一次 REST 报错把链路卡死。 */
    async _backfill() {
      await this.loadConversations().catch(() => {})
      const id = this.activeId
      if (id == null) return
      delete this.messages[id]
      delete this.members[id]
      await this._ensureHistory(id).catch(() => {})
      await this._ensureMembers(id).catch(() => {})
      await this.markRead(id).catch(() => {})
    },

    /** WS 收到新消息：追加到历史、刷新会话列表项、维护未读。 */
    _onReceive(msg) {
      const list = this.messages[msg.conversation_id]
      if (list && !list.some((m) => m.id === msg.id)) list.push(msg)

      const conv = this.conversations.find((c) => c.conversation_id === msg.conversation_id)
      if (conv) {
        conv.last_message = {
          id: msg.id,
          sender_id: msg.sender_id,
          sender_nickname: msg.sender_nickname,
          msg_type: msg.msg_type,
          recalled: Boolean(msg.recalled_at),
          preview: msg.content.slice(0, 30),
          created_at: msg.created_at,
        }
      }

      const uid = useAuthStore().user?.id
      if (msg.conversation_id === this.activeId) {
        // 当前会话视作已读：红点归零（不在此处调接口，打开时已标过、离开时再标）
        if (conv) {
          conv.unread = 0
          conv.mention = false
        }
      } else if (conv && msg.sender_id !== uid) {
        conv.unread = (conv.unread || 0) + 1
        // @我标记：后端已解析好 mentions，这里只管打点，刷新页面后由服务端状态自然重置
        if (Array.isArray(msg.mentions) && msg.mentions.includes(uid)) conv.mention = true
        // 非当前会话的新消息：播放提示音（关闭提示音或免打扰时内部静默）
        useSettingsStore().playNotice()
      }
    },

    /** 系统通知帧：撤回 / 置顶变更（后端 push_system_notice 广播）。
     *
     * 与 _onReceive 一样保持幂等——同一事件重复到达结果一致，
     * 因此广播包含发起者本人也不会产生副作用。 */
    _onSystemNotice(data) {
      if (!data || !data.event) return
      const cid = data.conversation_id

      if (data.event === 'message_recalled') {
        for (const list of Object.values(this.messages)) {
          const msg = list.find((m) => m.id === data.message_id)
          if (msg) {
            msg.recalled_at = data.recalled_at || new Date().toISOString()
            msg.content = ''
          }
        }
        // 会话列表摘要同步：撤回的是最后一条时，摘要不再显示原文
        const conv = this.conversations.find((c) => c.conversation_id === cid)
        if (conv?.last_message?.id === data.message_id) {
          conv.last_message.recalled = true
          conv.last_message.preview = ''
        }
        return
      }

      if (data.event === 'report_handled') {
        // 举报处置回执（reports.py 定向推给举报人）：弹一下即可，
        // 完整结果在"我的举报"列表里常驻，不依赖这条提示
        const verdict = data.status === 'resolved' ? '已受理并处理' : data.status === 'rejected' ? '经审理不成立' : data.status
        useToastStore().info(`你的举报已处理：${verdict}`)
        return
      }

      if (data.event === 'message_pinned' || data.event === 'message_unpinned') {
        const pinned = data.event === 'message_pinned'
        for (const msg of this.messages[cid] || []) {
          // 置顶唯一化：目标是唯一置顶，其余清掉
          if (pinned && msg.is_pinned && msg.id !== data.message_id) msg.is_pinned = false
          if (msg.id === data.message_id) msg.is_pinned = pinned
        }
      }
    },

    /** typing 帧：4 秒自动过期兜底（对方停下来不会发"取消"帧，只是不再续）。
     *  防御性忽略自己 uid 的帧：后端本已排除发起者，这里再筛一道。 */
    _onTyping(data) {
      if (!data || data.user_id === useAuthStore().user?.id) return
      const key = `${data.conversation_id}:${data.user_id}`
      this.typing[key] = true
      clearTimeout(this._typingTimers[key])
      this._typingTimers[key] = setTimeout(() => {
        this.typing[key] = false
        delete this._typingTimers[key]
      }, 4000)
    },

    /** 输入框每次按键调用：每会话 3s 最多发一帧 typing，持续敲字则提示常亮。 */
    notifyTyping(conversationId) {
      if (conversationId == null) return
      const now = Date.now()
      if (now - (this.lastTypingSent[conversationId] || 0) < 3000) return
      this.lastTypingSent[conversationId] = now
      useWebsocketStore().send({ type: 'typing', conversation_id: conversationId })
    },
  },
})
