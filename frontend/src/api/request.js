/**
 * REST 请求封装：全站唯一的 fetch 出口。
 *
 * 职责（且仅限职责）：
 * 1. 自动拼接 Authorization: Bearer <jwt>；
 * 2. 统一解析 FastAPI 的错误结构 { detail }，抛出带可读 message 的 Error；
 * 3. 401 统一处理：清除本地令牌并跳转登录页（令牌是否过期由后端判定，
 *    前端不自行判断有效期，与系统设计 2.2.3 一致）。
 */
import { clearToken, getToken } from './token'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

/**
 * @param {string} path 以 / 开头的接口路径
 * @param {{method?: string, body?: object, formData?: FormData, auth?: boolean}} [options]
 * @returns {Promise<any>} 解析后的 JSON（204 时为 null）
 */
export async function request(path, options = {}) {
  const { method = 'GET', body, formData, auth = true } = options

  const headers = {}
  if (auth) headers.Authorization = `Bearer ${getToken()}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const resp = await fetch(path, {
    method,
    headers,
    body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
  })

  // 会话过期：清令牌回登录页。用 location 跳转而非 router，
  // 避免 api 层反向依赖 router 形成循环引用。
  // 管理端有独立登录口，按当前所处分区回到对应登录页。
  if (resp.status === 401) {
    clearToken()
    const inAdminArea = window.location.pathname.startsWith('/admin')
    window.location.href = inAdminArea ? '/admin/login' : '/login'
    throw new ApiError('登录已过期，请重新登录', 401)
  }

  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`
    try {
      const data = await resp.json()
      // FastAPI 校验错误是 { detail: [{msg}] } 数组，取第一条可读信息
      if (typeof data.detail === 'string') detail = data.detail
      else if (Array.isArray(data.detail) && data.detail.length)
        detail = data.detail[0].msg ?? detail
    } catch {
      /* 非 JSON 响应体，保留默认提示 */
    }
    throw new ApiError(detail, resp.status)
  }

  if (resp.status === 204) return null
  return resp.json()
}
