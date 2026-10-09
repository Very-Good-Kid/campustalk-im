<script setup>
/**
 * 群资料浮层（对齐 ProfileCard 的形式）：群通知里点开某条记录查看群详情，
 * 并从中进入群聊。
 *
 * 数据复用"加群预览"接口（知道群号即可查，不要求是群成员），
 * 因此成员与非成员都能打开。
 */
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import ModalDialog from '@/components/ModalDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { previewGroup } from '@/api/conversations'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  open: { type: Boolean, default: false },
  /** 要展示的群 id（= 会话 id） */
  conversationId: { type: Number, default: 0 },
})
const emit = defineEmits(['close'])

const router = useRouter()
const chat = useChatStore()
const toast = useToastStore()

const group = ref(null)

watch(
  () => [props.open, props.conversationId],
  async ([open, id]) => {
    group.value = null
    if (!open || !id) return
    try {
      group.value = await previewGroup(id)
    } catch (e) {
      toast.error(e.message)
      emit('close')
    }
  },
  { immediate: true },
)

async function sendMessage() {
  if (!group.value) return
  // 会话来列表可能还没包含该群，先刷新再跳转
  await chat.loadConversations().catch(() => {})
  emit('close')
  router.push(`/chat/${group.value.conversation_id}`)
}
</script>

<template>
  <ModalDialog :open="open" title="群资料" @close="emit('close')">
    <div v-if="group" class="group">
      <div class="head-row">
        <UserAvatar :name="group.name" :url="group.avatar_url" :size="64" />
        <div>
          <div class="name">{{ group.name }}</div>
          <div class="meta">群号 {{ group.conversation_id }} · {{ group.member_count }} 名成员</div>
        </div>
      </div>
      <dl class="rows">
        <div class="row-item">
          <dt>群主</dt>
          <dd>{{ group.owner_name || '—' }}</dd>
        </div>
        <div v-if="group.description" class="row-item">
          <dt>简介</dt>
          <dd>{{ group.description }}</dd>
        </div>
      </dl>
    </div>
    <div v-else class="empty"><span class="icon">⏳</span>加载中…</div>

    <template #footer>
      <button class="btn btn-ghost" @click="emit('close')">关闭</button>
      <button v-if="group" class="btn btn-primary" @click="sendMessage">发消息</button>
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
.name {
  font-size: 18px;
  font-weight: 700;
}
.meta {
  font-size: 13px;
  color: var(--g-8);
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
  word-break: break-word;
}
</style>
