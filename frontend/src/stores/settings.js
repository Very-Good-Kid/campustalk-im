/**
 * 用户偏好设置：只保存在本机浏览器（localStorage），不入库、不上传。
 *
 * 只放"真正会被消费"的项，避免设置页出现点了没反应的开关：
 * - sound 消息提示音 → chat store 收到非当前会话的新消息时播放（Web Audio 合成，无音频文件）
 * - dnd   免打扰     → 提示音静默
 * - zoom  界面缩放   → 写入 <html> 的 zoom，整体界面（含字号）等比缩放
 *
 * 主题与语言属后续规划项，设置页只保留入口并提示"开发中"。
 */
import { defineStore } from 'pinia'

const STORAGE_KEY = 'ct_prefs'

const DEFAULTS = { sound: true, dnd: false, zoom: 1 }

/** 界面缩放档位（用 zoom 而非 font-size：现有样式以 px 为主，只改字号不会整体生效） */
export const ZOOM_LEVELS = [
  { value: 0.9, label: '小' },
  { value: 1, label: '中' },
  { value: 1.1, label: '大' },
]

function readPrefs() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }
  } catch {
    return { ...DEFAULTS }
  }
}

export const useSettingsStore = defineStore('settings', {
  state: () => readPrefs(),

  actions: {
    persist() {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ sound: this.sound, dnd: this.dnd, zoom: this.zoom }),
      )
    },

    /** 把偏好应用到 DOM：应用挂载前调用一次，之后每次修改再调用 */
    applyPrefs() {
      document.documentElement.style.zoom = String(this.zoom || 1)
    },

    setSound(v) {
      this.sound = v
      this.persist()
    },

    setDnd(v) {
      this.dnd = v
      this.persist()
    },

    setZoom(v) {
      this.zoom = v
      this.applyPrefs()
      this.persist()
    },

    /**
     * 新消息提示音：用 Web Audio 合成一声短促的"叮"。
     * 关闭提示音 / 免打扰时直接返回；任何异常都静默——
     * 绝不能因为提示音失败而影响消息接收这一主流程。
     */
    playNotice() {
      if (!this.sound || this.dnd) return
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext
        if (!Ctx) return
        const ctx = new Ctx()
        const osc = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.type = 'sine'
        osc.frequency.value = 880
        gain.gain.setValueAtTime(0.12, ctx.currentTime)
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.18)
        osc.connect(gain)
        gain.connect(ctx.destination)
        osc.start()
        osc.stop(ctx.currentTime + 0.18)
        osc.onended = () => ctx.close()
      } catch {
        /* 浏览器未授权音频等情况静默忽略 */
      }
    },
  },
})
