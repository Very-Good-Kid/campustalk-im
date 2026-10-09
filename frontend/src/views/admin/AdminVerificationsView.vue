<script setup>
/**
 * 管理端 · 学号审核（设计 2.3.9）。
 *
 * 证明材料存放在**未挂载静态路由**的私密目录，只能通过带管理员鉴权的
 * 接口读取；审核结论作出后后端即删除原件（数据最小化）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import ModalDialog from '@/components/ModalDialog.vue'
import { fetchProof, listVerificationRequests, reviewVerification } from '@/api/governance'
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()

const reqStatus = ref('pending')
const requests = ref([])
const loading = ref(false)

/** 证明材料预览 */
const proofUrl = ref('')
const proofTitle = ref('')
/** 通过二次确认 */
const approveTarget = ref(null)
/** 驳回理由 */
const rejectTarget = ref(null)
const rejectNote = ref('')

const STATUS_OPTIONS = [
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
]

async function load() {
  loading.value = true
  try {
    requests.value = await listVerificationRequests(reqStatus.value)
  } catch (e) {
    toast.error(e.message)
  } finally {
    loading.value = false
  }
}

/** 调阅证明材料：转发为 ObjectURL，关闭时释放，避免内存泄漏。 */
async function viewProof(req) {
  try {
    releaseProof()
    proofUrl.value = await fetchProof(req.request_id)
    proofTitle.value = `${req.applicant} 的证明材料`
  } catch (e) {
    toast.error(e.message)
  }
}

function releaseProof() {
  if (proofUrl.value) {
    URL.revokeObjectURL(proofUrl.value)
    proofUrl.value = ''
  }
}

async function doApprove() {
  try {
    await reviewVerification(approveTarget.value.request_id, 'approve')
    toast.success('已通过，新学号已写入并留痕')
    approveTarget.value = null
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

function askReject(req) {
  rejectTarget.value = req
  rejectNote.value = ''
}

async function doReject() {
  if (!rejectNote.value.trim()) {
    toast.error('驳回必须填写理由')
    return
  }
  try {
    await reviewVerification(rejectTarget.value.request_id, 'reject', rejectNote.value.trim())
    toast.success('已驳回')
    rejectTarget.value = null
    await load()
  } catch (e) {
    toast.error(e.message)
  }
}

onMounted(load)
onBeforeUnmount(releaseProof)
</script>

<template>
  <div class="admin-page">
    <div class="filter card">
      <button
        v-for="o in STATUS_OPTIONS"
        :key="o.value"
        class="tab"
        :class="{ active: reqStatus === o.value }"
        @click="reqStatus = o.value; load()"
      >
        {{ o.label }}
      </button>
    </div>

    <div class="card list-card">
      <div v-for="r in requests" :key="r.request_id" class="row">
        <div class="main">
          <div class="line">
            <span class="strong">{{ r.applicant }}</span>
            <span class="sub">@{{ r.username }}</span>
          </div>
          <div class="mono">{{ r.old_student_id || '（原为空）' }} → {{ r.new_student_id }}</div>
          <div v-if="r.user_note" class="sub">说明：{{ r.user_note }}</div>
        </div>
        <div class="ops">
          <button v-if="r.has_proof" class="btn btn-ghost btn-sm" @click="viewProof(r)">查看证明</button>
          <button class="btn btn-primary btn-sm" @click="approveTarget = r">通过</button>
          <button class="btn btn-danger btn-sm" @click="askReject(r)">驳回</button>
        </div>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!requests.length" class="empty"><span class="icon">🗂️</span>暂无该状态的申请</div>
    </div>

    <!-- 证明材料预览 -->
    <ModalDialog :open="!!proofUrl" :title="proofTitle" width="520" @close="releaseProof">
      <img :src="proofUrl" class="proof-img" alt="证明材料" />
    </ModalDialog>

    <!-- 通过二次确认 -->
    <ModalDialog
      :open="!!approveTarget"
      title="确认通过"
      width="400"
      @close="approveTarget = null"
    >
      <p class="confirm-text">
        确认通过「{{ approveTarget?.applicant }}」的学号变更申请？
        通过后将写入新学号并记录审核人与时间，证明材料原件随即删除。
      </p>
      <template #footer>
        <button class="btn btn-ghost" @click="approveTarget = null">取消</button>
        <button class="btn btn-primary" @click="doApprove">确认通过</button>
      </template>
    </ModalDialog>

    <!-- 驳回理由 -->
    <ModalDialog :open="!!rejectTarget" title="驳回申请" width="380" @close="rejectTarget = null">
      <div class="field">
        <label>驳回理由（必填）</label>
        <textarea v-model="rejectNote" class="input" rows="3" maxlength="200"></textarea>
      </div>
      <template #footer>
        <button class="btn btn-ghost" @click="rejectTarget = null">取消</button>
        <button class="btn btn-danger" @click="doReject">确认驳回</button>
      </template>
    </ModalDialog>
  </div>
</template>

<style scoped>
.admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.filter {
  display: flex;
  gap: 6px;
  padding: 12px 14px;
}
.tab {
  height: 30px;
  padding: 0 14px;
  border: 1px solid var(--g-5);
  border-radius: var(--radius-s);
  background: var(--g-1);
  font-size: 12.5px;
  color: var(--g-9);
  cursor: pointer;
  font-family: var(--font-cjk);
}
.tab.active {
  background: var(--brand-1);
  border-color: var(--brand-3);
  color: var(--brand-7);
  font-weight: 700;
}
.list-card {
  padding: 6px 20px;
}
.row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--g-3);
}
.row:last-child {
  border-bottom: none;
}
.main {
  min-width: 0;
  font-size: 13px;
}
.line {
  display: flex;
  align-items: center;
  gap: 6px;
}
.strong {
  font-weight: 700;
}
.mono {
  font-family: var(--font-mono);
  margin: 4px 0;
}
.sub {
  font-size: 12px;
  color: var(--g-8);
}
.ops {
  display: flex;
  gap: 8px;
  flex: none;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.proof-img {
  max-width: 100%;
  border-radius: var(--radius-s);
  border: 1px solid var(--g-4);
}
.confirm-text {
  font-size: 13.5px;
  color: var(--g-10);
  line-height: 1.7;
}
</style>
