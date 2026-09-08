<script setup lang="ts">
import { computed, onMounted, ref, shallowRef } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, ApiError, type EvaluatorOption, type Version } from '../api/client'
import { runsApi } from '../api/runs'
import { datasetApi } from '../api/datasets'
import DatasetList from '../components/dataset/DatasetList.vue'
import VersionSelector from '../components/dataset/VersionSelector.vue'
import CaseTable from '../components/dataset/CaseTable.vue'
import CaseEditor from '../components/dataset/CaseEditor.vue'
import type { RunProgress } from '../types/run'
import type {
  DatasetExport, DatasetSummary, DatasetVersion, EvaluationCase, ValidationIssue,
} from '../types/dataset'

const emit = defineEmits<{ runCreated: [run: RunProgress] }>()

const datasets = shallowRef<DatasetSummary[]>([])
const versions = shallowRef<DatasetVersion[]>([])
const activeDatasetId = ref('')
const activeVersionId = ref('')
const activeCaseId = ref('')
const editedCase = ref<EvaluationCase|null>(null)
const targetVersions = ref<Version[]>([])
const evaluators = ref<EvaluatorOption[]>([])
const selectedAgent = ref('loan-agent-v2-fixed')
const selectedEvaluators = ref<string[]>([])
const busy = ref(false)
const loading = ref(false)
const validationIssues = ref<ValidationIssue[]>([])
const datasetDialog = ref(false)
const editorOpen = ref(false)
const runDialog = ref(false)
const runCaseIds = ref<string[]|undefined>()
const workspaceView = ref<'catalog'|'detail'>('catalog')
const detailTab = ref<'cases'|'versions'|'settings'>('cases')
const dialogMode = ref<'create'|'copy'>('create')
const dialogSourceDatasetId = ref('')
const dialogSourceVersion = ref<number|null>(null)
const dialogName = ref('')
const dialogDescription = ref('')
const importInput = ref<HTMLInputElement|null>(null)
const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value))

const activeVersion = computed<DatasetVersion|null>(
  () => versions.value.find(item => item.id === activeVersionId.value) ?? null,
)
const editable = computed(() => activeVersion.value?.status === 'draft')
const publishedVersions = computed(() => versions.value.filter(item => item.status === 'published'))
const activeDataset = computed(() => datasets.value.find(item => item.id === activeDatasetId.value) ?? null)
const activeCaseIssues = computed(() => {
  const caseIndex = activeVersion.value?.cases.findIndex(item => item.id === activeCaseId.value) ?? -1
  if (caseIndex < 0) return []
  const prefix = `cases[${caseIndex}]`
  return validationIssues.value.filter(issue => issue.path.startsWith(prefix))
})

function chooseVersion(preferredId = '') {
  const selected = versions.value.find(item => item.id === preferredId)
    ?? versions.value.find(item => item.status === 'draft')
    ?? publishedVersions.value[0]
    ?? null
  activeVersionId.value = selected?.id ?? ''
  selectFirstCase(selected)
}

function selectFirstCase(version: DatasetVersion|null) {
  const selected = version?.cases.find(item => item.id === activeCaseId.value)
    ?? version?.cases[0]
    ?? null
  activeCaseId.value = selected?.id ?? ''
  editedCase.value = selected ? cloneJson(selected) : null
}

async function loadDatasets(preferredDatasetId = activeDatasetId.value) {
  datasets.value = await datasetApi.list()
  const selected = datasets.value.find(item => item.id === preferredDatasetId)
  if (selected) return selectDataset(selected.id)
  activeDatasetId.value = ''
  versions.value = []
  workspaceView.value = 'catalog'
  chooseVersion()
}

async function selectDataset(datasetId: string, preferredVersionId = '') {
  loading.value = true
  try {
    activeDatasetId.value = datasetId
    const detail = await datasetApi.detail(datasetId)
    versions.value = detail.versions
    chooseVersion(preferredVersionId)
    workspaceView.value = 'detail'
    detailTab.value = 'cases'
    editorOpen.value = false
  } finally {
    loading.value = false
  }
}

function selectVersion(version: DatasetVersion) {
  activeVersionId.value = version.id
  validationIssues.value = []
  editorOpen.value = false
  selectFirstCase(version)
}

function selectCase(item: EvaluationCase) {
  activeCaseId.value = item.id
  editedCase.value = cloneJson(item)
  editorOpen.value = true
}

function newCase(): EvaluationCase {
  return {
    id: crypto.randomUUID(),
    name: '新用例',
    category: 'positive',
    difficulty: 'medium',
    tags: [],
    notes: '',
    initial_state: {},
    turns: [{
      id: crypto.randomUUID(),
      input: { skill: 'loan_approval' },
      expected_skill: 'loan_approval',
      expectations: [],
      required_tools: [],
      forbidden_tools: [],
      policy_rules: [],
      notes: '',
    }],
  }
}

function addCase() {
  const item = newCase()
  activeCaseId.value = item.id
  editedCase.value = item
  validationIssues.value = []
  editorOpen.value = true
}

async function refreshAfterMutation(version: DatasetVersion, caseId = activeCaseId.value) {
  datasets.value = await datasetApi.list()
  versions.value = await datasetApi.versions(activeDatasetId.value)
  activeVersionId.value = version.id
  activeCaseId.value = caseId
  const current = versions.value.find(item => item.id === version.id) ?? version
  const selected = current.cases.find(item => item.id === caseId) ?? current.cases[0] ?? null
  editedCase.value = selected ? cloneJson(selected) : null
}

async function saveCase(item: EvaluationCase) {
  if (!activeDatasetId.value || !editable.value) return
  busy.value = true
  try {
    const exists = activeVersion.value?.cases.some(entry => entry.id === item.id) ?? false
    const version = exists
      ? await datasetApi.updateCase(activeDatasetId.value, item)
      : await datasetApi.addCase(activeDatasetId.value, item)
    await refreshAfterMutation(version, item.id)
    validationIssues.value = []
    editorOpen.value = false
    ElMessage.success('用例已保存到草稿')
  } catch (error) {
    showError(error, '保存用例失败')
  } finally {
    busy.value = false
  }
}

async function copyCase(item: EvaluationCase) {
  if (!editable.value) return
  const version = await datasetApi.copyCase(activeDatasetId.value, item.id)
  const copied = version.cases.find(entry => !activeVersion.value?.cases.some(old => old.id === entry.id))
  await refreshAfterMutation(version, copied?.id)
  editorOpen.value = true
  ElMessage.success('已复制用例')
}

async function removeCase(item: EvaluationCase) {
  await ElMessageBox.confirm(`删除草稿中的“${item.name}”？已发布版本不会受影响。`, '删除用例', { type: 'warning' })
  const version = await datasetApi.removeCase(activeDatasetId.value, item.id)
  activeCaseId.value = ''
  await refreshAfterMutation(version)
  ElMessage.success('用例已从草稿移除')
}

async function reorderCases(ids: string[]) {
  const version = await datasetApi.reorderCases(activeDatasetId.value, ids)
  await refreshAfterMutation(version)
}

function openCreate() {
  dialogMode.value = 'create'
  dialogSourceDatasetId.value = ''
  dialogSourceVersion.value = null
  dialogName.value = ''
  dialogDescription.value = ''
  datasetDialog.value = true
}

function openCopy(item: DatasetSummary) {
  dialogMode.value = 'copy'
  dialogSourceDatasetId.value = item.id
  dialogSourceVersion.value = item.version
  dialogName.value = `${item.name}（副本）`
  dialogDescription.value = item.description
  datasetDialog.value = true
}

async function submitDatasetDialog() {
  if (!dialogName.value.trim()) return ElMessage.warning('请输入测评集名称')
  busy.value = true
  try {
    const result = dialogMode.value === 'create'
      ? await datasetApi.create(dialogName.value, dialogDescription.value)
      : await datasetApi.copy(
          dialogSourceDatasetId.value,
          dialogName.value,
          dialogSourceVersion.value ?? undefined,
        )
    datasetDialog.value = false
    await loadDatasets(result.dataset.id)
    ElMessage.success(dialogMode.value === 'create' ? '测评集已创建' : '测评集已复制')
  } catch (error) {
    showError(error, '操作失败')
  } finally {
    busy.value = false
  }
}

async function archiveDataset(item: DatasetSummary) {
  await ElMessageBox.confirm(`归档“${item.name}”？历史版本和运行记录仍可读取。`, '归档测评集', { type: 'warning' })
  await datasetApi.archive(item.id)
  await loadDatasets('')
  ElMessage.success('测评集已归档')
}

async function createDraft(base: number|null) {
  busy.value = true
  try {
    const draft = await datasetApi.createDraft(activeDatasetId.value, base)
    await selectDataset(activeDatasetId.value, draft.id)
    editorOpen.value = editedCase.value !== null
    ElMessage.success('新版本草稿已创建')
  } catch (error) {
    showError(error, '创建草稿失败')
  } finally {
    busy.value = false
  }
}

async function discardDraft() {
  await ElMessageBox.confirm('放弃当前草稿？草稿中的修改将无法恢复。', '放弃草稿', { type: 'warning' })
  await datasetApi.discardDraft(activeDatasetId.value)
  await selectDataset(activeDatasetId.value)
  ElMessage.success('草稿已放弃')
}

async function publishDraft() {
  busy.value = true
  validationIssues.value = []
  try {
    const published = await datasetApi.publish(activeDatasetId.value)
    await selectDataset(activeDatasetId.value, published.id)
    datasets.value = await datasetApi.list()
    ElMessage.success(`已发布 v${published.version}`)
  } catch (error) {
    if (error instanceof ApiError && Array.isArray(error.detail)) {
      validationIssues.value = error.detail as ValidationIssue[]
    } else if (
      error instanceof ApiError
      && error.status === 422
      && error.detail === 'published DatasetVersion requires at least one Case'
    ) {
      validationIssues.value = [{ path: 'cases', message: '测评集至少需要一个用例' }]
    }
    showError(error, '发布失败，请检查用例')
  } finally {
    busy.value = false
  }
}

async function exportVersion(version: number) {
  const payload = await datasetApi.exportVersion(activeDatasetId.value, version)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${activeDataset.value?.name ?? 'dataset'}-v${version}.json`
  link.click()
  URL.revokeObjectURL(url)
}

function openImport() {
  importInput.value?.click()
}

function backToCatalog() {
  workspaceView.value = 'catalog'
  editorOpen.value = false
  runDialog.value = false
}

function openRunSetup(caseIds?: string[]) {
  if (activeVersion.value?.status !== 'published') {
    ElMessage.warning('只能运行已发布版本')
    return
  }
  runCaseIds.value = caseIds
  runDialog.value = true
}

async function importDataset(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const payload = JSON.parse(await file.text()) as DatasetExport
    const result = await datasetApi.importDataset(payload)
    await loadDatasets(result.dataset.id)
    ElMessage.success('测评集已导入')
  } catch (error) {
    showError(error, '导入失败')
  } finally {
    input.value = ''
  }
}

async function launchEvaluation(caseIds?: string[]) {
  if (!activeVersion.value?.version) return ElMessage.warning('只能运行已发布版本')
  if (!selectedEvaluators.value.length) return ElMessage.warning('请至少选择一个评估器')
  if (caseIds && caseIds.length === 0) return ElMessage.warning('请选择至少一个用例')
  busy.value = true
  try {
    const run = await runsApi.launch({
      version: selectedAgent.value,
      datasetId: activeDatasetId.value,
      datasetVersion: activeVersion.value.version,
      evaluatorIds: selectedEvaluators.value,
      caseIds,
    })
    runDialog.value = false
    emit('runCreated', run)
    ElMessage.success(caseIds ? '当前用例已进入队列' : '评估已进入队列')
  } catch (error) {
    showError(error, '运行评估失败')
  } finally {
    busy.value = false
  }
}

function launchSelectedCase() {
  return launchEvaluation(runCaseIds.value)
}

function showError(error: unknown, fallback: string) {
  ElMessage.error(error instanceof Error ? error.message : fallback)
}

onMounted(async () => {
  try {
    const [agents, evaluatorItems] = await Promise.all([api.versions(), api.evaluators()])
    targetVersions.value = agents
    evaluators.value = evaluatorItems
    selectedEvaluators.value = evaluatorItems.map(item => item.id)
    await loadDatasets()
  } catch (error) {
    showError(error, '无法加载测评集')
  }
})
</script>

<template>
  <section class="dataset-workspace" aria-labelledby="dataset-workspace-title">
    <div class="workspace-heading">
      <div>
        <span class="step">DATASET WORKSPACE</span>
        <h1 id="dataset-workspace-title">测评集与用例管理</h1>
        <p>维护可复用用例，发布不可变版本，并从确定版本启动评估。</p>
      </div>
      <el-button v-if="workspaceView === 'detail'" @click="backToCatalog">返回测评集列表</el-button>
    </div>

    <div v-if="workspaceView === 'catalog'" v-loading="loading">
      <DatasetList
        :items="datasets"
        :selected-id="activeDatasetId"
        :loading="loading"
        @select="selectDataset"
        @create="openCreate"
        @copy="openCopy"
        @archive="archiveDataset"
        @import="openImport"
      />
    </div>

    <div v-else-if="activeDataset" class="dataset-detail" v-loading="loading">
      <header class="dataset-detail-header">
        <div>
          <div class="dataset-detail-title">
            <h2>{{ activeDataset.name }}</h2>
            <el-tag v-if="activeVersion?.status === 'draft'" type="warning">草稿编辑中</el-tag>
            <el-tag v-else type="success" effect="plain">已发布 v{{ activeVersion?.version }}</el-tag>
          </div>
          <p>{{ activeDataset.description || '暂无描述' }}</p>
        </div>
        <div class="dataset-detail-actions">
          <el-button
            v-if="activeVersion?.status === 'published'"
            :disabled="!activeCaseId"
            @click="openRunSetup(activeCaseId ? [activeCaseId] : [])"
          >运行当前用例</el-button>
          <el-button
            v-if="activeVersion?.status === 'published'"
            type="primary"
            data-testid="open-run-dataset"
            @click="openRunSetup()"
          >运行此版本</el-button>
        </div>
      </header>

      <VersionSelector
        :versions="versions"
        :active-id="activeVersionId"
        :busy="busy"
        @select="selectVersion"
        @create-draft="createDraft"
        @publish="publishDraft"
        @discard="discardDraft"
        @export="exportVersion"
      />

      <el-alert
        v-if="validationIssues.length"
        class="validation-alert"
        title="草稿尚不能发布"
        type="error"
        :closable="false"
        show-icon
      >
        <ul><li v-for="issue in validationIssues" :key="`${issue.path}-${issue.message}`"><code>{{ issue.path }}</code>：{{ issue.message }}</li></ul>
      </el-alert>

      <nav class="dataset-detail-tabs" aria-label="测评集详情">
        <button :class="{ active: detailTab === 'cases' }" @click="detailTab = 'cases'">用例</button>
        <button :class="{ active: detailTab === 'versions' }" @click="detailTab = 'versions'">版本记录</button>
        <button :class="{ active: detailTab === 'settings' }" @click="detailTab = 'settings'">基本信息</button>
      </nav>

      <CaseTable
        v-if="detailTab === 'cases'"
        :items="activeVersion?.cases ?? []"
        :selected-id="activeCaseId"
        :editable="editable"
        @select="selectCase"
        @add="addCase"
        @copy="copyCase"
        @remove="removeCase"
        @reorder="reorderCases"
        @run="item => openRunSetup([item.id])"
      />

      <section v-else-if="detailTab === 'versions'" class="dataset-tab-content">
        <div class="tab-section-heading"><div><h3>版本记录</h3><p>已发布版本保持不变；修改内容前需创建新的草稿。</p></div></div>
        <div class="version-history">
          <button v-for="item in versions" :key="item.id" :class="{ active: item.id === activeVersionId }" @click="selectVersion(item)">
            <span><b>{{ item.status === 'draft' ? '当前草稿' : `v${item.version}` }}</b><small>{{ item.cases.length }} 个用例 · {{ new Date(item.updated_at).toLocaleString('zh-CN') }}</small></span>
            <el-tag :type="item.status === 'draft' ? 'warning' : 'success'" size="small" effect="plain">{{ item.status === 'draft' ? `基于 v${item.based_on_version ?? '空白'}` : '已发布' }}</el-tag>
          </button>
        </div>
      </section>

      <section v-else class="dataset-tab-content dataset-settings">
        <div><span>测评集 ID</span><code>{{ activeDataset.id }}</code></div>
        <div><span>当前版本</span><b>{{ activeVersion?.status === 'draft' ? '草稿' : `v${activeVersion?.version}` }}</b></div>
        <div><span>当前用例数</span><b>{{ activeVersion?.cases.length ?? 0 }}</b></div>
        <div class="dataset-settings-actions">
          <el-button @click="openCopy(activeDataset)">复制测评集</el-button>
          <el-button type="danger" plain @click="archiveDataset(activeDataset)">归档测评集</el-button>
        </div>
      </section>
    </div>

    <input ref="importInput" class="hidden-file-input" type="file" accept="application/json,.json" @change="importDataset" />

    <el-drawer v-model="editorOpen" :title="editable ? '编辑用例' : '查看用例'" size="min(860px, 96vw)" destroy-on-close>
      <CaseEditor
        :item="editedCase"
        :editable="editable"
        :saving="busy"
        :validation-issues="activeCaseIssues"
        @save="saveCase"
      />
    </el-drawer>

    <el-dialog v-model="runDialog" :title="runCaseIds ? '运行当前用例' : '运行测评集版本'" width="min(560px, 94vw)">
      <div class="run-dialog-summary">
        <b>{{ activeDataset?.name }} · v{{ activeVersion?.version }}</b>
        <span>{{ runCaseIds ? '仅运行选中的 1 个用例' : `运行全部 ${activeVersion?.cases.length ?? 0} 个用例` }}</span>
      </div>
      <el-form label-position="top">
        <el-form-item label="Agent 版本">
          <el-select v-model="selectedAgent" data-testid="dataset-agent-select" aria-label="运行 Agent 版本">
            <el-option v-for="item in targetVersions" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="评估器">
          <el-select v-model="selectedEvaluators" multiple collapse-tags aria-label="运行评估器">
            <el-option v-for="item in evaluators" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="runDialog = false">取消</el-button>
        <el-button type="primary" :loading="busy" data-testid="run-dataset-version" @click="launchSelectedCase">确认运行</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="datasetDialog" :title="dialogMode === 'create' ? '新建测评集' : '复制测评集'" width="min(460px, 92vw)">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="dialogName" data-testid="dataset-name" /></el-form-item>
        <el-form-item v-if="dialogMode === 'create'" label="描述"><el-input v-model="dialogDescription" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="datasetDialog = false">取消</el-button><el-button type="primary" :loading="busy" data-testid="submit-dataset" @click="submitDatasetDialog">确认</el-button></template>
    </el-dialog>
  </section>
</template>
