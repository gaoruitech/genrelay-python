# genrelay-python

Python client for [GenRelay](https://genrelay.ai/?utm_source=github&utm_medium=readme&utm_campaign=genrelay-python) — one API for **Veo 3.1**, **Grok Imagine**, **Nano Banana Pro/2**, **GPT Image 2** and **Omni Flash**. Text-to-video, image-to-video, first/last-frame, and image generation.

```bash
pip install genrelay
```

## Quick start

```python
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
```

That's the whole loop: submit, poll with backoff, stream to disk. Generation
takes seconds to minutes depending on the model and length.

## Why this exists

Chat and image edits on GenRelay are **OpenAI-compatible** — point the
official `openai` package at `https://genrelay.ai/v1` and you're done:

```python
from openai import OpenAI
client = OpenAI(base_url="https://genrelay.ai/v1", api_key="sk-...")
```

Generation jobs are different: they're asynchronous, with a submit → poll →
download cycle that has no equivalent in that SDK. That's what this package
handles — the polling loop, the backoff, the terminal-state detection, the
streamed download, and typed errors instead of dict-digging.

## Async, when you need control

```python
job = client.videos.create(model="veo_3_1", prompt="...", seconds=8)
print(job.id, job.status)          # task_xxx queued

# ... do other work, persist job.id, come back later ...

video = client.videos.wait(job.id, timeout=900)
```

Watch progress while it runs:

```python
client.videos.generate(
    model="veo_3_1",
    prompt="...",
    on_progress=lambda v: print(f"{v.status} {v.progress}%"),
)
```

## Models

| Model | Kind | Notes |
|---|---|---|
| `veo_3_1` | video | Google Veo 3.1 |
| `veo_3_1-fl` | video | first/last frame |
| `veo_3_1-components` | video | component-guided |
| `grok-imagine-video-1-5-preview` | video | xAI Grok Imagine 1.5 |
| `grok-imagine-1-0-video` | video | Grok Imagine 1.0 |
| `omni-flash` | video | fast, long clips |
| `omni_flash_abra_edit` | video | video editing |
| `nano-banana-pro` | image | Google |
| `nano-banana-2` | image | Google |
| `gpt-image-2` | image | OpenAI |

Current model list, options and per-tier pricing: [GenRelay docs](https://genrelay.ai/docs?utm_source=github&utm_medium=readme&utm_campaign=genrelay-python) · [Pricing](https://genrelay.ai/pricing?utm_source=github&utm_medium=readme&utm_campaign=genrelay-python)

## Parameters

| Name | Type | Notes |
|---|---|---|
| `model` | str | required |
| `prompt` | str | required |
| `seconds` | int \| str | 1–60, default 4. Ignored by image models |
| `size` | str | `"1280x720"`. Aspect ratio is inferred — no separate parameter |
| `tier` | str | `1k`/`2k`/`4k` (images), `720p`/`1080p`/`4k` (Veo) |
| `reference_images` | list[str] | HTTPS or `data:` URLs |
| `metadata` | dict | model-specific extras, e.g. `{"first_last_frame": True}` |

> **Set `tier` explicitly.** Pricing is per tier, and a `size` that matches no
> tier falls back to the model's base rate — which can cost noticeably more
> than you expected.

Unknown keyword arguments are forwarded as-is, so new API fields work before
this client knows about them.

## Errors

```python
from genrelay import InsufficientCreditsError, JobFailedError, JobTimeout

try:
    video = client.videos.generate(model="veo_3_1", prompt="...")
except InsufficientCreditsError:
    ...                      # 402 — top up
except JobFailedError as e:
    print(e.video.error)     # model couldn't produce a result
except JobTimeout as e:
    print(e.task_id)         # still running — poll later, don't resubmit
```

`JobTimeout` deliberately keeps the task id: resubmitting bills a second time,
polling doesn't.

All exceptions derive from `GenRelayError`.

## Configuration

| | |
|---|---|
| `GENRELAY_API_KEY` | API key, or pass `api_key=` |
| `GENRELAY_BASE_URL` | override the endpoint (default `https://genrelay.ai/v1`) |

```python
client = GenRelay(api_key="sk-...", timeout=60.0, max_retries=2)
```

`GenRelay` is a context manager and closes its HTTP client on exit. Pass your
own `httpx.Client` via `http_client=` to control pooling or proxies.

## License

MIT
