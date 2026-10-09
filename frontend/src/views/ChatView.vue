<script setup>
/**
 * 聊天页（设计 2.3.4）：消息区 + 输入区，单聊 / 群聊 / 频道三种会话共用。
 *
 * 能力：文本 / 表情 / 图片 / 文件发送、历史游标分页（上滚加载）、
 * 撤回（本人 3 分钟内）、举报、频道置顶话题帖、群成员管理（邀请 / 移除 / 退群）。
 * 所有确认均为页面内浮窗（ModalDialog），不使用浏览器原生弹窗。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import EmojiPicker from '@/components/EmojiPicker.vue'
import MessageBubble from '@/components/MessageBubble.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import ProfileCard from '@/components/ProfileCard.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import ChannelDetailView from '@/views/ChannelDetailView.vue'
import { IMAGE_ACCEPT, uploadFile } from '@/api/content'
import * as convApi from '@/api/conversations'
import { createReport } from '@/api/governance'
import { getFriends } from '@/api/friends'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'
import { EMOJIS, detectMsgType, formatDateTime, parseUtc } from '@/utils/format'

const props = defineProps({
  /** 路由参数 /chat/:id */
  id: { type: String, required: true },
})

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const toast = useToastStore()

const conversationId = computed(() => Number(props.id))
const conv = computed(() => chat.activeConversation)
const isGroupOrChannel = computed(() => conv.value && conv.value.type !== 'single')
const isChannel = computed(() => conv.value?.type === 'channel')
/** 群聊 / 频道显示发送者昵称；单聊靠左右位置即可区分 */
const showNickname = computed(() => isGroupOrChannel.value)

/** "对方正在输入…"：单聊不点名；群聊/频道拼最多三个昵称，再多用"等" */
const typingHint = computed(() => {
  const uids = chat.activeTypingUids
  if (!uids.length) return ''
  if (!isGroupOrChannel.value) return '对方正在输入…'
  const names = uids
    .slice(0, 3)
    .map((id) => chat.activeMembers.find((m) => m.user_id === id)?.nickname || '有人')
  return names.join('、') + (uids.length > 3 ? ' 等' : '') + '正在输入…'
})

const messagesEl = ref(null)
const inputText = ref('')
const showEmoji = ref(false)
const showMembers = ref(false)

/** 会话内消息搜索：后端 ngram 全文索引，点结果跳到锚点上下文页 */
const showSearch = ref(false)
const searchQ = ref('')
const searchResults = ref([])
const searching = ref(false)
const searchedOnce = ref(false)
/** 跳转落点高亮（2 秒自动清） */
const highlightMsgId = ref(null)
let highlightTimer = null

const imageInput = ref(null)
const fileInput = ref(null)

/** 撤回时间窗：与后端 RECALL_WINDOW_SECONDS 保持一致（3 分钟） */
const RECALL_WINDOW_MS = 180 * 1000

/** 右键菜单"回复表情包"的快捷表情（取全量表情集前 8 个） */
const QUICK_EMOJIS = EMOJIS.slice(0, 8)

/** 当前用户在会话中的角色（成员管理入口显示用） */
const myRole = computed(() => {
  if (conv.value?.is_owner) return 'owner'
  return chat.activeMembers.find((m) => m.user_id === auth.user?.id)?.role || 'member'
})
const canManage = computed(() => myRole.value === 'owner' || myRole.value === 'admin')

onMounted(() => {
  chat.openConversation(conversationId.value).then(scrollToBottom)
})

watch(conversationId, (id) => {
  if (!id) return
  showMembers.value = false
  closeSearch()
  chat.openConversation(id).then(scrollToBottom)
})

function scrollToBottom() {
  nextTick(() => {
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

/** 上滚到顶加载更早的历史（游标分页）。 */
function onScroll() {
  const el = messagesEl.value
  if (!el || chat.loadingMore || chat.hasMore[conversationId.value] === false) return
  const before = el.scrollHeight
  chat.loadMore(conversationId.value).then(() => {
    nextTick(() => {
      // 保持视口停留在原位置附近，避免加载后跳到顶部
      if (el.scrollTop === 0) el.scrollTop = el.scrollHeight - before
    })
  })
}

/** ---------- 会话内搜索：回车查 → 点结果 → 换成锚点页并滚过去 ---------- */

function toggleSearch() {
  showSearch.value = !showSearch.value
  if (!showSearch.value) closeSearch()
}

function closeSearch() {
  showSearch.value = false
  searchQ.value = ''
  searchResults.value = []
  searchedOnce.value = false
  highlightMsgId.value = null
}

async function runMsgSearch() {
  const q = searchQ.value.trim()
  if (!q || searching.value) return
  searching.value = true
  try {
    searchResults.value = await convApi.searchMessages(conversationId.value, q)
    searchedOnce.value = true
  } catch (e) {
    toast.error(e.message)
  } finally {
    searching.value = false
  }
}

/** 点击搜索结果：拉锚点上下文页替换当前列表，滚动居中并闪一下落点 */
async function jumpToMessage(messageId) {
  try {
    const page = await convApi.getMessagesAround(conversationId.value, messageId)
    chat.messages[conversationId.value] = page
    // 替换后不是最新一页，向上加载照常可用；向下靠实时推送续接
    chat.hasMore[conversationId.value] = true
    await nextTick()
    const el = document.getElementById(`msg-${messageId}`)
    if (!el) return
    el.scrollIntoView({ block: 'center' })
    highlightMsgId.value = messageId
    clearTimeout(highlightTimer)
    highlightTimer = setTimeout(() => {
      highlightMsgId.value = null
    }, 2000)
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 发送：文本 / 表情 / 图片 / 文件 ---------- */

function sendText() {
  const content = inputText.value
  if (!content.trim()) return
  // 纯表情与空白 → msg_type=emoji，否则 text（与后端约定一致）
  chat.sendMessage({
    conversationId: conversationId.value,
    msgType: detectMsgType(content),
    content: content.trim(),
    replyToId: quoteTarget.value?.id || null,
  })
  inputText.value = ''
  showEmoji.value = false
  cancelQuote()
  scrollToBottom()
}

function insertEmoji(emoji) {
  inputText.value += emoji
}

async function pickImage(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file) await sendMedia(file)
}

async function pickFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (file) await sendMedia(file)
}

/** 先上传拿 URL，再以对应消息类型走同一条 WS 发送链路（二进制绝不进帧）。 */
async function sendMedia(file) {
  const kind = file.type.startsWith('image/') ? 'image' : 'file'
  try {
    const data = await uploadFile(file, kind)
    chat.sendMessage({
      conversationId: conversationId.value,
      msgType: data.kind,
      content: data.url,
      fileName: data.file_name,
      fileSize: data.file_size,
    })
    scrollToBottom()
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 消息动作：撤回 / 举报 / 置顶 ---------- */

const confirmRecall = ref(null) // 待撤回的消息
const reportTarget = ref(null) // 待举报的消息
const reportReason = ref('')

/** 右键上下文菜单（长按菜单的桌面形态）：复制 / 转发 / 引用 / 回复表情包 / 举报 */
const msgMenu = ref(null) // { x, y, msg }

function openMsgMenu(event, msg) {
  if (msg.recalled_at) return
  // 菜单宽度约 160px、高度约 190px，贴边时向内收
  const x = Math.min(event.clientX, window.innerWidth - 170)
  const y = Math.min(event.clientY, window.innerHeight - 200)
  msgMenu.value = { x, y, msg }
}

async function copyMsg(msg) {
  try {
    await navigator.clipboard.writeText(msg.content)
    toast.success('已复制到剪贴板')
  } catch {
    toast.error('复制失败')
  } finally {
    msgMenu.value = null
  }
}

function reportFromMenu() {
  reportTarget.value = msgMenu.value.msg
  reportReason.value = ''
  msgMenu.value = null
}

/** 右键菜单 → 撤回：先关菜单，再走原有的确认浮窗 */
function recallFromMenu() {
  confirmRecall.value = msgMenu.value.msg
  msgMenu.value = null
}

/** 引用回复：输入框上方挂引用预览，随下一条文本一起发出 */
const quoteTarget = ref(null)

function startQuote() {
  quoteTarget.value = msgMenu.value.msg
  msgMenu.value = null
}

function cancelQuote() {
  quoteTarget.value = null
}

/** 回复表情包：直接以 emoji 消息回应目标消息 */
function replyEmoji(emoji) {
  chat.sendMessage({
    conversationId: conversationId.value,
    msgType: 'emoji',
    content: emoji,
    replyToId: msgMenu.value.msg.id,
  })
  msgMenu.value = null
  scrollToBottom()
}

/** 转发：选一个会话，把消息原样重发（文本 / 图片 / 文件 / 名片均支持） */
const forwardTarget = ref(null) // 待转发的消息
const forwardTo = ref('')

function startForward() {
  forwardTarget.value = msgMenu.value.msg
  forwardTo.value = ''
  msgMenu.value = null
}

function doForward() {
  if (!forwardTo.value) {
    toast.error('请选择要转发到的会话')
    return
  }
  chat.sendMessage({
    conversationId: Number(forwardTo.value),
    msgType: forwardTarget.value.msg_type,
    content: forwardTarget.value.content,
    fileName: forwardTarget.value.file_name,
    fileSize: forwardTarget.value.file_size,
  })
  toast.success('已转发')
  forwardTarget.value = null
}

/** 点击空白处 / Esc 关闭右键菜单 */
function onGlobalClick() {
  msgMenu.value = null
}
function onEscKey(e) {
  if (e.key === 'Escape') msgMenu.value = null
}
onMounted(() => {
  document.addEventListener('click', onGlobalClick)
  document.addEventListener('keyup', onEscKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onGlobalClick)
  document.removeEventListener('keyup', onEscKey)
  clearTimeout(highlightTimer)
})

/** 引用消息的内容预览（从已加载历史中查找） */
function quotePreview(id) {
  const target = chat.activeMessages.find((m) => m.id === id)
  if (!target) return '原消息'
  const who = target.sender_nickname
  const body =
    target.msg_type === 'image'
      ? '[图片]'
      : target.msg_type === 'file'
        ? `[文件] ${target.file_name || ''}`
        : target.msg_type === 'card'
          ? '[好友名片]'
          : target.msg_type === 'emoji'
            ? `[表情] ${target.content}`
            : target.content
  return `${who}: ${body}`
}

function canRecall(msg) {
  return (
    msg.sender_id === auth.user?.id &&
    Date.now() - parseUtc(msg.created_at).getTime() <= RECALL_WINDOW_MS
  )
}

async function doRecall() {
  try {
    await chat.recall(confirmRecall.value.id)
    toast.success('已撤回')
  } catch (e) {
    toast.error(e.message)
  } finally {
    confirmRecall.value = null
  }
}

async function doReport() {
  if (!reportReason.value.trim()) {
    toast.error('请填写举报理由')
    return
  }
  try {
    await createReport(reportTarget.value.id, reportReason.value.trim())
    toast.success('举报已提交，等待管理员处理')
    reportTarget.value = null
    reportReason.value = ''
  } catch (e) {
    toast.error(e.message)
  }
}

async function togglePin(msg) {
  try {
    await chat.setPinned(conversationId.value, msg.id, !msg.is_pinned)
    toast.success(msg.is_pinned ? '已取消置顶' : '已置顶为话题帖')
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 历史可见性（仅群聊，群主 / 管理员） ---------- */
const historyMode = ref('all')
const historyLimit = ref(20)

// 切换会话或保存后，同步为后端当前值
watch(
  () => [conv.value?.conversation_id, conv.value?.history_visible_mode, conv.value?.history_limit],
  () => {
    historyMode.value = conv.value?.history_visible_mode || 'all'
    historyLimit.value = conv.value?.history_limit || 20
  },
  { immediate: true },
)

async function saveHistoryVisibility() {
  if (historyMode.value === 'recent_n' && (!historyLimit.value || historyLimit.value < 1)) {
    toast.error('请填写 1–500 之间的条数')
    return
  }
  try {
    await convApi.updateHistoryVisibility(
      conversationId.value,
      historyMode.value,
      historyMode.value === 'recent_n' ? historyLimit.value : null,
    )
    toast.success('历史可见性已更新')
    await chat.loadConversations()
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 成员管理（群聊 / 频道） ---------- */

const showInvite = ref(false)
const inviteSelected = ref('')
const myFriendsForInvite = ref([])
const showLeaveConfirm = ref(false)

async function toggleMembers() {
  showMembers.value = !showMembers.value
  if (showMembers.value) {
    await chat.loadMembers(conversationId.value).catch((e) => toast.error(e.message))
  }
}

async function openInvite() {
  showInvite.value = true
  inviteSelected.value = ''
  try {
    myFriendsForInvite.value = await getFriends()
  } catch (e) {
    toast.error(e.message)
  }
}

async function doInvite() {
  if (!inviteSelected.value) {
    toast.error('请选择要邀请的好友')
    return
  }
  try {
    await convApi.inviteMember(conversationId.value, Number(inviteSelected.value))
    toast.success('已邀请入群')
    showInvite.value = false
    await chat.loadMembers(conversationId.value)
  } catch (e) {
    toast.error(e.message)
  }
}

async function doRemoveMember(userId) {
  try {
    await convApi.removeMember(conversationId.value, userId)
    toast.success('已移除该成员')
    await chat.loadMembers(conversationId.value)
  } catch (e) {
    toast.error(e.message)
  }
}

async function doLeave() {
  try {
    await convApi.leaveConversation(conversationId.value)
    chat.removeConversationLocally(conversationId.value)
    showLeaveConfirm.value = false
    toast.success('已退出')
    router.push('/')
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 群 / 频道头像 ---------- */

const avatarInput = ref(null)

async function pickGroupAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const data = await uploadFile(file, 'image')
    await convApi.updateConversation(conversationId.value, { avatar_url: data.url })
    // 本地立即生效，再同步会话列表
    if (conv.value) conv.value.avatar_url = data.url
    await chat.loadConversations()
    toast.success('头像已更新')
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 好友名片消息 ---------- */

const cardUserId = ref(0)
const showCard = ref(false)

function viewCard(userId) {
  cardUserId.value = userId
  showCard.value = true
}
</script>

<template>
  <!-- 频道：右侧直接展开内容社区（帖子流），与私聊 / 群聊共用会话分区布局 -->
  <ChannelDetailView v-if="isChannel" :id="props.id" />

  <div v-else class="chat">
    <!-- 头部 -->
    <header v-if="conv" class="chat-head">
      <div class="title-wrap">
        <h2>{{ conv.name }}</h2>
        <span class="tag" :class="isChannel ? 'tag-teal' : 'tag-brand'">
          {{ conv.type === 'single' ? '单聊' : conv.type === 'group' ? '群聊' : '频道' }}
        </span>
        <span v-if="conv.type === 'group'" class="group-no">群号 {{ conv.conversation_id }}</span>
        <span v-if="isGroupOrChannel" class="member-count">{{ chat.activeMembers.length }} 人</span>
      </div>
      <div class="head-actions">
        <button class="btn btn-ghost btn-sm" :class="{ 'btn-on': showSearch }" @click="toggleSearch">
          {{ showSearch ? '关闭搜索' : '搜索消息' }}
        </button>
        <button v-if="isGroupOrChannel" class="btn btn-ghost btn-sm" @click="toggleMembers">
          {{ showMembers ? '收起成员' : '成员管理' }}
        </button>
      </div>
    </header>

    <div class="chat-body">
      <div class="msg-col">
        <!-- 会话内搜索：≥ 2 字走 ngram 全文索引，单字后端回退 LIKE；点结果跳转 -->
        <div v-if="showSearch" class="search-panel">
          <input
            v-model="searchQ"
            class="search-input"
            placeholder="搜索本会话消息，回车查找"
            @keyup.enter="runMsgSearch"
          />
          <button class="btn btn-ghost btn-sm" :disabled="searching" @click="runMsgSearch">
            {{ searching ? '搜索中…' : '搜索' }}
          </button>
          <span v-if="searchedOnce && !searching" class="search-count">
            {{ searchResults.length ? `${searchResults.length} 条结果` : '没有找到匹配的消息' }}
          </span>
          <ul v-if="searchResults.length" class="search-results">
            <li v-for="r in searchResults" :key="r.id" class="search-item" @click="jumpToMessage(r.id)">
              <span class="si-head">
                <span class="si-name">{{ r.sender_nickname }}</span>
                <span class="si-time">{{ formatDateTime(r.created_at) }}</span>
              </span>
              <span class="si-content">{{ r.content }}</span>
            </li>
          </ul>
        </div>

        <!-- 置顶话题帖（仅频道） -->
        <div v-if="isChannel && chat.activePinnedMessage" class="pinned card">
          <span class="pin-icon">📌</span>
          <div class="pin-body">
            <span class="pin-label">置顶话题帖</span>
            <span class="pin-content">{{ chat.activePinnedMessage.content }}</span>
          </div>
        </div>

        <!-- 消息区 -->
        <div ref="messagesEl" class="messages" @scroll="onScroll">
          <div v-if="chat.hasMore[conversationId] !== false && chat.activeMessages.length" class="load-more">
            <button class="btn btn-ghost btn-sm" :disabled="chat.loadingMore" @click="onScroll">
              {{ chat.loadingMore ? '加载中…' : '加载更早的消息' }}
            </button>
          </div>
          <div
            v-for="msg in chat.activeMessages"
            :id="`msg-${msg.id}`"
            :key="msg.id"
            :class="{ 'msg-flash': highlightMsgId === msg.id }"
            @contextmenu.prevent="openMsgMenu($event, msg)"
          >
          <MessageBubble
            :msg="msg"
            :mine="msg.sender_id === auth.user?.id"
            :show-nickname="showNickname"
            :quote-preview="msg.reply_to_id ? quotePreview(msg.reply_to_id) : ''"
            @view-card="viewCard"
            @view-user="viewCard"
          >
            <!-- 悬浮动作条：仅保留频道置顶（撤回 / 举报均已并入右键菜单）。
                 无可用操作时整个容器不渲染，否则悬停会留下一个空白小白条 -->
            <div
              v-if="!msg.recalled_at && isChannel && canManage"
              class="msg-actions"
              :class="{ mine: msg.sender_id === auth.user?.id }"
            >
              <button @click="togglePin(msg)">
                {{ msg.is_pinned ? '取消置顶' : '置顶' }}
              </button>
            </div>
          </MessageBubble>
          </div>
          <div v-if="!chat.loading && !chat.activeMessages.length" class="empty">
            <span class="icon">✉️</span>还没有消息，发第一条吧
          </div>
        </div>

        <!-- 输入区 -->
        <div class="composer">
          <!-- 引用预览条 -->
          <div v-if="quoteTarget" class="quote-preview">
            <span class="quote-text">{{ quotePreview(quoteTarget.id) }}</span>
            <button class="quote-cancel" title="取消引用" @click="cancelQuote">×</button>
          </div>
          <!-- 输入中提示：typing 帧驱动，4 秒无续帧自动消 -->
          <div v-if="typingHint" class="typing-hint">{{ typingHint }}</div>
          <div class="tools">
            <div class="emoji-wrap">
              <button class="tool" title="表情" @click="showEmoji = !showEmoji">😊</button>
              <EmojiPicker v-if="showEmoji" @select="insertEmoji" />
            </div>
            <button class="tool" title="发送图片" @click="imageInput.click()">🖼️</button>
            <button class="tool" title="发送文件" @click="fileInput.click()">📎</button>
            <span class="tool-tip">Enter 发送 · Shift+Enter 换行</span>
          </div>
          <div class="input-row">
            <textarea
              v-model="inputText"
              class="input composer-input"
              rows="1"
              placeholder="输入消息…"
              @input="chat.notifyTyping(conversationId)"
              @keydown.enter.exact.prevent="sendText"
            ></textarea>
            <button class="btn btn-primary send-btn" @click="sendText">发送</button>
          </div>
          <input ref="imageInput" type="file" :accept="IMAGE_ACCEPT" hidden @change="pickImage" />
          <input ref="fileInput" type="file" hidden @change="pickFile" />
        </div>
      </div>

      <!-- 成员管理侧栏（群聊 / 频道） -->
      <aside v-if="isGroupOrChannel && showMembers" class="members card">
        <div class="group-ident">
          <button
            class="avatar-btn"
            :disabled="!canManage"
            :title="canManage ? '点击更换头像' : ''"
            @click="canManage && avatarInput.click()"
          >
            <UserAvatar :name="conv.name" :url="conv.avatar_url" :size="48" />
            <span v-if="canManage" class="avatar-edit">✎</span>
          </button>
          <span class="group-name">{{ conv.name }}</span>
        </div>
        <div class="members-head">
          <span>成员（{{ chat.activeMembers.length }}）</span>
          <button v-if="conv.type === 'group' && canManage" class="btn btn-ghost btn-sm" @click="openInvite">
            + 邀请
          </button>
        </div>
        <div class="members-list">
          <div v-for="m in chat.activeMembers" :key="m.user_id" class="member">
            <UserAvatar
              class="link"
              :name="m.nickname"
              :url="m.avatar_url"
              :size="32"
              title="查看资料"
              @click="viewCard(m.user_id)"
            />
            <span class="member-name link" @click="viewCard(m.user_id)">{{ m.nickname }}</span>
            <span v-if="m.role !== 'member'" class="tag" :class="m.role === 'owner' ? 'tag-coral' : 'tag-brand'">
              {{ m.role === 'owner' ? '群主' : '管理员' }}
            </span>
            <button
              v-if="canManage && m.role === 'member' && m.user_id !== auth.user?.id"
              class="kick"
              title="移除成员"
              @click="doRemoveMember(m.user_id)"
            >
              移除
            </button>
          </div>
        </div>
        <!-- 历史可见性：仅群聊 + 管理权限（设计 2.2.7，三种模式互斥） -->
        <div v-if="conv.type === 'group' && canManage" class="history-vis">
          <div class="vis-head">历史消息对新成员</div>
          <select v-model="historyMode" class="input vis-select">
            <option value="all">全部可见</option>
            <option value="since_join">仅加入之后</option>
            <option value="recent_n">仅最近 N 条</option>
          </select>
          <input
            v-if="historyMode === 'recent_n'"
            v-model.number="historyLimit"
            class="input vis-limit"
            type="number"
            min="1"
            max="500"
            placeholder="20"
          />
          <button class="btn btn-ghost btn-sm vis-save" @click="saveHistoryVisibility">
            保存历史可见性
          </button>
        </div>

        <button class="btn btn-danger leave-btn" @click="showLeaveConfirm = true">
          {{ isChannel ? '退出频道' : '退出群聊' }}
        </button>
        <input ref="avatarInput" type="file" :accept="IMAGE_ACCEPT" hidden @change="pickGroupAvatar" />
      </aside>
    </div>

    <!-- 消息右键上下文菜单：复制 / 转发 / 引用 / 回复表情包 / 举报 -->
    <Teleport to="body">
      <div
        v-if="msgMenu"
        class="msg-menu"
        :style="{ left: msgMenu.x + 'px', top: msgMenu.y + 'px' }"
        @click.stop
        @contextmenu.prevent.stop
      >
        <button :disabled="!['text', 'emoji'].includes(msgMenu.msg.msg_type)" @click="copyMsg(msgMenu.msg)">
          复制
        </button>
        <button @click="startForward">转发</button>
        <button :disabled="msgMenu.msg.msg_type !== 'text'" @click="startQuote">引用</button>
        <div class="menu-emojis">
          <button v-for="e in QUICK_EMOJIS" :key="e" class="emoji-cell" @click="replyEmoji(e)">
            {{ e }}
          </button>
        </div>
        <button v-if="canRecall(msgMenu.msg)" class="danger" @click="recallFromMenu">撤回</button>
        <button v-if="msgMenu.msg.sender_id !== auth.user?.id" class="danger" @click="reportFromMenu">
          举报
        </button>
      </div>
    </Teleport>

    <!-- 转发：选择目标会话 -->
    <ModalDialog :open="!!forwardTarget" title="转发消息" width="400" @close="forwardTarget = null">
      <div class="field">
        <label>选择要转发到的会话</label>
        <select v-model="forwardTo" class="input">
          <option value="" disabled>请选择</option>
          <option
            v-for="c in chat.conversations"
            :key="c.conversation_id"
            :value="c.conversation_id"
            :disabled="c.conversation_id === conversationId"
          >
            {{ c.name }}（{{ c.type === 'single' ? '单聊' : c.type === 'group' ? '群聊' : '频道' }}）
          </option>
        </select>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="forwardTarget = null">取消</button>
        <button class="btn btn-primary" @click="doForward">转发</button>
      </template>
    </ModalDialog>

    <!-- 撤回确认 -->
    <ModalDialog :open="!!confirmRecall" title="撤回消息" width="360" @close="confirmRecall = null">
      <p>确定撤回这条消息吗？对方界面会同步显示"撤回了一条消息"。</p>
      <template #footer>
        <button class="btn btn-ghost" @click="confirmRecall = null">取消</button>
        <button class="btn btn-primary" @click="doRecall">撤回</button>
      </template>
    </ModalDialog>

    <!-- 举报 -->
    <ModalDialog :open="!!reportTarget" title="举报消息" @close="reportTarget = null">
      <div class="field">
        <label>举报理由（必填）</label>
        <textarea v-model="reportReason" class="input" rows="3" maxlength="200" placeholder="请描述该消息的违规情况"></textarea>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="reportTarget = null">取消</button>
        <button class="btn btn-primary" @click="doReport">提交举报</button>
      </template>
    </ModalDialog>

    <!-- 邀请入群 -->
    <ModalDialog :open="showInvite" title="邀请好友入群" width="380" @close="showInvite = false">
      <div class="field">
        <label>选择好友</label>
        <select v-model="inviteSelected" class="input">
          <option value="" disabled>请选择</option>
          <option v-for="f in myFriendsForInvite" :key="f.friend_user_id" :value="f.friend_user_id">
            {{ f.remark || f.nickname }}（@{{ f.username }}）
          </option>
        </select>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showInvite = false">取消</button>
        <button class="btn btn-primary" @click="doInvite">邀请</button>
      </template>
    </ModalDialog>

    <!-- 退群确认 -->
    <ModalDialog :open="showLeaveConfirm" title="退出确认" width="380" @close="showLeaveConfirm = false">
      <p>确定退出「{{ conv?.name }}」吗？退出后将不再接收该会话消息。</p>
      <template #footer>
        <button class="btn btn-ghost" @click="showLeaveConfirm = false">取消</button>
        <button class="btn btn-danger" @click="doLeave">退出</button>
      </template>
    </ModalDialog>

    <!-- 好友名片 -->
    <ProfileCard :open="showCard" :user-id="cardUserId" @close="showCard = false" />
  </div>
</template>

<style scoped>
.chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}
.chat-head {
  height: 52px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--g-1);
  border-bottom: 1px solid var(--g-4);
}
.head-actions {
  display: flex;
  gap: 8px;
  flex: none;
}
.btn-on {
  color: var(--brand-7);
  background: var(--brand-1);
}

/* ---------- 会话内搜索 ---------- */
.search-panel {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: var(--g-1);
  border-bottom: 1px solid var(--g-4);
}
.search-input {
  flex: 1;
  min-width: 200px;
  max-width: 360px;
  border: 1px solid var(--g-4);
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  background: #fff;
}
.search-input:focus {
  outline: none;
  border-color: var(--brand-4);
}
.search-count {
  font-size: 12px;
  color: var(--g-8);
}
.search-results {
  flex-basis: 100%;
  max-height: 190px;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--g-4);
  border-radius: var(--radius-s);
  background: #fff;
}
.search-item {
  padding: 7px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--g-2);
}
.search-item:last-child {
  border-bottom: none;
}
.search-item:hover {
  background: var(--brand-1);
}
.si-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--g-8);
}
.si-name {
  font-weight: 600;
  color: var(--g-12);
}
.si-content {
  display: block;
  font-size: 12px;
  color: var(--g-10);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 搜索跳转落点：描边闪 2 秒提示位置，不改变气泡自身配色 */
.msg-flash :deep(.bubble),
.msg-flash :deep(.img-bubble),
.msg-flash :deep(.file-bubble),
.msg-flash :deep(.card-bubble) {
  outline: 2px solid var(--coral-5);
  outline-offset: 2px;
  transition: outline-color 0.4s;
}
.title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.title-wrap h2 {
  font-size: 16px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.group-no,
.member-count {
  font-size: 12px;
  color: var(--g-8);
}

.chat-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.msg-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.pinned {
  display: flex;
  gap: 10px;
  margin: 12px 20px 0;
  padding: 10px 14px;
  background: var(--coral-1);
  border-color: var(--coral-3);
  flex: none;
}
.pin-icon {
  font-size: 18px;
}
.pin-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.pin-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--coral-7);
}
.pin-content {
  font-size: 13px;
  color: var(--g-11);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  min-height: 0;
}
.load-more {
  text-align: center;
  margin-bottom: 8px;
}

/* 右键上下文菜单：固定定位在点击处，无浮动动画 */
.msg-menu {
  position: fixed;
  z-index: 200;
  min-width: 150px;
  padding: 6px;
  background: var(--g-1);
  border: 1px solid var(--g-4);
  border-radius: var(--radius-m);
  box-shadow: var(--shadow-pop);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.msg-menu > button {
  border: none;
  background: none;
  text-align: left;
  font-size: 13px;
  color: var(--g-11);
  padding: 7px 12px;
  border-radius: var(--radius-s);
  cursor: pointer;
  font-family: var(--font-cjk);
}
.msg-menu > button:hover:not(:disabled) {
  background: var(--brand-1);
  color: var(--brand-7);
}
.msg-menu > button:disabled {
  color: var(--g-6);
  cursor: not-allowed;
}
.msg-menu > button.danger:hover {
  background: var(--coral-1);
  color: var(--coral-7);
}
.menu-emojis {
  display: flex;
  gap: 2px;
  padding: 4px 6px;
  border-top: 1px solid var(--g-3);
  border-bottom: 1px solid var(--g-3);
}
.emoji-cell {
  border: none;
  background: none;
  font-size: 17px;
  cursor: pointer;
  padding: 2px 3px;
  border-radius: 4px;
}
.emoji-cell:hover {
  background: var(--g-2);
}

/* 引用预览条：输入框上方 */
.quote-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding: 6px 10px;
  background: var(--g-2);
  border-left: 2px solid var(--brand-7);
  border-radius: var(--radius-s);
}
.quote-text {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: var(--g-8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.quote-cancel {
  border: none;
  background: none;
  color: var(--g-7);
  font-size: 15px;
  cursor: pointer;
  line-height: 1;
  padding: 0 2px;
}
.quote-cancel:hover {
  color: var(--g-11);
}

/* 悬浮动作条：悬停消息行时浮现在气泡正上方。
 * 必须是 position: absolute —— 让它脱离文档流，否则悬停时会把消息行撑高，
 * 而 .row 是底部对齐，头像与气泡就会上下位移（看起来像"浮动动画"）。 */
:deep(.stack) {
  position: relative;
}
.msg-actions {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 0;
  display: none;
  gap: 10px;
  padding: 3px 8px;
  background: var(--g-1);
  border: 1px solid var(--g-4);
  border-radius: var(--radius-s);
  box-shadow: var(--shadow-card);
  white-space: nowrap;
  z-index: 3;
}
.msg-actions button {
  border: none;
  background: none;
  color: var(--g-8);
  cursor: pointer;
  padding: 0;
  font-size: 11px;
}
.msg-actions button:hover {
  color: var(--brand-7);
}
:deep(.row:hover) .msg-actions {
  display: inline-flex;
}
.msg-actions.mine {
  left: auto;
  right: 0;
}

.composer {
  flex: none;
  border-top: 1px solid var(--g-4);
  background: var(--g-1);
  padding: 10px 20px 14px;
}
.tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  position: relative;
}
.emoji-wrap {
  position: relative;
}
.tool {
  border: none;
  background: none;
  font-size: 20px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
}
.tool:hover {
  background: var(--g-3);
}
.tool-tip {
  margin-left: auto;
  font-size: 11px;
  color: var(--g-7);
}
/* 输入中提示：teal 在线语义色，占位矮行不推挤消息区 */
.typing-hint {
  font-size: 12px;
  line-height: 18px;
  color: var(--teal-6);
}
.input-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}
/* 与右侧发送按钮（.btn 高 38px）等高：单行输入，多行在框内滚动 */
.composer-input {
  height: 38px;
  min-height: 38px;
  padding: 8px 14px;
  line-height: 20px;
  resize: none;
}
.send-btn {
  flex: none;
}

/* 历史可见性设置（仅群聊 + 管理权限） */
.history-vis {
  padding: 12px 14px;
  border-top: 1px solid var(--g-4);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.vis-head {
  font-size: 12px;
  font-weight: 700;
  color: var(--g-8);
}
.vis-select {
  height: 34px;
  font-size: 13px;
}
.vis-limit {
  height: 34px;
}
.vis-save {
  align-self: flex-start;
}

/* 成员侧栏 */
.members {
  width: 240px;
  flex: none;
  margin: 12px 12px 12px 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.group-ident {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 14px 10px;
  border-bottom: 1px solid var(--g-4);
}
.avatar-btn {
  position: relative;
  border: none;
  background: none;
  padding: 0;
  border-radius: 50%;
}
.avatar-btn:not(:disabled) {
  cursor: pointer;
}
.avatar-edit {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--brand-7);
  color: #fff;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.group-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--g-11);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.members-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--g-10);
}
.members-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.member {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-s);
}
.member:hover {
  background: var(--g-2);
}
/* 头像 / 昵称可点击查看资料卡 */
.link {
  cursor: pointer;
}
.member-name {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kick {
  border: none;
  background: none;
  font-size: 11px;
  color: var(--error-tx);
  cursor: pointer;
  display: none;
}
.member:hover .kick {
  display: inline;
}
.leave-btn {
  margin: 10px;
}
</style>
