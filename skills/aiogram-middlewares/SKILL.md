---
name: aiogram-middlewares
description: >
  Use when implementing aiogram 3 middleware, workflow-data dependency injection, or handler flags.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram middlewares and dependency injection

Middleware wraps dispatch execution, and workflow data is its dependency injection.
The two are the same mechanism seen from two angles: a
middleware writes into `data`, and handlers declare what they want by parameter name.

## when to use this skill

- injecting a database session, config object, or service into handlers
- authentication, throttling, or feature gating that must short-circuit an update
- per-update resources with setup and teardown
- measuring or logging handler execution
- reading per-handler configuration inside a middleware
- a handler raising `TypeError` about a missing injected argument

## the contract

```python
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class Example(BaseMiddleware):
    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # before
        result = await handler(event, data)
        # after
        return result
```

Three behaviours follow from the signature:

- **Call `handler(event, data)` to continue.** Return without calling it and the update
  stops there — nothing downstream runs.
- **`data` is workflow data.** Values are available to downstream callables by name;
  inner-middleware injection cannot satisfy filters that have already run.
- **Return value propagates.** Returning a Telegram method object from a webhook-driven
  update lets aiogram answer the request inline.

The precise type of `handler` is
`Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]`; `Any` is used above so the
example stays readable.

## inner versus outer

This is the distinction that matters most, and the one most often got wrong.

| | `outer_middleware()` | `middleware()` |
|---|---|---|
| runs | before filters | after filters |
| sees | events of that type reaching this router | only events with a matching handler |
| can | reject an update before any filter runs | wrap the matched handler |
| use for | auth, throttling, bans, i18n, global context | per-handler resources, timing |

```python
from typing import Any

from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.types import TelegramObject


class Guard(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        return await handler(event, data)


dispatcher = Dispatcher()
router = Router(name="mw-scope")

dispatcher.update.outer_middleware(
    Guard()
)  # every update type, after aiogram's built-in error/user-context/FSM middleware
router.message.outer_middleware(Guard())  # every message reaching this router
router.message.middleware(Guard())  # only messages that matched a handler
```

`dispatcher.update.outer_middleware(...)` is the only place that sees *all* update types
in one chain — `update` is the root observer. Registering there is how you install a
global concern once instead of per observer.

A middleware registered on a parent router also covers its children.
"Before filters" means filters downstream of that middleware, not earlier filters on
ancestors. Put a value needed by a filter in an outer scope that actually wraps it.

## workflow data is the DI container

There is no `Provide[...]`, no container, no decorator. Values are put into a dict; a
handler receives them by declaring a parameter of the same name.

```python
from typing import Any

from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.types import Message, TelegramObject


class Config:
    admin_ids: frozenset[int] = frozenset({1})


class Repository:
    async def is_banned(self, user_id: int) -> bool:
        return False


class RepositoryMiddleware(BaseMiddleware):
    """Per-update scope: build it here, tear it down here."""

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        data["repository"] = Repository()
        return await handler(event, data)


router = Router(name="di")


@router.message()
async def handler(message: Message, config: Config, repository: Repository) -> None:
    if message.from_user is None or await repository.is_banned(message.from_user.id):
        return
    await message.answer(f"{len(config.admin_ids)} admins")


# Process-wide values go on the Dispatcher itself.
dispatcher = Dispatcher(config=Config())
dispatcher["build"] = "2026.08"
dispatcher.update.outer_middleware(RepositoryMiddleware())
dispatcher.include_router(router)

assert dispatcher["config"].admin_ids == frozenset({1})
```

Three scopes, and the right one is usually obvious:

| Scope | How | Use for |
|---|---|---|
| process | `Dispatcher(key=value)` or `dp["key"] = value` | config, connection pools, clients |
| run | `start_polling(bot, key=value)` | values known only at launch |
| update | middleware writing to `data` | sessions, transactions, request context |

Injection is by **name**, not type annotation; two differently named parameters do not
receive the same object just because their annotations match. Do not store a current
user, locale or transaction on `self`: one middleware instance handles concurrent
updates. Keep per-update values in `data` and process-wide clients/pools in workflow
data; do not share a mutable transaction as a process singleton.

### reserved keys

aiogram populates these itself. Overwriting them breaks the framework:

`bot`, `bots`, `dispatcher`, `event_router`, `event_update`, `event_from_user`,
`event_chat`, `event_context`, `state`, `raw_state`, `fsm_storage`, `handler`.

`event_from_user` and `event_chat` are especially useful in middleware — they are
resolved when that update carries a user/chat (either may be absent), so you do not need to branch on whether the
event is a `Message`, a `CallbackQuery`, or a `ChatMemberUpdated`.

### missing keys fail late

Requesting a name that is not in workflow data raises `TypeError` when the handler is
called, not when it is registered. A handler that "randomly 500s" usually declares a
dependency whose middleware was never installed, or was installed on a different router.

## setup and teardown

Put teardown in `finally`, and decide deliberately whether a failing handler commits:

```python
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class UnitOfWork:
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...


class UnitOfWorkMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        uow = UnitOfWork()
        data["uow"] = uow
        try:
            result = await handler(event, data)
            await uow.commit()
        except BaseException:  # roll back cancellation too, then propagate it
            await uow.rollback()
            raise
        else:
            return result
        finally:
            await uow.close()
```

Do not swallow the exception here. Let it reach `@router.error`, which is where logging
and user-facing failure messages belong.
`UnitOfWork` is an application stub, not an aiogram database API. A handled refusal that
returns normally also reaches `commit()`; choose the success/rollback contract explicitly.
Keep write transactions short. Rolling back storage cannot undo a Telegram send already
accepted inside the handler; use explicit effect checkpoints for durable operations.
Repeated cancellation can interrupt awaited rollback/close: do not return an unsettled
connection to a pool. Use the application's cancellation-safe cleanup and recovery policy.

## short-circuiting

An outer middleware that returns without calling `handler` drops the update silently:

```python
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import CallbackQuery, TelegramObject, Update


class BanList(BaseMiddleware):
    def __init__(self, banned: frozenset[int]) -> None:
        self.banned = banned

    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is not None and user.id in self.banned:
            # Still answer callback queries, or the client spins forever.
            callback = event.callback_query if isinstance(event, Update) else event
            if isinstance(callback, CallbackQuery):
                await callback.answer("You are blocked.", show_alert=True)
            return None
        return await handler(event, data)


dispatcher = Dispatcher()
dispatcher.update.outer_middleware(BanList(frozenset({999})))
```

When you drop a `CallbackQuery`, answer it first. Dropping it silently leaves a spinner
on the user's button until the query expires.

## flags

Flags attach metadata to a handler that middleware can read. `aiogram.flags` is a
generator: any attribute becomes a flag decorator.

```python
from typing import Any

from aiogram import BaseMiddleware, Router, flags
from aiogram.dispatcher.flags import get_flag
from aiogram.types import Message, TelegramObject

router = Router(name="flags")


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        limit = get_flag(data, "rate_limit", default=0)
        if limit:
            pass  # apply the per-handler budget
        return await handler(event, data)


@router.message()
@flags.rate_limit(5)
@flags.chat_action("typing")
async def slow(message: Message) -> None:
    await message.answer("done")


router.message.middleware(RateLimitMiddleware())
```

`get_flag(data, name, default=None)` reads from workflow data, where aiogram has placed
the matched `handler`. Flags are therefore only visible to **inner** middleware — an
outer middleware runs before a handler is chosen and has no flags to read.

Flags can also be passed at registration: `router.message.register(fn, flags={"rate_limit": 5})`.

## bundled middleware

aiogram ships three you should know about:

```python
from aiogram import Dispatcher, Router
from aiogram.client.session.middlewares.request_logging import RequestLogging
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from aiogram.utils.chat_action import ChatActionMiddleware

router = Router(name="bundled")

# Answers every callback query automatically after the handler returns.
router.callback_query.middleware(CallbackAnswerMiddleware())

# Consumes the @flags.chat_action("typing") flag.
router.message.middleware(ChatActionMiddleware())

dispatcher = Dispatcher()
dispatcher.include_router(router)
```

`RequestLogging` is a **session** middleware, not a dispatch middleware — it wraps
outgoing API calls:

```python
from aiogram import Bot
from aiogram.client.session.middlewares.request_logging import RequestLogging

bot = Bot(token="123456:TEST")
bot.session.middleware(RequestLogging(ignore_methods=[]))
```

`CallbackAnswerMiddleware(pre=False, text=None, show_alert=None, url=None, cache_time=None)`
answers after the handler by default; `pre=True` answers before it runs.

Choose one ACK owner. Default post-handler answering is too late for a handler that
waits on rendering, storage, or queue work. Pre-answering cannot later be changed into
a branch-specific rejection alert. For that flow, perform cheap validation and one
explicit ACK before slow work, and disable automatic answering for the same handler
using the middleware's supported flags. Include middleware and lock ordering when
testing ACK timing; a correct first line in the handler does not bypass an earlier wait.

## ordering

Middleware runs in registration order, outermost first: dispatcher `update` outer →
router outer (parents before children) → filters → router inner → handler. Unwinding
happens in reverse.

Register the cheapest rejections first. A ban check that costs a dict lookup should run
before an i18n middleware that touches storage.
New `dispatcher.update.outer_middleware(...)` registrations follow the built-in error,
user-context and FSM middleware. With event isolation enabled, the FSM middleware can
await a lock and storage before a custom middleware or handler starts. An ACK on the
first handler line therefore does not prove prompt answering. Verify the assembled chain
under contention; do not remove isolation or user-context setup merely to move the ACK.

## checklist

- global concerns on `dispatcher.update.outer_middleware`, not repeated per observer
- rejections in **outer** middleware, resources in **inner** middleware
- every `data[...]` write matched by a handler parameter somewhere
- teardown in `finally`; exceptions re-raised, not swallowed
- callback queries answered before an update is dropped
- no reserved workflow-data key overwritten
- flags read with `get_flag`, and only from inner middleware
- filter dependencies injected before those filters; per-update data never stored on `self`
- registration order tested through dispatch, including built-in FSM waits and ACK ownership
- rollback/close complete on cancellation; storage rollback never claimed to undo remote effects

## see also

- `using-aiogram` — the overview
- `aiogram-routing` — where middleware attaches
- `aiogram-rate-limits` — throttling built on outer middleware
- `aiogram-errors` — what happens to exceptions middleware re-raises
- `aiogram-fsm` — `state` is injected by aiogram's own FSM middleware
