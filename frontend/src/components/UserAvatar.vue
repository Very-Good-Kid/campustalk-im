<script setup>
/**
 * 用户 / 会话头像：有图显示图片，无图按名称首字渲染彩色圆。
 * 颜色由名称哈希决定，保证同一人颜色稳定。
 */
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, default: '' },
  url: { type: String, default: '' },
  size: { type: Number, default: 40 },
})

const PALETTE = ['#2e5dff', '#1fbfa6', '#ff6a45', '#7a5cff', '#e37318', '#149e89']

const initial = computed(() => (props.name || '?').trim().charAt(0).toUpperCase())

const bgColor = computed(() => {
  let hash = 0
  for (const ch of props.name || '') hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[hash % PALETTE.length]
})
</script>

<template>
  <img v-if="url" class="avatar" :src="url" :alt="name" />
  <span v-else class="avatar avatar-fallback" :style="{ background: bgColor, fontSize: size * 0.42 + 'px' }">
    {{ initial }}
  </span>
</template>

<style scoped>
.avatar {
  width: v-bind("size + 'px'");
  height: v-bind("size + 'px'");
  border-radius: 50%;
  object-fit: cover;
  flex: none;
}
.avatar-fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 700;
  user-select: none;
}
</style>
