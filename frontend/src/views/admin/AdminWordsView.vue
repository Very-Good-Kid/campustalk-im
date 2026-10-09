<!--
  管理端 · 敏感词库（对应后端 /api/admin/sensitive-words）。

  交互刻意保持"一张表＋一个输入框"的极简形态：词库是低频维护项，
  不值得做分页/搜索/批量导入；真正重要的行为发生在保存之后——
  服务端写库并经总线控制帧让所有实例立刻重建前缀树，无需重启。
-->
<script setup>
import { onMounted, ref } from 'vue'

import { addSensitiveWord, deleteSensitiveWord, listSensitiveWords } from '@/api/admin'
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
const words = ref([])
const loading = ref(true)
const input = ref('')
const submitting = ref(false)

async function load() {
  loading.value = true
  try {
    words.value = await listSensitiveWords()
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

async function submit() {
  const word = input.value.trim()
  if (!word || submitting.value) return
  submitting.value = true
  try {
    await addSensitiveWord(word)
    input.value = ''
    toast.success(`已添加「${word}」，全实例即时生效`)
    await load()
  } catch (e) {
    toast.error(e.message)
  } finally {
    submitting.value = false
  }
}

async function remove(w) {
  try {
    await deleteSensitiveWord(w.id)
    toast.success(`已删除「${w.word}」`)
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

function fmt(ts) {
  return ts ? ts.replace('T', ' ').slice(0, 16) : ''
}

onMounted(load)
</script>

<template>
  <div class="words-page">
    <header class="page-head">
      <h2>敏感词库</h2>
      <p class="sub">事中防线词表：新消息与频道发帖命中即拒。改词即时生效，无需重启服务。</p>
    </header>

    <div class="add-row card">
      <input
        v-model="input"
        class="input"
        maxlength="50"
        placeholder="输入要拦截的词，回车添加"
        @keydown.enter.prevent="submit"
      />
      <button class="btn btn-primary" :disabled="!input.trim() || submitting" @click="submit">
        添加
      </button>
    </div>

    <div class="list card">
      <div v-if="loading" class="empty">加载中…</div>
      <table v-else-if="words.length">
        <thead>
          <tr>
            <th>敏感词</th>
            <th>添加时间</th>
            <th class="col-op">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in words" :key="w.id">
            <td class="word">{{ w.word }}</td>
            <td class="time">{{ fmt(w.created_at) }}</td>
            <td class="col-op">
              <button class="btn btn-sm btn-danger" @click="remove(w)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">词库为空——当前不会拦截任何内容</div>
      <p v-if="!loading" class="count">共 {{ words.length }} 条</p>
    </div>
  </div>
</template>

<style scoped>
.words-page {
  padding: 20px 24px;
}
.page-head h2 {
  margin: 0 0 4px;
  font-size: 18px;
  color: var(--g-12);
}
.sub {
  margin: 0 0 16px;
  font-size: 12px;
  color: var(--g-8);
}
.add-row {
  display: flex;
  gap: 10px;
  padding: 14px;
  margin-bottom: 16px;
}
.add-row .input {
  flex: 1;
}
.list {
  padding: 4px 14px 10px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  text-align: left;
  padding: 9px 6px;
  border-bottom: 1px solid var(--g-3);
}
th {
  color: var(--g-8);
  font-weight: 500;
}
.word {
  color: var(--g-12);
  font-weight: 500;
}
.time {
  color: var(--g-8);
}
.col-op {
  width: 90px;
}
.btn-danger {
  background: var(--error);
  color: #fff;
  border: none;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
  border-radius: var(--radius-s);
  cursor: pointer;
}
.empty {
  padding: 26px;
  text-align: center;
  color: var(--g-7);
  font-size: 13px;
}
.count {
  margin: 10px 2px 0;
  font-size: 12px;
  color: var(--g-8);
}
</style>
