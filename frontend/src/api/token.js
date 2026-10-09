/**
 * 令牌存取：localStorage 的唯一读写点。
 *
 * 独立成模块是为了让 request.js（无 Pinia 上下文）与 auth store
 * 都能拿到 token，且避免两者互相依赖。
 */
const KEY = 'ct_token'

export function getToken() {
  return localStorage.getItem(KEY) || ''
}

export function setToken(token) {
  localStorage.setItem(KEY, token)
}

export function clearToken() {
  localStorage.removeItem(KEY)
}
