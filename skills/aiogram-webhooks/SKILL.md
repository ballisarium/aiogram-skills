---
name: aiogram-webhooks
description: >
  Use when configuring or debugging aiogram 3 aiohttp webhooks, secret-token checks, or polling conflicts.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-07"
---

# aiogram webhooks

aiogram ships **one** webhook integration: aiohttp, in `aiogram.webhook.aiohttp_server`.
FastAPI, Flask, and others work, but you write the glue.

## when to use this skill

- deploying behind HTTPS instead of polling
- `TelegramConflictError` after switching modes
- securing the webhook endpoint
- serving several bots from one process
- updates arriving but no handler running

## polling or webhook

| | Polling | Webhook |
|---|---|---|
| needs a public HTTPS endpoint | no | yes |
| latency | one long-poll round trip | immediate |
| scaling | one consumer per token | many replicas behind a load balancer |
| local development | trivial | needs a tunnel |
| failure mode | reconnects on its own | Telegram retries, then backs off |

Polling also works in production with a single consumer; choose a webhook when the
deployment needs inbound HTTP delivery or multiple replicas. **Never both at once on one token** —
that is what `TelegramConflictError` means.

## minimal webhook app

```python
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

WEBHOOK_PATH = "/telegram/webhook"

router = Router(name="webhook-demo")


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer("hello over a webhook")


def build_app(token: str, base_url: str, secret: str) -> web.Application:
    if not secret:
        raise ValueError("webhook secret must not be empty")
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    async def on_startup(_: web.Application) -> None:
        await bot.set_webhook(
            url=f"{base_url}{WEBHOOK_PATH}",
            secret_token=secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
            drop_pending_updates=False,
        )

    app = web.Application()
    app.on_startup.append(on_startup)

    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=secret,
        handle_in_background=True,
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dispatcher, bot=bot)
    return app


if __name__ == "__main__":
    application = build_app(
        os.environ["BOT_TOKEN"],
        os.environ["WEBHOOK_BASE_URL"],
        os.environ["WEBHOOK_SECRET"],
    )
    web.run_app(application, host="127.0.0.1", port=8080)
```

Run behind a TLS terminator that can reach the loopback listener. This stateless demo
acknowledges in the background; it does not promise durable delivery of the reply.

Verified signatures:

```text
SimpleRequestHandler(dispatcher, bot, handle_in_background=True,
                     secret_token=None, **data)
TokenBasedRequestHandler(dispatcher, handle_in_background=True,
                         bot_settings=None, **data)
setup_application(app, dispatcher, /, **kwargs)
```

`setup_application` wires the dispatcher's startup and shutdown hooks into aiohttp's
lifecycle. Without it, dispatcher lifecycle hooks (including FSM storage cleanup) do not run.
`SimpleRequestHandler.register()` separately registers its own bot-session close hook.
That hook does not drain application work or the handler's background update tasks.
Stop admission and drain/checkpoint owned work before closing sessions/storage; order
your application shutdown hooks deliberately, rather than assuming registration is a
complete recovery protocol.

Extra `**data` on the handler joins workflow data for every update — the webhook
equivalent of `start_polling(bot, key=value)`.

## security

Telegram will deliver to any URL that answers. Three defences, in order of importance:

### 1. secret token

```python
import secrets

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiohttp import web

secret = secrets.token_urlsafe(32)

app = web.Application()
SimpleRequestHandler(
    dispatcher=Dispatcher(),
    bot=Bot(token="123456:TEST"),
    secret_token=secret,
).register(app, path="/hook")
```

Telegram echoes the value in `X-Telegram-Bot-Api-Secret-Token`, and
`SimpleRequestHandler.verify_secret` rejects mismatches with 401. **Always set it.**
Without it, anyone who guesses the URL can inject updates and impersonate any user.

### 2. an unguessable path

Include a random component in the path. It is defence in depth, not a substitute for the
secret token.

### 3. IP filtering

```python
from aiogram.webhook.aiohttp_server import ip_filter_middleware
from aiogram.webhook.security import IPFilter
from aiohttp import web

allowed = IPFilter.default()
assert "149.154.160.1" in allowed
assert "91.108.4.1" in allowed
assert "192.0.2.1" not in allowed
app = web.Application(middlewares=[ip_filter_middleware(allowed)])
```

`IPFilter.default()` carries Telegram's published subnets. This middleware reads the
leftmost `X-Forwarded-For` value. Trust it only behind a proxy that replaces untrusted
forwarding headers and when the backend cannot be reached directly. Keep the secret
header check as well; clients can otherwise forge the forwarded IP.

## managing the webhook

```python
from aiogram import Bot, Dispatcher


async def switch_to_webhook(bot: Bot, dispatcher: Dispatcher, url: str, secret: str) -> None:
    await bot.set_webhook(
        url=url,
        secret_token=secret,
        allowed_updates=dispatcher.resolve_used_update_types(),
        max_connections=40,
        drop_pending_updates=False,
    )


async def switch_to_polling(bot: Bot) -> None:
    """Required before polling; otherwise every getUpdates raises Conflict."""
    await bot.delete_webhook(drop_pending_updates=False)


async def diagnose(bot: Bot) -> str:
    info = await bot.get_webhook_info()
    return (
        f"configured={bool(info.url)} pending={info.pending_update_count} "
        f"has_last_error={bool(info.last_error_message)}"
    )
```

`get_webhook_info()` is the first thing to check when a webhook bot goes quiet:

| Field | Reading |
|---|---|
| `url` empty | no webhook is set — Telegram is waiting for `getUpdates` |
| `pending_update_count` growing | your endpoint is failing or too slow |
| `last_error_message` | Telegram's own description of the failure |
| `last_error_date` | when it last failed |
| `ip_address` | the address Telegram resolved |

`drop_pending_updates=True` discards the backlog. Convenient in development, destructive
in production.

## handle_in_background

`handle_in_background=True` (the default) acknowledges the request immediately and
processes the update in a task. After this acknowledgement a crash or handler failure
will not cause Telegram to redeliver it. Choose deliberately: important jobs need durable
intake before acknowledgement, plus deduplication by bot/update id. Background tasks in
aiogram are not a durable queue. An error handler that returns normally does not request
redelivery either.

For important work, use the existing application's durable intake boundary: verify the
secret, validate the update, atomically record/claim `(bot.id, update_id)` and enqueue the
work, then return 2xx. A duplicate already recorded update should acknowledge without
enqueuing again. If intake fails, do not send a success acknowledgement. Deduplication
must be atomic across replicas; a check-then-insert or process-local set is insufficient.
Update deduplication prevents duplicate admission, not duplicate external effects after a
worker crash. Those still need [intent/ACK recovery](../using-aiogram/references/durable-operations.md).
Do not retrofit this into every stateless handler; choose the delivery guarantee explicitly.

`handle_in_background=False` processes inline and lets you **answer the update with the
HTTP response** — one fewer API call:

```python
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Message

router = Router(name="inline-response")


@router.message()
async def reply_inline(message: Message) -> TelegramMethod[Message]:
    """Returning a method object answers the webhook request directly."""
    return SendMessage(chat_id=message.chat.id, text="pong")


dispatcher = Dispatcher()
dispatcher.include_router(router)
assert isinstance(Bot(token="123456:TEST"), Bot)
```

Only one method can be returned per update. An inline Bot API response gives the bot
no result object or success acknowledgement; make an explicit API call when that result
matters. `feed_webhook_update` also falls back to background processing after its default
55-second timeout, even when the request handler starts inline. Keep this path short;
`handle_in_background=False` alone is not durable intake or a guarantee that HTTP success
means the handler completed. Do not put a critical result only in the inline response:
without a result ACK you cannot cache its file id, checkpoint its message id, or infer
that it was delivered.

## several bots on one endpoint

```python
from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import TokenBasedRequestHandler, setup_application
from aiohttp import web

dispatcher = Dispatcher()
app = web.Application()

TokenBasedRequestHandler(
    dispatcher=dispatcher,
    bot_settings={"default": DefaultBotProperties(parse_mode="HTML")},
).register(app, path="/webhook/{bot_token}")

setup_application(app, dispatcher)
```

This is an API construction example, not a secured endpoint. Upstream discourages
token-based URLs because proxies can log them. `TokenBasedRequestHandler.verify_secret`
returns True by default; passing `secret_token` through `**data` does not enable a check.
Prefer separate `SimpleRequestHandler` endpoints with checked secrets or implement a
trusted per-bot resolver and verification before exposing a multi-bot endpoint.

## deployment notes

- **Cloud Bot API:** HTTPS on port 443, 80, 88, or 8443. A local Bot API server has
  different webhook transport constraints.
- The certificate must be valid, or supplied to `set_webhook(certificate=...)` if
  self-signed.
- Configure the webhook from one designated startup owner or deploy step, not every
  replica boot. `setWebhook` is global for the token.
- With several replicas, all of them serve the same URL behind a load balancer. That is
  fine. When using FSM, process-local `MemoryStorage` will diverge; share storage and
  the required event-isolation/ownership mechanism. Shared FSM storage alone does not
  serialise concurrent handlers or make external delivery idempotent.
- Telegram retries failed deliveries. Handlers must be idempotent.

## troubleshooting

| Symptom | Check |
|---|---|
| no updates at all | `get_webhook_info().url`, then `last_error_message` |
| `TelegramConflictError` | a poller is still running, or a webhook is still set |
| 401 from your endpoint | `secret_token` mismatch between `set_webhook` and the handler |
| some update types missing | `allowed_updates` on `set_webhook` |
| `pending_update_count` climbing | handler too slow, or the endpoint is 5xx-ing |
| startup hooks never run | `setup_application` not called |
| works locally, not deployed | TLS terminator not forwarding, or wrong port |

## checklist

- exactly one of polling or webhook per token
- `secret_token` set and verified
- `allowed_updates` from `resolve_used_update_types()`
- `setup_application` called
- acknowledgement policy deliberate; important work durably admitted before 2xx
- bot/update deduplication atomic across replicas; delivery recovery handled separately
- inline response not used where a confirmed result/message/file id is required
- owned background work drained/checkpointed before sessions and storage close
- persistent FSM storage when running more than one replica
- handlers idempotent against Telegram retries
- `delete_webhook()` before falling back to polling

## see also

- `using-aiogram` — polling and the run loop
- `aiogram-routing` — `feed_webhook_update` and `allowed_updates`
- `aiogram-errors` — `TelegramConflictError`
- `aiogram-fsm` — why storage matters across replicas
