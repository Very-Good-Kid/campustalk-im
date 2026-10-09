/**
 * 全局轻提示（Toast）状态。
 *
 * 统一替代浏览器原生 alert：后端的拒绝理由都通过这里展示，
 * 保证提示风格与界面一致（设计 2.3.8 "不使用原生弹窗"约定）。
 */
import { defineStore } from 'pinia'

let nextId = 1

export const useToastStore = defineStore('toast', {
  state: () => ({ items: [] }),
  actions: {
    /** kind = success / error / info，默认自动消失 3 秒。 */
    show(message, kind = 'info', duration = 3000) {
      const id = nextId++
      this.items.push({ id, message, kind })
      setTimeout(() => this.dismiss(id), duration)
    },
    success(message) {
      this.show(message, 'success')
    },
    error(message) {
      this.show(message, 'error')
    },
    info(message) {
      this.show(message, 'info')
    },
    dismiss(id) {
      this.items = this.items.filter((t) => t.id !== id)
    },
  },
})

/** 便捷组合式函数，组件内直接 useToast().success('...')。 */
export function useToast() {
  return useToastStore()
}
