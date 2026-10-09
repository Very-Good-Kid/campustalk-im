<script setup>
/**
 * 通用浮窗（页面内 Modal）：替代浏览器原生 alert / confirm / prompt。
 * 点击遮罩或右上角 × 关闭；确认类操作的按钮由使用方放在 footer 插槽。
 */
defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  width: { type: Number, default: 420 },
})
const emit = defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="overlay" @click.self="emit('close')">
      <div class="dialog card" :style="{ width: width + 'px' }">
        <div class="head">
          <h3>{{ title }}</h3>
          <button class="close" aria-label="关闭" @click="emit('close')">×</button>
        </div>
        <div class="body">
          <slot />
        </div>
        <div v-if="$slots.footer" class="foot">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(11, 13, 19, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.dialog {
  max-width: calc(100vw - 48px);
  max-height: calc(100vh - 96px);
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-pop);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 0;
}
.head h3 {
  font-size: 16px;
}
.close {
  border: none;
  background: none;
  font-size: 20px;
  color: var(--g-7);
  cursor: pointer;
  line-height: 1;
}
.close:hover {
  color: var(--g-11);
}
.body {
  padding: 16px 20px;
  overflow-y: auto;
}
.foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 0 20px 18px;
}
</style>
