"""GenRelay — unified API client for Veo 3.1, Grok Imagine, Nano Banana and more.

Generation jobs are asynchronous: you submit, the server works for anywhere
from seconds to minutes, then you collect. This package wraps that loop —
submit, poll with backoff, stream the result to disk — so callers write one
line instead of a retry loop.

Chat and image edits are OpenAI-compatible; use the official ``openai``
package against ``https://genrelay.ai/v1`` for those.
"""

from .errors import (
    APIError,
    AuthenticationError,
    GenRelayError,
    InsufficientCreditsError,
    JobFailedError,
    JobTimeout,
    RateLimitError,
)
from .types import TERMINAL_STATUSES, Video, VideoError, VideoStatus

__version__ = "0.1.0"

from ._client import GenRelay, Videos  # noqa: E402  (needs __version__ above)

__all__ = [
    "GenRelay",
    "Videos",
    "Video",
    "VideoError",
    "VideoStatus",
    "TERMINAL_STATUSES",
    "GenRelayError",
    "APIError",
    "AuthenticationError",
    "InsufficientCreditsError",
    "RateLimitError",
    "JobFailedError",
    "JobTimeout",
    "__version__",
]
