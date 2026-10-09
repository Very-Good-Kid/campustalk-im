/**
 * 治理域接口：举报提交与处置、学号变更申请与审核。
 * （对应后端 routers/reports.py、verifications.py）
 *
 * 注意：管理端的账号治理接口（禁用/启用、重置密码、授权、学号直改）
 * 已集中于 `api/admin.js`，本模块不再承载。
 */
import { request } from './request'

/** ---------- 举报 ---------- */

export function createReport(messageId, reason) {
  return request('/api/reports', {
    method: 'POST',
    body: { message_id: messageId, reason },
  })
}

/** 管理员：举报列表，status = pending / resolved / rejected / all。 */
export function listReports(status = 'pending') {
  return request(`/api/reports?status=${status}`)
}

/**
 * 管理员处置举报。
 * @param {'resolved'|'rejected'} action
 * @param {'none'|'ban'} [punish] resolved 时可一并封禁被举报消息的发布者
 */
export function handleReport(reportId, action, punish = 'none') {
  return request(`/api/reports/${reportId}`, { method: 'PUT', body: { action, punish } })
}

/** ---------- 学号变更（用户侧） ---------- */

/**
 * 提交学号变更申请。证明材料走 multipart Form（new_student_id / user_note / proof）。
 */
export function submitStudentIdRequest(newStudentId, userNote, proofFile) {
  const formData = new FormData()
  formData.append('new_student_id', newStudentId)
  if (userNote) formData.append('user_note', userNote)
  formData.append('proof', proofFile)
  return request('/api/verifications/student-id', { method: 'POST', formData })
}

/** 我提交的学号变更申请与处理进展。 */
export function getMyVerifications() {
  return request('/api/verifications/my')
}

/** ---------- 学号变更（管理员侧） ---------- */

export function listVerificationRequests(reqStatus = 'pending') {
  return request(`/api/verifications?req_status=${reqStatus}`)
}

/**
 * 审核学号变更：action = approve / reject（驳回必须附 note）。
 * 返回的是 FileResponse（图片二进制），需转 ObjectURL 展示。
 */
export function reviewVerification(requestId, action, note = null) {
  return request(`/api/verifications/${requestId}/review`, {
    method: 'POST',
    body: { action, note },
  })
}

/** 管理员调阅证明材料（带鉴权的图片二进制，调用方负责转 ObjectURL）。 */
export async function fetchProof(requestId) {
  const resp = await fetch(`/api/verifications/${requestId}/proof`, {
    headers: { Authorization: `Bearer ${localStorage.getItem('ct_token') || ''}` },
  })
  if (!resp.ok) {
    let detail = `读取失败（${resp.status}）`
    try {
      detail = (await resp.json()).detail ?? detail
    } catch {
      /* 二进制响应无 JSON */
    }
    throw new Error(detail)
  }
  return URL.createObjectURL(await resp.blob())
}

