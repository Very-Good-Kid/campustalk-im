<script setup>
/**
 * 通知面板：type=friend 好友通知（收到的申请 / 我发出的申请）；
 * type=group 群通知（加群申请审批：待我处理 / 我发出的）。
 *
 * 两个列表都默认只展示前几条，其余通过「查看全部」浮窗查看；
 * 「我发出的申请」会保留同意 / 拒绝结果，不再在对方处理后凭空消失。
 *
 * 整条记录可点击：好友记录弹出用户资料卡（ProfileCard），
 * 群记录弹出群资料浮层（GroupCard），详情里再进会话发消息。
 * 列表本身只显示状态文字，操作入口都藏在点开的详情浮层里。
 */
import { computed, onMounted, ref } from 'vue'

import GroupCard from '@/components/GroupCard.vue'
import ModalDialog from '@/components/ModalDialog.vue'
import ProfileCard from '@/components/ProfileCard.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import * as convApi from '@/api/conversations'
import * as friendsApi from '@/api/friends'
import { useChatStore } from '@/stores/chat'
import { useFriendsStore } from '@/stores/friends'
import { useGroupRequestsStore } from '@/stores/groupRequests'
import { useToastStore } from '@/stores/toast'
import { formatDateTime } from '@/utils/format'

const props = defineProps({
  /** friend=好友通知 / group=群通知 */
  type: { type: String, default: 'friend' },
})

const friendsStore = useFriendsStore()
const groupStore = useGroupRequestsStore()
const chat = useChatStore()
const toast = useToastStore()

/** 列表默认展示条数，超出部分走「查看全部」 */
const PREVIEW_COUNT = 3
const showAllReceived = ref(false)
const showAllSent = ref(false)

const receivedPreview = computed(() => friendsStore.received.slice(0, PREVIEW_COUNT))
const sentPreview = computed(() => friendsStore.sent.slice(0, PREVIEW_COUNT))

/** 状态文案：两个方向都会出现"已同意"（记录保留，点开卡片可发消息） */
const RECEIVED_STATUS = { pending: '待我处理', accepted: '已同意', rejected: '已拒绝' }
const SENT_STATUS = { pending: '待对方处理', accepted: '已同意', rejected: '已拒绝' }
/** 加群申请：待处理方是群主 / 管理员，文案单独区分 */
const GROUP_SENT_STATUS = { pending: '待群主处理', accepted: '已同意', rejected: '已拒绝' }
const STATUS_TAG = { pending: 'tag-warning', accepted: 'tag-success', rejected: 'tag-error' }

/** 用户资料卡 / 群资料浮层：0 表示关闭 */
const cardUserId = ref(0)
const cardConversationId = ref(0)

function openProfile(user) {
  if (user?.id) cardUserId.value = user.id
}

function openGroupCard(conversationId) {
  if (conversationId) cardConversationId.value = conversationId
}

onMounted(() => {
  if (props.type === 'group') {
    groupStore.loadAll().catch((e) => toast.error(e.message))
    // 同意入群后会话列表需要刷新，进来时同步一次
    chat.loadConversations().catch(() => {})
  } else if (!friendsStore.loaded) {
    friendsStore.loadAll().catch((e) => toast.error(e.message))
  }
})

/** 处理收到的申请：同意 / 拒绝。 */
async function handleRequest(requestId, action) {
  try {
    await friendsApi.handleFriendRequest(requestId, action)
    toast.success(action === 'accept' ? '已同意，你们现在是好友了' : '已拒绝')
    await friendsStore.loadAll()
  } catch (e) {
    toast.error(e.message)
  }
}

/** 审批加群申请：同意后申请人立即入群。 */
async function handleGroup(requestId, action) {
  try {
    await convApi.handleGroupRequest(requestId, action)
    toast.success(action === 'accept' ? '已同意入群' : '已拒绝')
    await groupStore.loadAll()
    await chat.loadConversations()
  } catch (e) {
    toast.error(e.message)
  }
}
</script>

<template>
  <div class="notify-panel">
    <template v-if="type === 'friend'">
      <!-- 收到的申请 -->
      <section class="card block">
        <div class="block-head">
          <h3>收到的申请（{{ friendsStore.received.length }}）</h3>
          <button
            v-if="friendsStore.received.length > PREVIEW_COUNT"
            class="btn btn-ghost btn-sm"
            @click="showAllReceived = true"
          >
            查看全部
          </button>
        </div>
        <div
          v-for="r in receivedPreview"
          :key="r.request_id"
          class="item clickable"
          @click="openProfile(r.user)"
        >
          <UserAvatar class="link" :name="r.user?.nickname" :url="r.user?.avatar_url" :size="40" />
          <div class="item-mid link">
            <div class="item-name">{{ r.user?.nickname }}</div>
            <div class="item-sub">@{{ r.user?.username }} · {{ formatDateTime(r.created_at) }}</div>
            <div v-if="r.request_message" class="item-msg">"{{ r.request_message }}"</div>
          </div>
          <template v-if="r.status === 'pending'">
            <button class="btn btn-primary btn-sm" @click.stop="handleRequest(r.request_id, 'accept')">同意</button>
            <button class="btn btn-ghost btn-sm" @click.stop="handleRequest(r.request_id, 'reject')">拒绝</button>
          </template>
          <span v-else class="tag" :class="STATUS_TAG[r.status]">{{ RECEIVED_STATUS[r.status] }}</span>
        </div>
        <div v-if="!friendsStore.received.length" class="empty"><span class="icon">📭</span>暂无收到的申请</div>
      </section>

      <!-- 我发出的申请 -->
      <section class="card block">
        <div class="block-head">
          <h3>申请通知（我发出的，{{ friendsStore.sent.length }}）</h3>
          <button
            v-if="friendsStore.sent.length > PREVIEW_COUNT"
            class="btn btn-ghost btn-sm"
            @click="showAllSent = true"
          >
            查看全部
          </button>
        </div>
        <div
          v-for="r in sentPreview"
          :key="r.request_id"
          class="item clickable"
          @click="openProfile(r.user)"
        >
          <UserAvatar class="link" :name="r.user?.nickname" :url="r.user?.avatar_url" :size="40" />
          <div class="item-mid link">
            <div class="item-name">{{ r.user?.nickname }}</div>
            <div class="item-sub">@{{ r.user?.username }} · {{ formatDateTime(r.created_at) }}</div>
          </div>
          <span class="tag" :class="STATUS_TAG[r.status]">{{ SENT_STATUS[r.status] }}</span>
        </div>
        <div v-if="!friendsStore.sent.length" class="empty"><span class="icon">📤</span>暂无发出的申请</div>
      </section>
    </template>

    <template v-else>
      <!-- 收到的加群申请（我是群主 / 管理员） -->
      <section class="card block">
        <h3>加群申请（待我处理）</h3>
        <div
          v-for="r in groupStore.received"
          :key="r.request_id"
          class="item clickable"
          @click="openGroupCard(r.conversation.conversation_id)"
        >
          <UserAvatar
            class="link"
            :name="r.user?.nickname"
            :url="r.user?.avatar_url"
            :size="40"
            @click.stop="openProfile(r.user)"
          />
          <div class="item-mid link">
            <div class="item-name">{{ r.user?.nickname }}</div>
            <div class="item-sub">
              申请加入「{{ r.conversation.name }}」（群号 {{ r.conversation.conversation_id }}） ·
              {{ formatDateTime(r.created_at) }}
            </div>
            <div v-if="r.message" class="item-msg">"{{ r.message }}"</div>
          </div>
          <template v-if="r.status === 'pending'">
            <button class="btn btn-primary btn-sm" @click.stop="handleGroup(r.request_id, 'accept')">同意</button>
            <button class="btn btn-ghost btn-sm" @click.stop="handleGroup(r.request_id, 'reject')">拒绝</button>
          </template>
          <span v-else class="tag" :class="STATUS_TAG[r.status]">
            {{ r.status === 'rejected' ? '已拒绝' : '已同意' }}
          </span>
        </div>
        <div v-if="!groupStore.received.length" class="empty">
          <span class="icon">📭</span>暂无加群申请
        </div>
      </section>

      <!-- 我发出的加群申请 -->
      <section class="card block">
        <h3>我发出的加群申请（{{ groupStore.sent.length }}）</h3>
        <div
          v-for="r in groupStore.sent"
          :key="r.request_id"
          class="item clickable"
          @click="openGroupCard(r.conversation.conversation_id)"
        >
          <UserAvatar :name="r.conversation.name" :url="r.conversation.avatar_url" :size="40" />
          <div class="item-mid">
            <div class="item-name">{{ r.conversation.name }}</div>
            <div class="item-sub">
              群号 {{ r.conversation.conversation_id }} · {{ formatDateTime(r.created_at) }}
            </div>
            <div v-if="r.message" class="item-msg">"{{ r.message }}"</div>
          </div>
          <span class="tag" :class="STATUS_TAG[r.status]">{{ GROUP_SENT_STATUS[r.status] }}</span>
        </div>
        <div v-if="!groupStore.sent.length" class="empty">
          <span class="icon">📤</span>还没有发出过加群申请<br />在「联系人 → 群聊 → 加入群聊」输入群号申请
        </div>
      </section>
    </template>

    <!-- 查看全部：收到的申请 -->
    <ModalDialog :open="showAllReceived" title="收到的申请" width="520" @close="showAllReceived = false">
      <div class="all-list">
        <div
          v-for="r in friendsStore.received"
          :key="r.request_id"
          class="item clickable"
          @click="openProfile(r.user)"
        >
          <UserAvatar class="link" :name="r.user?.nickname" :url="r.user?.avatar_url" :size="36" />
          <div class="item-mid link">
            <div class="item-name">{{ r.user?.nickname }}</div>
            <div class="item-sub">@{{ r.user?.username }} · {{ formatDateTime(r.created_at) }}</div>
          </div>
          <template v-if="r.status === 'pending'">
            <button class="btn btn-primary btn-sm" @click.stop="handleRequest(r.request_id, 'accept')">同意</button>
            <button class="btn btn-ghost btn-sm" @click.stop="handleRequest(r.request_id, 'reject')">拒绝</button>
          </template>
          <span v-else class="tag" :class="STATUS_TAG[r.status]">{{ RECEIVED_STATUS[r.status] }}</span>
        </div>
        <div v-if="!friendsStore.received.length" class="empty">暂无收到的申请</div>
      </div>
    </ModalDialog>

    <!-- 查看全部：我发出的申请 -->
    <ModalDialog :open="showAllSent" title="我发出的申请" width="520" @close="showAllSent = false">
      <div class="all-list">
        <div
          v-for="r in friendsStore.sent"
          :key="r.request_id"
          class="item clickable"
          @click="openProfile(r.user)"
        >
          <UserAvatar class="link" :name="r.user?.nickname" :url="r.user?.avatar_url" :size="36" />
          <div class="item-mid link">
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

    <!-- 群资料浮窗（点开加群申请记录查看群详情，并从中发消息） -->
    <GroupCard
      :open="cardConversationId > 0"
      :conversation-id="cardConversationId"
      @close="cardConversationId = 0"
    />
  </div>
</template>

<style scoped>
.notify-panel {
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
  padding: 18px 24px;
}
.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.block h3 {
  font-size: 15px;
  margin-bottom: 8px;
}
.block-head h3 {
  margin-bottom: 0;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
}
/* 整条记录可点击：点开详情浮层（用户资料卡 / 群资料浮层） */
.item.clickable {
  cursor: pointer;
  border-radius: var(--radius-s);
  padding: 8px;
  margin: 0 -8px;
}
.item.clickable:hover {
  background: var(--g-2);
}
.item-mid {
  flex: 1;
  min-width: 0;
}
/* 头像与昵称可点击查看资料 */
.link {
  cursor: pointer;
}
.link:hover .item-name {
  color: var(--brand-7);
}
.item-name {
  font-size: 13.5px;
  font-weight: 600;
}
.item-sub {
  font-size: 12px;
  color: var(--g-8);
}
.item-msg {
  font-size: 12px;
  color: var(--g-9);
  background: var(--g-3);
  border-radius: 6px;
  padding: 2px 8px;
  margin-top: 2px;
}
.all-list {
  max-height: 420px;
  overflow-y: auto;
}
</style>
