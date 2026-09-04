<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, type DatasetOption, type EvaluatorKind, type EvaluatorOption, type Overview, type Report, type Run, type Trace, type Version } from './api/client'
import DatasetWorkspace from './pages/DatasetWorkspace.vue'
import { includeEvaluatorPrerequisites } from './state/evaluators'
import { useJudgeProviderState } from './state/judgeProvider'

const overview = ref<Overview>({ total_runs: 0, completed_runs: 0, case_count: 0, latest: null })
const versions = ref<Version[]>([])
const datasets = ref<DatasetOption[]>([])
const evaluators = ref<EvaluatorOption[]>([])
const runs = ref<Run[]>([])
const selectedVersion = ref('loan-agent-v2-fixed')
const selectedDataset = ref('loan-agent-demo')
const selectedCaseIds = ref<string[]>([])
const selectedEvaluators = ref<string[]>([])
const { judgeService, judgeModel, judgeApiKey, judgeBaseUrl } = useJudgeProviderState()
const report = ref<Report|null>(null)
const trace = ref<Trace|null>(null)
const loading = ref(false)
const traceOpen = ref(false)
const page = ref<'evaluate'|'datasets'>(location.pathname.startsWith('/datasets') ? 'datasets' : 'evaluate')

const caseNames = computed(() => Object.fromEntries((report.value?.run.snapshot.dataset.cases ?? []).map(c => [c.id, c.name])))
const failed = computed(() => report.value?.results.filter(item => item.outcome === 'fail') ?? [])
const selectedAgent = computed(() => versions.value.find(item => item.id === selectedVersion.value))
const selectedDatasetInfo = computed(() => datasets.value.find(item => item.id === selectedDataset.value))
const kindsInUse = computed(() => new Set(
  evaluators.value.filter(item => selectedEvaluators.value.includes(item.id)).map(item => item.kind)
))
const judgeSelected = computed(() => kindsInUse.value.has('llm_judge'))
const judgeProviderReady = computed(() =>
  Boolean(
    judgeModel.value.trim()
    && judgeApiKey.value
    && (judgeService.value !== 'custom' || judgeBaseUrl.value.trim()),
  ),
)
const evaluatorById = computed(() => Object.fromEntries(evaluators.value.map(item => [item.id, item])))

async function refresh() {
  const [summary, targetVersions, datasetOptions, evaluatorOptions, recentRuns] = await Promise.all([
    api.overview(), api.versions(), api.datasets(), api.evaluators(), api.runs(),
  ])
  overview.value = summary
  versions.value = targetVersions
  datasets.value = datasetOptions
  evaluators.value = evaluatorOptions
  runs.value = recentRuns
  const availableCaseIds = new Set(selectedDatasetInfo.value?.cases.map(item => item.id) ?? [])
  selectedCaseIds.value = selectedCaseIds.value.filter(id => availableCaseIds.has(id))
  if (selectedCaseIds.value.length === 0) {
    selectedCaseIds.value = [...availableCaseIds]
  }
  if (selectedEvaluators.value.length === 0) selectedEvaluators.value = evaluatorOptions.map(item => item.id)
  if (!report.value && summary.latest) report.value = summary.latest
}

async function launch() {
  if (selectedEvaluators.value.length === 0) return ElMessage.warning('请至少选择一个评估器')
  if (selectedCaseIds.value.length === 0) return ElMessage.warning('请至少选择一个 Case')
  if (selectedDatasetInfo.value?.version == null) return ElMessage.warning('请选择已有发布版本的测评集')
  if (judgeSelected.value && !judgeProviderReady.value) return ElMessage.warning('请填写完整的 Judge 模型配置')
  loading.value = true
  try {
    const run = await api.launch(
      selectedVersion.value,
      selectedDataset.value,
      selectedDatasetInfo.value.version,
      selectedEvaluators.value,
      judgeSelected.value ? {
        provider: judgeService.value,
        model: judgeModel.value.trim(),
        api_key: judgeApiKey.value,
        base_url: judgeService.value === 'custom' ? judgeBaseUrl.value.trim() : null,
      } : null,
      selectedCaseIds.value,
    )
    report.value = await api.report(run.id)
    await refresh()
    document.querySelector('#result-report')?.scrollIntoView({ behavior: 'smooth' })
    ElMessage.success('评估已完成，指标与证据已持久化')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '评估失败')
  } finally {
    loading.value = false
  }
}

function normalizeEvaluatorSelection(ids: string[]) {
  const normalized = includeEvaluatorPrerequisites(ids, evaluators.value)
  selectedEvaluators.value = normalized.ids
  if (normalized.added.length) {
    const names = normalized.added.map(id => evaluatorById.value[id]?.name ?? id)
    ElMessage.info(`已自动选择前置评估器：${names.join('、')}`)
  }
}

function selectDatasetCases() {
  selectedCaseIds.value = selectedDatasetInfo.value?.cases.map(item => item.id) ?? []
}

function selectJudgeService() {
  if (judgeService.value === 'deepseek') judgeModel.value = 'deepseek-v4-pro'
  else if (judgeService.value === 'openai') judgeModel.value = 'gpt-5-mini'
  else judgeModel.value = ''
}

function pasteJudgeApiKey(event: ClipboardEvent) {
  const value = event.clipboardData?.getData('text')
  if (value === undefined) return
  event.preventDefault()
  judgeApiKey.value = value.trim()
}

async function openRun(id: string) { report.value = await api.report(id); trace.value = null }
async function openTrace(caseId: string) { if (!report.value) return; trace.value = await api.trace(report.value.run.id, caseId); traceOpen.value = true }
function navigate(next: 'evaluate'|'datasets') {
  page.value = next
  const path = next === 'datasets' ? '/datasets' : '/'
  if (location.pathname !== path) history.pushState({}, '', path)
}
function onPopState() { page.value = location.pathname.startsWith('/datasets') ? 'datasets' : 'evaluate' }
async function showCreatedRun(run: Run) {
  await openRun(run.id)
  await refresh()
  navigate('evaluate')
  requestAnimationFrame(() => document.querySelector('#result-report')?.scrollIntoView({ behavior: 'smooth' }))
}
const asPercent = (score: number|null) => score === null ? 'N/A' : `${Math.round(score * 100)}%`
const outcomeText = { pass: '通过', fail: '失败', review: '待复核', not_applicable: '不适用', error: '评估错误' }
const outcomeType = (outcome: string) => outcome === 'pass' ? 'success' : outcome === 'not_applicable' ? 'info' : outcome === 'review' ? 'warning' : 'danger'
const kindText: Record<EvaluatorKind, string> = { rule: '规则评估器', llm_judge: 'LLM 评估器', hybrid: '复合评估器' }
const policyText: Record<string, string> = { on_pass: '前置通过时执行', on_pass_or_review: '前置通过或待复核时执行', always: '始终执行' }
/** Vote distribution as "pass 2 · fail 1", so a split decision stays visible. */
const voteText = (votes: Record<string, number>) =>
  Object.entries(votes).map(([label, count]) => `${outcomeText[label as keyof typeof outcomeText] ?? label} ${count}`).join(' · ')

onMounted(() => {
  window.addEventListener('popstate', onPopState)
  refresh().catch(error => ElMessage.error(`无法连接后端：${error.message}`))
})
onUnmounted(() => window.removeEventListener('popstate', onPopState))
</script>

<template>
  <div class="shell">
    <header>
      <div><p class="eyebrow">AGENT QUALITY GATE</p><h1>AgentGate 评估台</h1><p>配置评估对象，运行用例，并用可追溯指标判断是否达到发布门槛。</p></div>
      <div class="header-actions">
        <el-tag effect="dark" type="success">P1 演示</el-tag>
        <nav aria-label="主导航">
          <button :class="{ active: page === 'evaluate' }" data-testid="nav-evaluate" @click="navigate('evaluate')">评估运行</button>
          <button :class="{ active: page === 'datasets' }" data-testid="nav-datasets" @click="navigate('datasets')">测评集管理</button>
        </nav>
      </div>
    </header>

    <main v-if="page === 'evaluate'">
      <section class="region config-region" aria-labelledby="config-title">
        <div class="region-heading"><div><span class="step">01 · EVALUATION SETUP</span><h2 id="config-title">评估配置</h2><p>选择 Agent、数据集与评估器，然后启动一次真实评估。</p></div><div class="run-count">已完成 {{ overview.completed_runs }} 次运行</div></div>

        <div class="config-grid">
          <article class="config-card">
            <div class="card-index">A</div><label>Agent</label>
            <el-select v-model="selectedVersion" data-testid="agent-select" aria-label="Agent 版本">
              <el-option v-for="item in versions" :key="item.id" :label="`${item.label} · ${item.id}`" :value="item.id" />
            </el-select>
            <p>{{ selectedAgent?.label }}，使用确定性 Provider 执行。</p>
          </article>

          <article class="config-card">
            <div class="card-index">D</div><label>Dataset</label>
            <el-select v-model="selectedDataset" data-testid="dataset-select" aria-label="数据集" @change="selectDatasetCases">
              <el-option v-for="item in datasets" :key="item.id" :label="`${item.name} · v${item.version}`" :value="item.id" />
            </el-select>
            <p>{{ selectedDatasetInfo?.description }} · {{ selectedDatasetInfo?.case_count ?? 0 }} 个用例</p>
            <label class="case-select-label">Cases</label>
            <el-checkbox-group v-model="selectedCaseIds" class="case-select-list" aria-label="运行用例">
              <el-checkbox v-for="item in selectedDatasetInfo?.cases ?? []" :key="item.id" :value="item.id">
                {{ item.name }}
              </el-checkbox>
            </el-checkbox-group>
          </article>

          <article class="config-card evaluator-card">
            <div class="card-index">E</div><label>Evaluators & Metrics</label>
            <div class="evaluator-kinds" aria-label="评估器分类">
              <span v-for="kind in (['rule','llm_judge','hybrid'] as EvaluatorKind[])" :key="kind" :class="{ 'active-kind': kindsInUse.has(kind) }">
                {{ kindText[kind] }}<template v-if="!evaluators.some(item => item.kind === kind)"> · 未配置</template>
              </span>
            </div>
            <el-checkbox-group v-model="selectedEvaluators" class="evaluator-list" @change="normalizeEvaluatorSelection">
              <el-checkbox v-for="item in evaluators" :key="item.id" :value="item.id" border>
                <span class="eval-name">
                  {{ item.name }}
                  <el-tag v-if="item.kind !== 'rule'" size="small" type="warning" effect="plain">{{ kindText[item.kind] }}</el-tag>
                </span>
                <small>
                  {{ item.metric }} · {{ item.dimension }}
                  <template v-for="ref in item.prerequisites" :key="ref.evaluator_id">
                    · 依赖 {{ evaluatorById[ref.evaluator_id]?.name ?? ref.evaluator_id }}（{{ policyText[ref.policy] }}）
                  </template>
                </small>
              </el-checkbox>
            </el-checkbox-group>
            <div v-if="judgeSelected" class="judge-key" data-testid="judge-provider">
              <label>Judge 模型配置</label>
              <div class="judge-provider-fields">
                <el-select v-model="judgeService" aria-label="模型服务商" @change="selectJudgeService">
                  <el-option label="DeepSeek" value="deepseek" />
                  <el-option label="OpenAI" value="openai" />
                  <el-option label="自定义服务" value="custom" />
                </el-select>
                <el-input v-model="judgeModel" aria-label="Judge Model" placeholder="模型名称" />
                <input
                  v-model="judgeApiKey"
                  class="judge-secret-input"
                  type="password"
                  autocomplete="new-password"
                  aria-label="Judge API Key"
                  placeholder="API Key"
                  @paste="pasteJudgeApiKey"
                />
                <el-input v-if="judgeService === 'custom'" v-model="judgeBaseUrl" aria-label="API Base URL" placeholder="API Base URL，例如 https://host/v1" />
              </div>
            </div>
          </article>
        </div>

        <div class="launch-bar">
          <div><b>{{ selectedEvaluators.length }}</b> 个评估器已启用 <span>· 结果将写入 SQLite</span></div>
          <el-button type="primary" size="large" :loading="loading" :disabled="selectedEvaluators.length === 0 || (judgeSelected && !judgeProviderReady)" @click="launch">运行评估 <span>→</span></el-button>
        </div>
      </section>

      <section id="result-report" class="region report-region" aria-labelledby="report-title">
        <div class="region-heading report-heading">
          <div><span class="step">02 · RESULT REPORT</span><h2 id="report-title">结果报告</h2><p v-if="report">{{ report.run.snapshot.target.version }} · {{ report.run.snapshot.dataset.dataset_name }} v{{ report.run.snapshot.dataset.version }}</p><p v-else>运行评估后在此查看指标、失败证据和轨迹。</p></div>
          <el-tag v-if="report" :type="report.gate.outcome === 'pass' ? 'success' : 'danger'" effect="dark" size="large">{{ report.gate.outcome === 'pass' ? '发布门槛通过' : '发布门槛未通过' }}</el-tag>
        </div>

        <template v-if="report">
          <div class="metric-grid" aria-label="评估指标">
            <article v-for="metric in report.metrics" :key="`${metric.level}-${metric.key}`" class="metric-card" :data-testid="`metric-${metric.level}-${metric.key}`">
              <span>{{ metric.label }} · {{ metric.level }}</span><strong>{{ asPercent(metric.score) }}</strong>
              <el-progress :percentage="Math.round((metric.score ?? 0) * 100)" :show-text="false" :stroke-width="7" :color="(metric.score ?? 0) >= .95 ? '#20b486' : '#e85d75'" />
              <small>{{ metric.passed }} 通过 · {{ metric.failed }} 失败 · {{ metric.not_applicable }} 不适用<span v-if="metric.errors"> · {{ metric.errors }} 错误</span></small>
            </article>
            <article class="metric-card gate-card"><span>发布门槛</span><strong>{{ Math.round(report.gate.threshold * 100) }}%</strong><small>{{ report.gate.reason }}</small></article>
          </div>

          <div class="report-grid">
            <article class="report-panel">
              <div class="panel-title"><h3>全部检查结果</h3><el-tag type="danger" plain>{{ failed.length }} 项失败</el-tag></div>
              <div v-for="item in report.results" :key="`${item.case_id}-${item.evaluator_id}`" class="result-item">
                <div class="result-head">
                  <span><b>{{ caseNames[item.case_id] }} · {{ item.evaluator_name }}</b><small>{{ item.reason }}</small></span>
                  <el-tag :type="outcomeType(item.outcome)" size="small">{{ outcomeText[item.outcome] }}</el-tag>
                </div>
                <ul v-if="item.checks.length" class="check-list">
                  <li v-for="check in item.checks" :key="check.id">
                    <span>
                      {{ check.name }} · {{ check.reason }}
                      <small v-if="check.expected !== null || check.actual !== null" class="expected-actual">期望 {{ JSON.stringify(check.expected) }} · 实际 {{ check.actual_missing ? '字段不存在' : JSON.stringify(check.actual) }}</small>
                    </span>
                    <el-tag :type="outcomeType(check.outcome)" size="small" effect="plain">{{ outcomeText[check.outcome] }}</el-tag>
                  </li>
                </ul>
                <div v-if="item.judge_evidence" class="judge-evidence" :data-testid="`judge-evidence-${item.evaluator_id}`">
                  <span>模型 {{ item.judge_evidence.resolved_model ?? item.judge_evidence.requested_model }}</span>
                  <span>评审 {{ item.judge_evidence.samples }} 次 · {{ voteText(item.judge_evidence.votes) }}</span>
                  <span v-if="item.judge_evidence.truncated" class="judge-warn">输出被截断</span>
                  <span v-if="item.judge_evidence.input_tokens !== null">Token {{ item.judge_evidence.input_tokens }}/{{ item.judge_evidence.output_tokens }}</span>
                  <span>Prompt {{ item.judge_evidence.prompt_sha256.slice(0, 8) }} · Rubric {{ item.judge_evidence.rubric_sha256.slice(0, 8) }}</span>
                </div>
                <div v-if="item.error_evidence" class="judge-evidence judge-warn" :data-testid="`error-evidence-${item.evaluator_id}`">
                  <span>评估器未能完成检查（{{ item.error_evidence.category }}）</span>
                  <span v-if="item.error_evidence.retryable">可重试</span>
                </div>
                <button v-if="item.outcome === 'fail'" class="trace-link" @click="openTrace(item.case_id)">查看失败轨迹 →</button>
              </div>
            </article>

            <article class="report-panel">
              <div class="panel-title"><h3>最近运行</h3><span>{{ runs.length }} 条</span></div>
              <el-table :data="runs" empty-text="暂无运行" size="small">
                <el-table-column label="Agent" min-width="190"><template #default="scope">{{ scope.row.snapshot.target.version }}</template></el-table-column>
                <el-table-column prop="status" label="状态" width="95" />
                <el-table-column label="操作" width="70"><template #default="scope"><el-button link type="primary" @click="openRun(scope.row.id)">查看</el-button></template></el-table-column>
              </el-table>
            </article>
          </div>
        </template>
        <el-empty v-else description="尚无结果，请先在上方运行评估" />
      </section>
    </main>
    <main v-else class="dataset-main"><DatasetWorkspace @run-created="showCreatedRun" /></main>

    <el-drawer v-model="traceOpen" title="失败用例轨迹" size="min(520px, 92vw)">
      <template v-if="trace">
        <p class="trace-case">{{ caseNames[trace.case_id] }}</p>
        <div v-if="trace.turns.length" class="trace-turns">
          <h3>各轮输入与输出</h3>
          <el-card v-for="(turn, index) in trace.turns" :key="turn.turn_id" shadow="never">
            <b>第 {{ index + 1 }} 轮 · {{ turn.turn_id }}</b>
            <small>输入</small><pre>{{ JSON.stringify(turn.input, null, 2) }}</pre>
            <small>输出</small><pre>{{ JSON.stringify(turn.output, null, 2) }}</pre>
            <small>轮次结束状态</small><pre>{{ JSON.stringify(turn.state, null, 2) }}</pre>
          </el-card>
        </div>
        <h3>执行轨迹</h3>
        <el-timeline><el-timeline-item v-for="span in trace.spans" :key="span.id" :timestamp="`步骤 ${span.sequence}`" placement="top"><el-card shadow="never"><b>{{ span.name }}</b><el-tag size="small">{{ span.kind }}</el-tag><small v-if="span.attributes.turn_id">轮次 {{ span.attributes.turn_id }}</small><pre>{{ JSON.stringify(span.attributes, null, 2) }}</pre></el-card></el-timeline-item></el-timeline>
        <h3>最终状态</h3><pre>{{ JSON.stringify(trace.final_state, null, 2) }}</pre>
        <h3>最终输出</h3><pre>{{ JSON.stringify(trace.final_output, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>
