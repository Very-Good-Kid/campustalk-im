<script setup>
/**
 * 好友资料面板（联系人页主栏，参照 QQ）：
 * 大头像 + 账号 + 资料区（备注 / 分组下拉 / 特别关心可直接编辑）+ 操作行。
 * 操作行与资料卡垂直居中对齐：分享好友（选会话发名片）/ 删除好友 / 发消息。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import ModalDialog from '@/components/ModalDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import * as channelApi from '@/api/channelContent'
import * as friendsApi from '@/api/friends'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useFriendsStore } from '@/stores/friends'
import { useToastStore } from '@/stores/toast'
import { useWebsocketStore } from '@/stores/websocket'

const props = defineProps({
  /** 路由参数 /contacts/friend/:userId */
  userId: { type: String, required: true },
})

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const friendsStore = useFriendsStore()
const toast = useToastStore()
const ws = useWebsocketStore()

const profile = ref(null)
const loading = ref(true)

/** 好友关系数据（备注 / 分组 / 特别关心），非好友时为空 */
const relation = computed(() =>
  friendsStore.friends.find((f) => f.friend_user_id === Number(props.userId)),
)

/** 是否在查看自己（侧栏「我」条目进来）：操作行与好友不同 */
const isSelf = computed(() => Number(props.userId) === auth.user?.id)

/** 分组下拉选项：已有分组 + 默认分组 */
const groupOptions = computed(() => {
  const names = new Set(['我的好友'])
  for (const f of friendsStore.friends) names.add(f.group_name || '我的好友')
  return [...names]
})

/** 资料区编辑态（仅好友可编辑） */
const editForm = ref({ remark: '', group_name: '我的好友', is_starred: false })
const showDelete = ref(false)
const showShare = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    if (!friendsStore.loaded) await friendsStore.loadAll()
    profile.value = await friendsApi.getUserProfile(props.userId)
    syncForm()
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
})

function syncForm() {
  editForm.value = {
    remark: relation.value?.remark || '',
    group_name: relation.value?.group_name || '我的好友',
    is_starred: relation.value?.is_starred || false,
  }
}

/** 保存备注 / 分组 / 特别关心（资料区改动即保存） */
async function saveRelation() {
  if (!relation.value) return
  try {
    await friendsApi.updateFriend(Number(props.userId), {
      remark: editForm.value.remark.trim() || null,
      group_name: editForm.value.group_name === '我的好友' ? null : editForm.value.group_name,
      is_starred: editForm.value.is_starred,
    })
    await friendsStore.loadAll()
    syncForm()
    toast.success('已保存')
  } catch (e) {
    toast.error(e.message)
  }
}

async function sendMessage() {
  try {
    const data = await friendsApi.openSingleConversation(Number(props.userId))
    await chat.loadConversations()
    router.push(`/chat/${data.conversation_id}`)
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 分享好友：选择一个会话，发送好友名片消息 ---------- */
const shareTarget = ref('')
const sharing = ref(false)

function openShare() {
  shareTarget.value = ''
  showShare.value = true
}

async function doShare() {
  if (!shareTarget.value) {
    toast.error('请选择要分享到的会话')
    return
  }
  const target = chat.conversations.find((c) => c.conversation_id === Number(shareTarget.value))
  sharing.value = true
  try {
    if (target?.type === 'channel') {
      // 频道是内容社区（帖子流）：名片以"名片帖"落库，回到频道即可看到
      await channelApi.createPost(target.conversation_id, { cardUserId: Number(props.userId) })
      toast.success(`好友名片已发布到「${target.name}」`)
    } else {
      // 群聊 / 单聊走实时消息流；断线时发送会被静默丢弃，这里先挡掉
      if (!ws.connected) {
        toast.error('连接已断开，名片发送失败，请稍后重试')
        return
      }
      chat.sendMessage({
        conversationId: target?.conversation_id ?? Number(shareTarget.value),
        msgType: 'card',
        content: String(props.userId),
      })
      toast.success('好友名片已发送')
    }
    showShare.value = false
  } catch (e) {
    toast.error(e.message)
  } finally {
    sharing.value = false
  }
}

async function doDelete() {
  try {
    await friendsApi.deleteFriend(Number(props.userId))
    toast.success('已删除好友')
    showDelete.value = false
    await friendsStore.loadAll()
    await chat.loadConversations()
    router.push('/contacts')
  } catch (e) {
    toast.error(e.message)
  }
}
</script>

<template>
  <div class="friend-panel">
    <div v-if="loading" class="empty"><span class="icon">⏳</span>加载中…</div>

    <template v-else-if="profile">
      <!-- 头部：大头像 + 名称 + 账号 -->
      <header class="head card">
        <UserAvatar :name="relation?.remark || profile.nickname" :url="profile.avatar_url" :size="88" />
        <div class="head-mid">
          <h2>
            <span v-if="relation?.is_starred" class="star">⭐</span>{{ relation?.remark || profile.nickname }}
          </h2>
          <p class="account">@{{ profile.username }}</p>
          <span v-if="isSelf" class="tag tag-brand">我自己</span>
          <span v-else-if="relation" class="tag tag-teal">好友</span>
          <span v-else class="tag">非好友</span>
        </div>
      </header>

      <!-- 资料区：备注 / 分组 / 特别关心可直接编辑（仅好友） -->
      <section class="info card">
        <div class="row">
          <span class="label">学号</span>
          <span class="value">{{ profile.student_id || '未填写' }}</span>
        </div>
        <div class="row">
          <span class="label">院系</span>
          <span class="value">{{ profile.department || '未填写' }}</span>
        </div>
        <div class="row">
          <span class="label">班级</span>
          <span class="value">{{ profile.class_name || '未填写' }}</span>
        </div>
        <template v-if="relation">
          <div class="row">
            <span class="label">备注名</span>
            <input
              v-model="editForm.remark"
              class="input inline-input"
              maxlength="50"
              placeholder="留空则显示昵称"
              @keyup.enter="saveRelation"
              @blur="saveRelation"
            />
          </div>
          <div class="row">
            <span class="label">分组</span>
            <select v-model="editForm.group_name" class="input inline-input" @change="saveRelation">
              <option v-for="g in groupOptions" :key="g" :value="g">{{ g }}</option>
            </select>
          </div>
          <div class="row">
            <span class="label">特别关心</span>
            <label class="star-toggle">
              <input v-model="editForm.is_starred" type="checkbox" @change="saveRelation" />
              置顶展示
            </label>
          </div>
        </template>
      </section>

      <!-- 操作行：与资料卡垂直居中对齐；查看自己时给出编辑资料 + 发消息 -->
      <footer class="ops">
        <button v-if="isSelf" class="btn btn-ghost op-btn" @click="router.push('/profile')">
          编辑资料
        </button>
        <template v-else-if="relation">
          <button class="btn btn-ghost op-btn" @click="openShare">分享好友</button>
          <button class="btn btn-ghost op-btn" @click="showDelete = true">删除好友</button>
        </template>
        <button class="btn btn-primary op-btn" @click="sendMessage">发消息</button>
      </footer>
    </template>

    <div v-else class="empty"><span class="icon">🙏</span>用户不存在或已注销</div>

    <!-- 分享好友：选择会话发送名片 -->
    <ModalDialog :open="showShare" title="分享好友" width="400" @close="showShare = false">
      <div class="field">
        <label>选择要分享到的会话</label>
        <select v-model="shareTarget" class="input">
          <option value="" disabled>请选择</option>
          <option v-for="c in chat.conversations" :key="c.conversation_id" :value="c.conversation_id">
            {{ c.name }}（{{ c.type === 'single' ? '单聊' : c.type === 'group' ? '群聊' : '频道' }}）
          </option>
        </select>
      </div>
      <p class="share-hint">将以「好友名片」消息发送到所选会话。</p>
      <template #footer>
        <button class="btn btn-ghost" @click="showShare = false">取消</button>
        <button class="btn btn-primary" :disabled="sharing" @click="doShare">发送</button>
      </template>
    </ModalDialog>

    <!-- 删除确认 -->
    <ModalDialog :open="showDelete" title="删除好友" width="360" @close="showDelete = false">
      <p>确定删除好友「{{ relation?.remark || profile?.nickname }}」吗？双方关系将同时解除，历史会话不再显示。</p>
      <template #footer>
        <button class="btn btn-ghost" @click="showDelete = false">取消</button>
        <button class="btn btn-danger" @click="doDelete">删除</button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.friend-panel {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 720px;
}
.head {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 24px;
}
.head h2 {
  font-size: 22px;
}
.head-mid {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
.account {
  font-size: 14px;
  color: var(--g-8);
}
.star {
  margin-right: 4px;
}
.info {
  padding: 10px 24px;
}
.row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 0;
  border-bottom: 1px solid var(--g-3);
  font-size: 14px;
}
.row:last-child {
  border-bottom: none;
}
.label {
  width: 72px;
  flex: none;
  color: var(--g-8);
  font-size: 13px;
}
.value {
  color: var(--g-12);
}
.inline-input {
  max-width: 280px;
  height: 30px;
}
.star-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
  color: var(--g-10);
}
/* 操作行：与上方资料卡垂直居中对齐 */
.ops {
  display: flex;
  gap: 14px;
  justify-content: center;
}
.op-btn {
  min-width: 108px;
}
.share-hint {
  font-size: 12px;
  color: var(--g-8);
}
</style>
