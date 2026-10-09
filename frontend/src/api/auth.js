/**
 * 身份域接口：注册、登录、个人资料（对应后端 routers/auth.py）。
 */
import { request } from './request'

/** 注册。成功返回用户信息（不含密码）。 */
export function register(payload) {
  return request('/api/auth/register', { method: 'POST', body: payload, auth: false })
}

/** 登录。成功返回 { access_token, user_id, nickname, is_admin }。 */
export function login(username, password) {
  return request('/api/auth/login', {
    method: 'POST',
    body: { username, password },
    auth: false,
  })
}

/** 当前登录用户资料。 */
export function getMe() {
  return request('/api/auth/me')
}

/** 修改个人资料（昵称 / 签名 / 院系 / 班级 / 头像 URL）。 */
export function updateMe(payload) {
  return request('/api/auth/me', { method: 'PUT', body: payload })
}

/** 修改密码：校验原密码，新密码需两次一致且通过后端强度校验。 */
export function changePassword(oldPassword, newPassword, confirmPassword) {
  return request('/api/auth/me/password', {
    method: 'POST',
    body: {
      old_password: oldPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    },
  })
}

/** 退出登录：通知后端记录最后在线时间（令牌失效由前端清除完成）。 */
export function logout() {
  return request('/api/auth/logout', { method: 'POST' })
}
