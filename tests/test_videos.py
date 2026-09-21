"""Tests for the generation client.

Everything runs against an httpx mock transport — no network, no API key, no
credits burned. The point is to pin the behaviour that is easy to get wrong:
polling stops at terminal states, failures raise instead of returning a
half-empty object, and HTTP status codes map to the right exception.
"""

from __future__ import annotations

import json

import httpx
import pytest

from genrelay import (
    APIError,
    AuthenticationError,
    GenRelay,
    InsufficientCreditsError,
    JobFailedError,
    JobTimeout,
    RateLimitError,
)


def client_with(handler) -> GenRelay:
    transport = httpx.MockTransport(handler)
    return GenRelay(
        api_key="sk-test",
        http_client=httpx.Client(transport=transport),
        max_retries=0,
    )


def job(status: str, **extra) -> dict:
    body = {
        "id": "task_abc",
        "task_id": "task_abc",
        "object": "video",
        "model": "veo_3_1",
        "status": status,
        "progress": 100 if status == "completed" else 10,
        "created_at": 1790000000,
    }
    body.update(extra)
    return body


# ------------------------------------------------------------------- create


def test_create_sends_only_the_fields_given():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=job("queued"))

    c = client_with(handler)
    c.videos.create(model="veo_3_1", prompt="a fox", seconds=8, tier="1080p")

    # Optional params the caller omitted must not be sent at all: sending
    # size=None would override a model default server-side.
    assert seen == {"model": "veo_3_1", "prompt": "a fox", "seconds": 8, "tier": "1080p"}


def test_create_passes_unknown_fields_through():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=job("queued"))

    c = client_with(handler)
    c.videos.create(model="m", prompt="p", some_new_api_field="x")
    assert seen["some_new_api_field"] == "x"


def test_create_sends_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["ua"] = request.headers.get("User-Agent")
        return httpx.Response(200, json=job("queued"))

    client_with(handler).videos.create(model="m", prompt="p")
    assert seen["auth"] == "Bearer sk-test"
    assert seen["ua"].startswith("genrelay-python/")


# --------------------------------------------------------------------- wait


def test_wait_polls_until_completed():
    states = iter(["queued", "in_progress", "completed"])
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=job(next(states), output_url="https://x/v"))

    c = client_with(handler)
    video = c.videos.wait("task_abc", poll_interval=0.001)

    assert calls["n"] == 3
    assert video.succeeded and video.is_done
    assert video.output_url == "https://x/v"


def test_wait_raises_on_failed_and_keeps_the_job():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=job("failed", error={"message": "unsafe prompt", "code": "rejected"}),
        )

    c = client_with(handler)
    with pytest.raises(JobFailedError) as excinfo:
        c.videos.wait("task_abc", poll_interval=0.001)

    # The failed job must be reachable — callers need the reason and the model.
    assert excinfo.value.video.error.code == "rejected"
    assert "unsafe prompt" in str(excinfo.value)


def test_wait_times_out_without_losing_the_task_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=job("in_progress"))

    c = client_with(handler)
    with pytest.raises(JobTimeout) as excinfo:
        c.videos.wait("task_abc", timeout=0.05, poll_interval=0.001)

    # Losing the id would force a resubmit, which bills a second time.
    assert excinfo.value.task_id == "task_abc"


def test_on_progress_sees_every_poll():
    states = iter(["queued", "in_progress", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=job(next(states)))

    seen = []
    c = client_with(handler)
    c.videos.wait("task_abc", poll_interval=0.001, on_progress=seen.append)
    assert [v.status for v in seen] == ["queued", "in_progress", "completed"]


# ----------------------------------------------------------------- generate


def test_generate_creates_then_waits():
    seen_paths = []
    states = iter(["queued", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json=job("queued"))
        return httpx.Response(200, json=job(next(states)))

    c = client_with(handler)
    video = c.videos.generate(model="veo_3_1", prompt="p", poll_interval=0.001)

    assert seen_paths[0] == ("POST", "/v1/videos")
    assert all(m == "GET" for m, _ in seen_paths[1:])
    assert video.succeeded


# ------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (402, InsufficientCreditsError),
        (429, RateLimitError),
        (400, APIError),
        (500, APIError),
    ],
)
def test_status_codes_map_to_exceptions(status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope", "code": "e"}})

    c = client_with(handler)
    with pytest.raises(expected) as excinfo:
        c.videos.create(model="m", prompt="p")
    assert excinfo.value.status == status
    assert excinfo.value.code == "e"


def test_error_message_survives_a_plain_string_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    c = client_with(handler)
    with pytest.raises(APIError) as excinfo:
        c.videos.create(model="m", prompt="p")
    assert "upstream exploded" in str(excinfo.value)


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("GENRELAY_API_KEY", raising=False)
    with pytest.raises(AuthenticationError):
        GenRelay()


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("GENRELAY_API_KEY", "sk-env")
    assert GenRelay().api_key == "sk-env"


# ----------------------------------------------------------------- download


def test_download_streams_to_disk(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/videos/task_abc/content"
        return httpx.Response(200, content=b"\x00\x01binary")

    c = client_with(handler)
    out = c.videos.download("task_abc", tmp_path / "nested" / "clip.mp4")

    assert out.read_bytes() == b"\x00\x01binary"
    # The .part file must not survive a successful download.
    assert not (tmp_path / "nested" / "clip.mp4.part").exists()


def test_download_raises_before_writing_anything(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "gone"}})

    c = client_with(handler)
    dest = tmp_path / "clip.mp4"
    with pytest.raises(APIError):
        c.videos.download("task_abc", dest)
    assert not dest.exists()


# -------------------------------------------------------------------- types


def test_legacy_task_id_is_accepted_when_id_is_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        body = job("completed")
        del body["id"]  # older responses only carried task_id
        return httpx.Response(200, json=body)

    c = client_with(handler)
    assert c.videos.retrieve("task_abc").id == "task_abc"


def test_raw_keeps_unmodelled_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=job("completed", future_field={"a": 1}))

    c = client_with(handler)
    assert c.videos.retrieve("task_abc").raw["future_field"] == {"a": 1}
