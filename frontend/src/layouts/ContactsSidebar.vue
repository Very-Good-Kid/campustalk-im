<script setup>
/**
 * 联系人侧边栏（参照 QQ）：从上到下依次为
 * 好友管理 → 好友通知（角标）→ 群通知 → 好友 | 群聊 切换（默认好友）→ 分组呈现的列表。
 * 好友模式按已有分组折叠展示，点好友进右侧资料页；群聊模式列出已加入的群聊。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import JoinGroupDialog from '@/components/JoinGroupDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useFriendsStore } from '@/stores/friends'
import { useGroupRequestsStore } from '@/stores/groupRequests'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const friendsStore = useFriendsStore()
const chat = useChatStore()
const groupRequestsStore = useGroupRequestsStore()

/** create-group：请求父级（AppLayout）打开"发起群聊"浮窗 */
const emit = defineEmits(['create-group'])

/** 加入群聊浮窗显隐（表单状态内聚在 JoinGroupDialog） */
const showJoin = ref(false)

/** 好友 / 群聊 切换，默认好友 */
const mode = ref('friends')

/** 已展开的分组名：默认展开「我的好友」（"我"与好友直接可见），其余折叠 */
const expandedGroups = reactive(new Set(['我的好友']))

onMounted(() => {
  if (!friendsStore.loaded) friendsStore.loadAll().catch(() => {})
  groupRequestsStore.loadAll().catch(() => {})
})

/** 按分组名分组；「我的好友」是默认分组，始终存在（即使一个好友都没有） */
const groups = computed(() => {
  const map = new Map([['我的好友', []]])
  for (const f of friendsStore.friends) {
    const key = f.group_name || '我的好友'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(f)
  }
  return [...map.entries()]
})

/** 群聊模式：按 顶置 / 班级 / 我创建 / 我管理 / 我加入 分类（参照 QQ）。
 *  顶置群聊与班级群聊为概念占位：班级群聊（老师 / 班委创建的办公学习群）后续推出。 */
const groupSections = computed(() => {
  const created = []
  const managed = []
  const joined = []
  for (const c of chat.conversations.filter((c) => c.type === 'group')) {
    if (c.my_role === 'owner') created.push(c)
    else if (c.my_role === 'admin') managed.push(c)
    else joined.push(c)
  }
  return [
    { name: '顶置群聊', list: [], concept: true },
    { name: '班级群聊', list: [], concept: true },
    { name: '我创建的群聊', list: created },
    { name: '我管理的群聊', list: managed },
    { name: '我加入的群聊', list: joined },
  ]
})

function toggleGroup(name) {
  if (expandedGroups.has(name)) expandedGroups.delete(name)
  else expandedGroups.add(name)
}

function openFriend(f) {
  router.push(`/contacts/friend/${f.friend_user_id}`)
}

/** 「我」的资料页：与好友走同一条路由 */
function openSelf() {
  if (auth.user?.id) router.push(`/contacts/friend/${auth.user.id}`)
}

function openGroup(c) {
  router.push(`/contacts/group/${c.conversation_id}`)
}

function isActive(to) {
  return route.path === to
}

function openJoin() {
  showJoin.value = true
}
</script>

<template>
  <div class="contacts-side">
    <nav class="side-menu">
      <router-link to="/contacts/manage" class="menu-item" :class="{ active: isActive('/contacts/manage') }">
        <span class="menu-label">好友管理</span>
      </router-link>
      <router-link
        to="/contacts/friend-notify"
        class="menu-item"
        :class="{ active: isActive('/contacts/friend-notify') }"
      >
        <span class="menu-label">好友通知</span>
        <span v-if="friendsStore.pendingReceivedCount" class="badge">
          {{ friendsStore.pendingReceivedCount > 99 ? '99+' : friendsStore.pendingReceivedCount }}
        </span>
      </router-link>
      <router-link
        to="/contacts/group-notify"
        class="menu-item"
        :class="{ active: isActive('/contacts/group-notify') }"
      >
        <span class="menu-label">群通知</span>
        <span v-if="groupRequestsStore.pendingReceivedCount" class="badge">
          {{ groupRequestsStore.pendingReceivedCount > 99 ? '99+' : groupRequestsStore.pendingReceivedCount }}
        </span>
      </router-link>
    </nav>

    <!-- 好友 | 群聊 切换 -->
    <div class="seg">
      <button class="seg-btn" :class="{ on: mode === 'friends' }" @click="mode = 'friends'">好友</button>
      <button class="seg-btn" :class="{ on: mode === 'groups' }" @click="mode = 'groups'">群聊</button>
    </div>

    <!-- 好友：按分组折叠呈现 -->
    <div v-if="mode === 'friends'" class="contact-list">
      <div v-for="[name, list] in groups" :key="name" class="group">
        <button class="group-head" @click="toggleGroup(name)">
          <span class="arrow" :class="{ open: expandedGroups.has(name) }">▸</span>
          <span class="group-name">{{ name }}</span>
          <span class="group-count">{{ list.length }}</span>
        </button>
        <template v-if="expandedGroups.has(name)">
          <!-- 「我」固定在「我的好友」组内第一条 -->
          <button
            v-if="name === '我的好友'"
            class="contact-item self"
            :class="{ active: route.path === `/contacts/friend/${auth.user?.id}` }"
            @click="openSelf"
          >
            <UserAvatar :name="auth.user?.nickname" :url="auth.user?.avatar_url" :size="34" />
            <span class="contact-name">
              {{ auth.user?.nickname }}<span class="self-tag">我</span>
            </span>
          </button>
          <button
            v-for="f in list"
            :key="f.friend_user_id"
            class="contact-item"
            :class="{ active: route.path === `/contacts/friend/${f.friend_user_id}` }"
            @click="openFriend(f)"
          >
            <UserAvatar :name="f.remark || f.nickname" :url="f.avatar_url" :size="34" />
            <span class="contact-name">
              <span v-if="f.is_starred" class="star">⭐</span>{{ f.remark || f.nickname }}
              <span
                class="online-dot"
                :class="{ on: friendsStore.online[f.friend_user_id] }"
                :title="friendsStore.online[f.friend_user_id] ? '在线' : '离线'"
              ></span>
            </span>
          </button>
        </template>
      </div>
      <div v-if="!friendsStore.friends.length" class="empty">
        <span class="icon">👥</span>还没有好友<br />去「好友管理」添加
      </div>
    </div>

    <!-- 群聊：按 顶置 / 班级 / 我创建 / 我管理 / 我加入 分类 -->
    <div v-else class="contact-list">
      <div class="create-row">
        <button class="create-group" @click="emit('create-group')">＋ 创建群聊</button>
        <button class="create-group" @click="openJoin">＋ 加入群聊</button>
      </div>
      <div v-for="sec in groupSections" :key="sec.name" class="group">
        <button class="group-head" @click="toggleGroup(sec.name)">
          <span class="arrow" :class="{ open: expandedGroups.has(sec.name) }">▸</span>
          <span class="group-name">{{ sec.name }}</span>
          <span class="group-count">{{ sec.list.length }}</span>
        </button>
        <template v-if="expandedGroups.has(sec.name)">
          <div v-if="!sec.list.length" class="group-empty">
            {{ sec.concept ? '概念阶段 · 后续推出' : '暂无群聊' }}
          </div>
          <button
            v-for="c in sec.list"
            :key="c.conversation_id"
            class="contact-item"
            :class="{ active: route.path === `/contacts/group/${c.conversation_id}` }"
            @click="openGroup(c)"
          >
            <UserAvatar :name="c.name" :url="c.avatar_url" :size="34" />
            <span class="contact-name">{{ c.name }}</span>
          </button>
        </template>
      </div>
    </div>

    <!-- 加入群聊：输入群号发起申请（群主 / 管理员审批） -->
    <JoinGroupDialog
      :open="showJoin"
      @close="showJoin = false"
      @submitted="groupRequestsStore.loadAll().catch(() => {})"
    />
  </div>
</template>

<style scoped>
.contacts-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.side-menu {
  padding: 4px 8px 0;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
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

.seg {
  display: flex;
  gap: 4px;
  margin: 8px 12px;
  padding: 3px;
  background: var(--g-3);
  border-radius: var(--radius-s);
}
.seg-btn {
  flex: 1;
  height: 26px;
  border: none;
  border-radius: calc(var(--radius-s) - 2px);
  background: none;
  font-size: 12.5px;
  color: var(--g-9);
  cursor: pointer;
  font-family: var(--font-cjk);
}
.seg-btn.on {
  background: var(--g-1);
  color: var(--brand-7);
  font-weight: 700;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.contact-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 0 8px 12px;
}
/* 群聊模式顶部的入口行：创建 / 加入 */
.create-row {
  display: flex;
  gap: 6px;
  margin: 4px 0 6px;
}
.create-group {
  flex: 1;
  height: 32px;
  border: 1px dashed var(--g-5);
  border-radius: var(--radius-s);
  background: none;
  color: var(--brand-7);
  font-size: 12.5px;
  font-weight: 600;
  font-family: var(--font-cjk);
  cursor: pointer;
}
.create-group:hover {
  background: var(--brand-1);
  border-color: var(--brand-3);
}
.join-hint {
  font-size: 12px;
  color: var(--g-8);
}.group-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 6px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  color: var(--g-8);
  font-family: var(--font-cjk);
  border-radius: var(--radius-s);
}
.group-head:hover {
  background: var(--g-2);
}
.arrow {
  display: inline-block;
  transition: transform 0.15s;
  font-size: 10px;
}
.arrow.open {
  transform: rotate(90deg);
}
.group-name {
  flex: 1;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-count {
  color: var(--g-7);
  font-weight: 500;
}
.group-empty {
  font-size: 11.5px;
  color: var(--g-7);
  padding: 4px 8px 8px 22px;
}

.contact-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: none;
  background: none;
  border-radius: var(--radius-s);
  cursor: pointer;
  text-align: left;
  font-family: var(--font-cjk);
}
.contact-item:hover {
  background: var(--g-2);
}
.contact-item.active {
  background: var(--brand-1);
}
.contact-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--g-11);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.star {
  margin-right: 2px;
}
/* 在线绿点：teal 是规范里"在线"语义色；离线留灰点，行宽不跳动 */
.online-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  margin-left: 6px;
  border-radius: 50%;
  background: var(--g-5);
  vertical-align: 1px;
}
.online-dot.on {
  background: var(--teal-5);
}
/* 「我」：昵称后的标记 */
.self-tag {
  margin-left: 6px;
  padding: 0 6px;
  height: 16px;
  line-height: 16px;
  font-size: 10px;
  border-radius: 999px;
  background: var(--brand-1);
  color: var(--brand-7);
  vertical-align: middle;
}
.empty {
  text-align: center;
  font-size: 12px;
  color: var(--g-7);
  padding: 24px 0;
  line-height: 1.9;
}
</style>
