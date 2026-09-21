"""Typed views over the API's JSON payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

VideoStatus = Literal["queued", "in_progress", "completed", "failed"]

#: Statuses the server never moves away from. Polling stops here.
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})


@dataclass(frozen=True)
class VideoError:
    """The ``error`` object present on failed jobs."""

    message: str = ""
    code: str = ""

    @classmethod
    def _from_json(cls, data: Any) -> "VideoError | None":
        if not isinstance(data, dict):
            return None
        return cls(
            message=str(data.get("message") or ""),
            code=str(data.get("code") or ""),
        )


@dataclass(frozen=True)
class Video:
    """One generation job.

    The same shape is returned by create and by every poll, so a ``Video`` is
    a snapshot rather than a live handle — re-read it to see progress move.

    Despite the name the API uses ``object == "video"`` for image jobs too;
    that is the platform's convention, not a bug in this client.
    """

    id: str
    status: VideoStatus
    model: str = ""
    progress: int = 0
    created_at: int = 0
    completed_at: int | None = None
    expires_at: int | None = None
    output_url: str | None = None
    error: VideoError | None = None
    #: The untouched response body. Anything this dataclass does not model yet
    #: (new fields, model-specific extras) stays reachable here.
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_done(self) -> bool:
        """True once the server will not change this job any further."""
        return self.status in TERMINAL_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    @classmethod
    def _from_json(cls, data: dict[str, Any]) -> "Video":
        # `id` is the documented field; `task_id` is the deprecated alias kept
        # for older integrations. Prefer `id`, fall back so we keep working if
        # a response only carries the legacy name.
        ident = data.get("id") or data.get("task_id") or ""

        def _opt_int(key: str) -> int | None:
            value = data.get(key)
            return int(value) if isinstance(value, (int, float)) else None

        return cls(
            id=str(ident),
            status=str(data.get("status") or "queued"),  # type: ignore[arg-type]
            model=str(data.get("model") or ""),
            progress=int(data.get("progress") or 0),
            created_at=int(data.get("created_at") or 0),
            completed_at=_opt_int("completed_at"),
            expires_at=_opt_int("expires_at"),
            output_url=data.get("output_url") or None,
            error=VideoError._from_json(data.get("error")),
            raw=data,
        )
