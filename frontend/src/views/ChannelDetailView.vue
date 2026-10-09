<script setup>
/**
 * 频道帖子流页（信息结构图 ⑥ 内容社区）：频道作为论坛 / 朋友圈形态的内容社区，
 * 进入频道看到的是可沉淀的帖子流（时间 / 热度排序），而不是实时消息流。
 *
 * 能力：发帖（文本 / 图片 / 表情）、编辑 / 删除 / 置顶（权限各异）、
 * 评论与二级回复、评论点赞、频道头像与信息维护。
 * 非成员进入时显示频道资料卡 + 加入按钮（加入免审）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import EmojiPicker from '@/components/EmojiPicker.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import ProfileCard from '@/components/ProfileCard.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import * as channelApi from '@/api/channelContent'
import { IMAGE_ACCEPT, IMAGE_MAX, uploadFile } from '@/api/content'
import * as convApi from '@/api/conversations'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useToastStore } from '@/stores/toast'
import { formatDateTime } from '@/utils/format'

const props = defineProps({
  /** 路由参数 /channels/:id */
  id: { type: String, required: true },
})

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()
const toast = useToastStore()

const conversationId = computed(() => Number(props.id))
const PAGE_SIZE = 10
const MAX_IMAGES = 9

/** ---------- 频道状态 ---------- */

const loading = ref(true)
const notJoined = ref(false)
const myRole = ref('')
const meta = reactive({ name: '', description: '', avatar_url: '', member_count: 0, creator: '' })
const canManage = computed(() => myRole.value === 'owner' || myRole.value === 'admin')
const canModerate = computed(() => canManage.value || auth.isAdmin)

/** ---------- 帖子流 ---------- */

const posts = ref([])
const sort = ref('time')
const loadingMore = ref(false)
const hasMore = ref(false)

/** 发帖 */
const composerText = ref('')
const composerImages = ref([])
const showEmoji = ref(false)
const publishing = ref(false)
const imageInput = ref(null)

/** 评论：展开的帖子 → 评论树 / 草稿 / 回复目标 */
const expanded = reactive({})       // postId -> bool
const commentsByPost = reactive({}) // postId -> [{...评论, replies: []}]
const replyTo = reactive({})        // postId -> 被回复的评论
const draft = reactive({})          // postId -> 输入框内容

/** 编辑 / 删除确认 */
const showEdit = ref(false)
const editTarget = ref(null)
const editText = ref('')
const editImages = ref([])
const confirmTarget = ref(null)      // 待删除的帖子或评论 { type, post, comment }
const showSettings = ref(false)
const settingsForm = ref({ name: '', description: '' })
const avatarInput = ref(null)

/** 资料卡：点击头像 / 昵称 / 名片帖打开（0 表示关闭） */
const cardUserId = ref(0)

function viewCard(userId) {
  if (userId) cardUserId.value = Number(userId)
}

watch(sort, reloadPosts)
watch(conversationId, () => {
  resetAll()
  load()
})

resetAllMeta()
load()

function resetAllMeta() {
  notJoined.value = false
  myRole.value = ''
  Object.assign(meta, { name: '', description: '', avatar_url: '', member_count: 0, creator: '' })
}

function resetAll() {
  resetAllMeta()
  posts.value = []
  hasMore.value = false
  Object.keys(expanded).forEach((k) => delete expanded[k])
  Object.keys(commentsByPost).forEach((k) => delete commentsByPost[k])
  Object.keys(replyTo).forEach((k) => delete replyTo[k])
  Object.keys(draft).forEach((k) => delete draft[k])
}

async function load() {
  loading.value = true
  try {
    await loadMembership()
    await loadMeta()
    if (!notJoined.value) await reloadPosts()
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

async function loadMembership() {
  try {
    const list = await convApi.getMembers(conversationId.value)
    const me = list.find((m) => m.user_id === auth.user?.id)
    myRole.value = me?.role || 'member'
    notJoined.value = false
  } catch (e) {
    if (e.status === 403) {
      notJoined.value = true
      myRole.value = ''
    } else {
      throw e
    }
  }
}

async function loadMeta() {
  const all = await convApi.getChannels('')
  const c = all.find((x) => x.conversation_id === conversationId.value)
  if (c) {
    Object.assign(meta, {
      name: c.name,
      description: c.description,
      avatar_url: c.avatar_url,
      member_count: c.member_count,
      creator: c.creator,
    })
  }
}

async function reloadPosts() {
  const items = await channelApi.getPosts(conversationId.value, { sort: sort.value, limit: PAGE_SIZE })
  posts.value = items
  hasMore.value = items.length >= PAGE_SIZE
}

async function loadMore() {
  loadingMore.value = true
  try {
    const items = await channelApi.getPosts(conversationId.value, {
      sort: sort.value,
      limit: PAGE_SIZE,
      offset: posts.value.length,
    })
    posts.value.push(...items)
    hasMore.value = items.length >= PAGE_SIZE
  } catch (e) {
    toast.error(e.message)
  } finally {
    loadingMore.value = false
  }
}

/** ---------- 加入频道 ---------- */

async function join() {
  try {
    await convApi.joinChannel(conversationId.value)
    toast.success(`已加入「${meta.name}」`)
    notJoined.value = false
    myRole.value = 'member'
    await chat.loadConversations()
    await Promise.all([loadMeta(), reloadPosts()])
  } catch (e) {
    toast.error(e.message)
  }
}

/** ---------- 发帖 ---------- */

function insertEmoji(emoji) {
  composerText.value += emoji
}

async function pickImages(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  const room = MAX_IMAGES - composerImages.value.length
  if (files.length > room) toast.error(`图片最多 ${MAX_IMAGES} 张`)
  for (const file of files.slice(0, room)) {
    try {
      const data = await uploadFile(file, 'image')
      composerImages.value.push(data.url)
    } catch (e) {
      toast.error(e.message)
    }
  }
}

async function publish() {
  const content = composerText.value.trim()
  if (!content && !composerImages.value.length) {
    toast.error('说点什么或配张图吧')
    return
  }
  publishing.value = true
  try {
    const post = await channelApi.createPost(conversationId.value, {
      content,
      images: composerImages.value,
    })
    posts.value.unshift(post)
    composerText.value = ''
    composerImages.value = []
    showEmoji.value = false
  } catch (e) {
    toast.error(e.message)
  } finally {
    publishing.value = false
  }
}

/** ---------- 帖子操作：点赞 / 置顶 / 编辑 / 删除 ---------- */

async function toggleLike(post) {
  const liked = !post.liked_by_me
  post.liked_by_me = liked
  post.like_count += liked ? 1 : -1
  try {
    await channelApi.likePost(conversationId.value, post.id, liked)
  } catch (e) {
    post.liked_by_me = !liked
    post.like_count += liked ? -1 : 1
    toast.error(e.message)
  }
}

async function togglePin(post) {
  try {
    await channelApi.pinPost(conversationId.value, post.id, !post.is_pinned)
    post.is_pinned = !post.is_pinned
    toast.success(post.is_pinned ? '已置顶' : '已取消置顶')
  } catch (e) {
    toast.error(e.message)
  }
}

function openEdit(post) {
  editTarget.value = post
  editText.value = post.content
  editImages.value = [...post.images]
  showEdit.value = true
}

async function saveEdit() {
  const content = editText.value.trim()
  if (!content && !editImages.value.length) {
    toast.error('内容不能为空')
    return
  }
  try {
    const updated = await channelApi.updatePost(conversationId.value, editTarget.value.id, {
      content,
      images: editImages.value,
    })
    replacePost(updated)
    showEdit.value = false
    toast.success('帖子已更新')
  } catch (e) {
    toast.error(e.message)
  }
}

function replacePost(updated) {
  const idx = posts.value.findIndex((p) => p.id === updated.id)
  if (idx >= 0) posts.value[idx] = updated
}

async function doConfirm() {
  const { type, post, comment } = confirmTarget.value
  try {
    if (type === 'post') {
      await channelApi.deletePost(conversationId.value, post.id)
      posts.value = posts.value.filter((p) => p.id !== post.id)
      toast.success('帖子已删除')
    } else {
      await channelApi.deleteComment(conversationId.value, comment.id)
      post.comment_count -= 1
      await reloadComments(post)
      toast.success('评论已删除')
    }
  } catch (e) {
    toast.error(e.message)
  } finally {
    confirmTarget.value = null
  }
}

/** ---------- 评论 ---------- */

async function toggleComments(post) {
  expanded[post.id] = !expanded[post.id]
  if (expanded[post.id] && !commentsByPost[post.id]) {
    await reloadComments(post)
  }
}

async function reloadComments(post) {
  const list = await channelApi.getComments(conversationId.value, post.id)
  commentsByPost[post.id] = buildTree(list)
}

function buildTree(list) {
  const byId = new Map(list.map((c) => [c.id, { ...c, replies: [] }]))
  const tops = []
  for (const c of byId.values()) {
    if (c.parent_id && byId.has(c.parent_id)) byId.get(c.parent_id).replies.push(c)
    else tops.push(c)
  }
  return tops
}

function startReply(post, comment) {
  replyTo[post.id] = comment
}

function cancelReply(post) {
  delete replyTo[post.id]
}

async function submitComment(post) {
  const content = (draft[post.id] || '').trim()
  if (!content) {
    toast.error('评论内容不能为空')
    return
  }
  const target = replyTo[post.id]
  try {
    await channelApi.createComment(conversationId.value, post.id, content, target?.id ?? null)
    draft[post.id] = ''
    cancelReply(post)
    post.comment_count += 1
    expanded[post.id] = true
    await reloadComments(post)
  } catch (e) {
    toast.error(e.message)
  }
}

async function toggleCommentLike(post, comment) {
  const liked = !comment.liked_by_me
  comment.liked_by_me = liked
  comment.like_count += liked ? 1 : -1
  try {
    await channelApi.likeComment(conversationId.value, comment.id, liked)
  } catch (e) {
    comment.liked_by_me = !liked
    comment.like_count += liked ? -1 : 1
    toast.error(e.message)
  }
}

function canDeleteComment(comment) {
  return comment.author?.user_id === auth.user?.id || canModerate.value
}

/** ---------- 频道头像与信息 ---------- */

async function pickAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const data = await uploadFile(file, 'image')
    await convApi.updateConversation(conversationId.value, { avatar_url: data.url })
    meta.avatar_url = data.url
    await chat.loadConversations()
    toast.success('频道头像已更新')
  } catch (e) {
    toast.error(e.message)
  }
}

function openSettings() {
  settingsForm.value = { name: meta.name, description: meta.description || '' }
  showSettings.value = true
}

async function saveSettings() {
  const name = settingsForm.value.name.trim()
  if (!name) {
    toast.error('请填写频道名称')
    return
  }
  try {
    await convApi.updateConversation(conversationId.value, {
      name,
      description: settingsForm.value.description.trim(),
    })
    meta.name = name
    meta.description = settingsForm.value.description.trim()
    showSettings.value = false
    await chat.loadConversations()
    toast.success('频道信息已更新')
  } catch (e) {
    toast.error(e.message)
  }
}
</script>

<template>
  <div class="channel-detail">
    <!-- 频道头部 -->
    <header class="head card">
      <button
        class="avatar-btn"
        :disabled="!canManage"
        :title="canManage ? '点击更换头像' : ''"
        @click="canManage && avatarInput.click()"
      >
        <UserAvatar :name="meta.name" :url="meta.avatar_url" :size="56" />
        <span v-if="canManage" class="avatar-edit">✎</span>
      </button>
      <div class="head-mid">
        <div class="head-title">
          <h2>{{ meta.name || '频道' }}</h2>
          <span class="tag tag-teal">频道</span>
        </div>
        <p class="desc">{{ meta.description || '这个频道还没有简介' }}</p>
        <p class="meta">
          <span v-if="meta.member_count">{{ meta.member_count }} 名成员</span>
          <span v-if="meta.creator">创建者：{{ meta.creator }}</span>
        </p>
      </div>
      <div class="head-actions" v-if="!notJoined">
        <button v-if="canManage" class="btn btn-ghost btn-sm" @click="openSettings">频道设置</button>
        <button class="btn btn-ghost btn-sm" @click="router.push('/channels')">频道广场</button>
      </div>
      <input ref="avatarInput" type="file" :accept="IMAGE_ACCEPT" hidden @change="pickAvatar" />
    </header>

    <!-- 未加入：资料卡 + 加入按钮 -->
    <div v-if="notJoined" class="join-card card">
      <p>加入后即可浏览与发布帖子</p>
      <button class="btn btn-primary" @click="join">加入频道</button>
    </div>

    <template v-else>
      <!-- 发帖 -->
      <div class="composer card">
        <UserAvatar :name="auth.user?.nickname" :url="auth.user?.avatar_url" :size="40" />
        <div class="composer-main">
          <textarea
            v-model="composerText"
            class="input composer-input"
            rows="3"
            maxlength="5000"
            placeholder="分享点什么到这个频道…"
          ></textarea>
          <div v-if="composerImages.length" class="thumbs">
            <div v-for="(img, i) in composerImages" :key="img" class="thumb">
              <img :src="img" alt="配图" />
              <button class="thumb-del" title="移除" @click="composerImages.splice(i, 1)">×</button>
            </div>
          </div>
          <div class="composer-tools">
            <div class="emoji-wrap">
              <button class="tool" title="表情" @click="showEmoji = !showEmoji">😊</button>
              <EmojiPicker v-if="showEmoji" @select="insertEmoji" />
            </div>
            <button class="tool" title="添加图片" @click="imageInput.click()">🖼️</button>
            <span class="tip">{{ composerImages.length ? `${composerImages.length}/${MAX_IMAGES} 图` : '支持文本 / 图片 / 表情' }}</span>
            <button class="btn btn-primary btn-sm publish" :disabled="publishing" @click="publish">
              {{ publishing ? '发布中…' : '发布' }}
            </button>
          </div>
          <input ref="imageInput" type="file" :accept="IMAGE_ACCEPT" multiple hidden @change="pickImages" />
        </div>
      </div>

      <!-- 排序 -->
      <div class="sort-bar">
        <button class="sort" :class="{ on: sort === 'time' }" @click="sort = 'time'">最新</button>
        <button class="sort" :class="{ on: sort === 'hot' }" @click="sort = 'hot'">最热</button>
      </div>

      <!-- 帖子流 -->
      <div v-if="loading" class="empty"><span class="icon">⏳</span>加载中…</div>
      <template v-else>
        <article v-for="post in posts" :key="post.id" class="post card">
          <div class="post-head">
            <UserAvatar
              class="link"
              :name="post.author.nickname"
              :url="post.author.avatar_url"
              :size="36"
              title="查看资料"
              @click="viewCard(post.author.user_id)"
            />
            <div class="post-author">
              <span class="nick link" @click="viewCard(post.author.user_id)">{{ post.author.nickname }}</span>
              <span class="time">{{ formatDateTime(post.created_at) }}</span>
            </div>
            <span v-if="post.is_pinned" class="tag tag-coral">📌 置顶</span>
            <div class="post-menu">
              <button v-if="post.author.user_id === auth.user?.id && !post.card" @click="openEdit(post)">编辑</button>
              <button v-if="canManage" @click="togglePin(post)">
                {{ post.is_pinned ? '取消置顶' : '置顶' }}
              </button>
              <button
                v-if="post.author.user_id === auth.user?.id || canModerate"
                class="danger"
                @click="confirmTarget = { type: 'post', post }"
              >
                删除
              </button>
            </div>
          </div>

          <p v-if="post.content" class="post-content">{{ post.content }}</p>
          <!-- 名片帖：被分享的好友，点击查看资料 -->
          <div v-if="post.card" class="post-card card" @click="viewCard(post.card.user_id)">
            <UserAvatar :name="post.card.nickname" :url="post.card.avatar_url" :size="40" />
            <span class="post-card-body">
              <span class="post-card-title">👤 好友名片 · 点击查看资料</span>
              <span class="post-card-name">{{ post.card.nickname }}</span>
            </span>
          </div>
          <div v-if="post.images.length" class="post-images" :class="{ single: post.images.length === 1 }">
            <img v-for="img in post.images" :key="img" :src="img" alt="帖子配图" />
          </div>

          <div class="post-foot">
            <button class="act" :class="{ on: post.liked_by_me }" @click="toggleLike(post)">
              {{ post.liked_by_me ? '❤️' : '🤍' }} {{ post.like_count }}
            </button>
            <button class="act" @click="toggleComments(post)">
              💬 {{ post.comment_count }}{{ expanded[post.id] ? ' 收起评论' : ' 评论' }}
            </button>
          </div>

          <!-- 评论区（展开后显示） -->
          <div v-if="expanded[post.id]" class="comments">
            <div v-if="!commentsByPost[post.id]" class="comments-loading">评论加载中…</div>
            <template v-else>
              <div v-if="!commentsByPost[post.id].length" class="comments-empty">还没有评论，来抢沙发</div>
              <div v-for="c in commentsByPost[post.id]" :key="c.id" class="comment">
                <UserAvatar
                  class="link"
                  :name="c.author?.nickname || '已删除'"
                  :url="c.author?.avatar_url"
                  :size="28"
                  title="查看资料"
                  @click="c.author && viewCard(c.author.user_id)"
                />
                <div class="comment-main">
                  <div class="comment-head">
                    <span class="nick">{{ c.author?.nickname || '该评论已删除' }}</span>
                    <span class="time">{{ formatDateTime(c.created_at) }}</span>
                  </div>
                  <p class="comment-content">{{ c.content }}</p>
                  <div class="comment-acts" v-if="c.author">
                    <button @click="startReply(post, c)">回复</button>
                    <button :class="{ on: c.liked_by_me }" @click="toggleCommentLike(post, c)">
                      {{ c.liked_by_me ? '❤️' : '🤍' }} {{ c.like_count }}
                    </button>
                    <button v-if="canDeleteComment(c)" class="danger" @click="confirmTarget = { type: 'comment', post, comment: c }">
                      删除
                    </button>
                  </div>
                  <!-- 二级回复 -->
                  <div v-if="c.replies.length" class="replies">
                    <div v-for="r in c.replies" :key="r.id" class="reply">
                      <div class="comment-head">
                        <span
                          class="nick"
                          :class="{ link: r.author }"
                          @click="r.author && viewCard(r.author.user_id)"
                        >
                          {{ r.author?.nickname || '该评论已删除' }}
                        </span>
                        <span v-if="r.parent_author" class="reply-to">回复 @{{ r.parent_author }}</span>
                        <span class="time">{{ formatDateTime(r.created_at) }}</span>
                      </div>
                      <p class="comment-content">{{ r.content }}</p>
                      <div class="comment-acts" v-if="r.author">
                        <button @click="startReply(post, r)">回复</button>
                        <button :class="{ on: r.liked_by_me }" @click="toggleCommentLike(post, r)">
                          {{ r.liked_by_me ? '❤️' : '🤍' }} {{ r.like_count }}
                        </button>
                        <button v-if="canDeleteComment(r)" class="danger" @click="confirmTarget = { type: 'comment', post, comment: r }">
                          删除
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <!-- 评论输入 -->
            <div class="comment-input">
              <div v-if="replyTo[post.id]" class="replying">
                回复 @{{ replyTo[post.id].author?.nickname }}
                <button @click="cancelReply(post)">×</button>
              </div>
              <div class="comment-row">
                <input
                  v-model="draft[post.id]"
                  class="input"
                  :placeholder="replyTo[post.id] ? `回复 @${replyTo[post.id].author?.nickname}…` : '发表评论…'"
                  maxlength="1000"
                  @keyup.enter="submitComment(post)"
                />
                <button class="btn btn-primary btn-sm" @click="submitComment(post)">发送</button>
              </div>
            </div>
          </div>
        </article>

        <div v-if="!posts.length" class="empty">
          <span class="icon">📝</span>还没有帖子，发第一帖吧
        </div>
        <div v-if="posts.length && hasMore" class="load-more">
          <button class="btn btn-ghost btn-sm" :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? '加载中…' : '加载更多帖子' }}
          </button>
        </div>
      </template>
    </template>

    <!-- 编辑帖子 -->
    <ModalDialog :open="showEdit" title="编辑帖子" @close="showEdit = false">
      <div class="field">
        <label>正文</label>
        <textarea v-model="editText" class="input" rows="4" maxlength="5000"></textarea>
      </div>
      <div class="field">
        <label>配图（最多 {{ MAX_IMAGES }} 张）</label>
        <div class="thumbs">
          <div v-for="(img, i) in editImages" :key="img" class="thumb">
            <img :src="img" alt="配图" />
            <button class="thumb-del" @click="editImages.splice(i, 1)">×</button>
          </div>
          <button v-if="editImages.length < MAX_IMAGES" class="thumb add" @click="editImageInput.click()">＋</button>
        </div>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showEdit = false">取消</button>
        <button class="btn btn-primary" @click="saveEdit">保存</button>
      </template>
    </ModalDialog>

    <!-- 编辑图片选择复用同一个 input：编辑弹窗打开时选择计入 editImages -->
    <input
      ref="editImageInput"
      type="file"
      :accept="IMAGE_ACCEPT"
      multiple
      hidden
      @change="
        async (e) => {
          const files = [...(e.target.files || [])]
          e.target.value = ''
          const room = MAX_IMAGES - editImages.length
          for (const f of files.slice(0, room)) {
            try {
              const d = await uploadFile(f, 'image')
              editImages.push(d.url)
            } catch (err) {
              toast.error(err.message)
            }
          }
        }
      "
    />

    <!-- 频道设置 -->
    <ModalDialog :open="showSettings" title="频道设置" @close="showSettings = false">
      <div class="field">
        <label>频道名称</label>
        <input v-model="settingsForm.name" class="input" maxlength="100" />
      </div>
      <div class="field">
        <label>频道简介</label>
        <textarea v-model="settingsForm.description" class="input" rows="3" maxlength="500"></textarea>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="showSettings = false">取消</button>
        <button class="btn btn-primary" @click="saveSettings">保存</button>
      </template>
    </ModalDialog>

    <!-- 删除确认 -->
    <ModalDialog :open="!!confirmTarget" title="删除确认" width="380" @close="confirmTarget = null">
      <p>{{ confirmTarget?.type === 'post' ? '确定删除这条帖子吗？删除后不可恢复。' : '确定删除这条评论吗？' }}</p>
      <template #footer>
        <button class="btn btn-ghost" @click="confirmTarget = null">取消</button>
        <button class="btn btn-danger" @click="doConfirm">删除</button>
      </template>
    </ModalDialog>

    <!-- 资料卡（点击头像 / 昵称 / 名片帖） -->
    <ProfileCard :open="cardUserId > 0" :user-id="cardUserId" @close="cardUserId = 0" />
  </div>
</template>

<style scoped>
.channel-detail {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  max-width: 760px;
}

/* 头部 */
.head {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 18px;
}
.avatar-btn {
  position: relative;
  border: none;
  background: none;
  padding: 0;
  cursor: default;
  border-radius: 50%;
}
.avatar-btn:disabled {
  cursor: default;
}
.avatar-btn:not(:disabled) {
  cursor: pointer;
}
.avatar-edit {
  position: absolute;
  right: -2px;
  bottom: -2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--brand-7);
  color: #fff;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.head-mid {
  flex: 1;
  min-width: 0;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.head-title h2 {
  font-size: 18px;
}
.desc {
  font-size: 13px;
  color: var(--g-9);
  margin-top: 4px;
}
.meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--g-8);
  margin-top: 6px;
}
.head-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.join-card {
  padding: 22px;
  text-align: center;
  font-size: 14px;
  color: var(--g-10);
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
}

/* 发帖 */
.composer {
  display: flex;
  gap: 12px;
  padding: 14px;
}
.composer-main {
  flex: 1;
  min-width: 0;
}
.composer-input {
  height: auto;
  line-height: 1.5;
  resize: vertical;
}
.thumbs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.thumb {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: var(--radius-s);
  overflow: hidden;
  border: 1px solid var(--g-4);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.thumb-del {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}
.thumb.add {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--g-8);
  background: var(--g-2);
  cursor: pointer;
}
.composer-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.emoji-wrap {
  position: relative;
}
/* EmojiPicker 默认向上弹出，发帖框在页面上部，改为向下弹出 */
.composer :deep(.picker) {
  bottom: auto;
  top: 100%;
  margin: 6px 0 0;
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
.tip {
  font-size: 11px;
  color: var(--g-7);
  margin-right: auto;
}

/* 排序 */
.sort-bar {
  display: flex;
  gap: 6px;
}
.sort {
  border: 1px solid var(--g-4);
  background: var(--g-1);
  border-radius: 999px;
  font-size: 12px;
  padding: 4px 14px;
  cursor: pointer;
  color: var(--g-9);
}
.sort.on {
  background: var(--brand-7);
  border-color: var(--brand-7);
  color: #fff;
  font-weight: 600;
}

/* 帖子 */
.post {
  padding: 16px;
}
.post-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.post-author {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.nick {
  font-size: 13px;
  font-weight: 700;
  color: var(--g-11);
}
.time {
  font-size: 11px;
  color: var(--g-7);
}
.post-menu {
  display: none;
  gap: 10px;
}
.post-menu button {
  border: none;
  background: none;
  font-size: 12px;
  color: var(--g-8);
  cursor: pointer;
  padding: 0;
}
.post-menu button:hover {
  color: var(--brand-7);
}
.post-menu button.danger:hover {
  color: var(--error-tx);
}
.post:hover .post-menu {
  display: inline-flex;
}
.post-content {
  font-size: 14px;
  line-height: 1.7;
  color: var(--g-12);
  margin: 10px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
}
/* 名片帖 */
.post-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-top: 10px;
  max-width: 320px;
  cursor: pointer;
}
.post-card:hover {
  border-color: var(--brand-3);
}
.post-card-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.post-card-title {
  font-size: 12px;
  color: var(--g-8);
}
.post-card-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--g-12);
}
/* 头像 / 昵称可点击查看资料卡 */
.link {
  cursor: pointer;
}
.nick.link:hover {
  color: var(--brand-7);
}
.post-images {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin-top: 10px;
}
.post-images.single img {
  max-width: 280px;
  max-height: 280px;
  object-fit: cover;
  border-radius: var(--radius-s);
}
.post-images:not(.single) img {
  width: 100%;
  aspect-ratio: 1;
  object-fit: cover;
  border-radius: var(--radius-s);
}
.post-foot {
  display: flex;
  gap: 18px;
  margin-top: 12px;
}
.act {
  border: none;
  background: none;
  font-size: 13px;
  color: var(--g-8);
  cursor: pointer;
  padding: 2px 0;
}
.act.on {
  color: var(--coral-7);
  font-weight: 700;
}
.act:hover {
  color: var(--brand-7);
}
.load-more {
  text-align: center;
}

/* 评论 */
.comments {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--g-4);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.comments-empty,
.comments-loading {
  font-size: 12px;
  color: var(--g-7);
  text-align: center;
  padding: 6px 0;
}
.comment {
  display: flex;
  gap: 8px;
}
.comment-main {
  flex: 1;
  min-width: 0;
}
.comment-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.comment-head .nick {
  font-size: 12px;
}
.reply-to {
  font-size: 11px;
  color: var(--brand-7);
}
.comment-content {
  font-size: 13px;
  color: var(--g-11);
  margin: 2px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.comment-acts {
  display: flex;
  gap: 12px;
  margin-top: 2px;
}
.comment-acts button {
  border: none;
  background: none;
  font-size: 11px;
  color: var(--g-7);
  cursor: pointer;
  padding: 0;
}
.comment-acts button:hover,
.comment-acts button.on {
  color: var(--brand-7);
}
.comment-acts button.danger:hover {
  color: var(--error-tx);
}
.replies {
  margin-top: 8px;
  padding: 8px 10px;
  background: var(--g-2);
  border-radius: var(--radius-s);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.reply .comment-content {
  font-size: 12px;
}
.comment-input {
  margin-top: 4px;
}
.replying {
  font-size: 12px;
  color: var(--brand-7);
  margin-bottom: 4px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.replying button {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--g-7);
}
.comment-row {
  display: flex;
  gap: 8px;
}
</style>
