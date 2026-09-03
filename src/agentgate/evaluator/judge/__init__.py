"""LLM Judge evaluation.

Model access arrives through `EvaluationContext`, never by importing a provider:
`evaluator/` must stay runnable, testable, and offline without `integrations/`.
"""

from .answer_quality import AnswerQualityJudge, JudgeNotConfigured, decide
from .contract import (
    FAIL, MAX_REASON_CHARS, MAX_VIOLATIONS, PASS, UNCERTAIN, VERDICTS,
    JudgeContractError, Verdict, Violation, parse_verdict, response_instructions,
)
from .model_protocol import (
    CredentialChecker, CredentialUnavailable, JudgeModelClient, JudgeModelError,
    JudgeModelInvalidResponse, JudgeModelTimeout, JudgeModelUnavailable,
    JudgeRequest, JudgeResponse, ResponseFormat, request_fingerprint,
)
from .prompt import build_judge_request, select_material, truncate

__all__ = [
    "FAIL", "MAX_REASON_CHARS", "MAX_VIOLATIONS", "PASS", "UNCERTAIN", "VERDICTS",
    "AnswerQualityJudge", "CredentialChecker", "CredentialUnavailable",
    "JudgeContractError", "JudgeModelClient", "JudgeModelError",
    "JudgeModelInvalidResponse", "JudgeModelTimeout", "JudgeModelUnavailable",
    "JudgeNotConfigured", "JudgeRequest", "JudgeResponse", "ResponseFormat",
    "Verdict", "Violation", "build_judge_request", "decide",
    "parse_verdict", "request_fingerprint", "response_instructions",
    "select_material", "truncate",
]
