<script setup>
/**
 * 我的页（设计 2.3.6）：按路由拆分第一级选项——
 * /profile 个人资料：头像、昵称、签名、院系、班级（用户名与学号只读），可修改密码；
 * /profile/student-id 学号变更：用户提交证明材料申请，查看处理进展。
 *
 * 管理功能（总览 / 账号管理 / 举报处置 / 学号审核）已迁至**独立管理端**（/admin），
 * 用户端只保留侧边栏的「进入管理后台」链接，本页不再内嵌任何管理操作（设计 2.3.9）。
 *
 * 学号不可自助修改——它是"后台实名"的载体，变更必须走审核通道。
 */
import { computed, onMounted, ref } from 'vue'

import ModalDialog from '@/components/ModalDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { changePassword } from '@/api/auth'
import { uploadFile, IMAGE_ACCEPT } from '@/api/content'
import { getMyVerifications, submitStudentIdRequest } from '@/api/governance'
import { useAuthStore } from '@/stores/auth'
import { useSettingsStore, ZOOM_LEVELS } from '@/stores/settings'
import { useToastStore } from '@/stores/toast'
import { formatDateTime } from '@/utils/format'

const props = defineProps({
  /** 路由参数 /profile/:tab（缺省 info） */
  tab: { type: String, default: 'info' },
})

const auth = useAuthStore()
const toast = useToastStore()
const settings = useSettingsStore()

/** 主题 / 语言：入口保留，功能待后续接入 */
function notReady(name) {
  toast.info(`${name}功能还在开发中`)
}

/** /profile/admin 已迁至独立管理端；个人页保留 info / student-id / settings */
const PROFILE_TABS = ['student-id', 'settings']
const activeTab = computed(() => (PROFILE_TABS.includes(props.tab) ? props.tab : 'info'))

/** ---------- 基础资料 ---------- */
const form = ref({ nickname: '', bio: '', department: '', class_name: '' })
const avatarInput = ref(null)
const saving = ref(false)

onMounted(() => {
  fillForm()
  loadMyVerifications()
})

function fillForm() {
  const u = auth.user
  form.value = {
    nickname: u?.nickname || '',
    bio: u?.bio || '',
    department: u?.department || '',
    class_name: u?.class_name || '',
  }
}

async function pickAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  // 头像限制 2MB（比聊天图片严格，避免个人页加载缓慢）
  if (file.size > 2 * 1024 * 1024) {
    toast.error('头像不能超过 2MB')
    return
  }
  try {
    const data = await uploadFile(file, 'image')
    await auth.updateProfile({ avatar_url: data.url })
    toast.success('头像已更新')
  } catch (e) {
    toast.error(e.message)
  }
}

async function save() {
  if (!form.value.nickname.trim()) {
    toast.error('昵称不能为空')
    return
  }
  saving.value = true
  try {
    await auth.updateProfile({
      nickname: form.value.nickname.trim(),
      bio: form.value.bio.trim() || null,
      department: form.value.department.trim() || null,
      class_name: form.value.class_name.trim() || null,
    })
    toast.success('资料已保存')
  } catch (e) {
    toast.error(e.message)
  } finally {
    saving.value = false
  }
}

/** ---------- 修改密码 ---------- */
const showPwd = ref(false)
const pwdForm = ref({ old_password: '', new_password: '', confirm_password: '' })
const pwdSaving = ref(false)

async function submitPassword() {
  if (!pwdForm.value.old_password) {
    toast.error('请填写原密码')
    return
  }
  if (pwdForm.value.new_password.length < 6) {
    toast.error('新密码至少 6 位')
    return
  }
  if (pwdForm.value.new_password !== pwdForm.value.confirm_password) {
    toast.error('两次输入的新密码不一致')
    return
  }
  pwdSaving.value = true
  try {
    await changePassword(
      pwdForm.value.old_password,
      pwdForm.value.new_password,
      pwdForm.value.confirm_password,
    )
    toast.success('密码已修改')
    showPwd.value = false
    pwdForm.value = { old_password: '', new_password: '', confirm_password: '' }
  } catch (e) {
    toast.error(e.message)
  } finally {
    pwdSaving.value = false
  }
}

/** ---------- 学号变更申请（用户侧） ---------- */
const myRequests = ref([])
const showApply = ref(false)
const applyForm = ref({ new_student_id: '', user_note: '' })
const proofInput = ref(null)
const proofFile = ref(null)

async function loadMyVerifications() {
  try {
    myRequests.value = await getMyVerifications()
  } catch (e) {
    toast.error(e.message)
  }
}

function pickProof(event) {
  proofFile.value = event.target.files?.[0] || null
}

async function submitApply() {
  const sid = applyForm.value.new_student_id.trim()
  if (!sid) {
    toast.error('请填写新学号')
    return
  }
  if (!proofFile.value) {
    toast.error('请上传证明材料（学生证照片或学信网截图）')
    return
  }
  try {
    await submitStudentIdRequest(sid, applyForm.value.user_note.trim() || null, proofFile.value)
    toast.success('申请已提交，等待管理员核实')
    showApply.value = false
    applyForm.value = { new_student_id: '', user_note: '' }
    proofFile.value = null
    await loadMyVerifications()
  } catch (e) {
    toast.error(e.message)
  }
}

const STATUS_TEXT = { pending: '待处理', approved: '已通过', rejected: '已驳回' }
</script>

<template>
  <div class="profile-page">
    <div class="col">
      <!-- 个人资料 -->
      <div v-if="activeTab === 'info'" class="card block">
        <h3>个人资料</h3>
        <div class="avatar-row">
          <UserAvatar :name="auth.user?.nickname" :url="auth.user?.avatar_url" :size="72" />
          <button class="btn btn-ghost btn-sm" @click="avatarInput.click()">更换头像</button>
          <span class="avatar-tip">jpg / png / gif · ≤10MB</span>
          <input ref="avatarInput" type="file" :accept="IMAGE_ACCEPT" hidden @change="pickAvatar" />
        </div>

        <div class="grid2">
          <div class="field">
            <label>用户名（不可修改）</label>
            <input class="input" :value="auth.user?.username" readonly />
          </div>
          <div class="field">
            <label>学号（实名载体，不可自助修改）</label>
            <input class="input" :value="auth.user?.student_id || '未填写'" readonly />
          </div>
        </div>
        <div class="grid2">
          <div class="field">
            <label>昵称</label>
            <input v-model="form.nickname" class="input" maxlength="50" />
          </div>
          <div class="field">
            <label>个性签名</label>
            <input v-model="form.bio" class="input" maxlength="200" />
          </div>
        </div>
        <div class="grid2">
          <div class="field">
            <label>院系</label>
            <input v-model="form.department" class="input" maxlength="100" />
          </div>
          <div class="field">
            <label>班级</label>
            <input v-model="form.class_name" class="input" maxlength="100" />
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存资料' }}
          </button>
          <button class="btn btn-ghost" @click="showPwd = true">修改密码</button>
        </div>
      </div>

      <!-- 学号变更申请 -->
      <div v-else-if="activeTab === 'student-id'" class="card block">
        <div class="block-head">
          <h3>学号变更申请</h3>
          <button class="btn btn-ghost btn-sm" @click="showApply = true">提交申请</button>
        </div>
        <p class="hint">学号是后台实名载体，不可自助修改；转专业、留级等情形请提交证明材料（学生证照片 / 学信网截图），由管理员核实后变更。</p>
        <div v-for="r in myRequests" :key="r.request_id" class="apply-row">
          <span class="mono">{{ r.old_student_id || '（原为空）' }} → {{ r.new_student_id }}</span>
          <span class="tag" :class="r.status === 'approved' ? 'tag-success' : r.status === 'rejected' ? 'tag-error' : 'tag-warning'">
            {{ STATUS_TEXT[r.status] }}
          </span>
          <span v-if="r.review_note" class="review-note">{{ r.review_note }}</span>
          <span class="time">{{ formatDateTime(r.created_at) }}</span>
        </div>
        <div v-if="!myRequests.length" class="empty"><span class="icon">📄</span>暂无变更申请记录</div>
      </div>

      <!-- 设置：偏好仅保存在本机；主题与语言为后续规划项，入口先保留 -->
      <div v-else class="card block">
        <h3>设置</h3>
        <p class="hint">以下偏好仅保存在本机浏览器，不会上传到服务器。</p>

        <div class="setting-group">
          <div class="setting-title">消息与提醒</div>
          <div class="setting-row">
            <div class="setting-mid">
              <div class="setting-name">消息提示音</div>
              <div class="setting-sub">收到新消息时播放一声提示音</div>
            </div>
            <button
              class="switch"
              :class="{ on: settings.sound }"
              :aria-pressed="settings.sound"
              @click="settings.setSound(!settings.sound)"
            >
              <span class="knob"></span>
            </button>
          </div>
          <div class="setting-row">
            <div class="setting-mid">
              <div class="setting-name">免打扰</div>
              <div class="setting-sub">开启后不再播放消息提示音</div>
            </div>
            <button
              class="switch"
              :class="{ on: settings.dnd }"
              :aria-pressed="settings.dnd"
              @click="settings.setDnd(!settings.dnd)"
            >
              <span class="knob"></span>
            </button>
          </div>
        </div>

        <div class="setting-group">
          <div class="setting-title">外观</div>
          <div class="setting-row">
            <div class="setting-mid">
              <div class="setting-name">界面缩放</div>
              <div class="setting-sub">整体放大 / 缩小（含字号）</div>
            </div>
            <div class="zoom-pick">
              <button
                v-for="z in ZOOM_LEVELS"
                :key="z.value"
                :class="{ on: settings.zoom === z.value }"
                @click="settings.setZoom(z.value)"
              >
                {{ z.label }}
              </button>
            </div>
          </div>
          <div class="setting-row">
            <div class="setting-mid">
              <div class="setting-name">主题</div>
              <div class="setting-sub">深色 / 浅色</div>
            </div>
            <button class="btn btn-ghost btn-sm" @click="notReady('主题切换')">浅色（开发中）</button>
          </div>
          <div class="setting-row">
            <div class="setting-mid">
              <div class="setting-name">语言</div>
              <div class="setting-sub">界面语言</div>
            </div>
            <button class="btn btn-ghost btn-sm" @click="notReady('语言切换')">简体中文（开发中）</button>
          </div>
        </div>

        <div class="setting-group">
          <div class="setting-title">关于</div>
          <div class="setting-row">
            <div class="setting-mid">
              <div class="setting-name">CampusTalk 校园即时通讯系统</div>
              <div class="setting-sub">版本 0.1.0 · 个人实践项目</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 提交学号变更申请 -->
    <ModalDialog :open="showApply" title="提交学号变更申请" @close="showApply = false">
      <div class="field">
        <label>新学号</label>
        <input v-model="applyForm.new_student_id" class="input" maxlength="32" />
      </div>
      <div class="field">
        <label>变更说明（如：转专业 / 教务录入错误）</label>
        <textarea v-model="applyForm.user_note" class="input" rows="2" maxlength="200"></textarea>
      </div>
      <div class="field">
        <label>证明材料（jpg / png / webp · ≤10MB）</label>
        <button class="btn btn-ghost btn-sm" @click="proofInput.click()">
          {{ proofFile ? `已选择：${proofFile.name}` : '选择图片' }}
        </button>
        <input ref="proofInput" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="pickProof" />
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showApply = false">取消</button>
        <button class="btn btn-primary" @click="submitApply">提交申请</button>
      </template>
    </ModalDialog>

    <!-- 修改密码 -->
    <ModalDialog :open="showPwd" title="修改密码" width="380" @close="showPwd = false">
      <div class="field">
        <label>原密码</label>
        <input v-model="pwdForm.old_password" class="input" type="password" maxlength="72" />
      </div>
      <div class="field">
        <label>新密码（至少 6 位，不得与原密码或用户名相同）</label>
        <input v-model="pwdForm.new_password" class="input" type="password" maxlength="72" />
      </div>
      <div class="field">
        <label>确认新密码</label>
        <input v-model="pwdForm.confirm_password" class="input" type="password" maxlength="72" />
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showPwd = false">取消</button>
        <button class="btn btn-primary" :disabled="pwdSaving" @click="submitPassword">
          {{ pwdSaving ? '提交中…' : '确认修改' }}
        </button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.profile-page {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  display: flex;
  gap: 20px;
  align-items: flex-start;
  min-height: 0;
}
.col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.block {
  padding: 22px 24px;
}
.block h3 {
  font-size: 16px;
  margin-bottom: 14px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.block-head h3 {
  margin-bottom: 0;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}
.btn-row {
  display: flex;
  gap: 10px;
}
.avatar-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}
.avatar-tip {
  font-size: 12px;
  color: var(--g-7);
}
.hint {
  font-size: 12.5px;
  color: var(--g-8);
  margin-bottom: 12px;
}
.apply-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--g-3);
  font-size: 13px;
  flex-wrap: wrap;
}
.review-note {
  color: var(--g-9);
  font-size: 12px;
}
.time {
  margin-left: auto;
  font-size: 11px;
  color: var(--g-7);
}
.mono {
  font-family: var(--font-mono);
}

/* ---------- 设置面板 ---------- */
.setting-group {
  border-top: 1px solid var(--g-3);
  padding-top: 14px;
  margin-top: 14px;
}
.setting-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--g-8);
  margin-bottom: 4px;
}
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 9px 0;
}
.setting-mid {
  min-width: 0;
}
.setting-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--g-11);
}
.setting-sub {
  font-size: 12px;
  color: var(--g-8);
}
/* 开关：纯 CSS 实现，不引入第三方组件 */
.switch {
  flex: none;
  position: relative;
  width: 42px;
  height: 24px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: var(--g-5);
  cursor: pointer;
  transition: background 0.15s;
}
.switch.on {
  background: var(--brand-7);
}
.switch .knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.15s;
}
.switch.on .knob {
  transform: translateX(18px);
}
/* 缩放档位选择 */
.zoom-pick {
  flex: none;
  display: flex;
  gap: 4px;
  padding: 3px;
  background: var(--g-3);
  border-radius: var(--radius-s);
}
.zoom-pick button {
  border: none;
  background: none;
  border-radius: calc(var(--radius-s) - 2px);
  font-size: 12.5px;
  color: var(--g-9);
  padding: 3px 12px;
  cursor: pointer;
  font-family: var(--font-cjk);
}
.zoom-pick button.on {
  background: var(--g-1);
  color: var(--brand-7);
  font-weight: 700;
}
</style>
