<script setup>
/**
 * 好友管理面板：分组管理（新建 / 重命名 / 删除分组、组内好友下拉换组）
 * 与添加好友（用户名精确搜索 / 同班同学 / 发出的申请）。
 * 检索隐私约定（设计 2.2.5）：搜索仅支持用户名精确匹配。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import ModalDialog from '@/components/ModalDialog.vue'
import ProfileCard from '@/components/ProfileCard.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import * as friendsApi from '@/api/friends'
import { useChatStore } from '@/stores/chat'
import { useFriendsStore } from '@/stores/friends'
import { useToastStore } from '@/stores/toast'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const friendsStore = useFriendsStore()
const chat = useChatStore()
const toast = useToastStore()

onMounted(() => {
  if (!friendsStore.loaded) friendsStore.loadAll().catch((e) => toast.error(e.message))
})

/** ---------- 分组管理 ---------- */
const groups = computed(() => {
  const map = new Map()
  for (const f of friendsStore.friends) {
    const key = f.group_name || '我的好友'
    if (!map.has(key)) map.set(key, [])
    map.get(key).push(f)
  }
  return [...map.entries()]
})

/** 分组下拉选项：已有分组（不含"我的好友"，它是默认兜底） */
const groupOptions = computed(() => [
  '我的好友',
  ...groups.value.map(([name]) => name).filter((n) => n !== '我的好友'),
])

/** 移动单个好友到目标分组（下拉换组） */
const moving = ref('')
async function moveFriend(f, groupName) {
  if (moving.value) return
  moving.value = f.friend_user_id
  try {
    await friendsApi.updateFriend(f.friend_user_id, {
      remark: f.remark || null,
      group_name: groupName === '我的好友' ? null : groupName,
      is_starred: f.is_starred,
    })
    await friendsStore.loadAll()
    toast.success(`已将「${f.remark || f.nickname}」移至「${groupName}」`)
  } catch (e) {
    toast.error(e.message)
  } finally {
    moving.value = ''
  }
}

/** 新建分组：命名 + 勾选成员移入（空分组无法在聚合模型中存在） */
const showCreate = ref(false)
const createName = ref('')
const createSelected = ref([])

function openCreate() {
  createName.value = ''
  createSelected.value = []
  showCreate.value = true
}

async function doCreate() {
  const name = createName.value.trim()
  if (!name) {
    toast.error('请填写分组名')
    return
  }
  if (groupOptions.value.includes(name)) {
    toast.error('分组已存在')
    return
  }
  if (!createSelected.value.length) {
    toast.error('请至少勾选一位移入该分组的好友')
    return
  }
  const list = friendsStore.friends.filter((f) => createSelected.value.includes(f.friend_user_id))
  await moveMembers(list, name)
  toast.success(`分组「${name}」已创建，移入 ${list.length} 人`)
  showCreate.value = false
}

const renameTarget = ref(null) // { name, list }
const renameValue = ref('')
const deleteGroupTarget = ref(null) // { name, list }

async function doRename() {
  const name = renameValue.value.trim()
  if (!name) {
    toast.error('请填写新分组名')
    return
  }
  await moveMembers(renameTarget.value.list, name)
  toast.success('分组已重命名')
  renameTarget.value = null
}

async function doDeleteGroup() {
  const { name, list } = deleteGroupTarget.value
  await moveMembers(list, null) // 成员迁回默认分组
  toast.success(`分组「${name}」已删除，成员移入「我的好友」`)
  deleteGroupTarget.value = null
}

/** 批量迁移成员（保留备注与特别关心） */
async function moveMembers(list, groupName) {
  try {
    await Promise.all(
      list.map((f) =>
        friendsApi.updateFriend(f.friend_user_id, {
          remark: f.remark || null,
          group_name: groupName,
          is_starred: f.is_starred,
        }),
      ),
    )
    await friendsStore.loadAll()
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 添加好友 ---------- */
const searchKey = ref('')
const searchResult = ref(null)
const classmates = ref([])
const showClassmates = ref(false)

async function doSearch() {
  const q = searchKey.value.trim()
  if (!q) return
  try {
    const list = await friendsApi.searchUsers(q)
    searchResult.value = list[0] || null
    if (!searchResult.value) toast.info('未找到该用户名对应的用户')
  } catch (e) {
    toast.error(e.message)
  }
}

async function loadClassmates() {
  try {
    classmates.value = await friendsApi.getClassmates()
    showClassmates.value = true
  } catch (e) {
    toast.error(e.message)
  }
}

async function addFriend(userId) {
  try {
    await friendsApi.sendFriendRequest(userId)
    toast.success('好友申请已发送，等待对方同意')
    await friendsStore.loadAll()
  } catch (e) {
    toast.error(e.message)
  }
}

/** 与某人的关系：friend 已是好友 / pending 已发申请待处理 / none 可加好友 */
function relationOf(userId) {
  if (!userId) return 'none'
  if (friendsStore.friends.some((f) => f.friend_user_id === userId)) return 'friend'
  const pending = friendsStore.sent.some((r) => r.user?.id === userId && r.status === 'pending')
  return pending ? 'pending' : 'none'
}

/** 已是好友：打开（或创建）私聊并跳转 */
async function sendMessage(userId) {
  try {
    const data = await friendsApi.openSingleConversation(userId)
    await chat.loadConversations()
    router.push(`/chat/${data.conversation_id}`)
  } catch (e) {
    toast.error(e.message)
  }
}

/** 发出的申请：默认只展示前几条，其余走「查看全部」；结果状态对发起方可见 */
const PREVIEW_COUNT = 3
const showAllSent = ref(false)
const sentPreview = computed(() => friendsStore.sent.slice(0, PREVIEW_COUNT))
const SENT_STATUS = { pending: '待对方处理', accepted: '已同意', rejected: '已拒绝' }
const STATUS_TAG = { pending: 'tag-warning', accepted: 'tag-success', rejected: 'tag-error' }

/** 资料卡：0 表示关闭；由条目上的头像 / 昵称触发 */
const cardUserId = ref(0)

function openProfile(user) {
  if (user?.id) cardUserId.value = user.id
}
</script>

<template>
  <div class="manage-panel">
    <!-- 分组管理 -->
    <section class="card block">
      <div class="block-head">
        <h3>分组管理</h3>
        <button class="btn btn-primary btn-sm" @click="openCreate">+ 新建分组</button>
      </div>
      <p class="hint">在好友右侧的下拉框中可直接更换分组；重命名会批量迁移组内好友，删除分组会把成员移入「我的好友」。</p>

      <div v-for="[name, list] in groups" :key="name" class="group">
        <div class="group-row">
          <span class="group-name">{{ name }}</span>
          <span class="group-count">{{ list.length }} 人</span>
          <span class="ops">
            <button v-if="name !== '我的好友'" class="btn btn-ghost btn-sm" @click="((renameTarget = { name, list }), (renameValue = name))">重命名</button>
            <button v-if="name !== '我的好友'" class="btn btn-ghost btn-sm" @click="deleteGroupTarget = { name, list }">删除</button>
          </span>
        </div>
        <div v-for="f in list" :key="f.friend_user_id" class="member-row">
          <UserAvatar :name="f.remark || f.nickname" :url="f.avatar_url" :size="30" />
          <span class="member-name">
            <span v-if="f.is_starred" class="star">⭐</span>{{ f.remark || f.nickname }}
          </span>
          <select
            class="input member-group"
            :value="name"
            :disabled="moving === f.friend_user_id"
            @change="moveFriend(f, $event.target.value)"
          >
            <option v-for="g in groupOptions" :key="g" :value="g">{{ g }}</option>
          </select>
        </div>
      </div>
      <div v-if="!groups.length" class="empty"><span class="icon">📂</span>暂无好友，先去添加吧</div>
    </section>

    <!-- 添加好友 -->
    <section class="card block">
      <h3>添加好友</h3>
      <div class="search">
        <input v-model="searchKey" class="input" placeholder="输入对方用户名精确搜索" @keyup.enter="doSearch" />
        <button class="btn btn-ghost btn-sm" @click="doSearch">搜索</button>
        <button class="btn btn-ghost btn-sm" @click="loadClassmates">同班同学</button>
      </div>
      <div v-if="searchResult" class="item">
        <UserAvatar
          class="link"
          :name="searchResult.nickname"
          :url="searchResult.avatar_url"
          :size="40"
          @click="openProfile(searchResult)"
        />
        <div class="item-mid link" @click="openProfile(searchResult)">
          <div class="item-name">{{ searchResult.nickname }}</div>
          <div class="item-sub">@{{ searchResult.username }}</div>
        </div>
        <button
          v-if="relationOf(searchResult.id) === 'friend'"
          class="btn btn-primary btn-sm"
          @click="sendMessage(searchResult.id)"
        >
          发消息
        </button>
        <button
          v-else-if="relationOf(searchResult.id) === 'pending'"
          class="btn btn-ghost btn-sm"
          disabled
        >
          已申请
        </button>
        <button v-else class="btn btn-primary btn-sm" @click="addFriend(searchResult.id)">加好友</button>
      </div>

      <div class="sub-label">
        <span>发出的申请（{{ friendsStore.sent.length }}）</span>
        <button
          v-if="friendsStore.sent.length > PREVIEW_COUNT"
          class="more-link"
          @click="showAllSent = true"
        >
          查看全部
        </button>
      </div>
      <div v-for="r in sentPreview" :key="r.request_id" class="item">
        <UserAvatar
          class="link"
          :name="r.user?.nickname"
          :url="r.user?.avatar_url"
          :size="36"
          @click="openProfile(r.user)"
        />
        <div class="item-mid link" @click="openProfile(r.user)">
          <div class="item-name">{{ r.user?.nickname }}</div>
          <div class="item-sub">@{{ r.user?.username }} · {{ formatDateTime(r.created_at) }}</div>
        </div>
        <span class="tag" :class="STATUS_TAG[r.status]">{{ SENT_STATUS[r.status] }}</span>
      </div>
      <div v-if="!friendsStore.sent.length" class="empty"><span class="icon">📤</span>暂无发出的申请</div>
    </section>

    <!-- 新建分组 -->
    <ModalDialog :open="showCreate" title="新建分组" width="420" @close="showCreate = false">
      <div class="field">
        <label>分组名</label>
        <input v-model="createName" class="input" maxlength="50" placeholder="如：同班 / 社团" />
      </div>
      <div class="field">
        <label>选择移入该分组的好友（至少一位）</label>
        <div class="friend-picks">
          <label v-for="f in friendsStore.friends" :key="f.friend_user_id" class="pick">
            <input v-model="createSelected" type="checkbox" :value="f.friend_user_id" />
            {{ f.remark || f.nickname }}
          </label>
          <div v-if="!friendsStore.friends.length" class="empty">暂无好友可移入</div>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showCreate = false">取消</button>
        <button class="btn btn-primary" @click="doCreate">创建</button>
      </template>
    </ModalDialog>

    <!-- 重命名分组 -->
    <ModalDialog :open="!!renameTarget" title="重命名分组" width="380" @close="renameTarget = null">
      <div class="field">
        <label>新分组名（原：{{ renameTarget?.name }}，{{ renameTarget?.list.length }} 人将一并迁移）</label>
        <input v-model="renameValue" class="input" maxlength="50" />
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="renameTarget = null">取消</button>
        <button class="btn btn-primary" @click="doRename">保存</button>
      </template>
    </ModalDialog>

    <!-- 删除分组确认 -->
    <ModalDialog :open="!!deleteGroupTarget" title="删除分组" width="380" @close="deleteGroupTarget = null">
      <p>确定删除分组「{{ deleteGroupTarget?.name }}」吗？组内 {{ deleteGroupTarget?.list.length }} 名成员将移入「我的好友」。</p>
      <template #footer>
        <button class="btn btn-ghost" @click="deleteGroupTarget = null">取消</button>
        <button class="btn btn-danger" @click="doDeleteGroup">删除</button>
      </template>
    </ModalDialog>

    <!-- 同班同学 -->
    <ModalDialog :open="showClassmates" title="找同班同学" width="420" @close="showClassmates = false">
      <div v-if="classmates.length" class="classmate-list">
        <div v-for="u in classmates" :key="u.id" class="item">
          <UserAvatar
            class="link"
            :name="u.nickname"
            :url="u.avatar_url"
            :size="36"
            @click="openProfile(u)"
          />
          <div class="item-mid link" @click="openProfile(u)">
            <div class="item-name">{{ u.nickname }}</div>
            <div class="item-sub">{{ u.department || '' }} {{ u.class_name || '' }}</div>
          </div>
          <button
            v-if="relationOf(u.id) === 'friend'"
            class="btn btn-primary btn-sm"
            @click="sendMessage(u.id)"
          >
            发消息
          </button>
          <button v-else-if="relationOf(u.id) === 'pending'" class="btn btn-ghost btn-sm" disabled>
            已申请
          </button>
          <button v-else class="btn btn-primary btn-sm" @click="addFriend(u.id)">加好友</button>
        </div>
      </div>
      <div v-else class="empty"><span class="icon">🎓</span>暂无同班同学，或你尚未填写班级</div>
    </ModalDialog>

    <!-- 查看全部：我发出的申请 -->
    <ModalDialog :open="showAllSent" title="我发出的申请" width="480" @close="showAllSent = false">
      <div class="all-list">
        <div v-for="r in friendsStore.sent" :key="r.request_id" class="item">
          <UserAvatar
            class="link"
            :name="r.user?.nickname"
            :url="r.user?.avatar_url"
            :size="36"
            @click="openProfile(r.user)"
          />
          <div class="item-mid link" @click="openProfile(r.user)">
            <div class="item-name">{{ r.user?.nickname }}</div>
            <div class="item-sub">@{{ r.user?.username }} · {{ formatDateTime(r.created_at) }}</div>
          </div>
          <span class="tag" :class="STATUS_TAG[r.status]">{{ SENT_STATUS[r.status] }}</span>
        </div>
        <div v-if="!friendsStore.sent.length" class="empty">暂无发出的申请</div>
      </div>
    </ModalDialog>

    <!-- 资料卡浮窗（复用组件，内部自行区分好友 / 非好友） -->
    <ProfileCard :open="cardUserId > 0" :user-id="cardUserId" @close="cardUserId = 0" />
  </div>
</template>

<style scoped>
.manage-panel {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 720px;
}
.block {
  padding: 20px 24px;
}
.block h3 {
  font-size: 15px;
  margin-bottom: 10px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.block-head h3 {
  margin-bottom: 0;
}
.hint {
  font-size: 12px;
  color: var(--g-8);
  margin-bottom: 8px;
}
.group {
  margin-bottom: 6px;
}
.group-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 0 5px;
  font-size: 13.5px;
}
.group-name {
  flex: 1;
  font-weight: 700;
}
.group-count {
  color: var(--g-8);
  font-size: 12px;
}
.ops {
  display: flex;
  gap: 6px;
}
.member-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 0 5px 12px;
}
.member-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.star {
  margin-right: 2px;
}
.member-group {
  width: 130px;
  height: 28px;
  flex: none;
  font-size: 12px;
}
.search {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
}
.item-mid {
  flex: 1;
  min-width: 0;
}
.item-name {
  font-size: 13.5px;
  font-weight: 600;
}
.item-sub {
  font-size: 12px;
  color: var(--g-8);
}
/* 头像与昵称可点击查看资料 */
.link {
  cursor: pointer;
}
.link:hover .item-name {
  color: var(--brand-7);
}
.sub-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12px;
  font-weight: 700;
  color: var(--g-8);
  margin: 12px 0 2px;
}
.more-link {
  border: none;
  background: none;
  color: var(--brand-7);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-cjk);
  cursor: pointer;
  padding: 0;
}
.more-link:hover {
  text-decoration: underline;
}
.all-list {
  max-height: 400px;
  overflow-y: auto;
}
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
.classmate-list {
  max-height: 360px;
  overflow-y: auto;
}
</style>
