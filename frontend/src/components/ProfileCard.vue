<script setup>
/**
 * 好友资料浮窗卡片（设计 2.3.8）：浮窗层而非独立页面。
 *
 * 三个触发入口共用本组件：好友列表、搜索结果、聊天中的名片消息。
 * 按当前关系渲染操作区：非好友→加为好友；好友→发消息 / 删除好友。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import UserAvatar from '@/components/UserAvatar.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import * as friendsApi from '@/api/friends'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  open: { type: Boolean, default: false },
  /** 要展示的用户 id */
  userId: { type: Number, default: 0 },
  /** 是否提供"删除好友"（好友列表场景） */
  showDelete: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'deleted'])

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const toast = useToastStore()

const profile = ref(null)
const isFriend = ref(false)
const showDeleteConfirm = ref(false)

/** 查看的是否是自己：给"编辑资料 + 发消息"，不给加好友 / 删除好友 */
const isSelf = computed(() => props.userId > 0 && props.userId === auth.user?.id)

watch(
  () => [props.open, props.userId],
  async ([open, uid]) => {
    profile.value = null
    isFriend.value = false
    if (!open || !uid) return
    try {
      const [p, friends] = await Promise.all([
        friendsApi.getUserProfile(uid),
        friendsApi.getFriends(),
      ])
      profile.value = p
      isFriend.value = friends.some((f) => f.friend_user_id === uid)
      // 这里拿到的资料是最新的：顺手刷新名片消息里该用户的头像，无需刷新页面
      chat.syncCardAvatar(p.id, p.avatar_url)
    } catch (e) {
      toast.error(e.message)
      emit('close')
    }
  },
  { immediate: true },
)

async function addFriend() {
  if (!profile.value) return
  try {
    await friendsApi.sendFriendRequest(profile.value.id)
    toast.success('好友申请已发送，等待对方同意')
    emit('close')
  } catch (e) {
    toast.error(e.message)
  }
}

/** 查看的是自己：去个人资料页编辑 */
function editProfile() {
  emit('close')
  router.push('/profile')
}

async function sendMessage() {
  try {
    const data = await friendsApi.openSingleConversation(profile.value.id)
    await chat.loadConversations()
    emit('close')
    router.push(`/chat/${data.conversation_id}`)
  } catch (e) {
    toast.error(e.message)
  }
}

async function doDelete() {
  try {
    await friendsApi.deleteFriend(profile.value.id)
    toast.success('已删除好友')
    showDeleteConfirm.value = false
    emit('deleted')
    emit('close')
  } catch (e) {
    toast.error(e.message)
  }
}
</script>

<template>
  <ModalDialog :open="open" title="用户资料" @close="emit('close')">
    <div v-if="profile" class="profile">
      <div class="head-row">
        <UserAvatar :name="profile.nickname" :url="profile.avatar_url" :size="64" />
        <div>
          <div class="nick">{{ profile.nickname }}</div>
          <div class="uname">@{{ profile.username }}</div>
        </div>
      </div>
      <dl class="rows">
        <div v-if="profile.student_id" class="row-item">
          <dt>学号</dt>
          <dd>{{ profile.student_id }}</dd>
        </div>
        <div v-if="profile.department" class="row-item">
          <dt>院系</dt>
          <dd>{{ profile.department }}</dd>
        </div>
        <div v-if="profile.class_name" class="row-item">
          <dt>班级</dt>
          <dd>{{ profile.class_name }}</dd>
        </div>
      </dl>
    </div>
    <div v-else class="empty"><span class="icon">⏳</span>加载中…</div>

    <template #footer>
      <template v-if="profile">
        <button v-if="isSelf" class="btn btn-ghost" @click="editProfile">编辑资料</button>
        <button v-if="showDelete && isFriend" class="btn btn-danger btn-sm" @click="showDeleteConfirm = true">
          删除好友
        </button>
        <button v-if="isSelf || isFriend" class="btn btn-primary" @click="sendMessage">发消息</button>
        <button v-else class="btn btn-primary" @click="addFriend">加为好友</button>
      </template>
    </template>
  </ModalDialog>

  <!-- 删除好友二次确认 -->
  <ModalDialog :open="showDeleteConfirm" title="删除好友" width="360" @close="showDeleteConfirm = false">
    <p>确定删除好友「{{ profile?.nickname }}」吗？双方好友关系将同时解除。</p>
    <template #footer>
      <button class="btn btn-ghost" @click="showDeleteConfirm = false">取消</button>
      <button class="btn btn-danger" @click="doDelete">删除</button>
    </template>
  </ModalDialog>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.nick {
  font-size: 18px;
  font-weight: 700;
}
.uname {
  font-size: 13px;
  color: var(--g-8);
  font-family: var(--font-mono);
}
.rows {
  border-top: 1px solid var(--g-4);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row-item {
  display: flex;
  gap: 14px;
  font-size: 13.5px;
}
.row-item dt {
  width: 40px;
  color: var(--g-8);
  flex: none;
}
.row-item dd {
  color: var(--g-12);
}
</style>
