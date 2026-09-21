"""Exceptions raised by the GenRelay client.

Every failure mode gets its own class so callers can react without parsing
strings: a 402 means "top up", a 429 means "back off", a failed job means
"the prompt or the model choice is the problem". Catching ``GenRelayError``
catches all of them.
"""

from __future__ import annotations

from typing import Any


class GenRelayError(Exception):
    """Base class for everything this library raises."""


class APIError(GenRelayError):
    """The API returned a non-2xx response.

    ``status`` is the HTTP status, ``code`` the machine-readable error code
    when the response carried one, and ``body`` the decoded payload (or the
    raw text when it was not JSON).
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - trivial
        parts = [super().__str__()]
        if self.status is not None:
            parts.append(f"(HTTP {self.status}")
            parts[-1] += f", code={self.code})" if self.code else ")"
        return " ".join(parts)


class AuthenticationError(APIError):
    """401 — the API key is missing, malformed, or revoked."""


class InsufficientCreditsError(APIError):
    """402 — the account is out of credits.

    Generation is pay-per-call, so this is an ordinary, expected outcome
    rather than a bug. Surface it to the user and let them top up.
    """


class RateLimitError(APIError):
    """429 — too many requests. Retry after a delay."""


class JobFailedError(GenRelayError):
    """The job was accepted but finished with ``status == "failed"``.

    This is not a transport error: the request was valid and billed-or-not per
    platform rules, but the upstream model could not produce a result. The
    failed :class:`~genrelay.types.Video` is attached as ``video`` so callers
    can inspect ``video.error`` and ``video.model``.
    """

    def __init__(self, message: str, *, video: Any = None) -> None:
        super().__init__(message)
        self.video = video


class JobTimeout(GenRelayError):
    """The job did not reach a terminal state within ``timeout`` seconds.

    The job itself keeps running server-side — the task id is attached as
    ``task_id`` so it can be polled again later instead of being resubmitted
    (resubmitting bills a second time).
    """

    def __init__(self, message: str, *, task_id: str | None = None) -> None:
        super().__init__(message)
        self.task_id = task_id
