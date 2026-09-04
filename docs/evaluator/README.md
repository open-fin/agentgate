# Evaluator

AgentGate evaluates a completed Case execution using two complementary methods:

```text
Case + normalized Trace
  -> structural Rule
  -> other deterministic Rules
  -> LLM Judge
  -> Hybrid
  -> Result / Metric / Gate
```

Rules verify facts that have an explicit contract. An LLM Judge assesses semantic
quality that a fixed operator cannot express. A Judge never replaces a deterministic
check for routing, tool use, arguments, state, policy, or output structure.

## Current implementation

### Evaluator contracts and execution

- `domain/evaluation.py` defines immutable Rule, LLM Judge, and Hybrid evaluator
  specifications. Prompt and rubric content are snapshotted and SHA-256 verified.
- The executor uses the stable phase order
  `structural_rule -> rule -> llm_judge -> hybrid`.
- A prerequisite is explicit and version-pinned. A failed prerequisite may skip a
  later evaluator as `NOT_APPLICABLE`; `blocking` severity alone never short-circuits
  execution.
- Evaluator definition and plan errors are validated before a Run starts.
  Evaluator/provider failures become `ERROR`, never an Agent `FAIL`.
- Results retain normalized score, verdict, reason, trace evidence, methods, and
  evaluator/Judge error evidence. Run snapshots retain evaluator definitions.

### Deterministic Rules

The default evaluator set contains rules for:

- skill routing;
- required and forbidden tools;
- tool arguments;
- final state;
- final output conditions; and
- policy compliance.

The deterministic layer is repeatable, fast, and token-free. JSON Schema is not yet
implemented: `MatchesJsonSchema` remains rejected during pre-run validation.

### LLM Judge

`judge/answer_quality.py` implements the current semantic Judge. It assesses answer
completeness and consistency with the execution, rather than repeating deterministic
checks. Its contract requires one JSON object containing a verdict (`pass`, `fail`, or
`uncertain`), score, confidence, reason, and optional violations.

Current capabilities:

- configurable prompt, rubric, provider/model reference, temperature, seed, input
  selection, score scale, output cap, timeout, sample count, and confidence threshold;
- three material selections: final output, output plus tools, or full trajectory;
- strict response parsing; malformed Judge output becomes evaluator `ERROR`;
- odd-number multi-sample voting; split or low-confidence decisions become `REVIEW`;
- prompt/rubric hashes, actual resolved model, request ID, token counts, latency,
  sample responses, and finish reason are persisted as Judge evidence;
- required PII/credential redaction before any Case or Trace material is sent to the
  Judge provider; and
- a programmable Fake Judge for offline unit tests without network calls.

There is deliberately no in-memory Judge response cache. In the current synchronous
one-evaluation-per-Case execution flow it has negligible hit rate, cannot survive a
process restart or Run retry, and cannot make historical verdicts reproducible. A
future retry/recovery feature must use persistent, Attempt-scoped completion records.

### Provider and credentials

`integrations/model_providers/openai_compatible.py` implements the current external
provider adapter. It uses bounded HTTP retries for temporary provider failures and
records no plaintext secret in domain data. The CLI resolves credential references of
the form `env:NAME`. The Web UI selects a model service and accepts its model and API
Key for one request. Known services supply their endpoint internally; only the custom
service option exposes an advanced API Base URL field. The password input is cleared
after the request and its value is never copied into a Run, Result, or SQLite record.

The provider boundary owns HTTP, authentication, timeout, retry, and usage parsing.
Prompt construction and Judge verdict parsing remain in `evaluator/judge/`.

### Hybrid

`WeightedHybridEvaluator` combines completed Rule and Judge Results using explicit
weights and a pass threshold. It preserves `ERROR` and `REVIEW` conservatively rather
than averaging them into a confident score. It is implemented but is not part of the
default evaluator set and has no evaluator-management UI yet.

### Demo and UI

The in-process Python loan demo has five independently runnable Cases covering loan approval, repayment-plan
generation, complaint intake, and credit inquiry. One target version takes the correct
high-risk action but makes a misleading customer-facing statement. Rules pass while a
real semantic Judge can fail it, demonstrating the intended Judge boundary. Selecting
an LLM Judge requires a configured real model service. The UI accepts its service,
model, and request-scoped API Key, and shows Judge model, votes, token usage, prompt/rubric
hashes, and error evidence. No HTTP Target is included in this demo.

## Deliberate boundaries

- `evaluator/` does not execute the Agent, persist Results, aggregate Metrics, or make
  Gate decisions.
- `integrations/model_providers/` does not contain prompts, rubrics, or verdict logic.
- `trace/redaction.py` protects Judge egress. It is not yet the complete UI/API trace
  data-protection policy.
- A Judge is an assistive semantic evaluator, not a replacement for domain-expert
  calibration or human review.

## Planned work

### Next: production safety and correctness

1. Redact or enforce access controls for Trace/Result API and UI output, not only
   Judge-provider egress.
2. Add Judge preflight validation for a composed provider/client and enforce a total
   evaluator deadline across samples and provider retries.
3. Add prompt-injection/adversarial-trace tests and label Agent-produced material as
   untrusted in Judge prompts.
4. Add provider capabilities for strict schema structured output while retaining local
   contract validation.
5. Define retention/redaction rules for raw Judge responses and sample responses.

### Evaluation quality and reproducibility

1. Build a domain-expert-labelled calibration set and report Judge-to-human agreement,
   disagreement, and review rates.
2. Add few-shot calibration examples, prompt/model regression suites, and periodic
   human review of high-cost or uncertain decisions.
3. Persist Judge completions by Run/Attempt/evaluator/turn/sample plus request hash,
   so recovery reuses already completed calls without creating a cross-Run global cache.
4. Pin concrete provider deployment/model versions and retain non-secret provider
   configuration needed to audit a verdict.
5. Add optional cross-model/pairwise judging and bias monitoring only after the
   single-Judge calibration baseline exists.

### Product capabilities

1. Implement JSON Schema Draft 2020-12 evaluation with safe local references and
   bounded diagnostics.
2. Implement evaluator CRUD, immutable publish/disable lifecycle, evaluator version
   selection, and management UI.
3. Implement encrypted, tenant-scoped private credential storage, RBAC, rotation, and
   audit logs. Environment variables remain POC-only.
4. Add asynchronous/distributed evaluator workers, concurrency and cost budgets,
   cancellation, retry/recovery, and trace-completeness coordination.
5. Add artifact and multimodal Judges, semantic trajectory evaluation, external
   evaluator adapters, and evaluation comparison/regression workflows.

## Verification

```bash
.venv/bin/python -m pytest -q
cd web && npm run typecheck
```

The Judge path has focused tests for phase ordering, prerequisites, contract failures,
provider retries, credential references, redaction, sampling/voting, evidence, and
snapshot provenance.

## Run the loan demo with a real Judge

Configure an OpenAI-compatible provider and select its credential catalogue ID:

```bash
read -s "AGENTGATE_JUDGE_API_KEY?Judge API Key: "
echo
export AGENTGATE_JUDGE_API_KEY
export AGENTGATE_JUDGE_ENDPOINT=https://api.deepseek.com/chat/completions
export AGENTGATE_JUDGE_MODEL=deepseek-v4-pro

agentgate evaluate --version loan-agent-v3-misleading \
  --judge-credential public --database ./agentgate.db
```

The CLI uses the selected credential reference. In the Web UI, select DeepSeek or
OpenAI and enter the model and API Key; a Base URL is required only for a custom
OpenAI-compatible service. Runs may select one or more Cases. Runs that select only
Rule evaluators do not require any Judge model configuration.
