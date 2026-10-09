/**
 * 管理端接口（对应后端 routers/admin.py 与 routers/auth.py 的 /admin-login）。
 *
 * 管理端与用户端共用同一套账号体系与令牌，但拥有**独立登录入口**；
 * 服务端以 `require_admin` 依赖为真正的安全边界——前端隐藏入口与路由守卫
 * 只是体验层，绕过它们直接调接口同样返回 403。
 */
import { request } from './request'

/** 管理端登录：非管理员会被服务端 403 拒绝，且**不签发令牌**。 */
export function adminLogin(username, password) {
  return request('/api/auth/admin-login', {
    method: 'POST',
    body: { username, password },
    auth: false,
  })
}

/** 总览计数：待处理举报 / 待审学号变更 / 账号计数 / 内容规模。 */
export function getOverview() {
  return request('/api/admin/overview')
}

/**
 * 账号列表。
 * @param {{q?: string, status?: 'all'|'active'|'disabled', page?: number, pageSize?: number}} [params]
 */
export function listUsers({ q = '', status = 'all', page = 1, pageSize = 20 } = {}) {
  const params = new URLSearchParams({
    status,
    page: String(page),
    page_size: String(pageSize),
  })
  if (q) params.set('q', q)
  return request(`/api/admin/users?${params}`)
}

/** 禁用 / 启用账号（禁用三处生效：登录 / 鉴权 / WS 握手）。 */
export function setUserStatus(userId, active) {
  return request(`/api/admin/users/${userId}/status`, {
    method: 'PUT',
    body: { active },
  })
}

/** 重置用户密码。 */
export function resetUserPassword(userId, newPassword) {
  return request(`/api/admin/users/${userId}/reset-password`, {
    method: 'POST',
    body: { new_password: newPassword },
  })
}

/** 授予 / 撤销管理员权限。 */
export function setUserAdmin(userId, isAdmin) {
  return request(`/api/admin/users/${userId}/admin`, {
    method: 'PUT',
    body: { is_admin: isAdmin },
  })
}

/** ---------- 敏感词库 ---------- */

/** 词库全量列表（按添加时间倒序）。 */
export function listSensitiveWords() {
  return request('/api/admin/sensitive-words')
}

/** 新增敏感词：服务端写库后会经总线让全部实例即时生效。 */
export function addSensitiveWord(word) {
  return request('/api/admin/sensitive-words', { method: 'POST', body: { word } })
}

/** 删除敏感词。 */
export function deleteSensitiveWord(wordId) {
  return request(`/api/admin/sensitive-words/${wordId}`, { method: 'DELETE' })
}

/** 管理员直改学号（修改人与时间由后端留痕）。 */
export function setUserStudentId(userId, newStudentId) {
  return request(`/api/admin/users/${userId}/student-id`, {
    method: 'PUT',
    body: { student_id: newStudentId },
  })
}
