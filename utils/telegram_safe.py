"""Conservative Telegram API pacing.

This reduces accidental request bursts and respects RetryAfter.
It does NOT guarantee immunity from Telegram restrictions.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

MIN_INTERVAL = max(0.15, float(os.getenv("TG_SAFE_MIN_INTERVAL", "0.35")))
MAX_RETRY = max(1, int(os.getenv("TG_SAFE_MAX_RETRY", "4")))
MAX_RETRY_AFTER = max(5, int(os.getenv("TG_SAFE_MAX_RETRY_AFTER", "60")))

_lock = asyncio.Lock()
_last_global = 0.0
_last_chat: dict[int, float] = defaultdict(float)


async def pace(chat_id: int | None = None) -> None:
    global _last_global
    async with _lock:
        now = time.monotonic()
        wait = max(0.0, MIN_INTERVAL - (now - _last_global))
        if chat_id is not None:
            wait = max(wait, MIN_INTERVAL - (now - _last_chat[chat_id]))
        if wait:
            await asyncio.sleep(wait)
        now = time.monotonic()
        _last_global = now
        if chat_id is not None:
            _last_chat[chat_id] = now


async def safe_telegram_call(
    fn: Callable[..., Awaitable[T]],
    *args,
    chat_id: int | None = None,
    **kwargs,
) -> T:
    from aiogram.exceptions import TelegramRetryAfter

    for attempt in range(MAX_RETRY):
        await pace(chat_id)
        try:
            return await fn(*args, **kwargs)
        except TelegramRetryAfter as exc:
            if attempt >= MAX_RETRY - 1:
                raise
            delay = min(
                max(int(getattr(exc, "retry_after", 1)), 1),
                MAX_RETRY_AFTER,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("Telegram API call exhausted retry budget")
