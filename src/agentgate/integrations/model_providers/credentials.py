"""Resolve a `credential_ref` into a secret without ever persisting the secret.

Run data records the reference, never the value. A reference is scheme
qualified so that a production secret service can be added later without
changing the meaning of existing references:

```text
env:AGENTGATE_JUDGE_API_KEY     read from the process environment (POC)
```

Nothing in this module returns a secret through `__repr__`, an exception
message, or a log record. `is_available()` exists so pre-run plan validation can
prove a reference resolves without reading, copying, or exposing its value.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from agentgate.evaluator.judge import CredentialUnavailable

ENV_SCHEME = "env"
SUPPORTED_SCHEMES = (ENV_SCHEME,)


def split_ref(credential_ref: str) -> tuple[str, str]:
    """Split `scheme:name`, rejecting unknown or malformed references."""
    scheme, separator, name = credential_ref.partition(":")
    if not separator or not scheme or not name:
        raise CredentialUnavailable(
            f"credential_ref must look like 'scheme:name'; got {credential_ref!r}"
        )
    if scheme not in SUPPORTED_SCHEMES:
        raise CredentialUnavailable(
            f"unsupported credential scheme {scheme!r}; "
            f"supported: {', '.join(SUPPORTED_SCHEMES)}"
        )
    return scheme, name


@runtime_checkable
class CredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> str: ...

    def is_available(self, credential_ref: str) -> bool: ...


class EnvCredentialResolver:
    """POC resolver backed by environment variables."""

    def resolve(self, credential_ref: str) -> str:
        _, name = split_ref(credential_ref)
        secret = os.environ.get(name)
        if not secret:
            # The name is safe to report; the value is not, and there is none.
            raise CredentialUnavailable(
                f"environment variable {name} is unset or empty"
            )
        return secret

    def is_available(self, credential_ref: str) -> bool:
        """Report resolvability for pre-run validation without exposing a value.

        A malformed or unsupported reference still raises. That is a mistake in
        the evaluator definition, not a missing secret, and reporting it as
        "credential not configured" would send an operator hunting for a key
        that was never the problem.
        """
        _, name = split_ref(credential_ref)
        return bool(os.environ.get(name))

    def __repr__(self) -> str:
        return "EnvCredentialResolver()"
