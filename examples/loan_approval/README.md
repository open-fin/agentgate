# Loan Agent Demo

The in-process Python `LoanAgent` demo covers five cases across four skills:

- high-risk loan approval requiring human review;
- low-risk direct approval;
- repayment-plan generation;
- complaint intake; and
- standalone credit inquiry.

The demo should show:

- business policy validation
- required and forbidden tool calls
- tool argument constraints
- final state assertions
- release gate decision

The target behavior is deterministic, while the selected LLM Judge is a real
OpenAI-compatible provider. Configure a provider endpoint, model, and credential
reference before running. For DeepSeek V4:

```bash
read -s "AGENTGATE_JUDGE_API_KEY?DeepSeek API Key: "
echo
export AGENTGATE_JUDGE_API_KEY
export AGENTGATE_JUDGE_ENDPOINT=https://api.deepseek.com/chat/completions
export AGENTGATE_JUDGE_MODEL=deepseek-v4-pro

agentgate evaluate --version loan-agent-v1-risky \
  --judge-credential public --database ./agentgate.db
agentgate evaluate --version loan-agent-v2-fixed \
  --judge-credential public --database ./agentgate.db
```

The available target versions are:

- `loan-agent-v1-risky`: incorrectly approves the high-risk application;
- `loan-agent-v2-fixed`: correctly sends it to human review; and
- `loan-agent-v3-misleading`: takes the correct action but falsely tells the
  customer the application was approved. This is the main semantic Judge scenario.

All target versions execute locally through the Python `LoanAgent`; this demo does
not require or configure an HTTP Target.

For the Web UI, select the Cases to run and enable `answer-quality`, then choose a
model service and enter its model and API Key. DeepSeek and OpenAI use built-in
endpoints; only a custom OpenAI-compatible service asks for an API Base URL.
