<script setup>
/**
 * 管理端 · 账号管理（设计 2.3.9）。
 *
 * 能力：搜索（用户名 / 昵称 / 学号）、状态筛选、分页列表、禁用与启用、
 * 重置密码、授予与撤销管理员、学号直改。禁用与撤销管理员均需二次确认。
 *
 * 禁用不是"某处加个判断"，而是三处同时拦截（登录 / 鉴权 / WS 握手），
 * 因此禁用后该账号的旧令牌会立即失效。
 */
import { onMounted, ref } from 'vue'

import ModalDialog from '@/components/ModalDialog.vue'
import {
  listUsers,
  resetUserPassword,
  setUserAdmin,
  setUserStudentId,
  setUserStatus,
} from '@/api/admin'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const toast = useToastStore()

const q = ref('')
const status = ref('all')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const items = ref([])
const loading = ref(false)

/** 通用确认浮窗 */
const confirmState = ref(null) // { title, text, action, danger }
/** 重置密码浮窗 */
const resetTarget = ref(null)
const resetPwd = ref('')
/** 学号直改浮窗 */
const sidTarget = ref(null)
const newSid = ref('')

async function load() {
  loading.value = true
  try {
    const data = await listUsers({
      q: q.value.trim(),
      status: status.value,
      page: page.value,
      pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function changePage(delta) {
  const maxPage = Math.max(1, Math.ceil(total.value / pageSize))
  const next = page.value + delta
  if (next < 1 || next > maxPage) return
  page.value = next
  load()
}

function askToggleStatus(u) {
  confirmState.value = {
    title: u.is_active ? '禁用账号' : '启用账号',
    text: u.is_active
      ? `确认禁用「${u.nickname}」？该账号将立即无法登录、已签发的令牌失效，且在线连接被断开。`
      : `确认恢复「${u.nickname}」的账号使用权？`,
    danger: u.is_active,
    action: () => setUserStatus(u.user_id, !u.is_active),
  }
}

function askToggleAdmin(u) {
  if (!u.is_admin) {
    confirmState.value = {
      title: '授予管理员权限',
      text: `确认将「${u.nickname}」设为管理员？其将可访问管理端全部功能。`,
      danger: false,
      action: () => setUserAdmin(u.user_id, true),
    }
    return
  }
  if (u.user_id === auth.user?.id) {
    toast.error('不能撤销自己的管理员权限')
    return
  }
  confirmState.value = {
    title: '撤销管理员权限',
    text: `确认撤销「${u.nickname}」的管理员权限？`,
    danger: true,
    action: () => setUserAdmin(u.user_id, false),
  }
}

async function doConfirm() {
  const st = confirmState.value
  if (!st) return
  try {
    await st.action()
    toast.success('操作成功')
    confirmState.value = null
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

function askReset(u) {
  resetTarget.value = u
  resetPwd.value = ''
}

async function doReset() {
  if (resetPwd.value.length < 6) {
    toast.error('新口令至少 6 位')
    return
  }
  try {
    await resetUserPassword(resetTarget.value.user_id, resetPwd.value)
    toast.success('口令已重置')
    resetTarget.value = null
  } catch (e) {
    toast.error(e.message)
  }
}

function askSid(u) {
  sidTarget.value = u
  newSid.value = u.student_id || ''
}

async function doSid() {
  const sid = newSid.value.trim()
  if (!sid) {
    toast.error('请填写学号')
    return
  }
  try {
    await setUserStudentId(sidTarget.value.user_id, sid)
    toast.success('学号已修改并留痕')
    sidTarget.value = null
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-users">
    <div class="toolbar card">
      <input
        v-model="q"
        class="input search"
        placeholder="搜索用户名 / 昵称 / 学号"
        @keyup.enter="search"
      />
      <select v-model="status" class="input select" @change="search">
        <option value="all">全部状态</option>
        <option value="active">正常</option>
        <option value="disabled">已禁用</option>
      </select>
      <button class="btn btn-primary" @click="search">搜索</button>
    </div>

    <div class="card table-card">
      <table class="table">
        <thead>
          <tr>
            <th>ID</th>
            <th>账号</th>
            <th>学号</th>
            <th>院系 / 班级</th>
            <th>身份</th>
            <th>状态</th>
            <th class="ops-col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in items" :key="u.user_id" :class="{ disabled: !u.is_active }">
            <td class="mono">{{ u.user_id }}</td>
            <td>
              <div class="nick">{{ u.nickname }}</div>
              <div class="sub mono">@{{ u.username }}</div>
            </td>
            <td class="mono">{{ u.student_id || '—' }}</td>
            <td>
              <div>{{ u.department || '—' }}</div>
              <div class="sub">{{ u.class_name || '—' }}</div>
            </td>
            <td>
              <span v-if="u.is_admin" class="tag tag-warning">管理员</span>
              <span v-else class="tag tag-brand">普通用户</span>
            </td>
            <td>
              <span v-if="u.is_active" class="tag tag-success">正常</span>
              <span v-else class="tag tag-error" :title="u.disabled_at ? formatDateTime(u.disabled_at) : ''">已禁用</span>
            </td>
            <td class="ops">
              <button class="btn btn-ghost btn-sm" @click="askSid(u)">改学号</button>
              <button class="btn btn-ghost btn-sm" @click="askReset(u)">重置口令</button>
              <button class="btn btn-ghost btn-sm" @click="askToggleAdmin(u)">
                {{ u.is_admin ? '撤销管理员' : '设为管理员' }}
              </button>
              <button
                class="btn btn-sm"
                :class="u.is_active ? 'btn-danger' : 'btn-primary'"
                @click="askToggleStatus(u)"
              >
                {{ u.is_active ? '禁用' : '启用' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="!loading && !items.length" class="empty"><span class="icon">🔍</span>没有符合条件的账号</div>
      <div v-if="loading" class="empty">加载中…</div>

      <div class="pager">
        <span class="pager-info">共 {{ total }} 条</span>
        <button class="btn btn-ghost btn-sm" :disabled="page <= 1" @click="changePage(-1)">上一页</button>
        <span class="pager-page">{{ page }}</span>
        <button
          class="btn btn-ghost btn-sm"
          :disabled="page * pageSize >= total"
          @click="changePage(1)"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- 二次确认 -->
    <ModalDialog
      :open="!!confirmState"
      :title="confirmState?.title || ''"
      width="400"
      @close="confirmState = null"
    >
      <p class="confirm-text">{{ confirmState?.text }}</p>
      <template #footer>
        <button class="btn btn-ghost" @click="confirmState = null">取消</button>
        <button
          class="btn"
          :class="confirmState?.danger ? 'btn-danger' : 'btn-primary'"
          @click="doConfirm"
        >
          确认
        </button>
      </template>
    </ModalDialog>

    <!-- 重置密码 -->
    <ModalDialog :open="!!resetTarget" title="重置口令" width="380" @close="resetTarget = null">
      <p class="confirm-text">为「{{ resetTarget?.nickname }}」设置新口令（至少 6 位）：</p>
      <div class="field">
        <input v-model="resetPwd" class="input" type="password" maxlength="72" />
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="resetTarget = null">取消</button>
        <button class="btn btn-primary" @click="doReset">确认重置</button>
      </template>
    </ModalDialog>

    <!-- 学号直改 -->
    <ModalDialog :open="!!sidTarget" title="修改学号" width="380" @close="sidTarget = null">
      <p class="confirm-text">
        「{{ sidTarget?.nickname }}」当前学号：{{ sidTarget?.student_id || '（未填写）' }}
      </p>
      <div class="field">
        <input v-model="newSid" class="input" maxlength="32" placeholder="新学号" />
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="sidTarget = null">取消</button>
        <button class="btn btn-primary" @click="doSid">确认修改</button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.admin-users {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.toolbar {
  display: flex;
  gap: 10px;
  padding: 14px 16px;
}
.search {
  flex: 1;
}
.select {
  width: 140px;
}
.table-card {
  padding: 6px 0 0;
}
.table {
  width: 100%;
  border-collapse: collapse;
}
.table th,
.table td {
  text-align: left;
  padding: 12px 16px;
  font-size: 13px;
  border-bottom: 1px solid var(--g-3);
  vertical-align: top;
}
.table th {
  font-size: 12px;
  font-weight: 700;
  color: var(--g-8);
  background: var(--g-2);
}
tr.disabled {
  background: var(--error-bg);
}
.nick {
  font-weight: 600;
}
.sub {
  font-size: 12px;
  color: var(--g-8);
}
.mono {
  font-family: var(--font-mono);
}
.ops-col {
  width: 300px;
}
.ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 16px;
}
.pager-info,
.pager-page {
  font-size: 12.5px;
  color: var(--g-8);
}
.confirm-text {
  font-size: 13.5px;
  color: var(--g-10);
  line-height: 1.7;
}
</style>
