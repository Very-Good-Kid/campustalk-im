<script setup>
/**
 * 加入群聊浮窗（两步）：输入群号 → 搜索预览群信息 → 确认后发送申请。
 * 申请由群主 / 管理员在「群通知」审批。
 *
 * 会话列表右上角"＋"菜单与联系人侧栏共用本组件，表单状态全部内聚，
 * 调用方只需控制 open 并监听 close / submitted。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import ModalDialog from '@/components/ModalDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { previewGroup, requestJoinGroup } from '@/api/conversations'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'submitted'])

const router = useRouter()
const chat = useChatStore()
const toast = useToastStore()

const joinCode = ref('')
const joinMessage = ref('')
/** 搜索到的群信息（非空即进入第二步预览） */
const preview = ref(null)
const searching = ref(false)
const joining = ref(false)

/** 能否发申请：已在该群 / 已有待处理申请时不允许 */
const canApply = computed(
  () =>
    Boolean(preview.value) &&
    !preview.value.joined &&
    preview.value.my_request_status !== 'pending',
)

// 每次打开都重置到第一步，避免上次的输入与预览残留
watch(
  () => props.open,
  (open) => {
    if (open) reset()
  },
)

function reset() {
  joinCode.value = ''
  joinMessage.value = ''
  preview.value = null
}

/** 第一步：按群号搜索群信息 */
async function search() {
  const id = Number(joinCode.value)
  if (!Number.isInteger(id) || id <= 0) {
    toast.error('请输入正确的群号')
    return
  }
  searching.value = true
  try {
    preview.value = await previewGroup(id)
  } catch (e) {
    preview.value = null
    toast.error(e.message)
  } finally {
    searching.value = false
  }
}

/** 第二步：确认后发送申请 */
async function submit() {
  if (!canApply.value) return
  joining.value = true
  try {
    await requestJoinGroup(preview.value.conversation_id, joinMessage.value.trim() || null)
    toast.success('加群申请已发送，等待群主处理')
    emit('submitted')
    emit('close')
  } catch (e) {
    toast.error(e.message)
  } finally {
    joining.value = false
  }
}

/** 已在该群：直接进入群聊 */
async function sendMessage() {
  if (!preview.value) return
  await chat.loadConversations().catch(() => {})
  emit('close')
  router.push(`/chat/${preview.value.conversation_id}`)
}
</script>

<template>
  <ModalDialog :open="open" title="加入群聊" width="420" @close="emit('close')">
    <!-- 第一步：输入群号搜索 -->
    <template v-if="!preview">
      <div class="field">
        <label>群号</label>
        <div class="search-row">
          <input
            v-model="joinCode"
            class="input"
            autofocus
            inputmode="numeric"
            placeholder="输入群号，点右侧搜索"
            @keyup.enter="search"
          />
          <button class="btn btn-primary" :disabled="searching" @click="search">
            {{ searching ? '搜索中…' : '搜索' }}
          </button>
        </div>
      </div>
      <p class="hint">先搜索出群聊信息确认无误，再发送加入申请。</p>
    </template>

    <!-- 第二步：预览群信息 + 申请 -->
    <template v-else>
      <div class="preview card">
        <UserAvatar :name="preview.name" :url="preview.avatar_url" :size="56" />
        <div class="preview-mid">
          <div class="preview-name">{{ preview.name }}</div>
          <div class="preview-sub">群号 {{ preview.conversation_id }} · {{ preview.member_count }} 名成员</div>
          <div class="preview-sub">群主：{{ preview.owner_name || '—' }}</div>
        </div>
      </div>
      <p v-if="preview.joined" class="tip">你已在该群中，可直接进入群聊。</p>
      <p v-else-if="preview.my_request_status === 'pending'" class="tip">
        你已提交过申请，请等待群主处理。
      </p>
      <p v-else-if="preview.my_request_status === 'rejected'" class="tip">
        上次申请被拒绝，可以重新申请。
      </p>
      <div v-else class="field">
        <label>附言（可选）</label>
        <input
          v-model="joinMessage"
          class="input"
          maxlength="200"
          placeholder="让群主知道你是谁"
          @keyup.enter="submit"
        />
      </div>
    </template>

    <template #footer>
      <button v-if="!preview" class="btn btn-ghost" @click="emit('close')">取消</button>
      <template v-else>
        <button class="btn btn-ghost" @click="reset">重新输入</button>
        <button v-if="preview.joined" class="btn btn-primary" @click="sendMessage">发消息</button>
        <button v-else-if="canApply" class="btn btn-primary" :disabled="joining" @click="submit">
          {{ joining ? '发送中…' : '发送申请' }}
        </button>
        <button v-else class="btn btn-primary" @click="emit('close')">知道了</button>
      </template>
    </template>
  </ModalDialog>
</template>

<style scoped>
.search-row {
  display: flex;
  gap: 8px;
}
.search-row .input {
  flex: 1;
  min-width: 0;
}
.preview {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
}
.preview-mid {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.preview-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--g-12);
}
.preview-sub {
  font-size: 12px;
  color: var(--g-8);
}
.hint,
.tip {
  font-size: 12px;
  color: var(--g-8);
  margin-top: 4px;
}
</style>
