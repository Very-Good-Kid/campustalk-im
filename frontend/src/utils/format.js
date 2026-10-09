/**
 * 展示层工具函数：时间、文件大小、消息预览、表情判定。
 *
 * 重要约定：后端时间统一存 UTC，序列化为**不带时区**的 isoformat 字符串
 * （如 2026-09-10T08:00:00）。JS 的 new Date() 会把无时区字符串按本地时区
 * 解析，因此必须补 "Z" 再解析，否则时间会错一个时区。
 */

/** 把后端的 UTC 无时区 iso 字符串安全转为 Date。 */
export function parseUtc(iso) {
  if (!iso) return null
  const hasZone = iso.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`)
}

/** 消息时间：当天显示 HH:mm，否则显示 月-日 HH:mm。 */
export function formatTime(iso) {
  const d = parseUtc(iso)
  if (!d) return ''
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (sameDay) return hm
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${hm}`
}

/** 完整时间（资料 / 审核记录等场景）。 */
export function formatDateTime(iso) {
  const d = parseUtc(iso)
  if (!d) return ''
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 字节数 → 可读大小。 */
export function formatSize(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 会话列表最后一条消息的摘要文案。 */
export function messagePreview(msg) {
  if (!msg) return ''
  // 撤回摘要带发送者昵称（"某某某 撤回了一条消息"），拿不到昵称时回退为通用文案
  if (msg.recalled) {
    return msg.sender_nickname ? `${msg.sender_nickname} 撤回了一条消息` : '撤回了一条消息'
  }
  switch (msg.msg_type) {
    case 'image':
      return '[图片]'
    case 'file':
      // 后端 preview 是 URL 前 30 字符，列表摘要只显示类型即可
      return '[文件]'
    case 'emoji':
      return msg.preview
    case 'card':
      return '[好友名片]'
    default:
      return msg.preview
  }
}

// 常用表情字符集（Unicode emoji 区段），用于"纯表情消息"判定
const EMOJI_RE =
  /^[\s\p{Extended_Pictographic}\u{FE0F}\u{200D}\u{1F3FB}-\u{1F3FF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}]+$/u

/**
 * 与后端约定的表情发送策略：内容全部由表情与空白组成时，
 * 以 msg_type = emoji 落库，否则为 text（两者链路完全相同）。
 */
export function detectMsgType(content) {
  const trimmed = content.trim()
  if (trimmed && EMOJI_RE.test(trimmed)) return 'emoji'
  return 'text'
}

/** 表情面板词库：常用 Unicode 表情，直接插入文本。 */
export const EMOJIS = [
  '😀', '😄', '😂', '🤣', '😊', '😍', '😘', '😜', '🤔', '😎',
  '😭', '😅', '🙃', '😴', '🥳', '🤗', '😷', '🤒', '👍', '👏',
  '🙏', '💪', '🤝', '✌️', '👌', '❤️', '💔', '💯', '🔥', '⭐',
  '🎉', '🎂', '🎁', '🌹', '☀️', '🌙', '🌈', '⚡', '☔', '❄️',
  '📚', '✏️', '🎓', '⚽', '🏀', '🎮', '🎵', '☕', '🍜', '🍎',
]
