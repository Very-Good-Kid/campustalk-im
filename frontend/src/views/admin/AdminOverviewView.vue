<script setup>
/**
 * 管理端 · 总览（设计 2.3.9）：待处理举报 / 待审学号变更 / 账号计数 / 内容规模。
 *
 * 只做计数，**不展示任何用户内容**——权限最小化与数据最小化原则的落地。
 * 待办卡可点击直达对应页面。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getOverview } from '@/api/admin'
import { useToastStore } from '@/stores/toast'

const router = useRouter()
const toast = useToastStore()

const data = ref(null)
const loading = ref(true)

onMounted(async () => {
  try {
    data.value = await getOverview()
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
})

/** 待办卡与统计卡的取数配置（图标 + 标签 + 取值 + 是否可点击直达）。 */
const TODO_CARDS = [
  { key: 'pending_reports', label: '待处理举报', icon: '🚩', to: '/admin/reports' },
  { key: 'pending_verifications', label: '待审学号变更', icon: '🗂️', to: '/admin/verifications' },
]

const USER_STATS = [
  { key: 'users_total', label: '账号总数' },
  { key: 'users_active', label: '正常' },
  { key: 'users_disabled', label: '已禁用' },
  { key: 'users_admin', label: '管理员' },
]

const CONTENT_STATS = [
  { key: 'messages_total', label: '消息总数' },
  { key: 'conversations_total', label: '会话总数' },
  { key: 'channels_total', label: '频道数' },
]

const LIVE_STATS = [
  { key: 'online_now', label: '当前在线' },
  { key: 'dau_today', label: '今日活跃（发言）' },
  { key: 'messages_today', label: '今日消息' },
]

/** 趋势柱高度：按 7 天最大值归一，最少留 4% 让 0 也看得见占位 */
function barHeight(count) {
  const list = data.value?.trend_7d || []
  const max = Math.max(...list.map((t) => t.count), 1)
  return `${Math.max(4, Math.round((count / max) * 100))}%`
}
</script>

<template>
  <div v-if="loading" class="empty">加载中…</div>

  <div v-else-if="data" class="overview">
    <div class="todo-row">
      <button
        v-for="c in TODO_CARDS"
        :key="c.key"
        class="card todo-card"
        :class="{ zero: !data[c.key] }"
        @click="router.push(c.to)"
      >
        <span class="todo-icon">{{ c.icon }}</span>
        <span class="todo-num">{{ data[c.key] }}</span>
        <span class="todo-label">{{ c.label }}</span>
      </button>
    </div>

    <div class="card block">
      <h3>活跃度</h3>
      <div class="stat-grid">
        <div v-for="s in LIVE_STATS" :key="s.key" class="stat">
          <span class="stat-num">{{ data[s.key] }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </div>
      </div>
      <div v-if="data.trend_7d?.length" class="trend" title="近 7 日消息量">
        <div v-for="t in data.trend_7d" :key="t.date" class="trend-col">
          <span class="trend-num">{{ t.count }}</span>
          <div class="trend-bar" :style="{ height: barHeight(t.count) }"></div>
          <span class="trend-date">{{ t.date }}</span>
        </div>
      </div>
    </div>

    <div class="card block">
      <h3>账号计数</h3>
      <div class="stat-grid">
        <div v-for="s in USER_STATS" :key="s.key" class="stat">
          <span class="stat-num">{{ data[s.key] }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </div>
      </div>
    </div>

    <div class="card block">
      <h3>内容规模</h3>
      <div class="stat-grid">
        <div v-for="s in CONTENT_STATS" :key="s.key" class="stat">
          <span class="stat-num">{{ data[s.key] }}</span>
          <span class="stat-label">{{ s.label }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.todo-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}
.todo-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 20px 22px;
  cursor: pointer;
  text-align: left;
  font-family: var(--font-cjk);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.todo-card:hover {
  border-color: var(--brand-3);
  box-shadow: var(--shadow-card);
}
.todo-card.zero {
  opacity: 0.6;
}
.todo-icon {
  font-size: 20px;
}
.todo-num {
  font-size: 30px;
  font-weight: 800;
  color: var(--brand-7);
  line-height: 1.1;
}
.todo-label {
  font-size: 13px;
  color: var(--g-9);
}
.block {
  padding: 22px 24px;
}
.block h3 {
  font-size: 16px;
  margin-bottom: 16px;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 16px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 16px;
  background: var(--g-2);
  border-radius: var(--radius-m);
}
.stat-num {
  font-size: 22px;
  font-weight: 800;
  color: var(--g-12);
}
.stat-label {
  font-size: 12.5px;
  color: var(--g-8);
}

/* ---------- 近 7 日消息趋势（纯 CSS 柱状，不引图表库） ---------- */
.trend {
  display: flex;
  align-items: stretch;
  gap: 10px;
  height: 130px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed var(--g-4);
}
.trend-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  min-width: 0;
}
.trend-num {
  font-size: 11px;
  color: var(--g-8);
}
.trend-bar {
  width: 100%;
  max-width: 34px;
  background: var(--brand-4);
  border-radius: 4px 4px 0 0;
  min-height: 3px;
}
.trend-col:hover .trend-bar {
  background: var(--brand-6);
}
.trend-date {
  font-size: 11px;
  color: var(--g-7);
}
</style>
