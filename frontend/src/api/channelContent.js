/**
 * 频道内容域接口（对应后端 routers/channels.py）：
 * 帖子 / 评论 / 点赞——频道作为"论坛 / 朋友圈式内容社区"的内容层，
 * 与消息流（conversations.js 的消息接口）相互独立。
 */
import { request } from './request'

/** ---------- 帖子 ---------- */

/**
 * 帖子列表。
 * @param {'time'|'hot'} sort time=时间序（置顶优先），hot=热度序（点赞/评论数优先）
 * @returns 帖子数组（少于 limit 条即无更多）
 */
export function getPosts(conversationId, { sort = 'time', limit = 10, offset = 0 } = {}) {
  const params = new URLSearchParams({ sort, limit: String(limit), offset: String(offset) })
  return request(`/api/conversations/${conversationId}/posts?${params}`)
}

/** 发帖：content / images / cardUserId 至少一项非空。cardUserId 用于"分享好友名片"。 */
export function createPost(conversationId, { content = '', images = [], cardUserId = null }) {
  return request(`/api/conversations/${conversationId}/posts`, {
    method: 'POST',
    body: { content, images, card_user_id: cardUserId },
  })
}

/** 帖子详情。 */
export function getPost(conversationId, postId) {
  return request(`/api/conversations/${conversationId}/posts/${postId}`)
}

/** 编辑帖子（仅作者本人）。 */
export function updatePost(conversationId, postId, { content = '', images = [] }) {
  return request(`/api/conversations/${conversationId}/posts/${postId}`, {
    method: 'PUT',
    body: { content, images },
  })
}

/** 删除帖子（本人 / 管理员，软删）。 */
export function deletePost(conversationId, postId) {
  return request(`/api/conversations/${conversationId}/posts/${postId}`, { method: 'DELETE' })
}

/** 置顶 / 取消置顶（仅频道管理）。 */
export function pinPost(conversationId, postId, pinned) {
  return request(`/api/conversations/${conversationId}/posts/${postId}/pin`, {
    method: pinned ? 'POST' : 'DELETE',
  })
}

/** ---------- 评论 ---------- */

/** 评论列表：两级扁平返回，parent_id 指向一级评论即为二级回复。 */
export function getComments(conversationId, postId) {
  return request(`/api/conversations/${conversationId}/posts/${postId}/comments`)
}

/** 发表评论；parentId 传一级评论 id 即为回复。 */
export function createComment(conversationId, postId, content, parentId = null) {
  return request(`/api/conversations/${conversationId}/posts/${postId}/comments`, {
    method: 'POST',
    body: { content, parent_id: parentId },
  })
}

/** 删除评论（本人 / 管理员，软删）。 */
export function deleteComment(conversationId, commentId) {
  return request(`/api/conversations/${conversationId}/comments/${commentId}`, {
    method: 'DELETE',
  })
}

/** ---------- 点赞 ---------- */

/** 点赞 / 取消点赞帖子。 */
export function likePost(conversationId, postId, liked) {
  return request(`/api/conversations/${conversationId}/posts/${postId}/like`, {
    method: liked ? 'POST' : 'DELETE',
  })
}

/** 点赞 / 取消点赞评论。 */
export function likeComment(conversationId, commentId, liked) {
  return request(`/api/conversations/${conversationId}/comments/${commentId}/like`, {
    method: liked ? 'POST' : 'DELETE',
  })
}
