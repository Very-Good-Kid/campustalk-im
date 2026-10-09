<script setup>
/**
 * 管理端 · 举报处置（设计 2.3.9）。
 *
 * 隐私边界（有意不做的事）：**只呈现被举报的那一条消息**，
 * 不提供浏览任意用户聊天记录的能力——权限最小化与数据最小化的落地。
 */
import { onMounted, ref } from 'vue'

import ModalDialog from '@/components/ModalDialog.vue'
import { handleReport, listReports } from '@/api/governance'
import { useToastStore } from '@/stores/toast'
import { formatDateTime } from '@/utils/format'

const toast = useToastStore()

const status = ref('pending')
const reports = ref([])
const loading = ref(false)

const STATUS_OPTIONS = [
  { value: 'pending', label: '待处理' },
  { value: 'resolved', label: '已处理' },
  { value: 'rejected', label: '已驳回' },
  { value: 'all', label: '全部' },
]

const STATUS_TEXT = { pending: '待处理', resolved: '已处理', rejected: '已驳回' }
const STATUS_TAG = { pending: 'tag-warning', resolved: 'tag-success', rejected: 'tag-error' }

async function load() {
  loading.value = true
  try {
    reports.value = await listReports(status.value)
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

async function onHandle(reportId, action) {
  try {
    await handleReport(reportId, action)
    toast.success(action === 'resolved' ? '已标记为处理完毕' : '已驳回举报')
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

/** 处理并封禁发布者（二次确认后执行） */
const banTarget = ref(null)

async function doBan() {
  try {
    const res = await handleReport(banTarget.value.report_id, 'resolved', 'ban')
    toast.success(res.banned ? `已处置，并封禁发布者「${res.banned}」` : '已处置')
    banTarget.value = null
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

onMounted(load)
</script>

<template>
  <div class="admin-page">
    <div class="filter card">
      <button
        v-for="o in STATUS_OPTIONS"
        :key="o.value"
        class="tab"
        :class="{ active: status === o.value }"
        @click="status = o.value; load()"
      >
        {{ o.label }}
      </button>
    </div>

    <div class="card list-card">
      <div v-for="r in reports" :key="r.report_id" class="row">
        <div class="main">
          <div class="line">
            <span class="strong">{{ r.reporter }}</span> 举报了
            <span class="mono">消息 #{{ r.message_id }}</span>
            <span class="tag" :class="STATUS_TAG[r.status]">{{ STATUS_TEXT[r.status] }}</span>
          </div>
          <div class="quote">"{{ r.message_content }}"</div>
          <div class="sub">理由：{{ r.reason }}</div>
          <div class="sub time">{{ formatDateTime(r.created_at) }}</div>
        </div>
        <div v-if="r.status === 'pending'" class="ops">
          <button class="btn btn-primary btn-sm" @click="onHandle(r.report_id, 'resolved')">处理完毕</button>
          <button class="btn btn-danger btn-sm" @click="banTarget = r">处理并封禁</button>
          <button class="btn btn-ghost btn-sm" @click="onHandle(r.report_id, 'rejected')">驳回</button>
        </div>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!reports.length" class="empty"><span class="icon">✅</span>暂无该状态的举报</div>
    </div>

    <!-- 处理并封禁：二次确认 -->
    <ModalDialog
      :open="!!banTarget"
      title="处理并封禁发布者"
      width="420"
      @close="banTarget = null"
    >
      <p class="confirm-text">
        确认将举报「消息 #{{ banTarget?.message_id }}」标记为已处理，并封禁其发布者？
      </p>
      <p class="confirm-text">
        封禁后该账号将立即无法登录、已签发的令牌失效、在线连接被断开（禁用三处同时生效）。
      </p>
      <template #footer>
        <button class="btn btn-ghost" @click="banTarget = null">取消</button>
        <button class="btn btn-danger" @click="doBan">确认处置并封禁</button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.filter {
  display: flex;
  gap: 6px;
  padding: 12px 14px;
}
.tab {
  height: 30px;
  padding: 0 14px;
  border: 1px solid var(--g-5);
  border-radius: var(--radius-s);
  background: var(--g-1);
  font-size: 12.5px;
  color: var(--g-9);
  cursor: pointer;
  font-family: var(--font-cjk);
}
.tab.active {
  background: var(--brand-1);
  border-color: var(--brand-3);
  color: var(--brand-7);
  font-weight: 700;
}
.list-card {
  padding: 6px 20px;
}
.row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--g-3);
}
.row:last-child {
  border-bottom: none;
}
.main {
  min-width: 0;
  font-size: 13px;
}
.line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.strong {
  font-weight: 700;
}
.mono {
  font-family: var(--font-mono);
}
.quote {
  background: var(--g-3);
  border-radius: 6px;
  padding: 5px 9px;
  margin: 6px 0;
  color: var(--g-10);
}
.sub {
  font-size: 12px;
  color: var(--g-8);
}
.time {
  margin-top: 4px;
}
.ops {
  display: flex;
  gap: 8px;
  flex: none;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.confirm-text {
  font-size: 13.5px;
  color: var(--g-10);
  line-height: 1.7;
}
.confirm-text + .confirm-text {
  margin-top: 8px;
}
</style>
