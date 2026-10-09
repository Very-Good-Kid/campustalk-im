/**
 * 关系域接口：好友增删改、申请流程、用户检索（对应后端 routers/friends.py）。
 *
 * 检索隐私约定：加好友仅支持「用户名精确匹配」；"找同班同学"是唯一的
 * 弱检索入口。前端不得提供按昵称 / 学号搜索的入口。
 */
import { request } from './request'

/** 用户名精确检索，返回数组（通常 0 或 1 条）。 */
export function searchUsers(username) {
  return request(`/api/users/search?q=${encodeURIComponent(username)}`)
}

/** 找同班同学（按班级精确匹配）。 */
export function getClassmates() {
  return request('/api/users/classmates')
}

/** 按 id 查用户简要资料（名片消息点击后使用）。 */
export function getUserProfile(userId) {
  return request(`/api/users/${userId}/profile`)
}

/** ---------- 好友申请 ---------- */

export function sendFriendRequest(friendId, requestMessage = null) {
  return request('/api/friends/requests', {
    method: 'POST',
    body: { friend_id: friendId, request_message: requestMessage },
  })
}

/** box = received（收到的）/ sent（发出的），仅返回 pending。 */
export function listFriendRequests(box = 'received') {
  return request(`/api/friends/requests?box=${box}`)
}

/** 处理申请：action = accept / reject。 */
export function handleFriendRequest(requestId, action) {
  return request(`/api/friends/requests/${requestId}`, {
    method: 'PUT',
    body: { action },
  })
}

/** ---------- 好友列表与信息修改 ---------- */

export function getFriends() {
  return request('/api/friends')
}

/** 好友在线快照：{ [用户id字符串]: 是否在线 }，后续变化由 WS presence 帧推送。 */
export function getFriendsOnline() {
  return request('/api/friends/online')
}

/** 修改好友信息：备注名、分组、特别关注（都是"我"持有的私有数据）。 */
export function updateFriend(friendUserId, payload) {
  return request(`/api/friends/${friendUserId}`, { method: 'PUT', body: payload })
}

/** 删除好友（后端双向删除两条记录）。 */
export function deleteFriend(friendUserId) {
  return request(`/api/friends/${friendUserId}`, { method: 'DELETE' })
}

/** 打开（或创建）与好友的私聊会话，返回 { conversation_id }。 */
export function openSingleConversation(friendId) {
  return request(`/api/friends/${friendId}/conversation`, { method: 'POST' })
}
