<script setup>
/**
 * 管理端布局骨架（设计 2.3.9）：独立子应用，不复用 IM 三栏骨架与 WebSocket。
 *
 * 视觉与用户端同源——完全复用 tokens.css 设计令牌，仅顶栏改用主色实底
 * 以形成"后台"辨识度。权限三层：入口层（用户端只留一个链接）、
 * 路由层（此处校验 is_admin）、接口层（服务端 require_admin，真正的安全边界）。
 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const toast = useToastStore()

/** 资料与权限校验完成前不渲染子页面 */
const ready = ref(false)

const NAVS = [
  { name: 'admin-overview', label: '总览', icon: '📊' },
  { name: 'admin-users', label: '账号管理', icon: '👥' },
  { name: 'admin-reports', label: '举报处置', icon: '🚩' },
  { name: 'admin-verifications', label: '学号审核', icon: '🗂️' },
  { name: 'admin-words', label: '敏感词库', icon: '🔤' },
]

onMounted(async () => {
  try {
    await auth.fetchMe()
  } catch (e) {
    toast.error(e.message)
    return
  }
  // 路由层：非管理员回管理端登录口（接口层还有 require_admin 兜底）
  if (!auth.isAdmin) {
    router.replace('/admin/login')
    return
  }
  ready.value = true
})

function logout() {
  auth.logout()
  router.push('/admin/login')
}

function backToApp() {
  router.push('/')
}
</script>

<template>
  <div class="admin-shell">
    <header class="admin-topbar">
      <div class="brand">CampusTalk<span class="brand-sub">管理后台</span></div>
      <div class="top-right">
        <span class="me-nick">{{ auth.user?.nickname }}</span>
        <button class="btn btn-sm top-btn" @click="backToApp">返回用户端</button>
        <button class="btn btn-sm top-btn" @click="logout">退出登录</button>
      </div>
    </header>

    <div class="admin-main">
      <aside class="admin-side">
        <nav class="admin-nav">
          <router-link
            v-for="n in NAVS"
            :key="n.name"
            :to="{ name: n.name }"
            class="admin-nav-item"
            :class="{ active: route.name === n.name }"
          >
            <span class="nav-icon">{{ n.icon }}</span>{{ n.label }}
          </router-link>
        </nav>
      </aside>

      <section class="admin-content">
        <template v-if="ready"><router-view /></template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.admin-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}
/* 顶栏用主色实底：与用户端同源（brand 色系），但具备后台辨识度 */
.admin-topbar {
  height: 56px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--brand-7);
  color: #fff;
}
.brand {
  font-size: 18px;
  font-weight: 800;
  color: #fff;
}
.brand-sub {
  margin-left: 10px;
  font-size: 12px;
  font-weight: 500;
  opacity: 0.85;
}
.top-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.me-nick {
  font-weight: 600;
}
.top-btn {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.35);
}
.top-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.24);
}

.admin-main {
  flex: 1;
  display: flex;
  min-height: 0;
}
.admin-side {
  width: 200px;
  flex: none;
  background: var(--g-1);
  border-right: 1px solid var(--g-4);
  padding: 12px 8px;
}
.admin-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.admin-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-s);
  font-size: 13px;
  font-weight: 600;
  color: var(--g-10);
}
.admin-nav-item:hover {
  background: var(--g-2);
}
.admin-nav-item.active {
  background: var(--brand-1);
  color: var(--brand-7);
}
.nav-icon {
  font-size: 14px;
}
.admin-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 24px 28px;
  background: var(--g-2);
}
</style>
