<script setup>
/**
 * 群资料面板（联系人页主栏）：群信息 + 成员列表 + 操作行。
 * 操作行与资料卡垂直居中对齐：分享群聊 / 发消息。
 * 群介绍 / 群公告属群管理范围（后续版本），先占位展示。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import ModalDialog from '@/components/ModalDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { getMembers } from '@/api/conversations'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  /** 路由参数 /contacts/group/:id（会话 id） */
  groupId: { type: String, required: true },
})

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const toast = useToastStore()

const members = ref([])
const loading = ref(true)

const conv = computed(() =>
  chat.conversations.find((c) => c.conversation_id === Number(props.groupId)),
)
const myRole = computed(() => {
  const me = members.value.find((m) => m.user_id === auth.user?.id)
  return me?.role || 'member'
})
const ownerName = computed(() => members.value.find((m) => m.role === 'owner')?.nickname || '—')

onMounted(async () => {
  try {
    members.value = await getMembers(Number(props.groupId))
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
})

function enterChat() {
  router.push(`/chat/${props.groupId}`)
}

/** 复制群号：方便把群号发给别人申请入群 */
async function copyGroupNo() {
  try {
    await navigator.clipboard.writeText(String(props.groupId))
    toast.success('群号已复制')
  } catch {
    toast.error('复制失败，请手动复制')
  }
}

/** 分享群聊：复制群信息到剪贴板（群名片消息后续版本接入） */
const showShare = ref(false)

async function doShare() {
  const text = `【CampusTalk 群聊】${conv.value?.name || ''}（群号 ${props.groupId}）`
  try {
    await navigator.clipboard.writeText(text)
    toast.success('群信息已复制，去粘贴分享吧')
    showShare.value = false
  } catch {
    toast.error('复制失败，请手动复制')
  }
}
</script>

<template>
  <div class="group-panel">
    <div v-if="loading" class="empty"><span class="icon">⏳</span>加载中…</div>

    <template v-else-if="conv">
      <header class="head card">
        <UserAvatar :name="conv.name" :url="conv.avatar_url" :size="88" />
        <div class="head-mid">
          <h2>{{ conv.name }}</h2>
          <p class="account">群聊 · {{ conv.member_count ?? members.length }} 名成员</p>
          <span class="tag tag-brand">群聊</span>
        </div>
      </header>

      <section class="info card">
        <div class="row">
          <span class="label">群号</span>
          <span class="value group-no">
            {{ groupId }}
            <button class="copy-no" @click="copyGroupNo">复制</button>
          </span>
        </div>
        <div class="row">
          <span class="label">群主</span>
          <span class="value">{{ ownerName }}</span>
        </div>
        <div class="row">
          <span class="label">我的身份</span>
          <span class="value">{{ myRole === 'owner' ? '群主' : myRole === 'admin' ? '管理员' : '成员' }}</span>
        </div>
        <div class="row">
          <span class="label">群介绍</span>
          <span class="value muted">暂未填写（后续版本支持）</span>
        </div>
        <div class="row">
          <span class="label">群公告</span>
          <span class="value muted">暂无公告（后续版本支持）</span>
        </div>
      </section>

      <section class="info card">
        <h3>成员（{{ members.length }}）</h3>
        <div class="member-list">
          <div v-for="m in members" :key="m.user_id" class="member">
            <UserAvatar :name="m.nickname" :url="m.avatar_url" :size="34" />
            <span class="member-name">{{ m.nickname }}</span>
            <span v-if="m.role !== 'member'" class="tag" :class="m.role === 'owner' ? 'tag-coral' : 'tag-brand'">
              {{ m.role === 'owner' ? '群主' : '管理员' }}
            </span>
          </div>
        </div>
      </section>

      <!-- 操作行：与上方资料卡垂直居中对齐 -->
      <footer class="ops">
        <button class="btn btn-ghost op-btn" @click="showShare = true">分享群聊</button>
        <button class="btn btn-primary op-btn" @click="enterChat">发消息</button>
      </footer>
    </template>

    <div v-else class="empty"><span class="icon">👪</span>群聊不存在或已退出</div>

    <!-- 分享群聊 -->
    <ModalDialog :open="showShare" title="分享群聊" width="380" @close="showShare = false">
      <p>
        将复制群信息：<strong>【CampusTalk 群聊】{{ conv?.name }}（群号 {{ groupId }}）</strong><br />
        群名片消息后续版本支持，当前以文本分享。
      </p>
      <template #footer>
        <button class="btn btn-ghost" @click="showShare = false">取消</button>
        <button class="btn btn-primary" @click="doShare">复制并分享</button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.group-panel {
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
.info {
  padding: 10px 24px;
}
.info h3 {
  font-size: 14px;
  padding: 10px 0 4px;
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
.muted {
  color: var(--g-7);
}
.group-no {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}
.copy-no {
  border: 1px solid var(--g-5);
  background: var(--g-1);
  border-radius: var(--radius-s);
  font-size: 12px;
  color: var(--brand-7);
  padding: 2px 8px;
  cursor: pointer;
  font-family: var(--font-cjk);
}
.copy-no:hover {
  border-color: var(--brand-3);
  background: var(--brand-1);
}
.member-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 6px;
  padding-bottom: 12px;
}
.member {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-radius: var(--radius-s);
  min-width: 0;
}
.member:hover {
  background: var(--g-2);
}
.member-name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
</style>
