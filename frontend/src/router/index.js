/**
 * 路由：分区页面 + 布局父路由 + 统一守卫。
 *
 * 结构对应设计 2.3：登录 / 注册页不使用布局骨架；
 * 会话大厅、聊天、好友、频道、频道帖子流、个人资料共用 AppLayout 三栏骨架。
 * 好友 / 频道 / 我的三个分区各自带第一级选项，固定呈现在左侧侧边栏
 * （/friends/:tab、/channels/mine、/profile/:tab），侧边栏随分区切换。
 * 守卫只认"本地是否有令牌"，令牌是否有效由接口 401 统一判定（request.js）。
 */
import { createRouter, createWebHistory } from 'vue-router'

import { getToken } from '@/api/token'
import AppLayout from '@/layouts/AppLayout.vue'

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  { path: '/register', name: 'register', component: () => import('@/views/RegisterView.vue'), meta: { public: true } },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: '', name: 'hall', component: () => import('@/views/HallView.vue') },
      { path: 'chat/:id(\\d+)', name: 'chat', component: () => import('@/views/ChatView.vue'), props: true },
      // 联系人分区：侧边栏第一级选项（好友管理 / 好友通知 / 群通知 / 好友|群聊列表），主栏为资料面板
      { path: 'friends/:rest*', redirect: '/contacts' },
      {
        path: 'contacts/:tab(manage|friend-notify|group-notify)?',
        name: 'contacts',
        component: () => import('@/views/ContactsView.vue'),
      },
      {
        path: 'contacts/friend/:userId(\\d+)',
        name: 'contacts-friend',
        component: () => import('@/views/ContactsView.vue'),
        props: true,
      },
      {
        path: 'contacts/group/:id(\\d+)',
        name: 'contacts-group',
        component: () => import('@/views/ContactsView.vue'),
        props: true,
      },
      { path: 'channels', name: 'channels', component: () => import('@/views/ChannelsView.vue'), props: { mode: 'square' } },
      { path: 'channels/mine', name: 'channels-mine', component: () => import('@/views/ChannelsView.vue'), props: { mode: 'mine' } },
      { path: 'channels/:id(\\d+)', name: 'channel-detail', component: () => import('@/views/ChannelDetailView.vue'), props: true },
      {
        path: 'profile/:tab(info|student-id|settings|admin)?',
        name: 'profile',
        component: () => import('@/views/ProfileView.vue'),
        props: (route) => ({ tab: route.params.tab || 'info' }),
      },
    ],
  },
  // 管理端：独立子应用（独立登录口 + 独立骨架，不复用 IM 布局与 WebSocket）
  {
    path: '/admin/login',
    name: 'admin-login',
    component: () => import('@/views/admin/AdminLoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    children: [
      { path: '', redirect: '/admin/overview' },
      { path: 'overview', name: 'admin-overview', component: () => import('@/views/admin/AdminOverviewView.vue') },
      { path: 'users', name: 'admin-users', component: () => import('@/views/admin/AdminUsersView.vue') },
      { path: 'reports', name: 'admin-reports', component: () => import('@/views/admin/AdminReportsView.vue') },
      { path: 'verifications', name: 'admin-verifications', component: () => import('@/views/admin/AdminVerificationsView.vue') },
      { path: 'words', name: 'admin-words', component: () => import('@/views/admin/AdminWordsView.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const inAdminArea = to.path.startsWith('/admin')
  // 未登录访问业务页 → 对应登录页（带上回跳地址）
  if (!to.meta.public && !getToken()) {
    return inAdminArea
      ? { path: '/admin/login', query: to.fullPath === '/admin' ? {} : { redirect: to.fullPath } }
      : { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  // 已登录访问登录 / 注册页 → 对应首页
  if (to.meta.public && getToken()) {
    if (to.name === 'login' || to.name === 'register') return { path: '/' }
    if (to.name === 'admin-login') return { path: '/admin/overview' }
  }
})

export default router
