<script setup>
/**
 * 全局轻提示容器：挂在 App.vue 根部，内容来自 toast store。
 */
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
</script>

<template>
  <Teleport to="body">
    <TransitionGroup name="toast" tag="div" class="host">
      <div v-for="t in toast.items" :key="t.id" class="toast" :class="t.kind" @click="toast.dismiss(t.id)">
        {{ t.message }}
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<style scoped>
.host {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  z-index: 200;
}
.toast {
  padding: 10px 20px;
  border-radius: var(--radius-s);
  font-size: 13px;
  font-weight: 500;
  box-shadow: var(--shadow-pop);
  cursor: pointer;
  background: var(--g-12);
  color: #fff;
}
.toast.success { background: var(--success); }
.toast.error { background: var(--error); }
.toast.info { background: var(--g-11); }

.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
