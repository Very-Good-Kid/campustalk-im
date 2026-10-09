/**
 * 应用入口：装配 Pinia、路由与全局样式。
 *
 * 装配顺序：先样式（设计令牌必须先于组件生效），再 Pinia（store 在
 * 路由守卫中使用），最后挂载应用。本文件不做任何业务逻辑。
 */
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { useSettingsStore } from './stores/settings'

import './assets/styles/tokens.css'
import './assets/styles/main.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// 挂载前套用本机偏好（界面缩放），避免首屏尺寸跳动
useSettingsStore(pinia).applyPrefs()

app.mount('#app')
