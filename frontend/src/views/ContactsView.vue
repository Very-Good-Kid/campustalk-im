<script setup>
/**
 * 联系人页主壳：左侧栏（ContactsSidebar）承载第一级选项与分组联系人列表，
 * 本组件只负责按路由在右侧主栏切换内容面板——
 * 好友资料 / 群资料 / 好友管理 / 好友通知 / 群通知 / 空态引导。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import FriendPanel from '@/views/contacts/FriendPanel.vue'
import GroupPanel from '@/views/contacts/GroupPanel.vue'
import ManagePanel from '@/views/contacts/ManagePanel.vue'
import NotifyPanel from '@/views/contacts/NotifyPanel.vue'

const route = useRoute()

const panel = computed(() => {
  if (route.name === 'contacts-friend') return 'friend'
  if (route.name === 'contacts-group') return 'group'
  if (route.params.tab) return route.params.tab // manage / friend-notify / group-notify
  return 'empty'
})
</script>

<template>
  <div class="contacts-page">
    <ManagePanel v-if="panel === 'manage'" />
    <NotifyPanel v-else-if="panel === 'friend-notify'" type="friend" />
    <NotifyPanel v-else-if="panel === 'group-notify'" type="group" />
    <!-- key 绑定路由参数：切换好友 / 群聊时强制重建面板。
         面板内部的数据只在 onMounted 里拉取一次（见 FriendPanel / GroupPanel），
         不加 key 会复用同一实例，右侧资料停留在上一个目标上。 -->
    <FriendPanel
      v-else-if="panel === 'friend'"
      :key="route.params.userId"
      :user-id="route.params.userId"
    />
    <GroupPanel
      v-else-if="panel === 'group'"
      :key="route.params.id"
      :group-id="route.params.id"
    />
    <div v-else class="empty pick-hint">
      <span class="icon">🫱</span>在左侧选择一位联系人或群聊<br />这里会展示资料卡片
    </div>
  </div>
</template>

<style scoped>
.contacts-page {
  flex: 1;
  display: flex;
  min-height: 0;
  min-width: 0;
}
.pick-hint {
  flex: 1;
  align-self: center;
  margin: 0 auto;
}
</style>
