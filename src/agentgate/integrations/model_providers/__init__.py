"""Judge-model access.

Every client here implements `evaluator/judge/model_protocol.py`. Application
composition picks the provider and a `credential_ref`; a Run records the
reference and never the secret.
"""

from .credentials import (
    SUPPORTED_SCHEMES, CredentialResolver, EnvCredentialResolver, split_ref,
)
from .fake import FakeJudgeModel, always_fail, request_fingerprint
from .openai_compatible import OpenAICompatibleJudgeModel

__all__ = [
    "SUPPORTED_SCHEMES", "CredentialResolver", "EnvCredentialResolver",
    "FakeJudgeModel", "OpenAICompatibleJudgeModel", "always_fail",
    "request_fingerprint", "split_ref",
]
