import type {
  DatasetSummary, DatasetVersion, EvaluationCase, JsonObject,
} from '../types/dataset'

export interface Version { id: string; label: string }
export type DatasetOption = DatasetSummary
export type EvaluatorKind = 'rule'|'llm_judge'|'hybrid'
export type ExecutionPhase = 'structural_rule'|'rule'|'llm_judge'|'hybrid'
export interface PrerequisiteSummary {
  evaluator_id: string
  policy: 'on_pass'|'on_pass_or_review'|'always'
}
export interface JudgeSummary {
  provider: string
  model: string
  samples: number
  input_selection: string
  credential_ref: string|null
}
export interface EvaluatorOption {
  id: string
  name: string
  kind: EvaluatorKind
  version: string
  dimension: string
  metric: string
  severity: 'standard'|'blocking'
  execution_phase: ExecutionPhase
  evaluator_type: string
  operator: string|null
  prerequisites: PrerequisiteSummary[]
  judge: JudgeSummary|null
}
export interface JudgeProviderInput {
  provider: 'deepseek'|'openai'|'custom'
  model: string
  api_key: string
  base_url?: string|null
}
export interface Run {
  id: string
  status: string
  snapshot: {
    target: { version: string }
    dataset: DatasetVersion
    selected_case_ids: string[]
    evaluator_specs: EvaluatorOption[]
  }
}
export interface Evidence { trace_id: string; span_ids: string[]; description: string }
export type Outcome = 'pass'|'fail'|'review'|'not_applicable'|'error'
export interface CheckResult {
  id: string
  name: string
  turn_id: string|null
  expectation_id: string|null
  outcome: Outcome
  score: number|null
  reason: string
  expected: unknown
  actual: unknown
  actual_missing: boolean
  evidence: Evidence[]
}
export interface JudgeEvidence {
  requested_model: string
  resolved_model: string|null
  prompt_sha256: string
  rubric_sha256: string
  raw_response: string
  request_id: string|null
  input_tokens: number|null
  output_tokens: number|null
  latency_ms: number|null
  samples: number
  votes: Record<string, number>
  sample_responses: string[]
  finish_reason: string|null
  truncated: boolean
  attempt_count: number
}
export interface ErrorEvidence {
  category: 'crash'|'timeout'|'invalid_output'
  exception_type: string
  message: string
  retryable: boolean
}
export interface Result {
  case_id: string
  evaluator_id: string
  evaluator_name: string
  evaluator_kind: EvaluatorKind
  dimension: string
  metric: string
  severity: 'standard'|'blocking'
  outcome: Outcome
  score: number|null
  reason: string
  primary_failure_step?: string
  evidence: Evidence[]
  checks: CheckResult[]
  judge_evidence: JudgeEvidence|null
  error_evidence: ErrorEvidence|null
}
export interface Gate {
  outcome: 'pass'|'fail'
  passed: number
  failed: number
  reviewed: number
  not_applicable: number
  errors: number
  score: number|null
  threshold: number
  reason: string
}
export interface Metric {
  key: string
  label: string
  level: 'overall'|'kind'|'dimension'|'metric'
  score: number|null
  passed: number
  failed: number
  reviewed: number
  not_applicable: number
  errors: number
  applicable: number
  total: number
  incomplete: boolean
}
export interface Report { run: Run; results: Result[]; gate: Gate; metrics: Metric[] }
export interface TraceTurn {
  turn_id: string
  input: JsonObject
  output: JsonObject
  state: JsonObject
}
export interface Trace {
  case_id: string
  spans: {
    id: string
    name: string
    kind: string
    sequence: number
    attributes: Record<string, unknown>
  }[]
  turns: TraceTurn[]
  final_state: Record<string, unknown>
  final_output: Record<string, unknown>
}
export interface Overview {
  total_runs: number
  completed_runs: number
  case_count: number
  latest: Report|null
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    const fallback = status >= 500
      ? '服务端执行失败，请查看启动终端中的错误日志'
      : `请求失败（HTTP ${status}）`
    super(
      Array.isArray(detail)
        ? detail.map(item => item?.message ?? JSON.stringify(item)).join('；')
        : typeof detail === 'string' && detail !== `HTTP ${status}`
          ? detail
          : fallback
    )
    this.status = status
    this.detail = detail
  }
}

export const request = async <T>(url: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(url, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }))
    throw new ApiError(response.status, payload.detail)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const api = {
  overview: () => request<Overview>('/api/overview'),
  versions: () => request<Version[]>('/api/versions'),
  datasets: () => request<DatasetSummary[]>('/api/datasets'),
  evaluators: () => request<EvaluatorOption[]>('/api/evaluators'),
  runs: () => request<Run[]>('/api/runs'),
  launch: (
    version: string,
    datasetId: string,
    datasetVersion: number,
    evaluatorIds: string[],
    judgeProvider: JudgeProviderInput|null = null,
    caseIds: string[]|null = null,
  ) => request<Run>('/api/evaluations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      version,
      dataset_id: datasetId,
      dataset_version: datasetVersion,
      evaluator_ids: evaluatorIds,
      judge_provider: judgeProvider,
      case_ids: caseIds,
    }),
  }),
  report: (id: string) => request<Report>(`/api/runs/${id}`),
  trace: (runId: string, caseId: string) =>
    request<Trace>(`/api/runs/${runId}/traces/${caseId}`),
}

export type { DatasetSummary, DatasetVersion, EvaluationCase }
