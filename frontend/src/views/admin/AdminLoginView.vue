<script setup>
/**
 * 管理端登录页（设计 2.3.9）：独立登录入口，居中卡片，不使用 IM 骨架。
 *
 * 与用户端登录的关键差异：密码正确但账号无管理员权限时，
 * 服务端直接 403 且**不签发令牌**——这里只负责把拒绝理由显示出来。
 */
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const form = ref({ username: '', password: '' })
const loading = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (!form.value.username || !form.value.password) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    await auth.adminLogin(form.value.username, form.value.password)
    router.push(route.query.redirect || '/admin/overview')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="admin-login-page">
    <div class="card login-card">
      <div class="brand">CampusTalk<span class="brand-sub">管理后台</span></div>
      <p class="tip">仅管理员可登录，账号与用户端一致</p>

      <div class="field">
        <label>用户名</label>
        <input
          v-model="form.username"
          class="input"
          placeholder="管理员账号"
          @keyup.enter="submit"
        />
      </div>
      <div class="field">
        <label>密码</label>
        <input
          v-model="form.password"
          class="input"
          type="password"
          placeholder="密码"
          @keyup.enter="submit"
        />
      </div>

      <p v-if="error" class="err-msg">{{ error }}</p>

      <button class="btn btn-primary submit" :disabled="loading" @click="submit">
        {{ loading ? '登录中…' : '登录管理后台' }}
      </button>

      <router-link class="back" to="/login">返回用户端登录</router-link>
    </div>
  </div>
</template>

<style scoped>
.admin-login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--g-2);
}
.login-card {
  width: 380px;
  padding: 32px 30px;
}
.brand {
  font-size: 20px;
  font-weight: 800;
  color: var(--brand-7);
}
.brand-sub {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--g-8);
}
.tip {
  font-size: 12.5px;
  color: var(--g-8);
  margin: 6px 0 20px;
}
.err-msg {
  font-size: 12.5px;
  color: var(--error-tx);
  margin-bottom: 10px;
}
.submit {
  width: 100%;
  margin-top: 4px;
}
.back {
  display: block;
  text-align: center;
  margin-top: 16px;
  font-size: 12.5px;
  color: var(--g-8);
}
.back:hover {
  color: var(--brand-7);
}
</style>
