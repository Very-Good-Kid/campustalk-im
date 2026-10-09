<script setup>
/**
 * 统一布局骨架（设计 2.2.1 / 2.3.10）：顶栏 + 左侧列表 + 右侧内容。
 *
 * 业务页面共用本骨架，页面只填充右侧内容区。
 * 本组件还承担两件全局事务：
 * 1. 进入布局 = 已登录：拉取完整资料、建立 WebSocket 连接、订阅消息帧；
 * 2. 左侧栏是分区主导航：会话区显示会话列表；好友 / 频道 / 我的区
 *    切换为该分区的第一级选项菜单（/friends/:tab、/channels/mine、/profile/:tab）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import JoinGroupDialog from '@/components/JoinGroupDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import ContactsSidebar from '@/layouts/ContactsSidebar.vue'
import * as friendsApi from '@/api/friends'
import { IMAGE_ACCEPT, uploadFile } from '@/api/content'
import { createGroup } from '@/api/conversations'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'
import { useWebsocketStore } from '@/stores/websocket'
import { formatTime, messagePreview } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const toast = useToastStore()
const ws = useWebsocketStore()

/** 资料加载完成前不渲染子页面：聊天页依赖"我是谁"判定气泡方向 */
const ready = ref(false)

/** 发起群聊浮窗 */
const showGroupModal = ref(false)

/** 会话列表右上角"＋"菜单；加入群聊浮窗 */
const showAddMenu = ref(false)
const showJoinDialog = ref(false)
const groupName = ref('')
const groupSelected = ref([])
const groupAvatarUrl = ref('')
const groupAvatarInput = ref(null)
const myFriends = ref([])

const NAVS = [
  { name: 'hall', label: '会话', icon: '💬', section: 'chat' },
  { name: 'contacts', label: '联系人', icon: '👥', section: 'friends' },
  { name: 'channels', label: '频道', icon: '📡', section: 'channels' },
  { name: 'profile', label: '我的', icon: '⚙️', section: 'profile' },
]

/** 当前分区：决定左侧栏显示会话列表还是分区第一级选项。 */
const section = computed(() => {
  if (route.name === 'contacts' || route.name === 'contacts-friend' || route.name === 'contacts-group') {
    return 'friends'
  }
  if (route.name === 'channels' || route.name === 'channels-mine' || route.name === 'channel-detail') {
    return 'channels'
  }
  if (route.name === 'profile') return 'profile'
  return 'chat'
})

const SECTION_TITLES = { channels: '频道', profile: '我的' }

/** 频道 / 我的分区的第一级选项（联系人分区有专用侧边栏 ContactsSidebar）。 */
const sectionMenus = computed(() => {
  if (section.value === 'channels') {
    return [
      { to: '/channels', label: '频道广场' },
      { to: '/channels/mine', label: '我的频道' },
    ]
  }
  if (section.value === 'profile') {
    const items = [
      { to: '/profile', label: '个人资料' },
      { to: '/profile/student-id', label: '学号变更' },
      { to: '/profile/settings', label: '设置' },
    ]
    // 管理功能已迁至独立管理端：用户端只保留一个入口链接（设计 2.3.9）
    if (auth.isAdmin) items.push({ to: '/admin/overview', label: '进入管理后台' })
    return items
  }
  return []
})

const activeConvId = computed(() =>
  route.name === 'chat' || route.name === 'channel-detail' ? Number(route.params.id) : null,
)

onMounted(async () => {
  try {
    await auth.fetchMe()
  } catch (e) {
    toast.error(e.message)
  }
  chat.bindWebsocket()
  useWebsocketStore().connect()
  chat.loadConversations().catch((e) => toast.error(e.message))
  ready.value = true
  document.addEventListener('click', closeAddMenu)
  document.addEventListener('keyup', onEscKey)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeAddMenu)
  document.removeEventListener('keyup', onEscKey)
})

/** 右上角"＋"菜单：点击空白 / Esc 关闭 */
function closeAddMenu() {
  showAddMenu.value = false
}

function onEscKey(e) {
  if (e.key === 'Escape') showAddMenu.value = false
}

/** 添加群聊：打开"加入群聊"浮窗（输入群号申请加入别人的群） */
function addGroupChat() {
  showAddMenu.value = false
  showJoinDialog.value = true
}

/** 添加好友：直接跳到联系人-好友管理页 */
function addFriend() {
  showAddMenu.value = false
  router.push('/contacts/manage')
}

/** 创建群聊：复用已有的发起群聊浮窗 */
function createGroupFromMenu() {
  showAddMenu.value = false
  openGroupModal()
}

async function openGroupModal() {
  groupName.value = ''
  groupSelected.value = []
  groupAvatarUrl.value = ''
  showGroupModal.value = true
  try {
    myFriends.value = await friendsApi.getFriends()
  } catch (e) {
    toast.error(e.message)
  }
}

async function pickGroupAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const data = await uploadFile(file, 'image')
    groupAvatarUrl.value = data.url
  } catch (e) {
    toast.error(e.message)
  }
}

async function submitCreateGroup() {
  if (!groupName.value.trim()) {
    toast.error('请填写群名称')
    return
  }
  if (!groupSelected.value.length) {
    toast.error('请至少选择一位成员')
    return
  }
  try {
    const data = await createGroup(
      groupName.value.trim(),
      groupSelected.value,
      groupAvatarUrl.value || null,
    )
    showGroupModal.value = false
    await chat.loadConversations()
    router.push(`/chat/${data.conversation_id}`)
    toast.success('群聊已创建')
  } catch (e) {
    toast.error(e.message)
  }
}

/** 会话列表入口：统一走聊天页。
 *
 *  频道不再跳转到频道分区（那会让左侧栏从"会话列表"切换走），
 *  而是由 ChatView 在右侧直接展开内容社区（帖子流），与私聊 / 群聊的交互一致。 */
function openConversation(c) {
  router.push(`/chat/${c.conversation_id}`)
}

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="shell">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="brand">CampusTalk<span class="brand-sub">校园即时通讯</span></div>
      <div class="top-right">
        <span v-if="auth.isAdmin" class="tag tag-warning">管理员</span>
        <span class="ws-dot" :class="{ on: ws.connected }" :title="ws.connected ? '已连接' : '连接中'"></span>
        <UserAvatar :name="auth.user?.nickname" :url="auth.user?.avatar_url" :size="32" />
        <span class="me-nick">{{ auth.user?.nickname }}</span>
        <button class="btn btn-ghost btn-sm" @click="logout">退出登录</button>
      </div>
    </header>

    <div class="main">
      <!-- 左侧列表 -->
      <aside class="side">
        <nav class="nav">
          <router-link
            v-for="n in NAVS"
            :key="n.name"
            :to="{ name: n.name }"
            class="nav-item"
            :class="{ active: n.section === section }"
          >
            <span class="nav-icon">{{ n.icon }}</span>{{ n.label }}
          </router-link>
        </nav>

        <!-- 会话区：常驻会话列表（未读红点、最后一条消息摘要） -->
        <template v-if="section === 'chat'">
          <div class="side-head">
            <span>会话列表</span>
            <div class="add-wrap">
              <button
                class="add-btn"
                :class="{ on: showAddMenu }"
                title="添加"
                aria-label="添加"
                @click.stop="showAddMenu = !showAddMenu"
              >
                ＋
              </button>
              <div v-if="showAddMenu" class="add-menu" @click.stop>
                <button @click="addGroupChat">添加群聊</button>
                <button @click="addFriend">添加好友</button>
                <button @click="createGroupFromMenu">创建群聊</button>
              </div>
            </div>
          </div>

          <div class="conv-list">
            <button
              v-for="c in chat.conversations"
              :key="c.conversation_id"
              class="conv-item"
              :class="{ active: c.conversation_id === activeConvId }"
              @click="openConversation(c)"
            >
              <UserAvatar :name="c.name" :url="c.avatar_url" :size="40" />
              <span v-if="c.type === 'channel'" class="conv-type">频道</span>
              <span class="conv-mid">
                <span class="conv-top">
                  <span class="conv-name">{{ c.name }}</span>
                  <span class="conv-time">{{ c.last_message ? formatTime(c.last_message.created_at) : '' }}</span>
                </span>
                <span class="conv-bottom">
                  <span v-if="c.mention" class="conv-mention">[有人@我]</span>
                  <span class="conv-preview">{{ messagePreview(c.last_message) }}</span>
                  <span v-if="c.unread" class="unread">{{ c.unread > 99 ? '99+' : c.unread }}</span>
                </span>
              </span>
            </button>
            <div v-if="!chat.conversations.length" class="empty">
              <span class="icon">💬</span>还没有会话<br />去好友页找人聊聊吧
            </div>
          </div>
        </template>

        <!-- 联系人区：专用侧边栏（好友管理 / 好友通知 / 群通知 / 好友|群聊 分组列表） -->
        <ContactsSidebar v-else-if="section === 'friends'" @create-group="openGroupModal" />

        <!-- 频道 / 我的区：第一级选项菜单 -->
        <template v-else>
          <div class="side-head">
            <span>{{ SECTION_TITLES[section] }}</span>
          </div>
          <nav class="section-menu">
            <router-link
              v-for="item in sectionMenus"
              :key="item.to"
              :to="item.to"
              class="menu-item"
              :class="{ active: route.path === item.to }"
            >
              <span class="menu-label">{{ item.label }}</span>
              <span v-if="item.badge" class="badge">{{ item.badge > 99 ? '99+' : item.badge }}</span>
            </router-link>
          </nav>
        </template>
      </aside>

      <!-- 右侧内容区 -->
      <section class="content">
        <template v-if="ready">
          <slot />
          <router-view />
        </template>
      </section>
    </div>

    <!-- 发起群聊 -->
    <ModalDialog :open="showGroupModal" title="发起群聊" @close="showGroupModal = false">
      <div class="field">
        <label>群头像</label>
        <div class="avatar-pick">
          <button class="avatar-btn" title="点击上传头像" @click="groupAvatarInput.click()">
            <UserAvatar :name="groupName || '群聊'" :url="groupAvatarUrl" :size="56" />
          </button>
          <span class="avatar-tip">可选，不上传则按群名生成默认头像</span>
          <input ref="groupAvatarInput" type="file" :accept="IMAGE_ACCEPT" hidden @change="pickGroupAvatar" />
        </div>
      </div>
      <div class="field">
        <label>群名称</label>
        <input v-model="groupName" class="input" maxlength="100" placeholder="给群起个名字" />
      </div>
      <div class="field">
        <label>选择初始成员（仅限好友，至少一位）</label>
        <div class="friend-picks">
          <label v-for="f in myFriends" :key="f.friend_user_id" class="pick">
            <input v-model="groupSelected" type="checkbox" :value="f.friend_user_id" />
            {{ f.remark || f.nickname }}
          </label>
          <div v-if="!myFriends.length" class="empty">暂无好友可邀请</div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showGroupModal = false">取消</button>
        <button class="btn btn-primary" @click="submitCreateGroup">创建</button>
      </template>
    </ModalDialog>

    <!-- 加入群聊（输入群号申请加入别人的群） -->
    <JoinGroupDialog :open="showJoinDialog" @close="showJoinDialog = false" />
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* ---------- 顶栏 ---------- */
.topbar {
  height: 56px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--g-1);
  border-bottom: 1px solid var(--g-4);
}
.brand {
  font-size: 18px;
  font-weight: 800;
  color: var(--brand-7);
}
.brand-sub {
  margin-left: 10px;
  font-size: 12px;
  font-weight: 500;
  color: var(--g-8);
}
.top-right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.me-nick {
  font-weight: 600;
}
.ws-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--g-6);
}
.ws-dot.on {
  background: var(--success);
}

/* ---------- 主体两栏 ---------- */
.main {
  flex: 1;
  display: flex;
  min-height: 0;
}
.side {
  width: 280px;
  flex: none;
  display: flex;
  flex-direction: column;
  background: var(--g-1);
  border-right: 1px solid var(--g-4);
  min-height: 0;
}
.content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

/* ---------- 左侧导航 ---------- */
.nav {
  display: flex;
  padding: 10px 12px 4px;
  gap: 4px;
}
.nav-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 32px;
  border-radius: var(--radius-s);
  font-size: 13px;
  color: var(--g-9);
  font-weight: 600;
  white-space: nowrap;
}
.nav-item:hover {
  background: var(--g-3);
}
.nav-item.active {
  background: var(--brand-1);
  color: var(--brand-7);
}
.nav-icon {
  font-size: 14px;
}

.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--g-8);
}

/* 会话列表右上角"＋"菜单：添加群聊 / 添加好友 / 创建群聊 */
.add-wrap {
  position: relative;
}
.add-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-s);
  background: none;
  color: var(--g-9);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.add-btn:hover,
.add-btn.on {
  background: var(--brand-1);
  color: var(--brand-7);
}
.add-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 50;
  min-width: 126px;
  padding: 4px;
  background: var(--g-1);
  border: 1px solid var(--g-4);
  border-radius: var(--radius-m);
  box-shadow: var(--shadow-pop);
  display: flex;
  flex-direction: column;
}
.add-menu button {
  border: none;
  background: none;
  text-align: left;
  font-size: 13px;
  color: var(--g-11);
  padding: 8px 10px;
  border-radius: var(--radius-s);
  cursor: pointer;
  font-family: var(--font-cjk);
}
.add-menu button:hover {
  background: var(--brand-1);
  color: var(--brand-7);
}

/* ---------- 分区第一级选项菜单 ---------- */
.section-menu {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 0 8px;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: var(--radius-s);
  font-size: 13px;
  color: var(--g-10);
  margin-bottom: 2px;
}
.menu-item:hover {
  background: var(--g-2);
}
.menu-item.active {
  background: var(--brand-1);
  color: var(--brand-7);
  font-weight: 700;
}
.menu-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.badge {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--coral-5);
  color: #fff;
  font-size: 10px;
}

/* ---------- 会话列表 ---------- */
.conv-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.conv-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
  font-family: var(--font-cjk);
}
.conv-item:hover {
  background: var(--g-2);
}
.conv-item.active {
  background: var(--brand-1);
}
.conv-type {
  flex: none;
  font-size: 10px;
  color: var(--teal-7, #149e89);
  border: 1px solid currentColor;
  border-radius: 4px;
  padding: 0 4px;
  line-height: 1.4;
  align-self: center;
}
.avatar-pick {
  display: flex;
  align-items: center;
  gap: 12px;
}
.avatar-btn {
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  border-radius: 50%;
}
.avatar-tip {
  font-size: 12px;
  color: var(--g-7);
}
.conv-mid {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.conv-top,
.conv-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.conv-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--g-12);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-time {
  font-size: 11px;
  color: var(--g-7);
  flex: none;
}
.conv-preview {
  font-size: 12px;
  color: var(--g-8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* @我提示：与未读红点同族色，只占很小一块，点进会话即消 */
.conv-mention {
  flex: none;
  font-size: 12px;
  font-weight: 600;
  color: var(--coral-6);
}
.unread {
  flex: none;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--coral-5);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* ---------- 群聊浮窗 ---------- */
.friend-picks {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--g-4);
  border-radius: var(--radius-s);
  padding: 8px 10px;
}
.pick {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  cursor: pointer;
}
</style>
