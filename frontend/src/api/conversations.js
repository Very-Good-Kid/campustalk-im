/**
 * 会话域 + 消息域接口（对应后端 routers/conversations.py 与 routers/messages.py，
 * 两者共用 /api/conversations 前缀，前端按同一前缀归并一个模块）。
 */
import { request } from './request'

/** ---------- 会话 ---------- */

/** 会话列表：含未读数、最后一条消息、是否群主。 */
export function getConversations() {
  return request('/api/conversations')
}

/** 创建群聊：初始成员仅可从好友中选择。 */
export function createGroup(name, memberIds, avatarUrl = null) {
  return request('/api/conversations/group', {
    method: 'POST',
    body: { name, member_ids: memberIds, avatar_url: avatarUrl },
  })
}

/** 创建频道。 */
export function createChannel(name, description = null, avatarUrl = null) {
  return request('/api/conversations/channel', {
    method: 'POST',
    body: { name, description, avatar_url: avatarUrl },
  })
}

/** 修改群 / 频道信息（名称 / 头像 / 简介），仅群主或管理员。传空串表示清空简介。 */
export function updateConversation(conversationId, payload) {
  return request(`/api/conversations/${conversationId}`, {
    method: 'PUT',
    body: payload,
  })
}

/**
 * 设置群聊历史可见性（仅群主 / 管理员，仅群聊）。
 * @param {'all'|'since_join'|'recent_n'} mode 三种模式互斥、不叠加
 * @param {number|null} limit 仅 recent_n 时生效
 */
export function updateHistoryVisibility(conversationId, mode, limit = null) {
  return request(`/api/conversations/${conversationId}/history-visibility`, {
    method: 'PUT',
    body: { mode, limit: mode === 'recent_n' ? limit : null },
  })
}

/** 频道广场：支持关键词检索，返回各频道是否已加入。 */
export function getChannels(q = '') {
  const query = q ? `?q=${encodeURIComponent(q)}` : ''
  return request(`/api/conversations/channels${query}`)
}

/** 免审加入频道。 */
export function joinChannel(conversationId) {
  return request(`/api/conversations/${conversationId}/join`, { method: 'POST' })
}

/** 退出群聊 / 频道。 */
export function leaveConversation(conversationId) {
  return request(`/api/conversations/${conversationId}/leave`, { method: 'POST' })
}

/** ---------- 加群申请（群聊：搜索预览 → 申请 → 群主 / 管理员审批） ---------- */

/** 按群号搜索群信息（加群前预览），群不存在会返回 404。 */
export function previewGroup(conversationId) {
  return request(`/api/conversations/${conversationId}/group-preview`)
}

/** 申请加入群聊（群号 = 会话 id），附言可选。 */
export function requestJoinGroup(conversationId, message = null) {
  return request(`/api/conversations/${conversationId}/join-requests`, {
    method: 'POST',
    body: { message },
  })
}

/** box = received（待我审批）/ sent（我发出的），返回申请数组。 */
export function listGroupRequests(box = 'received') {
  return request(`/api/conversations/join-requests?box=${box}`)
}

/** 审批加群申请：action = accept / reject。 */
export function handleGroupRequest(requestId, action) {
  return request(`/api/conversations/join-requests/${requestId}`, {
    method: 'PUT',
    body: { action },
  })
}

/** ---------- 成员管理 ---------- */

export function getMembers(conversationId) {
  return request(`/api/conversations/${conversationId}/members`)
}

/** 群主 / 管理员邀请成员入群。 */
export function inviteMember(conversationId, userId) {
  return request(`/api/conversations/${conversationId}/members`, {
    method: 'POST',
    body: { user_id: userId },
  })
}

/** 群主 / 管理员移除成员。 */
export function removeMember(conversationId, userId) {
  return request(`/api/conversations/${conversationId}/members/${userId}`, {
    method: 'DELETE',
  })
}

/** ---------- 消息 ---------- */

/**
 * 历史消息（游标分页，返回值为**时间正序**）。
 * @param {string|null} cursor 上一页最早一条消息的 created_at，取更早一页
 */
export function getHistory(conversationId, cursor = null, limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  return request(`/api/conversations/${conversationId}/messages?${params}`)
}

/** 标记会话已读（更新 last_read_message_id，未读红点据此归零）。 */
export function markRead(conversationId) {
  return request(`/api/conversations/${conversationId}/read`, { method: 'POST' })
}

/** 会话内消息搜索（全文索引 ngram，单字回退 LIKE；时间倒序）。 */
export function searchMessages(conversationId, q, limit = 30) {
  return request(
    `/api/conversations/${conversationId}/search-messages?q=${encodeURIComponent(q)}&limit=${limit}`
  )
}

/** 以目标消息为锚点取前后各 20 条上下文（时间正序），供搜索结果跳转落点。 */
export function getMessagesAround(conversationId, messageId) {
  return request(`/api/conversations/${conversationId}/messages/around/${messageId}`)
}

/** 撤回本人消息（3 分钟窗口由后端校验）。 */
export function recallMessage(messageId) {
  return request(`/api/conversations/messages/${messageId}/recall`, { method: 'POST' })
}

/** 置顶 / 取消置顶话题帖（仅频道创建者）。 */
export function pinMessage(conversationId, messageId) {
  return request(`/api/conversations/${conversationId}/messages/${messageId}/pin`, {
    method: 'POST',
  })
}

export function unpinMessage(conversationId, messageId) {
  return request(`/api/conversations/${conversationId}/messages/${messageId}/pin`, {
    method: 'DELETE',
  })
}
