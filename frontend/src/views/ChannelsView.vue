<script setup>
/**
 * 频道页（设计 2.3.7）：square 模式为频道广场（关键词检索 / 创建 / 免审加入），
 * mine 模式为我加入的频道。侧边栏第一级选项在两者间切换。
 * 加入免审——"免审进入 ≠ 免审发言"，发言仍受敏感词过滤约束。
 * 进入 / 加入后跳转频道帖子流页（ChannelDetailView），频道内容以帖子沉淀。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import ModalDialog from '@/components/ModalDialog.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { IMAGE_ACCEPT, uploadFile } from '@/api/content'
import { createChannel, getChannels, joinChannel } from '@/api/conversations'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  /** 路由模式：square=频道广场 / mine=我的频道 */
  mode: { type: String, default: 'square' },
})

const router = useRouter()
const chat = useChatStore()
const toast = useToastStore()

const keyword = ref('')
const channels = ref([])
const loading = ref(false)

const isMine = computed(() => props.mode === 'mine')
/** 我的频道 = 已加入的频道（广场接口带 joined 标记，前端过滤） */
const visibleChannels = computed(() =>
  isMine.value ? channels.value.filter((c) => c.joined) : channels.value,
)

const showCreate = ref(false)
const createForm = ref({ name: '', description: '', avatar_url: '' })
const avatarInput = ref(null)

onMounted(load)

async function load() {
  loading.value = true
  try {
    channels.value = await getChannels(keyword.value.trim())
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

async function join(c) {
  try {
    await joinChannel(c.conversation_id)
    toast.success(`已加入「${c.name}」`)
    await chat.loadConversations()
    router.push(`/channels/${c.conversation_id}`)
  } catch (e) {
    toast.error(e.message)
  }
}

function enter(c) {
  router.push(`/channels/${c.conversation_id}`)
}

async function pickAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const data = await uploadFile(file, 'image')
    createForm.value.avatar_url = data.url
  } catch (e) {
    toast.error(e.message)
  }
}

async function doCreate() {
  const name = createForm.value.name.trim()
  if (!name) {
    toast.error('请填写频道名称')
    return
  }
  try {
    const data = await createChannel(
      name,
      createForm.value.description.trim() || null,
      createForm.value.avatar_url || null,
    )
    toast.success('频道已创建')
    showCreate.value = false
    createForm.value = { name: '', description: '', avatar_url: '' }
    await chat.loadConversations()
    router.push(`/channels/${data.conversation_id}`)
  } catch (e) {
    toast.error(e.message)
  }
}
</script>

<template>
  <div class="channels">
    <header class="head">
      <div>
        <h2>{{ isMine ? '我的频道' : '频道广场' }}</h2>
        <p class="sub">
          {{
            isMine
              ? '你已加入的频道 · 点开即进入帖子流'
              : '围绕兴趣主题的公开讨论区 · 免审加入 · 陌生人也能同频交流'
          }}
        </p>
      </div>
      <button v-if="isMine" class="btn btn-ghost" @click="router.push('/channels')">去频道广场</button>
      <button v-else class="btn btn-primary" @click="showCreate = true">+ 创建频道</button>
    </header>

    <div v-if="!isMine" class="search">
      <input
        v-model="keyword"
        class="input"
        placeholder="按关键词检索频道，回车确认"
        @keyup.enter="load"
      />
      <button class="btn btn-ghost" @click="load">检索</button>
    </div>

    <div v-if="loading" class="empty"><span class="icon">⏳</span>加载中…</div>

    <div v-else-if="visibleChannels.length" class="grid">
      <div v-for="c in visibleChannels" :key="c.conversation_id" class="card ch-card">
        <div class="ch-head">
          <UserAvatar :name="c.name" :url="c.avatar_url" :size="44" />
          <div class="ch-title">
            <h3>{{ c.name }}</h3>
            <span v-if="c.joined" class="tag tag-teal">已加入</span>
          </div>
        </div>
        <p class="desc">{{ c.description || '这个频道还没有简介' }}</p>
        <div class="meta">
          <span>{{ c.member_count }} 名成员</span>
          <span v-if="c.creator">创建者：{{ c.creator }}</span>
        </div>
        <button class="btn btn-primary enter" @click="c.joined ? enter(c) : join(c)">
          {{ c.joined ? '进入' : '加入' }}
        </button>
      </div>
    </div>
    <div v-else-if="isMine" class="empty">
      <span class="icon">📡</span>还没有加入任何频道<br />去广场看看感兴趣的话题吧<br />
      <button class="btn btn-primary go-square" @click="router.push('/channels')">去频道广场</button>
    </div>
    <div v-else class="empty">
      <span class="icon">📡</span>没有找到相关频道<br />换个关键词，或创建第一个吧
    </div>

    <!-- 创建频道 -->
    <ModalDialog :open="showCreate" title="创建频道" @close="showCreate = false">
      <div class="field">
        <label>频道头像</label>
        <div class="avatar-pick">
          <button class="avatar-btn" title="点击上传头像" @click="avatarInput.click()">
            <UserAvatar :name="createForm.name || '频道'" :url="createForm.avatar_url" :size="56" />
          </button>
          <span class="avatar-tip">可选，不上传则按频道名生成默认头像</span>
          <input ref="avatarInput" type="file" :accept="IMAGE_ACCEPT" hidden @change="pickAvatar" />
        </div>
      </div>
      <div class="field">
        <label>频道名称</label>
        <input v-model="createForm.name" class="input" maxlength="100" placeholder="如：前端技术交流" />
      </div>
      <div class="field">
        <label>频道简介</label>
        <textarea v-model="createForm.description" class="input" rows="3" maxlength="500" placeholder="一句话介绍这个频道讨论什么"></textarea>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showCreate = false">取消</button>
        <button class="btn btn-primary" @click="doCreate">创建</button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.channels {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  min-height: 0;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
}
.head h2 {
  font-size: 20px;
}
.sub {
  font-size: 13px;
  color: var(--g-8);
  margin-top: 4px;
}
.search {
  display: flex;
  gap: 10px;
  max-width: 520px;
  margin-bottom: 20px;
}
.go-square {
  margin-top: 10px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.ch-card {
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ch-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ch-title {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ch-title h3 {
  font-size: 16px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
.desc {
  font-size: 13px;
  color: var(--g-9);
  min-height: 40px;
}
.meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--g-8);
}
.enter {
  margin-top: 4px;
}
</style>
