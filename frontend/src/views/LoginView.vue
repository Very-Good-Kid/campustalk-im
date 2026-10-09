<script setup>
/**
 * 登录页（设计 2.3.1）：居中卡片，不使用三栏骨架。
 * 登录失败统一提示"用户名或密码错误"——该文案由后端返回，前端不区分
 * 具体原因，避免账号枚举。
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const toast = useToastStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)
const errorMsg = ref('')

async function submit() {
  if (!form.username || !form.password) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    await auth.login(form.username, form.password)
    toast.success('登录成功')
    router.push(String(route.query.redirect || '/'))
  } catch (e) {
    errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="card box">
      <h1 class="logo">CampusTalk</h1>
      <p class="slogan">校园即时通讯 · 私聊 / 群聊 / 兴趣频道</p>

      <form @submit.prevent="submit">
        <div class="field">
          <label>用户名</label>
          <input v-model="form.username" class="input" autocomplete="username" placeholder="请输入用户名" />
        </div>
        <div class="field">
          <label>密码</label>
          <input
            v-model="form.password"
            class="input"
            type="password"
            autocomplete="current-password"
            placeholder="请输入密码"
          />
        </div>
        <div v-if="errorMsg" class="err form-err">{{ errorMsg }}</div>
        <button class="btn btn-primary submit" type="submit" :disabled="loading">
          {{ loading ? '登录中…' : '登 录' }}
        </button>
      </form>

      <p class="foot-tip">
        还没有账号？<router-link to="/register">注册新账号</router-link>
      </p>
    </div>
  </div>
</template>

<style scoped>
.page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--brand-10) 0%, var(--brand-7) 55%, var(--brand-5) 100%);
}
.box {
  width: 400px;
  padding: 40px 36px 28px;
}
.logo {
  text-align: center;
  font-size: 28px;
  font-weight: 800;
  color: var(--brand-7);
  letter-spacing: 1px;
}
.slogan {
  text-align: center;
  font-size: 13px;
  color: var(--g-8);
  margin: 8px 0 26px;
}
.form-err {
  background: var(--error-bg);
  color: var(--error-tx);
  border-radius: var(--radius-s);
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 14px;
}
.submit {
  width: 100%;
  height: 42px;
  font-size: 15px;
}
.foot-tip {
  text-align: center;
  font-size: 13px;
  color: var(--g-8);
  margin-top: 18px;
}
</style>
