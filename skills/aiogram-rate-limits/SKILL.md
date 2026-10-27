---
name: aiogram-rate-limits
description: >
  Use when handling aiogram 3 FloodWait, TelegramRetryAfter, outbound pacing, or inbound throttling.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram rate limits

**aiogram has no built-in throttler.** It gives you two things: `TelegramRetryAfter`
carrying `retry_after`, and `aiogram.utils.backoff.Backoff`. Pacing is your code.

Do not describe a custom throttler as an aiogram feature, and do not look for a
`@throttle` decorator — there isn't one.

## when to use this skill

- `TelegramRetryAfter` in the logs
- broadcasting to many users
- a user spamming a button
- deciding between reactive retry and proactive pacing
- protecting an expensive handler

## Telegram's limits

Quoted verbatim from the [Telegram bot FAQ](https://core.telegram.org/bots/faq):

> "In a single chat, avoid sending more than one message per second."

> "In a group, bots are not be able to send more than 20 messages per minute."

> "For bulk notifications, bots are not able to broadcast more than about 30 messages per
> second, unless they enable paid broadcasts to increase the limit."

These are **soft** and not exactly published per method. Exceeding them yields HTTP 429,
raised as `TelegramRetryAfter` only with a non-zero `parameters.retry_after`.
Without that parameter, HTTP 429 becomes `TelegramAPIError`.

`send_message(..., allow_paid_broadcast=True)` raises the ceiling at a cost in Stars;
`get-method.py sendMessage` shows the field. Do not enable paid delivery as an automatic
fallback; it changes the application's spending policy.

## reactive: honour retry_after

The one non-negotiable rule: **wait at least as long as Telegram tells you.** A hardcoded delay
either wastes time or gets you limited again.

```python
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramRetryAfter

T = TypeVar("T")


async def with_flood_retry(
    call: Callable[[], Awaitable[T]],
    attempts: int = 3,
    max_wait: float = 2.0,
) -> T:
    """Retry a known-rejected, safe-to-repeat call using Telegram's own delay."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if max_wait < 0:
        raise ValueError("max_wait must be non-negative")
    remaining_wait = max_wait
    for attempt in range(attempts):
        try:
            return await call()
        except TelegramRetryAfter as error:
            if attempt == attempts - 1 or error.retry_after > remaining_wait:
                raise
            remaining_wait -= error.retry_after
            await asyncio.sleep(error.retry_after)
    raise AssertionError("unreachable")
```

Usage: `await with_flood_retry(lambda: bot.send_message(chat_id=1, text="hi"))`.

Inline sleep retains the handler task and, with FSM event isolation enabled, its lock.
Later updates in that scope, including cancel callbacks, wait behind it. `max_wait`
bounds total inline sleep; a longer delay is re-raised without retrying early. Simple
bots can handle the refusal at the caller; a queue is not required. Run longer jobs
outside the interactive handler when necessary.

Note `retry_after` is an `int` number of seconds and can be large — Telegram sometimes
returns minutes. If the worker cannot wait, defer or reschedule the operation for
that deadline. Never cap the sleep and retry early. Do not multiply `retry_after` by exponential
backoff either: a server deadline and a transient-failure backoff are different budgets.

### queued work and shared cooldowns

Use the helper only when the caller owns the bounded wait and knows repetition is safe.
In a durable worker, make one attempt, preserve `retry_after` through wrappers, save the
resume checkpoint/deadline, and release the worker slot. A preview helper with its own
sleep/retry loop must not silently impose that policy on queued delivery.

Concurrent jobs need shared pacing at the API boundary. Reserve the next permitted time
atomically before a call; a lock that only serialises calls still permits a burst. Keep
planned spacing distinct from Telegram's cooldown, and preserve the maximum observed
deadline for the verified bot/method/resource scope. Recheck immediately before sending;
use an earlier preflight to avoid expensive preparation during a known cooldown. Do not
assume every 429 is global or that all limits are per-chat. A late success may relax an
adaptive pacing interval, but must never erase a newer 429 deadline.

When ordered batches share a destination, serialise admission/delivery in that scope,
not just each individual call. Keep a deferred earlier batch ahead of later batches when
FIFO is required, while unrelated destinations continue. Budget summaries, result sends,
and cosmetic edits together where they compete for the same observed limit. Pacing alone
is not proof a long series will avoid FloodWait; consider fewer messages if the requested
output contract permits it, and measure the real scenario.

Do not restart an acknowledged multipart delivery from item zero. Preserve preparation
and uploads across retries when their source/revision is still valid. Cosmetic progress
edits have a separate cadence and must not block the worker or replace a terminal result.
See [durable operations](../using-aiogram/references/durable-operations.md) when restart,
cancellation, or ambiguous mutations are involved; `retry_after` is not an idempotency key.

## proactive: pace outbound calls

Retrying alone means you always hit the wall first. A session middleware paces every API
call before it leaves:

```python
import asyncio
import time
from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import NextRequestMiddlewareType
from aiogram.methods import TelegramMethod


class GlobalPacer:
    """Session middleware enforcing a global calls-per-second ceiling.

    This is application code, not an aiogram feature. It smooths bursts; combine it
    with method-aware flood handling for calls Telegram limits anyway. This is
    neither a distributed limiter nor a guaranteed Telegram allowance.
    """

    def __init__(self, per_second: float = 25.0) -> None:
        if per_second <= 0:
            raise ValueError("per_second must be positive")
        self.interval = 1.0 / per_second
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[Any],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Any:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = time.monotonic() + self.interval
        return await make_request(bot, method)


bot = Bot(token="123456:TEST")
bot.session.middleware(GlobalPacer(per_second=25.0))
```

25 calls/s is an illustrative application setting, not a safe limit for every method.
A second bucket can enforce per-chat pacing, keyed by `getattr(method, "chat_id", None)`;
methods without a chat target need their own verified scope. Share state across processes
when necessary. A rate reservation is not a delivery lock: slow requests can overlap.

Session middleware differs from dispatch middleware: it wraps **outgoing API calls**, not
incoming updates. Both are useful, for opposite directions.

## broadcasting

```python
import asyncio
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)


async def broadcast(bot: Bot, user_ids: Iterable[int], text: str) -> dict[str, int]:
    """Sequential delivery; unexpected/auth/transport failures propagate to the job owner."""
    report = {"sent": 0, "deactivated": 0, "failed": 0}
    for user_id in user_ids:
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=user_id, text=text, parse_mode=None)
            except TelegramRetryAfter as error:
                if attempt == 2:
                    raise  # stop the job; do not advance through a server-imposed wait
                await asyncio.sleep(error.retry_after)
                continue
            except (TelegramForbiddenError, TelegramNotFound):
                report["deactivated"] += 1
            except TelegramBadRequest:
                report["failed"] += 1  # retain details in the application's job report
            else:
                report["sent"] += 1
            break
        await asyncio.sleep(0.04)  # application pace, not a guaranteed Telegram allowance
    return report
```

Three things that make broadcasts safe:

1. **Sequential with a delay**, not `asyncio.gather` over 10 000 users. Gathering
   creates an uncontrolled burst and makes ordered recovery harder.
2. **Classify failures.** This example targets private users only. Stop retries for
   `TelegramForbiddenError` and `TelegramNotFound`; mark a recipient inactive only when
   the failed method and target confirm unavailability, not for every missing permission.
3. **Make it resumable.** Persist progress; a broadcast to 100 000 users will outlive a
   deploy.

## inbound throttling

Limiting what *users* send you is the other direction, and it belongs in an **outer**
dispatch middleware so it runs before filters.

```python
import time
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import CallbackQuery, TelegramObject, Update


class UserThrottle(BaseMiddleware):
    """Per-user minimum interval between updates. In-process only."""

    def __init__(self, default_interval: float = 0.5) -> None:
        self.default_interval = default_interval
        self.last_seen: dict[tuple[int, int], float] = {}

    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        interval = self.default_interval
        key = (data["bot"].id, user.id)
        now = time.monotonic()
        if now - self.last_seen.get(key, float("-inf")) < interval:
            callback = event.callback_query if isinstance(event, Update) else event
            if isinstance(callback, CallbackQuery):
                await callback.answer("Too fast, please wait.", show_alert=False)
            return None

        self.last_seen[key] = now
        return await handler(event, data)


dispatcher = Dispatcher()
dispatcher.update.outer_middleware(UserThrottle())
```

Two details that are easy to get wrong:

- **Always answer a throttled `CallbackQuery`.** Dropping it silently leaves a spinner on
  the user's button until the query expires.
- **Do not reply to every throttled message.** Telling a spammer "slow down" on every
  message doubles your outbound traffic. Warn once, then stay quiet.

`get_flag` only sees flags when the handler has already been resolved, which this outer
middleware does not have. For genuinely per-handler budgets, register the throttle as
an **inner** middleware instead and accept that filters run first.

Expire idle entries in a long-lived process to bound memory.
An in-process dict is per-replica. With more than one process, use Redis (`INCR` plus
`EXPIRE` is enough for a fixed window).

## backoff helper

```python
from aiogram.utils.backoff import Backoff, BackoffConfig

config = BackoffConfig(min_delay=1.0, max_delay=30.0, factor=1.5, jitter=0.1)
backoff = Backoff(config)

assert backoff.next_delay > 0
backoff.reset()
```

This is the policy aiogram uses for polling reconnects. Use it for safe-to-repeat reads
or explicitly repeatable operations after network/5xx failures, not as permission to
resend an ambiguous result. Use `retry_after` for a known flood rejection — a backoff
curve is the wrong tool when the server told you the delay.

## what to reach for

| Problem | Solution |
|---|---|
| occasional 429 | `with_flood_retry` |
| bursts from parallel handlers | session-middleware pacer |
| broadcast | sequential loop with a delay, resumable |
| one user spamming | outer dispatch middleware |
| expensive handler | `@flags.rate_limit(...)` plus an inner middleware |
| network / 5xx | reconcile ambiguous effects; `Backoff` only for safe repetition |

## checklist

- `retry_after` honoured fully, not shortened or multiplied; queued waits release the slot
- shared cooldowns cannot be cleared by stale successes; scope verified per operation
- queued multipart work preserves required FIFO delivery and immutable resume order
- summaries/progress included in the observed traffic budget; cosmetic edits expendable
- broadcasts sequential, paced, resumable, and classifying permanent failures
- access failures stop retries; deactivation requires evidence about the affected target
- throttled callback queries answered
- throttle state shared across replicas when there is more than one
- no `asyncio.gather` over a large recipient list
- custom throttling documented as application code, not an aiogram feature

## see also

- `aiogram-errors` — the wider exception tree
- `aiogram-middlewares` — inner versus outer, and flags
- `skills/using-aiogram/references/telegram-quirks.md` — the quoted limits
