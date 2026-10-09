<script setup>
/**
 * 会话大厅（设计 2.3.3）：三栏骨架的右侧默认页。
 * 未选择会话时显示欢迎信息与上手引导，不允许出现空白区域。
 */
import { computed } from 'vue'

import { useChatStore } from '@/stores/chat'
import { useAuthStore } from '@/stores/auth'

const chat = useChatStore()
const auth = useAuthStore()

const stats = computed(() => ({
  conversations: chat.conversations.length,
  unread: chat.totalUnread,
}))
</script>

<template>
  <div class="hall">
    <div class="card panel">
      <h1>你好，{{ auth.user?.nickname }} 👋</h1>
      <p class="sub">欢迎回到 CampusTalk，从左侧选择一个会话开始聊天。</p>

      <div class="stats">
        <div class="stat card">
          <span class="num">{{ stats.conversations }}</span>
          <span class="lab">我的会话</span>
        </div>
        <div class="stat card">
          <span class="num" :class="{ hot: stats.unread > 0 }">{{ stats.unread }}</span>
          <span class="lab">未读消息</span>
        </div>
      </div>

      <div class="guide">
        <h3>快速上手</h3>
        <ol>
          <li>在「好友」页通过<strong>用户名精确搜索</strong>或「找同班同学」添加好友；</li>
          <li>点击好友「发消息」开始单聊，或在左侧「+ 群聊」发起群聊；</li>
          <li>在「频道」页免审加入兴趣频道，与同好长期讨论；</li>
          <li>聊天中可发送文本、表情、图片与文件，3 分钟内可撤回本人消息。</li>
        </ol>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hall {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  background: var(--g-2);
}
.panel {
  width: 560px;
  padding: 36px 40px;
}
h1 {
  font-size: 24px;
  margin-bottom: 6px;
}
.sub {
  color: var(--g-8);
  font-size: 14px;
  margin-bottom: 24px;
}
.stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 26px;
}
.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 18px;
  gap: 2px;
}
.num {
  font-size: 26px;
  font-weight: 800;
  color: var(--brand-7);
}
.num.hot {
  color: var(--coral-6);
}
.lab {
  font-size: 12px;
  color: var(--g-8);
}
.guide h3 {
  font-size: 15px;
  margin-bottom: 10px;
}
.guide ol {
  padding-left: 20px;
  color: var(--g-9);
  font-size: 13.5px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
</style>
