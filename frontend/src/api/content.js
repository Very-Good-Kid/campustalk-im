/**
 * 内容域接口：图片 / 文件上传（对应后端 routers/uploads.py）。
 *
 * 约定：返回的 url 存入消息 content 字段，二进制绝不进 WebSocket 帧。
 * 类型与大小的前端校验只是体验优化，服务端会重复校验。
 */
import { request } from './request'

export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/gif'
export const IMAGE_MAX = 10 * 1024 * 1024
export const FILE_MAX = 50 * 1024 * 1024

/**
 * 上传文件。
 * @param {File} file
 * @param {'image'|'file'} kind 仅用于前端提前拦截，服务端按 MIME 白名单判定
 * @returns {Promise<{url: string, file_name: string, file_size: number, kind: string}>}
 */
export async function uploadFile(file, kind = 'file') {
  const max = kind === 'image' ? IMAGE_MAX : FILE_MAX
  if (file.size > max) {
    throw new Error(`文件超过 ${Math.floor(max / 1024 / 1024)}MB 上限`)
  }

  const formData = new FormData()
  formData.append('file', file)

  return request('/api/upload', { method: 'POST', formData })
}
