"""Retry decorators using tenacity."""

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import httpx


def retry_on_http_error(max_attempts: int = 3, min_wait: int = 4, max_wait: int = 30):
    """Retry decorator for HTTP/API calls."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
        reraise=True,
    )
