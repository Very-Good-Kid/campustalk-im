<script setup>
/**
 * 表情面板：点选即通过 select 事件抛出 Unicode 表情字符，
 * 由调用方插入输入框。表情本身随文本消息走同一条发送链路。
 */
import { EMOJIS } from '@/utils/format'

const emit = defineEmits(['select'])
</script>

<template>
  <div class="picker card">
    <button v-for="e in EMOJIS" :key="e" class="cell" type="button" @click="emit('select', e)">
      {{ e }}
    </button>
  </div>
</template>

<style scoped>
.picker {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 2px;
  padding: 8px;
  box-shadow: var(--shadow-pop);
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 8px;
  z-index: 10;
}
.cell {
  border: none;
  background: none;
  font-size: 20px;
  padding: 4px;
  border-radius: 6px;
  cursor: pointer;
  line-height: 1.3;
}
.cell:hover {
  background: var(--brand-1);
}
</style>
