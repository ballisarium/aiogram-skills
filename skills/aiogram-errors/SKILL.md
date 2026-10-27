---
name: aiogram-errors
description: >
  Use when handling aiogram 3 API exceptions, error handlers, retries, or failed message edits.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram errors

`AiogramError` covers the exceptions below, not every exception in the package.
`TokenValidationError`, `SkipHandler` and `CancelHandler` inherit directly from `Exception`.
Telegram API failures are classified using response parameters, HTTP status and message.

```bash
python skills/using-aiogram/tools/get-exception.py --tree
python skills/using-aiogram/tools/get-exception.py TelegramRetryAfter
```

## when to use this skill

- deciding which exception to catch around an API call
- writing a global error handler
- a bot that dies on one bad chat
- reading an error string Telegram returned
- distinguishing a permanent failure from one worth retrying

## the hierarchy

Verified on aiogram 3.31.0:

```text
AiogramError
├── CallbackAnswerException
├── ClientDecodeError
├── DetailedAiogramError
│   ├── DataNotDictLikeError
│   ├── UnsupportedKeywordArgument
│   └── TelegramAPIError
│       ├── TelegramBadRequest
│       ├── TelegramConflictError
│       ├── TelegramForbiddenError
│       ├── TelegramMigrateToChat
│       ├── TelegramNetworkError
│       │   └── TelegramEntityTooLarge
│       ├── TelegramNotFound
│       ├── TelegramRetryAfter
│       ├── TelegramServerError
│       │   └── RestartingTelegram
│       └── TelegramUnauthorizedError
└── SceneException
```

`TelegramAPIError` carries the failed `method` and a diagnostic `message`.
`TelegramRetryAfter` and `TelegramMigrateToChat` augment the original description with
method/chat/delay context; their `message` is not the untouched server description.

Catch the narrowest class that matches the recovery you intend. `except TelegramAPIError`
around everything hides the difference between "retry in 30 seconds" and "this
target is unavailable".

## what each one means

| Exception | Meaning | Recovery |
|---|---|---|
| `TelegramBadRequest` | Telegram rejected the request | **read the message** — this class covers dozens of distinct causes |
| `TelegramForbiddenError` | access denied: blocked bot, removed bot, or missing rights | stop retries; deactivate only the affected target when the cause supports it |
| `TelegramNotFound` | chat, message, or user does not exist | permanent for that target |
| `TelegramUnauthorizedError` | token invalid or revoked | fatal: fix configuration |
| `TelegramConflictError` | another poller, or a webhook is set | run exactly one consumer |
| `TelegramRetryAfter` | flood limit with a server-supplied delay | retry only a known-rejected, safe-to-repeat operation after `error.retry_after`; queued work reschedules |
| `TelegramMigrateToChat` | group became a supergroup | re-send to `error.migrate_to_chat_id`, persist the new id |
| `TelegramEntityTooLarge` | upload exceeds Telegram's size limit | do not retry; shrink or refuse |
| `TelegramNetworkError` | transport failure; remote outcome may be unknown | backoff for safe reads; reconcile sends/mutations before repeating |
| `TelegramServerError` / `RestartingTelegram` | 5xx from Telegram | retry safe reads with backoff; a mutation may already have happened |
| `ClientDecodeError` | response could not be decoded or validated | inspect proxy/server/schema; a send may already have happened |
| `UnsupportedKeywordArgument` | unsupported registration keyword (often a v2 handler filter argument) | a bug in your code |
| `CallbackAnswerException` | misuse of the `CallbackAnswer` utility | a bug in your code |

`TelegramRetryAfter.retry_after` and `TelegramMigrateToChat.migrate_to_chat_id` are the
two attributes worth remembering — they carry the information needed to recover.

## error handlers

`@router.error(...)` receives an `ErrorEvent` with exactly two fields: `update` and
`exception`.

```python
import logging
import traceback

from aiogram import Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent, User

router = Router(name="errors")
logger = logging.getLogger(__name__)


@router.error(ExceptionTypeFilter(TelegramForbiddenError))
async def blocked(event: ErrorEvent, event_from_user: User | None = None) -> None:
    """Stop retries; inspect the failed target before deciding deactivation.

    Error handlers receive workflow data, so `event_from_user` is injected the same
    way it is for ordinary handlers. There is no `Update.event_from_user` attribute.
    """
    logger.info("delivery access denied")


@router.error(ExceptionTypeFilter(TelegramRetryAfter))
async def flooded(event: ErrorEvent) -> None:
    exception = event.exception
    if isinstance(exception, TelegramRetryAfter):
        logger.warning("flood limit, retry after %s s", exception.retry_after)


@router.error()
async def unhandled(event: ErrorEvent) -> None:
    """Register last: this matches everything."""
    logger.error(
        "unhandled update failure: %s\n%s",
        type(event.exception).__name__,
        "".join(traceback.format_tb(event.exception.__traceback__)),
    )
```

- Error handlers are matched in registration order, like any other observer. Specific
  first, catch-all last.
- An error handler that itself raises produces an unhandled exception. Keep them dull.
- Handling the error **swallows** it — the update is considered done. Re-raise if you want
  aiogram's default logging as well.

Use a local catch when the handler can recover; use a router error handler for shared
reporting. Record the original failure with redaction before a user-facing apology. That
API call may also fail (blocked user, expired callback, network failure).

The minimal callback fallback below assumes the query has not already been answered.
If handlers ACK early, use the application's per-update ACK tracking and report later
failures on the owned message surface; do not answer the same query again unconditionally.
Reporting must preserve the original failure even if the apology cannot be delivered.

```python
import logging
import traceback

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

router = Router(name="user-facing-errors")
logger = logging.getLogger(__name__)


@router.error()
async def apologise(event: ErrorEvent) -> None:
    """Answer the pending callback query too, or the client spins forever."""
    logger.error(
        "update failure: %s\n%s",
        type(event.exception).__name__,
        "".join(traceback.format_tb(event.exception.__traceback__)),
    )
    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer("Something went wrong.", show_alert=True)
        elif update.message is not None:
            await update.message.answer("The operation could not be confirmed.")
    except TelegramAPIError as reporting_error:
        logger.warning(
            "error notification failed: %s\n%s",
            type(reporting_error).__name__,
            "".join(traceback.format_tb(reporting_error.__traceback__)),
        )
```

## reading TelegramBadRequest

`TelegramBadRequest` is a bucket. The message decides what happened:

| Message fragment | Cause | Fix |
|---|---|---|
| `message is not modified` | requested edit already matches | treat as desired-state success for that exact edit, not delivery failure |
| `query is too old` | callback answered late or never | answer immediately |
| `message to edit not found` | message deleted, or wrong id | validate ownership/current generation before replacing the surface |
| `message can't be deleted` | outside Telegram's delete rules, not necessarily missing rights | check age (under 48 hours), private dice age (over 24 hours), protected creation service messages, then chat-specific rights; see [deletion rules](../using-aiogram/references/telegram-quirks.md#editing-and-deleting) |
| `chat not found` | wrong chat id, or bot never met the user | users must start the bot first |
| `can't parse entities` | malformed HTML/Markdown | escape, or use entities |
| `BUTTON_DATA_INVALID` | invalid button data, including an oversized payload | validate the payload and its 64-byte limit |
| `file is too big` | over the 20 MB download limit | use a local Bot API server |
| `not enough rights` | missing admin permission | grant it, or degrade gracefully |

Matching on substrings is fragile but is the only option Telegram gives. Isolate it in one
helper rather than scattering `in str(error)` across the codebase:

```python
from aiogram.exceptions import TelegramBadRequest


def is_not_modified(error: TelegramBadRequest) -> bool:
    return "message is not modified" in error.message.casefold()


def is_stale_callback(error: TelegramBadRequest) -> bool:
    return "query is too old" in error.message.casefold()
```

Classify at the boundary that can fail: an upload may reject input before a later
create/add call is reached. Map recognised validation/permission failures to the
appropriate user outcome without spending transient retry attempts. Keep unknown errors
reportable; an empty result alone does not establish which rejection occurred.

`BaseSession.check_response` constructs `TelegramRetryAfter` from
`parameters.retry_after` when non-zero; HTTP 429 alone falls back to `TelegramAPIError`.
A 400 response whose description merely says "retry after"
is still `TelegramBadRequest`. Only add a text compatibility classifier for an observed
response: match the whole normalised description, a positive delay, and the exact API
method whose rejection semantics were verified. Reject extra text, other methods, and
malformed delays; never turn arbitrary 400s into safe retries. Share that classification
between the immediate call and recovery path.

Before persisting or forwarding diagnostics, use bounded error codes and allowlisted
operation context. Never log update payloads, method objects or user text.
`ClientDecodeError.__str__` includes raw response data; other exception messages and
chained exceptions may also contain private values. The examples log the exception type
and stack frames with `traceback.format_tb`, without `str(error)`, `exc_info`, chains or
locals. Source lines remain visible: keep credentials out of source code. This needs no
custom formatter; use an existing redacting logger if the application has one.
Known user refusals and unexpected failures need distinct paths.

## retry policy

A transient cause does not imply a safe retry. A network error, timeout, cancellation,
5xx, or undecodable response after a send may hide acceptance. Do not blind-resend or
turn it into a generic "try again" action. Reconcile with available operation evidence;
when the Bot API offers no lookup/idempotency key, retain an explicit unknown outcome.

The inline example retries only a known flood rejection of this `send_message` call.
Transport/server failures propagate to the owner without a second send:

```python
import asyncio

from aiogram import Bot
from aiogram.exceptions import (
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)


async def send_reliably(
    bot: Bot, chat_id: int, text: str, attempts: int = 3, max_wait: float = 2.0
) -> bool:
    """True on ACK, False for unavailable target; ambiguous outcomes propagate.

    Assumes the direct flood response proves this send was rejected.
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if max_wait < 0:
        raise ValueError("max_wait must be non-negative")
    remaining_wait = max_wait
    for attempt in range(attempts):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
            return True
        except TelegramEntityTooLarge:
            raise  # permanent; classify before any generic network retry policy
        except (TelegramForbiddenError, TelegramNotFound):
            return False
        except TelegramRetryAfter as error:
            if attempt == attempts - 1 or error.retry_after > remaining_wait:
                raise
            remaining_wait -= error.retry_after
            await asyncio.sleep(error.retry_after)
    raise AssertionError("unreachable")
```

`aiogram.utils.backoff.Backoff` / `BackoffConfig` implement the exponential-with-jitter
policy aiogram uses for polling. Reuse it only after deciding repetition is safe; it does
not make a send idempotent.

Inline sleep retains the handler task and, when enabled, its FSM event-isolation lock.
The user's next callback, including cancel, can wait behind it. `max_wait` is a total
inline-sleep budget, not permission to retry early: a longer delay propagates to the
caller. A simple bot can report/defer the refusal; hand longer work off only when needed.
This inline retry example is not a worker recovery protocol. For queued sends or
mutations, use the existing application's
[delivery checkpoints and ambiguity handling](../using-aiogram/references/durable-operations.md).
API success, a failed metadata read, and a lost response are different outcomes; a failed
verification read must not automatically turn an acknowledged mutation into another send.

## do not swallow

```python
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest


async def bad(bot: Bot, chat_id: int) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text="hi")
    except Exception:  # noqa: BLE001 - shown as an anti-pattern
        pass  # WRONG: hides blocked users, bad tokens, and your own bugs


async def good(bot: Bot, chat_id: int, message_id: int) -> bool:
    """True means the requested state is present, not necessarily newly changed."""
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="hi")
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.casefold():
            raise
    return True
```

A bare `except Exception: pass` around an API call is the single most common way a bot
ends up silently doing nothing. Catch a named class, and make the failure visible.

Equally: repairing the visible response while leaving state or data inconsistent turns one
bug into two. Record acknowledged effects separately from failed follow-ups. Compensation
is another external mutation: perform it only with verified ownership and outcome, not as
an automatic rollback of an ambiguous send.

## checklist

- narrowest exception class caught for each recovery path
- `retry_after` honoured, never a hardcoded sleep
- access failures stop retries for the affected target; do not infer a user block from every 403
- permanent subclasses (especially `TelegramEntityTooLarge`) classified before generic retries
- network/timeout/5xx sends reconciled or marked unknown, never blindly resent
- identical edits count as desired-state success; cleanup cannot revoke a delivery ACK
- `TelegramMigrateToChat` persists the new chat id
- `@router.error` handlers ordered specific-first
- error handlers answer pending callback queries
- `TelegramBadRequest` substring checks isolated in helpers
- no bare `except Exception: pass` around API calls

## see also

- `aiogram-rate-limits` — `TelegramRetryAfter` in depth
- `aiogram-routing` — where `@router.error` sits
- `aiogram-filters` — `ExceptionTypeFilter` / `ExceptionMessageFilter`
- `skills/using-aiogram/references/telegram-quirks.md` — the behaviour behind these messages
