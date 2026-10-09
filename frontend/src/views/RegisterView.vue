<script setup>
/**
 * 注册页（设计 2.3.2）：居中卡片。
 *
 * 校验分层：失焦做单项格式校验（体验），唯一性 / 邀请码 / 协议勾选
 * 全部以后端为准。前端仅把后端的拒绝理由显示出来（不持有业务规则）。
 */
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

const router = useRouter()
const auth = useAuthStore()
const toast = useToastStore()

const form = reactive({
  invite_code: '',
  username: '',
  student_id: '',
  nickname: '',
  department: '',
  class_name: '',
  password: '',
  confirm_password: '',
  agree_terms: false,
})

const errors = reactive({})
const submitting = ref(false)

/** 失焦单项校验：只做格式与一致性，唯一性交给后端。 */
function validateField(key) {
  const v = String(form[key] ?? '').trim()
  switch (key) {
    case 'username':
      errors.username = !v ? '请输入用户名' : v.length < 4 ? '用户名至少 4 个字符' : ''
      break
    case 'nickname':
      errors.nickname = !v ? '请输入昵称' : ''
      break
    case 'password':
      errors.password = !v ? '请输入密码' : v.length < 6 ? '密码至少 6 位' : ''
      if (errors.confirm_password === undefined) break
    // eslint-disable-next-line no-fallthrough
    case 'confirm_password':
      errors.confirm_password = form.confirm_password !== form.password ? '两次输入的密码不一致' : ''
      break
  }
}

function validateAll() {
  ;['username', 'nickname', 'password', 'confirm_password'].forEach(validateField)
  if (!form.agree_terms) {
    errors.agree_terms = '请先阅读并同意用户协议'
    return false
  }
  errors.agree_terms = ''
  return !errors.username && !errors.nickname && !errors.password && !errors.confirm_password
}

async function submit() {
  if (!validateAll()) return
  submitting.value = true
  try {
    await auth.register({
      username: form.username.trim(),
      password: form.password,
      confirm_password: form.confirm_password,
      nickname: form.nickname.trim(),
      student_id: form.student_id.trim() || null,
      department: form.department.trim() || null,
      class_name: form.class_name.trim() || null,
      agree_terms: form.agree_terms,
      invite_code: form.invite_code.trim() || null,
    })
    toast.success('注册成功，请登录')
    router.push('/login')
  } catch (e) {
    toast.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="card box">
      <h1 class="logo">注册 CampusTalk</h1>
      <p class="slogan">学号即校园身份 · 请填写真实信息</p>

      <form @submit.prevent="submit">
        <div class="field">
          <label>邀请码</label>
          <input v-model="form.invite_code" class="input" placeholder="向班级 / 社团管理员获取" />
        </div>
        <div class="grid2">
          <div class="field">
            <label>用户名 *</label>
            <input v-model="form.username" class="input" @blur="validateField('username')" />
            <div v-if="errors.username" class="err">{{ errors.username }}</div>
          </div>
          <div class="field">
            <label>学号</label>
            <input v-model="form.student_id" class="input" maxlength="32" />
          </div>
        </div>
        <div class="grid2">
          <div class="field">
            <label>昵称 *</label>
            <input v-model="form.nickname" class="input" maxlength="50" @blur="validateField('nickname')" />
            <div v-if="errors.nickname" class="err">{{ errors.nickname }}</div>
          </div>
          <div class="field">
            <label>院系</label>
            <input v-model="form.department" class="input" maxlength="100" />
          </div>
        </div>
        <div class="field">
          <label>班级</label>
          <input v-model="form.class_name" class="input" maxlength="100" placeholder="如：软件工程2401" />
        </div>
        <div class="grid2">
          <div class="field">
            <label>密码 *</label>
            <input v-model="form.password" class="input" type="password" @blur="validateField('password')" />
            <div v-if="errors.password" class="err">{{ errors.password }}</div>
          </div>
          <div class="field">
            <label>确认密码 *</label>
            <input
              v-model="form.confirm_password"
              class="input"
              type="password"
              @blur="validateField('confirm_password')"
            />
            <div v-if="errors.confirm_password" class="err">{{ errors.confirm_password }}</div>
          </div>
        </div>

        <label class="agree">
          <input v-model="form.agree_terms" type="checkbox" @change="errors.agree_terms = ''" />
          我已阅读并同意<span class="link">《用户协议与社区规范》</span>（内容合规：发布内容不得违反法律法规）
        </label>
        <div v-if="errors.agree_terms" class="err">{{ errors.agree_terms }}</div>

        <button class="btn btn-primary submit" type="submit" :disabled="submitting">
          {{ submitting ? '注册中…' : '注 册' }}
        </button>
      </form>

      <p class="foot-tip">已有账号？<router-link to="/login">直接登录</router-link></p>
    </div>
  </div>
</template>

<style scoped>
.page {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  background: linear-gradient(135deg, var(--brand-10) 0%, var(--brand-7) 55%, var(--brand-5) 100%);
}
.box {
  width: 560px;
  padding: 36px 40px 28px;
}
.logo {
  text-align: center;
  font-size: 24px;
  font-weight: 800;
  color: var(--brand-7);
}
.slogan {
  text-align: center;
  font-size: 13px;
  color: var(--g-8);
  margin: 6px 0 22px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}
.agree {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
  color: var(--g-9);
  margin: 4px 0 6px;
  cursor: pointer;
}
.link {
  color: var(--brand-7);
}
.submit {
  width: 100%;
  height: 42px;
  font-size: 15px;
  margin-top: 10px;
}
.foot-tip {
  text-align: center;
  font-size: 13px;
  color: var(--g-8);
  margin-top: 16px;
}
</style>
