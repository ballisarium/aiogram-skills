---
name: aiogram-routing
description: >
  Use when registering or debugging aiogram 3 routers, handler order, observers, propagation, or allowed_updates.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram routing

A `Router` owns a set of typed observers. A `Dispatcher` is the root router plus the run
loop. Registration order decides which handler wins, and **the first match stops
propagation**.

Confirm the surface in your environment before relying on it:

```bash
python skills/using-aiogram/tools/get-router-api.py
```

## when to use this skill

- adding a handler and deciding which router it belongs to
- a handler that never fires, or fires when it should not
- composing domain routers into an application
- restricting a whole router to a chat type, a state, or an admin check
- deciding what to put in `allowed_updates`
- feeding updates manually, in tests or from a custom transport

## observers

The valid decorators are exactly the keys of `Router.observers`. On aiogram 3.31.0:

| Observer | Update it handles |
|---|---|
| `message` | new messages in private chats, groups, supergroups |
| `edited_message` | edits to those |
| `channel_post` / `edited_channel_post` | channel posts |
| `business_connection` / `business_message` / `edited_business_message` / `deleted_business_messages` | Telegram Business |
| `callback_query` | inline button presses |
| `inline_query` / `chosen_inline_result` | inline mode |
| `poll` / `poll_answer` | polls |
| `my_chat_member` | the bot's own membership changed |
| `chat_member` | another member's status changed (needs explicit `allowed_updates`) |
| `chat_join_request` | join requests |
| `message_reaction` / `message_reaction_count` | reactions |
| `chat_boost` / `removed_chat_boost` | boosts |
| `pre_checkout_query` / `shipping_query` / `purchased_paid_media` | payments |
| `guest_message` / `managed_bot` / `subscription` | Bot API 10.x surfaces |
| `stopped_message_generation` | user stopped a draft generation (Bot API 10.3) |
| `error` | exceptions raised while handling an update |

`error` is special: it receives an `ErrorEvent`, not a Telegram update.

Never hardcode this table into code. Ask the package:

```bash
python skills/using-aiogram/tools/get-router-api.py --observer chat_member
```

## registration forms

```python
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="registration")


@router.message(Command("ping"))
async def ping(message: Message) -> None:
    await message.answer("pong")


async def pong(message: Message) -> None:
    await message.answer("ping")


router.message.register(pong, Command("pong"))
```

`register(callback, *filters, flags=None, **kwargs)` is the imperative equivalent of the
decorator. Use it when handlers are created at run time; prefer the decorator otherwise
because it keeps the filter next to the function.

## composition and order

```python
from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

admin = Router(name="admin")
shop = Router(name="shop")
fallback = Router(name="fallback")


@admin.message(Command("stats"))
async def stats(message: Message) -> None:
    await message.answer("stats")


@fallback.message()
async def unknown(message: Message) -> None:
    """A bare observer matches everything. It must be included last."""
    await message.answer("I did not understand that.")


dispatcher = Dispatcher()
dispatcher.include_routers(admin, shop, fallback)
```

Rules that follow from the propagation model:

1. **Depth-first, in include order.** A parent router's own handlers are checked before
   its children.
2. **First match wins.** Once a handler returns, no other handler sees the update.
3. **A router may be included once.** Including it twice raises a `RuntimeError`;
   including it into two parents does too.
4. **Catch-alls go last.** A bare `@router.message()` in the first included router
   swallows the entire bot.

"Last" is relative to the actual router tree, not the source file. A fallback on the
Dispatcher or a parent router runs **before** its child feature routers even if its
decorator appears below `include_routers(...)`. Put generic message and expired-callback
handlers in a dedicated final child router. A handler that returns early because an
input is unsupported has still consumed the update; put that rejection in a filter if
another flow should handle it.

The most common "my handler never fires" cause is a broader handler registered earlier.
The second is a router that was never included.

Check overlaps through the application's actual Dispatcher composition, not only by
calling a handler directly. A global command may need a router before active FSM flows,
while a state-specific invalid-document handler must precede a generic file converter.
Test both active-state and idle paths, plus return/cancel. Preserve a utility command's
state unless its contract explicitly exits the flow.

Keep one explicit router composition as the order source of truth. Check the assembled
tree with overlapping updates: global exits before state handlers, state-specific input
rejections before generic file/text features, unknown-state recovery before unconditional
fallbacks, and the unknown-callback answer last. A root/catch-all test must prove which
handler actually ran, not merely that the intended handler's filter can match. Test
caption commands as well as text commands and both active/idle states. Do not infer
precedence from an observer inventory or a public command menu.

`Command` can match a caption as well as text. Consume the matching text/entity pair
(`text`/`entities` or `caption`/`caption_entities`), or explicitly restrict the handler to
text messages. A command omitted from the public command menu still needs correct routing.

## router-wide filters

`router.<observer>.filter(*filters)` applies to every handler in that observer of that
router — including handlers in child routers, since the check runs during propagation.

```python
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

private = Router(name="private-only")
private.message.filter(F.chat.type == ChatType.PRIVATE)


@private.message()
async def only_in_dm(message: Message) -> None:
    """Never fires in a group: the router-level filter rejects it first."""
    await message.answer("dm only")
```

This is the clean way to build an admin router, a private-chat router, or a
maintenance-mode router — far better than repeating the same guard on every handler.

## observer-level middleware

Each observer carries its own middleware chain:

```python
from typing import Any

from aiogram import BaseMiddleware, Router
from aiogram.types import TelegramObject


class Noop(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: dict[str, Any]) -> Any:
        return await handler(event, data)


router = Router(name="mw")
router.message.outer_middleware(Noop())  # before filters, sees every message
router.message.middleware(Noop())  # after filters, only on a match
```

See the `aiogram-middlewares` skill for the distinction and when each matters.

## allowed_updates

Telegram only delivers the update types you ask for, and the setting is stored
server-side. Ask for exactly what your handlers use:

```python
from aiogram import Dispatcher, Router
from aiogram.types import ChatMemberUpdated, Message

router = Router(name="used-types")


@router.message()
async def on_message(message: Message) -> None: ...


@router.chat_member()
async def on_member(event: ChatMemberUpdated) -> None: ...


dispatcher = Dispatcher()
dispatcher.include_router(router)

used = dispatcher.resolve_used_update_types()
assert "message" in used
assert "chat_member" in used
```

Pass it at start-up: `await dispatcher.start_polling(bot, allowed_updates=used)` or
`await bot.set_webhook(url, allowed_updates=used)`.

aiogram `start_polling()` automatically resolves registered update types when
`allowed_updates` is omitted. Raw `getUpdates`/`setWebhook` have different defaults:
omission retains the previous setting; an empty list excludes `chat_member` and
reaction updates. Pass the resolved list explicitly when setting a webhook.

`resolve_used_update_types(skip_events={"..."})` drops specific names when you deliberately
do not want them requested.

## feeding updates manually

```python
import asyncio
import datetime

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Chat, Message, Update, User

router = Router(name="manual")


@router.message()
async def handle(message: Message) -> None: ...


async def main() -> None:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    bot = Bot(token="123456:TEST")

    update = Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.datetime.now(datetime.timezone.utc),
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="T"),
            text="hi",
        ),
    )
    try:
        await dispatcher.feed_update(bot, update)
    finally:
        await bot.session.close()


asyncio.run(main())
```

- `feed_update(bot, update, **kwargs)` takes a parsed `Update`; extra kwargs join workflow
  data, which is how tests inject fakes.
- `feed_raw_update(bot, dict, **kwargs)` takes the raw JSON dict.
- `feed_webhook_update(bot, update)` additionally supports returning a method to answer
  the webhook request inline.

## letting an update fall through

Returning `None` from a handler does **not** continue propagation — the handler matched,
so dispatch is finished. To decline an update after the fact, raise `SkipHandler`:

```python
from aiogram import Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import Message

router = Router(name="skip")


@router.message()
async def maybe(message: Message) -> None:
    if not (message.text or "").startswith("!"):
        raise SkipHandler  # hand the update to the next matching handler
    await message.answer("bang")
```

Prefer a precise filter. `SkipHandler` is for decisions that genuinely cannot be made
until the handler body runs.

## checklist

- every router reachable from the `Dispatcher` via `include_router`/`include_routers`
- specific handlers registered before general ones; catch-alls last
- router-wide constraints expressed with `.filter()` rather than repeated `if`s
- `allowed_updates` derived from `resolve_used_update_types()`
- no router included twice
- handler modules import cleanly with no `Bot` construction at module scope
- catch-alls live in the final child, not on a parent before its feature children
- assembled Dispatcher tested with overlapping states, invalid input and text/caption commands
- global exits clean up their flows; state-preserving utility commands leave them intact

## see also

- `using-aiogram` — the framework overview
- `aiogram-filters` — what to put inside the decorator
- `aiogram-middlewares` — inner vs outer chains
- `aiogram-errors` — `@router.error` and `ErrorEvent`
- `aiogram-testing` — driving routers with `feed_update`
