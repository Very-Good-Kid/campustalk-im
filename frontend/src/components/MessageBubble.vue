<script setup>
/**
 * 消息气泡：纯展示组件，不持有业务规则。
 *
 * 按消息类型渲染：text / emoji（气泡）、image（内联图）、file（下载卡片）、
 * card（好友名片）、recalled（撤回提示条）。动作（撤回 / 置顶 / 右键菜单）
 * 由父组件在气泡外围提供。
 * 详细发送时间默认不展示：鼠标悬停本条消息超过 3 秒才出现在昵称旁，
 * 悬停不产生任何浮起效果。
 */
import { computed, onBeforeUnmount, ref } from 'vue'

import UserAvatar from '@/components/UserAvatar.vue'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime, formatSize } from '@/utils/format'

const auth = useAuthStore()

const props = defineProps({
  msg: { type: Object, required: true },
  /** 是否本人发送（决定左右与配色） */
  mine: { type: Boolean, default: false },
  /** 群聊 / 频道中是否显示发送者昵称 */
  showNickname: { type: Boolean, default: false },
  /** 引用回复的预览文本（父组件查历史生成，空串表示非引用消息） */
  quotePreview: { type: String, default: '' },
})

/** view-card：点击名片消息查看资料；view-user：点击头像查看发送者资料 */
const emit = defineEmits(['view-card', 'view-user'])

const isRecalled = computed(() => Boolean(props.msg.recalled_at))
const isImage = computed(() => props.msg.msg_type === 'image' && !isRecalled.value)
const isFile = computed(() => props.msg.msg_type === 'file' && !isRecalled.value)
const isCard = computed(() => props.msg.msg_type === 'card' && !isRecalled.value)
const isEmoji = computed(() => props.msg.msg_type === 'emoji')

/** 悬停超过 3 秒才显示详细时间（昵称左侧 / 右侧） */
const showTime = ref(false)
let hoverTimer = null

function onHoverStart() {
  hoverTimer = setTimeout(() => {
    showTime.value = true
  }, 3000)
}
function onHoverEnd() {
  clearTimeout(hoverTimer)
  showTime.value = false
}
onBeforeUnmount(() => clearTimeout(hoverTimer))

function openImage(event) {
  window.open(event.target.src, '_blank')
}

/** @我高亮：后端已解析出 mentions，这里只负责把文本里的 "@我的昵称" 切成高亮段。
 * 返回 null 表示无需分段，模板直接渲染原文，不动其它消息的渲染路径。 */
const mentionSegments = computed(() => {
  const m = props.msg
  const nickname = auth.user?.nickname
  if (!nickname || m.msg_type !== 'text' || !Array.isArray(m.mentions)) return null
  if (!m.mentions.includes(auth.user?.id)) return null
  const token = `@${nickname}`
  const parts = (m.content || '').split(token)
  if (parts.length < 2) return null
  const segs = []
  parts.forEach((p, i) => {
    if (i > 0) segs.push({ text: token, hit: true })
    if (p) segs.push({ text: p, hit: false })
  })
  return segs
})
</script>

<template>
  <!-- 撤回消息：居中灰色提示条 -->
  <div v-if="isRecalled" class="recalled-tip">{{ msg.sender_nickname }} 撤回了一条消息</div>

  <div v-else class="row" :class="{ mine }" @mouseenter="onHoverStart" @mouseleave="onHoverEnd">
    <UserAvatar
      :name="msg.sender_nickname"
      :url="msg.sender_avatar_url"
      :size="36"
      class="avatar link"
      title="查看资料"
      @click="emit('view-user', msg.sender_id)"
    />
    <div class="stack">
      <!-- 元信息行：昵称 + 悬停后浮现的详细时间（我的消息时间在昵称左侧） -->
      <div v-if="showNickname || showTime" class="meta" :class="{ mine }">
        <span v-if="showTime && mine" class="msg-time">{{ formatDateTime(msg.created_at) }}</span>
        <span v-if="showNickname" class="nickname">{{ msg.sender_nickname }}<span v-if="msg.sender_type === 'bot'" class="tag tag-teal bot">BOT</span></span>
        <span v-if="showTime && !mine" class="msg-time">{{ formatDateTime(msg.created_at) }}</span>
      </div>

      <!-- 图片消息：内联显示，点击新窗口查看原图 -->
      <img
        v-if="isImage"
        class="img-bubble"
        :src="msg.content"
        :alt="msg.file_name || '图片'"
        @click="openImage"
      />

      <!-- 文件消息：可下载卡片 -->
      <a v-else-if="isFile" class="file-bubble card" :href="msg.content" :download="msg.file_name || ''">
        <span class="file-icon">📄</span>
        <span class="file-meta">
          <span class="file-name">{{ msg.file_name || '未命名文件' }}</span>
          <span class="file-size">{{ formatSize(msg.file_size) }}</span>
        </span>
        <span class="file-down">下载</span>
      </a>

      <!-- 好友名片：展示被推荐用户的头像与昵称，点击查看资料由父组件处理 -->
      <div
        v-else-if="isCard"
        class="card-bubble card"
        @click="emit('view-card', msg.card_user?.id || Number(msg.content))"
      >
        <UserAvatar
          :name="msg.card_user?.nickname || '好友名片'"
          :url="msg.card_user?.avatar_url"
          :size="40"
        />
        <span class="card-body">
          <span class="card-title">{{ msg.card_user?.nickname || '好友名片' }}</span>
          <span class="card-sub">点击查看资料</span>
        </span>
      </div>

      <!-- 文本 / 表情：表情放大字号；@我时把 "@我的昵称" 高亮 -->
      <div v-else class="bubble" :class="{ emoji: isEmoji }">
        <div v-if="quotePreview" class="quote-bar">{{ quotePreview }}</div>
        <template v-if="mentionSegments">
          <span v-for="(seg, i) in mentionSegments" :key="i" :class="{ 'mention-hit': seg.hit }">{{ seg.text }}</span>
        </template>
        <template v-else>{{ msg.content }}</template>
      </div>

      <!-- 动作区插槽：撤回 / 置顶等由父组件提供 -->
      <slot />
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  /* 顶部对齐：昵称行与头像顶端对齐（原先底部对齐，头像会贴着气泡下沿） */
  align-items: flex-start;
  gap: 10px;
  margin: 10px 0;
}
.row.mine {
  flex-direction: row-reverse;
}
/* 头像可点击查看资料 */
.avatar.link {
  cursor: pointer;
}
.avatar.link:hover {
  opacity: 0.85;
}
.stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  max-width: 60%;
}
.row.mine .stack {
  align-items: flex-end;
}
.nickname {
  font-size: 12px;
  color: var(--g-8);
  display: flex;
  gap: 6px;
  align-items: center;
}
/* 元信息行：昵称 + 悬停时间；我的消息整体靠右 */
.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
/* 发送方：整行靠右，但保持"时间在昵称左侧"的自然顺序
   （原先用 row-reverse，把时间反到了昵称右侧） */
.meta.mine {
  justify-content: flex-end;
}
.msg-time {
  font-size: 11px;
  color: var(--g-7);
  white-space: nowrap;
}
.bot {
  height: 18px;
  padding: 0 6px;
  font-size: 10px;
}

.bubble {
  background: var(--g-1);
  border: 1px solid var(--g-4);
  border-radius: var(--radius-m);
  padding: 9px 13px;
  word-break: break-word;
  white-space: pre-wrap;
  max-width: 100%;
}
.row.mine .bubble {
  background: var(--brand-7);
  border-color: var(--brand-7);
  color: #fff;
}
.bubble.emoji {
  font-size: 30px;
  background: none;
  border: none;
  padding: 2px 4px;
}
/* @我命中段：浅珊瑚底 + 加粗，与未读红点同族色；气泡是 brand 底时改用白底反衬 */
.mention-hit {
  background: var(--coral-1);
  color: var(--coral-6);
  font-weight: 600;
  border-radius: 3px;
  padding: 0 2px;
}
.row.mine .mention-hit {
  background: rgba(255, 255, 255, 0.9);
}
.quote-bar {
  font-size: 12px;
  color: var(--g-8);
  background: rgba(0, 0, 0, 0.05);
  border-left: 2px solid var(--brand-5, #7aa2ff);
  border-radius: 4px;
  padding: 3px 8px;
  margin-bottom: 6px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row.mine .quote-bar {
  background: rgba(255, 255, 255, 0.25);
  color: rgba(255, 255, 255, 0.85);
  border-left-color: rgba(255, 255, 255, 0.7);
}

.img-bubble {
  max-width: 260px;
  max-height: 200px;
  border-radius: var(--radius-m);
  border: 1px solid var(--g-4);
  cursor: zoom-in;
  display: block;
}

.file-bubble,
.card-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  min-width: 200px;
  cursor: pointer;
  color: var(--g-12);
}
.file-bubble:hover,
.card-bubble:hover {
  border-color: var(--brand-3);
}
.file-icon {
  font-size: 24px;
}
.card-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.file-meta {
  display: flex;
  flex-direction: column;
}
.file-name {
  font-size: 13px;
  font-weight: 600;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-size {
  font-size: 11px;
  color: var(--g-8);
}
.file-down {
  margin-left: auto;
  font-size: 12px;
  color: var(--brand-7);
}

.card-title {
  display: block;
  font-size: 13px;
  font-weight: 600;
}
.card-sub {
  display: block;
  font-size: 11px;
  color: var(--g-8);
}

.recalled-tip {
  text-align: center;
  font-size: 12px;
  color: var(--g-7);
  margin: 8px 0;
}
</style>
