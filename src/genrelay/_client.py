"""HTTP client for the GenRelay generation API."""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import httpx

from .errors import (
    APIError,
    AuthenticationError,
    InsufficientCreditsError,
    JobFailedError,
    JobTimeout,
    RateLimitError,
)
from .types import Video

__all__ = ["GenRelay", "Videos"]

DEFAULT_BASE_URL = "https://genrelay.ai/v1"

# Generation is slow by nature — a 1080p Veo clip regularly takes minutes.
# These bound the *HTTP* calls, not the job: a job outliving the request is
# normal and is what polling is for.
DEFAULT_TIMEOUT = 60.0
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_MAX_WAIT = 900.0


def _user_agent(version: str) -> str:
    return f"genrelay-python/{version}"


class Videos:
    """Generation jobs — video *and* image (the API models both as "videos")."""

    def __init__(self, client: "GenRelay") -> None:
        self._client = client

    # ---------------------------------------------------------------- create

    def create(
        self,
        *,
        model: str,
        prompt: str,
        seconds: int | str | None = None,
        size: str | None = None,
        tier: str | None = None,
        reference_images: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        **extra: Any,
    ) -> Video:
        """Submit a job and return immediately, without waiting for the result.

        Args:
            model: Public model name, e.g. ``"veo_3_1"`` or ``"gpt-image-2"``.
            prompt: What to generate.
            seconds: Clip length, 1–60 (default 4). Ignored by image models.
            size: Pixel size as ``"WxH"``, e.g. ``"1280x720"``. The aspect
                ratio is inferred from it — there is no separate parameter.
            tier: Resolution/quality tier — ``1k``/``2k``/``4k`` for images,
                ``720p``/``1080p``/``4k`` for Veo video. **Worth setting
                explicitly**: pricing is per tier, and a size that matches no
                tier falls back to the model's base rate.
            reference_images: HTTPS URLs or ``data:`` URLs. Per-model limits
                apply; see the model's page.
            metadata: Model-specific extras that are not top-level fields,
                e.g. ``{"first_last_frame": True}`` for omni.
            **extra: Passed through verbatim, so a newly added API field is
                usable before this client knows about it.

        Returns:
            The job in its initial state — usually ``queued``.
        """
        body: dict[str, Any] = {"model": model, "prompt": prompt}
        if seconds is not None:
            body["seconds"] = seconds
        if size is not None:
            body["size"] = size
        if tier is not None:
            body["tier"] = tier
        if reference_images:
            body["reference_images"] = list(reference_images)
        if metadata:
            body["metadata"] = dict(metadata)
        body.update(extra)

        return Video._from_json(self._client._request("POST", "/videos", json=body))

    # -------------------------------------------------------------- retrieve

    def retrieve(self, task_id: str) -> Video:
        """Read the job's current state. One HTTP call, no waiting."""
        return Video._from_json(self._client._request("GET", f"/videos/{task_id}"))

    # ------------------------------------------------------------------ wait

    def wait(
        self,
        task_id: str,
        *,
        timeout: float = DEFAULT_MAX_WAIT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        on_progress: Callable[[Video], None] | None = None,
    ) -> Video:
        """Poll until the job reaches a terminal state.

        Raises:
            JobFailedError: the job finished as ``failed``.
            JobTimeout: still running when ``timeout`` elapsed. The job is
                *not* cancelled — poll ``task_id`` again later rather than
                resubmitting, which would bill a second time.
        """
        deadline = time.monotonic() + timeout
        attempt = 0

        while True:
            video = self.retrieve(task_id)
            if on_progress is not None:
                on_progress(video)
            if video.is_done:
                if video.status == "failed":
                    detail = video.error.message if video.error else "no detail given"
                    raise JobFailedError(
                        f"job {video.id} failed: {detail}", video=video
                    )
                return video

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JobTimeout(
                    f"job {task_id} still {video.status} after {timeout:g}s; "
                    f"poll it again later instead of resubmitting",
                    task_id=task_id,
                )

            # Small jitter so a batch of jobs started together does not poll in
            # lockstep. Capped at 10s: generation is slow, but people watch
            # progress bars.
            delay = min(poll_interval * (1 + 0.25 * attempt), 10.0)
            delay += random.uniform(0, 0.4)
            time.sleep(min(delay, max(remaining, 0.1)))
            attempt += 1

    # -------------------------------------------------------------- generate

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        timeout: float = DEFAULT_MAX_WAIT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        on_progress: Callable[[Video], None] | None = None,
        **params: Any,
    ) -> Video:
        """Submit and wait — the one-liner for scripts and notebooks.

        Equivalent to :meth:`create` followed by :meth:`wait`, and takes the
        same generation parameters as :meth:`create`.
        """
        job = self.create(model=model, prompt=prompt, **params)
        return self.wait(
            job.id,
            timeout=timeout,
            poll_interval=poll_interval,
            on_progress=on_progress,
        )

    # -------------------------------------------------------------- download

    def download(self, task_id: str, dest: str | Path) -> Path:
        """Stream the finished asset to ``dest`` and return the path.

        Streams rather than buffering: a minute of 1080p is tens of megabytes
        and there is no reason to hold it in memory.
        """
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling temp file first so an interrupted download never
        # leaves a half-written file that looks complete.
        tmp = path.with_suffix(path.suffix + ".part")
        with self._client._stream("GET", f"/videos/{task_id}/content") as response:
            with tmp.open("wb") as fh:
                for chunk in response.iter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
        tmp.replace(path)
        return path


class GenRelay:
    """Client for the GenRelay generation API.

    Usage::

        from genrelay import GenRelay

        client = GenRelay()  # reads GENRELAY_API_KEY
        video = client.videos.generate(
            model="veo_3_1",
            prompt="a neon fox running through a rainy city at night",
            seconds=8,
            size="1280x720",
            tier="1080p",
        )
        client.videos.download(video.id, "fox.mp4")

    Chat and image-edit endpoints are OpenAI-compatible — point the official
    ``openai`` package at ``https://genrelay.ai/v1`` for those. This client
    exists for the generation jobs, which are asynchronous and have no
    equivalent in that SDK.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
    ) -> None:
        key = api_key or os.environ.get("GENRELAY_API_KEY", "")
        if not key:
            raise AuthenticationError(
                "no API key: pass api_key=... or set GENRELAY_API_KEY"
            )
        self.api_key = key
        self.base_url = (base_url or os.environ.get("GENRELAY_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries = max(0, max_retries)

        from . import __version__

        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": _user_agent(__version__),
        }

        self.videos = Videos(self)

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "GenRelay":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --------------------------------------------------------------- request

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.request(
                    method, self._url(path), headers=self._headers, **kwargs
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(_backoff(attempt))
                    continue
                raise APIError(f"request to {path} timed out") from exc
            except httpx.HTTPError as exc:
                raise APIError(f"request to {path} failed: {exc}") from exc

            if response.status_code < 400:
                return _decode(response, path)

            # 429 and 5xx are worth retrying; 4xx means the request itself is
            # wrong and retrying would only bill or annoy.
            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                time.sleep(_retry_after(response) or _backoff(attempt))
                continue

            raise _error_for(response, path)

        raise APIError(f"request to {path} failed: {last_error}")

    def _stream(self, method: str, path: str, **kwargs: Any):
        return _StreamContext(self, method, path, kwargs)


class _StreamContext:
    """Context manager that surfaces API errors before the body is streamed."""

    def __init__(self, client: GenRelay, method: str, path: str, kwargs: dict[str, Any]):
        self._ctx = client._http.stream(
            method, client._url(path), headers=client._headers, **kwargs
        )
        self._path = path

    def __enter__(self) -> httpx.Response:
        response = self._ctx.__enter__()
        if response.status_code >= 400:
            response.read()  # error bodies are small; read before classifying
            raise _error_for(response, self._path)
        return response

    def __exit__(self, *exc: Any) -> None:
        self._ctx.__exit__(*exc)


# ------------------------------------------------------------------ helpers


def _backoff(attempt: int) -> float:
    return min(0.5 * (2**attempt), 8.0) + random.uniform(0, 0.3)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def _decode(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise APIError(
            f"{path} returned non-JSON body", status=response.status_code
        ) from exc
    if not isinstance(data, dict):
        raise APIError(f"{path} returned {type(data).__name__}, expected an object",
                       status=response.status_code, body=data)
    return data


def _error_for(response: httpx.Response, path: str) -> APIError:
    status = response.status_code
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = response.text

    message, code = _extract_error(body)
    message = message or f"{path} failed with HTTP {status}"

    cls = {
        401: AuthenticationError,
        403: AuthenticationError,
        402: InsufficientCreditsError,
        429: RateLimitError,
    }.get(status, APIError)
    return cls(message, status=status, code=code, body=body)


def _extract_error(body: Any) -> tuple[str, str | None]:
    """Pull (message, code) out of the several error shapes the API can emit."""
    if not isinstance(body, dict):
        return (str(body)[:300] if body else ""), None

    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or ""), (error.get("code") or None)
    if isinstance(error, str) and error:
        return error, None
    if body.get("message"):
        return str(body["message"]), (body.get("code") or None)
    return "", None
