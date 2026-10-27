# aiogram

aiogram is an asynchronous framework for the Telegram Bot API built on `asyncio`,
`aiohttp`, and `pydantic` v2. Every Bot API object is a pydantic model, every Bot API
method is a model too, and dispatching is done by routers holding typed observers.

Facts below were verified against **aiogram 3.31.0** (Telegram Bot API **10.3**) on
**2026-09-07**. Verify them again in your own environment before relying on any of it:

```bash
python skills/using-aiogram/tools/check-version.py
```

## when to use this skill

- writing, reviewing, or refactoring any bot that imports `aiogram`
- registering handlers and wiring routers into a `Dispatcher`
- choosing filters, or writing a custom `BaseFilter`
- injecting dependencies (database sessions, config, services) into handlers
- building keyboards and typed `callback_data`
- driving multi-step conversations with FSM
- sending or receiving files, albums, and formatted text
- choosing between long polling and a webhook, and shutting either down cleanly
- diagnosing `TelegramBadRequest`, `TelegramRetryAfter`, or a handler that never fires
- porting aiogram 2.x code to 3.x

Deeper topics live in sibling skills; see [see also](#see-also) at the end.

## tools

`skills/using-aiogram/tools/` holds lookup scripts that read **the aiogram installed in the
current environment**, so they stay correct across upgrades. Prefer them over recalling
an API from memory.

```bash
python skills/using-aiogram/tools/check-version.py               # installed versions + drift check
python skills/using-aiogram/tools/get-method.py sendMessage      # Bot API method -> args, types, return
python skills/using-aiogram/tools/get-type.py Message            # aiogram type -> fields + shortcuts
python skills/using-aiogram/tools/get-filter.py Command          # filter -> constructor signature
python skills/using-aiogram/tools/get-router-api.py --observers  # every valid @router.<name>()
python skills/using-aiogram/tools/get-exception.py --tree        # exception hierarchy
python skills/using-aiogram/tools/search-source.py <pattern>     # grep installed aiogram source
python skills/using-aiogram/tools/validate-example.py <path.md>  # run the examples in a Markdown file
```

Every tool supports `--help`; most support `--list` and `--json`. They exit `1` when a
name is unknown or drift is detected, so they compose into CI steps.

## install and pin

```bash
pip install "aiogram==3.31.0"
```

- `requires_python` for 3.31.0 is `>=3.10,<3.15`.
- Optional extras declared by the package: `fast` (uvloop + aiodns), `redis`, `mongo`,
  `i18n` (babel), `proxy`, `cli`, `signature` (cryptography), `docs`.
- Pin the major version. aiogram 3 and aiogram 2 share a package name and nothing else.

## minimal bot

This is the whole shape of an aiogram 3 program: a `Router` holds handlers, a
`Dispatcher` holds routers, and `Bot` is passed in at run time.

```python
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router(name=__name__)


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer("Hello! I am alive.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Points that matter:

- The token comes from the environment. Never inline a real token, and never commit one.
- `DefaultBotProperties` is the only supported way to set a default `parse_mode` in
  aiogram 3. The 2.x `Bot(parse_mode=...)` keyword is gone.
- `Message.answer` sends to the same chat; there is no global bot object to reach for.
- Everything runs under one `asyncio.run`. There is no `executor` module.

## project structure

Any layout works, but this one keeps registration traceable and imports side-effect free:

```text
bot/
├── __main__.py          # entrypoint: builds Bot + Dispatcher, starts polling/webhook
├── config.py            # settings loaded from the environment
├── handlers/
│   ├── __init__.py      # aggregates domain routers into one router
│   ├── common.py        # router = Router(name="common")
│   └── admin.py
├── keyboards/
├── states.py            # StatesGroup definitions
├── middlewares/
├── services/            # domain logic; isolate Telegram effects from CPU kernels
└── repositories/        # data access, no aiogram imports
tests/
```

Two rules make this layout safe:

1. **A module must not start anything on import.** No `Bot(...)` at module scope, no
   `asyncio.run(...)`, no config validation that raises at import time. Handler modules
   are imported by tests and by the router aggregator; importing them must be free.
2. **Separate computation from Telegram orchestration.** Handlers translate events into
   service calls; domain computations do not need a Bot. An API-facing service may use
   aiogram, but a process worker's CPU module must not import the dispatcher or start
   application resources just to render. This keeps unit tests and worker startup small.

The aggregator is plain composition:

```python
from aiogram import Router


def build_router() -> Router:
    """Build fresh domain routers; order decides which handler wins."""
    admin_router = Router(name="admin")  # register that domain's handlers here
    common_router = Router(name="common")
    root = Router(name="root")
    root.include_routers(admin_router, common_router)
    return root


assert build_router() is not build_router()
```

## keep the event loop responsive

Handlers should perform cheap validation and orchestration, then await asynchronous I/O
or submit work to the existing worker layer. `async def` and a typing indicator do not
make synchronous file I/O, rendering, encoding or archive creation asynchronous.

Use `asyncio.to_thread()` for blocking I/O and suitable native work that releases the GIL;
use an owned process/executor for substantial pure-Python CPU work. If work must stop on
cancel, own its process lifecycle; cancelling a running executor future is insufficient.
Bound admission as well as active workers; spawning unlimited tasks only moves
the backlog. Keep inexpensive input limits before expensive parsing; reuse the owning
validator rather than creating a weaker preflight path.

An offload is also a concurrency change. A cache of native font/image/parser objects may
return the same mutable object to several threads; even a read can trigger lazy mutation.
Verify the library's guarantees. Use independent instances or serialise all access with
a `threading.Lock` inside the synchronous worker, never block the event loop on that
lock. An `asyncio.Lock` is not a cross-thread lock. Check cold-cache concurrent calls, not
only warmed sequential ones. Cancelling the await does not terminate its running thread.

For stateful work, after a queue wait, lock or offloaded validation, re-read owner/state/revision
before committing a transition or sending a result. Another update may have cancelled
or replaced the draft while this handler was suspended. See
[durable operations](durable-operations.md) for cancellation and recovery.

## Bot, Dispatcher, Router

**`Bot`** is the API client. Verified constructor:

```text
Bot(token: str, session: BaseSession | None = None,
    default: DefaultBotProperties | None = None, **kwargs)
```

`Bot` is also callable: `await bot(SendMessage(chat_id=1, text="hi"))` is equivalent to
`await bot.send_message(chat_id=1, text="hi")`. Use whichever reads better; the method
objects are handy when you need to return a call from a webhook handler.

**`Dispatcher`** is the root router plus the run loop. Verified constructor:

```text
Dispatcher(*, storage: BaseStorage | None = None,
           fsm_strategy: FSMStrategy = FSMStrategy.USER_IN_CHAT,
           events_isolation: BaseEventIsolation | None = None,
           disable_fsm: bool = False, name: str | None = None, **kwargs)
```

Extra `**kwargs` become workflow data available to every handler — that is aiogram's
dependency injection, covered below.

**`Router`** groups handlers. `Router(*, name: str | None = None)`. A router can be
included exactly once; including it twice raises. Nesting is a tree, and events
propagate depth-first in registration order.

```python
from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

payments = Router(name="payments")
support = Router(name="support")


@payments.message(Command("pay"))
async def pay(message: Message) -> None:
    await message.answer("paying")


dispatcher = Dispatcher()
dispatcher.include_routers(payments, support)
```

`include_routers(*routers)` is the plural form; `include_router(router)` returns the
router it was given.

## handlers and update types

The valid decorators are exactly the observers a `Router` exposes. Ask the installed
package rather than guessing:

```bash
python skills/using-aiogram/tools/get-router-api.py --observers
```

On aiogram 3.31.0 that list is:

`business_connection`, `business_message`, `callback_query`, `channel_post`,
`chat_boost`, `chat_join_request`, `chat_member`, `chosen_inline_result`,
`deleted_business_messages`, `edited_business_message`, `edited_channel_post`,
`edited_message`, `error`, `guest_message`, `inline_query`, `managed_bot`, `message`,
`message_reaction`, `message_reaction_count`, `my_chat_member`, `poll`, `poll_answer`,
`pre_checkout_query`, `purchased_paid_media`, `removed_chat_boost`, `shipping_query`,
`stopped_message_generation`, `subscription`

Each observer offers three registration forms:

```python
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

router = Router(name="registration-forms")


# 1. decorator - the usual form
@router.message(Command("help"))
async def show_help(message: Message) -> None:
    await message.answer("help")


# 2. imperative - useful when handlers are built dynamically
async def show_about(message: Message) -> None:
    await message.answer("about")


router.message.register(show_about, Command("about"))


# 3. callback queries answer the query, not just the message
@router.callback_query(F.data == "ping")
async def ping(callback: CallbackQuery) -> None:
    await callback.answer()
```

**Always answer a callback query.** Telegram shows a spinner on the button until
`answer()` is called, and the query id expires. If every callback handler in a router
should answer automatically, `CallbackAnswerMiddleware()` defaults to `pre=False`:
it answers after the handler. Use `CallbackAnswerMiddleware(pre=True)` for an early ACK
only when a fixed answer suits every branch. Manual `callback.answer()` calls do not
update the middleware's answer tracking; choose one ACK owner. Handlers needing rejection
alerts should answer explicitly and disable automatic answering for those handlers.

Handler parameters are resolved by name from workflow data; a handler may declare only
the arguments it needs. The event itself is the first positional argument.

## filters

Filters decide whether a handler accepts an event. Multiple filters on one handler are
ANDed. See the `aiogram-filters` skill for the full surface; the essentials:

```python
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.types import Message

router = Router(name="filters-tour")


@router.message(CommandStart(deep_link=True))
async def start_with_payload(message: Message, command: CommandObject) -> None:
    """CommandStart injects a CommandObject; command.args holds the deep-link payload."""
    await message.answer(f"payload: {command.args}", parse_mode=None)


@router.message(Command("ban", prefix="/!"))
async def ban(message: Message) -> None:
    await message.answer("banned")


# F is a magic-filter over the event object: attribute access becomes a predicate.
@router.message(F.text.lower().startswith("hi"))
async def greet(message: Message) -> None:
    await message.answer("hi")


@router.message(F.photo)
async def got_photo(message: Message) -> None:
    await message.answer("nice photo")


@router.message(F.chat.type == ChatType.PRIVATE, StateFilter(None))
async def private_stateless(message: Message) -> None:
    await message.answer("private chat, no active state")
```

`Command` injects a `CommandObject` (fields: `prefix`, `command`, `mention`, `args`,
`regexp_match`, `magic_result`) into any handler that declares a `command` parameter.

**Ordering is everything.** The first handler whose filters pass wins, and propagation
stops there. Register specific handlers before catch-alls, and keep a bare
`@router.message()` last — or in a router included last.

## dependency injection

aiogram has no separate DI container. Anything placed in **workflow data** is offered to
every handler, filter, and middleware by parameter name.

Three ways in, from broadest to narrowest:

```python
import asyncio
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.types import Message, TelegramObject

router = Router(name="di")


class Repository:
    async def count_users(self) -> int:
        return 0


# 1. constructor kwargs / item assignment on the Dispatcher - process-wide singletons
def build_dispatcher(repository: Repository) -> Dispatcher:
    dispatcher = Dispatcher(repository=repository)
    dispatcher["app_name"] = "demo"
    return dispatcher


# 2. start_polling kwargs - per-run values; feed_update kwargs apply to one update
async def run(dispatcher: Dispatcher, bot: Bot) -> None:
    await dispatcher.start_polling(bot, extra="value")


# 3. middleware - per-update values, the right place for scoped resources
class SessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["session"] = object()  # open a real session here
        try:
            return await handler(event, data)
        finally:
            pass  # close it here


@router.message()
async def handler(message: Message, repository: Repository, app_name: str) -> None:
    """Declare only what you need; unused workflow data is simply not passed."""
    await message.answer(f"{app_name}: {await repository.count_users()}", parse_mode=None)
```

Names aiogram itself puts into workflow data include `bot`, `bots`, `dispatcher`,
`event_router`, `event_update`, `event_from_user`, `event_chat`, `state` (an
`FSMContext`), `raw_state`, and `handler`. Do not shadow them.

Requesting a parameter that is not in workflow data raises `TypeError` at handler call
time, not at registration time — this is a common cause of "handler silently 500s".

## middleware

`BaseMiddleware.__call__(self, handler, event, data)` — call `await handler(event, data)`
to continue, or return without calling it to stop the update.

- `router.<observer>.outer_middleware(m)` runs **before** filters. Use it for
  authentication, throttling, and anything that should short-circuit the update.
- `router.<observer>.middleware(m)` runs **after** filters, only when a handler matched.
  Use it for per-handler resources.
- `router.update.outer_middleware(m)` on the `Dispatcher` covers every update type.

```python
import time
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject


class TimingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        started = time.monotonic()
        try:
            return await handler(event, data)
        finally:
            data["elapsed"] = time.monotonic() - started


dispatcher = Dispatcher()
dispatcher.update.outer_middleware(TimingMiddleware())
```

Handler **flags** let a middleware read per-handler configuration:

```python
from aiogram import Router, flags
from aiogram.dispatcher.flags import get_flag
from aiogram.types import Message

router = Router(name="flags")


@router.message()
@flags.chat_action("typing")
@flags.rate_limit(5)
async def slow_handler(message: Message) -> None:
    await message.answer("done")


# inside a middleware: get_flag(data, "rate_limit", default=0)
assert get_flag({"handler": None}, "rate_limit", default=0) == 0
```

`aiogram.utils.chat_action.ChatActionMiddleware` already consumes the `chat_action` flag.

## finite state machine

FSM is for conversations that span several updates. A single-step action needs no state.

```python
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

router = Router(name="fsm")


class Registration(StatesGroup):
    waiting_for_name = State()
    waiting_for_age = State()


@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.")


@router.message(Command("register"))
async def start_registration(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Registration.waiting_for_name)
    await message.answer("What is your name?")


@router.message(Registration.waiting_for_name, F.text)
async def got_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(Registration.waiting_for_age)
    await message.answer("How old are you?")


@router.message(Registration.waiting_for_age, F.text.regexp(r"^\d{1,3}$"))
async def got_age(message: Message, state: FSMContext) -> None:
    data = await state.update_data(age=int(message.text or "0"))
    await state.clear()
    await message.answer(f"Registered {data['name']}, age {data['age']}", parse_mode=None)


@router.message(Registration.waiting_for_age)
async def bad_age(message: Message) -> None:
    """Stay in the state on invalid input; never advance silently."""
    await message.answer("Please send a number.")
```

- A `State` object used directly as a filter is shorthand for `StateFilter(that_state)`.
- `state.clear()` drops both the state and the data. Call it on success, cancel, and
  unrecoverable failure — otherwise users get stuck.
- Starting a fresh registration clears the previous attempt's data before setting its
  first state. Clearing FSM storage does not remove Telegram keyboards; read any stored
  message IDs before clearing and retire old controls separately.
- The default storage is `MemoryStorage`, which loses everything on restart. Use
  persistent storage when conversations must survive a restart.
- `FSMStrategy` members: `USER_IN_CHAT` (default), `CHAT`, `GLOBAL_USER`,
  `USER_IN_TOPIC`, `CHAT_TOPIC`.

See the `aiogram-fsm` skill for storage, key builders, and isolation.

## scenes

`aiogram.fsm.scene` layers a class-based wizard over FSM. The official documentation
labels it **experimental**: *"This feature is experimental and may be changed in future
versions."* Prefer plain FSM for code that must survive minor upgrades untouched. If you
do use scenes, see the `aiogram-scenes` skill.

## callback data

Use `CallbackData` for structured payloads; short constants are fine for simple actions.
Its typed, size-checked factory avoids ad hoc parsing. The Telegram limit is 64 bytes,
and aiogram enforces it on `pack()`
(`MAX_CALLBACK_LENGTH = 64`).

```python
from aiogram import Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="callbacks")


class OrderAction(CallbackData, prefix="order"):
    action: str
    order_id: int


def order_keyboard(order_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Confirm", callback_data=OrderAction(action="confirm", order_id=order_id))
    builder.button(text="Cancel", callback_data=OrderAction(action="cancel", order_id=order_id))
    builder.adjust(2)
    return builder


@router.callback_query(OrderAction.filter())
async def on_order(callback: CallbackQuery, callback_data: OrderAction) -> None:
    await callback.answer(f"{callback_data.action} #{callback_data.order_id}")


assert OrderAction(action="confirm", order_id=7).pack() == "order:confirm:7"
assert OrderAction.unpack("order:confirm:7").order_id == 7
```

The filter injects the parsed instance as `callback_data`. Narrow further with a magic
filter: `OrderAction.filter(F.action == "confirm")`.

Treat the payload as routing data, not storage. Keep large context server-side and put
only an identifier on the button. See `aiogram-callback-data`.

## keyboards

Use builders for dynamic rows. Direct markup models remain valid for small static menus.

```python
from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

inline = InlineKeyboardBuilder()
inline.button(text="Docs", url="https://docs.aiogram.dev/")
inline.button(text="Ping", callback_data="ping")
inline.adjust(1, 1)
inline_markup = inline.as_markup()

reply = ReplyKeyboardBuilder()
reply.add(KeyboardButton(text="Share phone", request_contact=True))
reply_markup = reply.as_markup(resize_keyboard=True, one_time_keyboard=True)
```

`adjust(*sizes, repeat=False)` reflows buttons into rows. The reply builder's `as_markup(**kwargs)` passes
extra keyword arguments straight to the markup model, which is how `resize_keyboard`
reaches `ReplyKeyboardMarkup`. See `aiogram-keyboards`.

## formatting messages

Prefer entities for composed text; preserve an existing safe HTML contract:

1. **`aiogram.utils.formatting`** — composes `MessageEntity` objects directly. No parse
   mode to parse. Nesting and length rules still apply.
2. **`aiogram.html` / `aiogram.md` helpers** with an explicit `parse_mode`; quote dynamic
   text before wrapping it. `html.bold()` does not escape its argument.
3. Plain output with `parse_mode=None` when no formatting is needed; omitting it may
   inherit the bot's HTML/Markdown default.

```python
from aiogram.utils.formatting import Bold, Text, as_list

content = Text("Hello, ", Bold("world"), "!")
payload = content.as_kwargs()
assert payload["text"] == "Hello, world!"
assert payload["entities"][0].type == "bold"

report = as_list(Text("line one"), Text("line two"))
assert "line one" in report.as_html()
```

`as_kwargs()` returns `{"text": ..., "entities": [...], "parse_mode": None}` — splat it
straight into `message.answer(**payload)`. See `aiogram-formatting`.

## files

```python
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, FSInputFile, Message, URLInputFile

router = Router(name="files")


@router.message(Command("files"))
async def send_files(message: Message, bot: Bot) -> None:
    await message.answer_document(FSInputFile("report.pdf", filename="report.pdf"))
    await message.answer_photo(URLInputFile("https://example.com/cat.jpg"))
    await message.answer_document(BufferedInputFile(b"raw bytes", filename="data.bin"))


@router.message(F.document)
async def receive_file(message: Message, bot: Bot) -> None:
    if message.document:
        # file_id is reusable and cheap; re-send by id instead of re-uploading.
        await message.answer_document(message.document.file_id)
        await bot.download(message.document, destination="downloaded.bin")
```

`file_id` values are **bot-scoped** — an id obtained by one bot cannot be used by
another. See `aiogram-files`.

## media groups

Outgoing albums use `MediaGroupBuilder`:

```python
from aiogram.utils.media_group import MediaGroupBuilder

album = MediaGroupBuilder(caption="Album caption")
album.add_photo(media="https://example.com/1.jpg")
album.add_photo(media="https://example.com/2.jpg")
media = album.build()
assert len(media) == 2
```

Incoming albums arrive as **separate updates sharing a `media_group_id`**. aiogram has no
built-in aggregator; you must buffer them yourself. See `aiogram-media-groups`.

## polling

```python
import asyncio
import os

from aiogram import Bot, Dispatcher


async def main() -> None:
    bot = Bot(token=os.environ["BOT_TOKEN"])
    dispatcher = Dispatcher()
    await dispatcher.start_polling(
        bot,
        allowed_updates=dispatcher.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

- `resolve_used_update_types()` inspects registered handlers and asks Telegram only for
  the update types you actually handle. `start_polling()` calls this automatically when
  `allowed_updates` is omitted; `set_webhook()` needs the list passed explicitly.
- `run_polling(...)` is the blocking synchronous wrapper around `start_polling`; call it
  from sync code instead of `asyncio.run`.
- `handle_signals=True` (default) installs SIGINT/SIGTERM handlers.
  `close_bot_session=True` (default) closes the aiohttp session on exit.
- Only one polling consumer per token may run at a time; a second raises
  `TelegramConflictError`.

## webhook

aiogram ships an aiohttp integration. Nothing else is bundled.

```python
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

WEBHOOK_PATH = "/webhook"


def build_app(bot: Bot, dispatcher: Dispatcher, secret: str, base_url: str) -> web.Application:
    app = web.Application()

    async def on_startup(bot: Bot) -> None:
        await bot.set_webhook(
            url=f"{base_url}{WEBHOOK_PATH}",
            secret_token=secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )

    dispatcher.startup.register(on_startup)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=secret,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)
    return app


# Constructing the app does not start the server or change a real webhook.
app = build_app(Bot(token="123456:TEST"), Dispatcher(), "example-secret", "https://example.com")
```

- `secret_token` is verified against Telegram's `X-Telegram-Bot-Api-Secret-Token` header.
  Always set it; without it anyone who learns the URL can inject updates.
- `setup_application` wires dispatcher startup/shutdown into the aiohttp lifecycle.
- Run **either** polling **or** a webhook, never both. Call `bot.delete_webhook()` before
  switching back to polling.
- `TokenBasedRequestHandler` serves many bots from one app, keyed by token in the path.

See `aiogram-webhooks`.

## errors

The hierarchy, read from the installed package (`get-exception.py --tree`):

```text
AiogramError
├── CallbackAnswerException
├── ClientDecodeError
├── DetailedAiogramError
│   ├── DataNotDictLikeError
│   ├── TelegramAPIError
│   │   ├── TelegramBadRequest
│   │   ├── TelegramConflictError
│   │   ├── TelegramEntityTooLarge      (via TelegramNetworkError)
│   │   ├── TelegramForbiddenError
│   │   ├── TelegramMigrateToChat
│   │   ├── TelegramNetworkError
│   │   ├── TelegramNotFound
│   │   ├── TelegramRetryAfter
│   │   ├── TelegramServerError
│   │   │   └── RestartingTelegram
│   │   └── TelegramUnauthorizedError
│   └── UnsupportedKeywordArgument
└── SceneException
```

Register a router-level error handler with `@router.error(...)`; the handler receives an
`ErrorEvent` with `update` and `exception` fields.

```python
import logging
import traceback

from aiogram import Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent

router = Router(name="errors")


@router.error(ExceptionTypeFilter(TelegramForbiddenError))
async def user_blocked_bot(event: ErrorEvent) -> None:
    """Inspect the failing method/chat; Forbidden is not always a blocked private user."""
    logging.warning("forbidden for update %s", event.update.update_id)


@router.error()
async def catch_all(event: ErrorEvent) -> None:
    logging.error(
        "unhandled error: %s\n%s",
        type(event.exception).__name__,
        "".join(traceback.format_tb(event.exception.__traceback__)),
    )
```

Exception messages (notably `ClientDecodeError` response data) and chains may contain
private values. This logs type and frames, not exception strings, chains or locals; see
[error diagnostics](../../aiogram-errors/SKILL.md#reading-telegrambadrequest).
`AiogramError` does not include `TokenValidationError`, `SkipHandler` or `CancelHandler`.

Common causes worth recognising:

| Exception | Typical cause |
|---|---|
| `TelegramBadRequest: message is not modified` | editing a message to identical text and markup |
| `TelegramBadRequest: query is too old` | callback answered too late, or never |
| `TelegramForbiddenError` | user blocked the bot, or bot removed from the chat |
| `TelegramConflictError` | two pollers on one token, or polling while a webhook is set |
| `TelegramRetryAfter` | flood limit hit; honour `retry_after` |
| `TelegramUnauthorizedError` | invalid or revoked token |

See `aiogram-errors`.

## rate limits

**aiogram has no built-in throttler.** It surfaces `TelegramRetryAfter` (carrying
`retry_after` seconds) and ships `aiogram.utils.backoff.Backoff`, but pacing outbound
calls is your code. Do not describe a custom throttler as an aiogram feature.

```python
import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter


async def send_with_retry(bot: Bot, chat_id: int, text: str, attempts: int = 3) -> None:
    """Honour Telegram's own backoff instruction rather than guessing a delay."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return
        except TelegramRetryAfter as error:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(error.retry_after)
```

Telegram's documented soft limits: roughly 30 messages/second overall, ~1 message/second
per chat, ~20 messages/minute per group. See `aiogram-rate-limits`.

## testing

`aiogram.test_utils` is **not** shipped in the PyPI wheel — `mocked_bot.py` lives in the
aiogram repository's `tests/` directory and is not importable from an installed release.
Verified with `python -c "import aiogram.test_utils"` → `ModuleNotFoundError`.

Test at the dispatcher boundary with `feed_update`, backed by a session that never
touches the network. `BaseSession` has exactly three abstract methods — `make_request`,
`stream_content`, and `close` — so a recording fake is short:

```python
import asyncio
import datetime
from collections.abc import AsyncGenerator
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import CommandStart
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User


def make_router() -> Router:
    router = Router(name="under-test")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer("Hello!")

    return router


class RecordingSession(BaseSession):
    """Records outgoing API calls and answers them with canned results."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.calls.append(method)
        assert isinstance(method, SendMessage), type(method).__name__
        now = datetime.datetime.now(datetime.timezone.utc)
        return Message(
            message_id=999,
            date=now,
            chat=Chat(id=1, type="private"),
            text=getattr(method, "text", None),
        ).as_(bot)

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def close(self) -> None:
        return None


def make_update(text: str) -> Update:
    now = datetime.datetime.now(datetime.timezone.utc)
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=now,
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="Tester"),
            text=text,
        ),
    )


async def check() -> None:
    session = RecordingSession()
    bot = Bot(token="123456:TEST", session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(make_router())

    try:
        await dispatcher.feed_update(bot, make_update("/start"))

        assert len(session.calls) == 1
        sent = session.calls[0]
        assert isinstance(sent, SendMessage)
        assert sent.text == "Hello!"
    finally:
        await dispatcher.storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(check())
```

See `aiogram-testing` for a reusable fake session that records outgoing calls.

## graceful shutdown

Register lifecycle hooks on the dispatcher; aiogram awaits them around the run loop.

```python
from aiogram import Bot, Dispatcher

dispatcher = Dispatcher()


@dispatcher.startup()
async def on_startup(bot: Bot) -> None:
    """Initialise application resources here; delivery mode is configured deliberately."""


@dispatcher.shutdown()
async def on_shutdown() -> None:
    """Close pools and flush buffers here; the loop is still running."""
```

`start_polling(handle_signals=True)` (the default) turns SIGINT/SIGTERM into a clean
`stop_polling()`. If you manage signals yourself, pass `handle_signals=False` and call
`dispatcher.stop_polling()`.

Always close the API session when you built the `Bot` yourself and disabled
`close_bot_session`: `await bot.session.close()`.

## configuration and secrets

- Read the token from the environment or a secret manager. Never commit it, never log it,
  never put it in a default argument.
- `aiogram.utils.token.validate_token` requires `"<digits>:<non-empty>"` without whitespace;
  a syntactically valid fake token such as `123456:TEST` is enough for offline tests.
- Keep configuration in one module that reads the environment once, and inject the
  resulting object through workflow data.
- A leaked token is revoked with `/revoke` in `@BotFather`.

## localisation is an output contract

For multilingual bots, use the existing locale catalogue for every message, button, callback
notification, validation error and background-worker result. Small examples here use
literal text only to demonstrate APIs. Keep keys and format placeholders consistent
across supported locales, including error, Back and recovery branches. Inject the
translator/language through workflow data; pass the required language policy across a
worker handoff instead of silently using a process-global default.

Compose the whole surface through one renderer for initial entry and restoration.
Validate final text, markup and placeholder substitutions in every locale; key parity
alone cannot prove translation meaning, button layout or Telegram rendering. Escape
untrusted substitutions for the output grammar; alerts and button labels are plain text.

## common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| handler never fires | a broader handler registered earlier consumed the update | reorder; register catch-alls last |
| handler never fires | router never included | `dispatcher.include_router(...)` |
| `chat_member` updates never arrive | not in `allowed_updates` | `allowed_updates=dispatcher.resolve_used_update_types()` |
| button spins forever | callback query not answered | `await callback.answer()` |
| `TypeError` in handler | requested a workflow-data key that does not exist | inject it in a middleware or on the dispatcher |
| state disappears across restarts | `MemoryStorage` loses it | use persistent storage if required |
| `message is not modified` | edited with identical content | compare before editing, or catch it |
| `TelegramConflictError` | webhook still set, or a second poller | `delete_webhook()`, run one consumer |
| callback payload rejected | over 64 bytes | shorten fields; store context server-side |
| connections churn or sessions leak | creating a `Bot` per update | reuse one `Bot` per token for the application lifetime; close its session on shutdown |
| API call never executes | coroutine created but not awaited | `await` asynchronous calls; creating a coroutine does not run it |
| all chats stall | blocking `requests` or `time.sleep` inside a handler | use asynchronous I/O and `asyncio.sleep`; offload unavoidable blocking work |

## aiogram 2.x versus 3.x

3.x is a rewrite; 2.x code does not run. Most bad examples on the internet are 2.x.

| aiogram 2.x | aiogram 3.x |
|---|---|
| `from aiogram import executor` | removed; use `asyncio.run(dispatcher.start_polling(bot))` |
| `executor.start_polling(dp)` | `await dispatcher.start_polling(bot)` |
| `@dp.message_handler(...)` | `@router.message(...)` |
| `@dp.callback_query_handler(...)` | `@router.callback_query(...)` |
| `Dispatcher(bot)` | `Dispatcher()`; the bot is passed at run time |
| `Bot(token, parse_mode="HTML")` | `Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))` |
| `types.Message` global-bot shortcuts | shortcuts resolve the bot from the event context |
| `state='*'` | `StateFilter("*")` |
| `dp.register_message_handler(fn, ...)` | `router.message.register(fn, ...)` |
| `middleware.setup(...)` | `router.message.middleware(...)` / `.outer_middleware(...)` |
| filters as keyword arguments | filters as positional arguments or magic `F` |
| `ChatType.PRIVATE` filter class | `F.chat.type == ChatType.PRIVATE` |

## forbidden patterns

Do not write any of these:

- `from aiogram import executor` — the module does not exist in 3.x.
- `@dp.message_handler(...)`, `@dp.callback_query_handler(...)` — 2.x decorators.
- `Bot(token=..., parse_mode=...)` — replaced by `DefaultBotProperties`.
- A module-level `Bot(...)` in a feature module — makes the module unimportable without a
  token and unusable in tests.
- `asyncio.run(...)` or `start_polling` at import time.
- Rebuilding complex dynamic markup with ad hoc row/payload logic instead of shared builders.
- `json.dumps(...)` inside `callback_data`.
- Bare `except Exception: pass` around an API call — it hides `TelegramForbiddenError`
  and leaves state corrupt.
- Catching `TelegramRetryAfter` and sleeping a hardcoded number instead of `retry_after`.
- Real tokens, chat ids, or user data in examples, tests, or fixtures.
- Running polling and a webhook against the same token.

## see also

- `aiogram-routing` — routers, observers, propagation order, `allowed_updates`
- `aiogram-filters` — `Command`, magic `F`, custom `BaseFilter`, filter composition
- `aiogram-middlewares` — inner vs outer middleware, workflow data, flags
- `aiogram-fsm` — states, storages, key builders, isolation
- `aiogram-scenes` — the experimental class-based wizard API
- `aiogram-callback-data` — typed payloads and the 64-byte budget
- `aiogram-keyboards` — inline and reply builders, pagination, edit-vs-send
- `aiogram-formatting` — entity-based text, parse modes, escaping
- `aiogram-files` — uploads, downloads, `file_id` reuse
- `aiogram-media-groups` — sending albums and aggregating incoming ones
- `aiogram-webhooks` — aiohttp integration, secret tokens, deployment
- `aiogram-errors` — the exception tree and error handlers
- `aiogram-rate-limits` — flood control, `TelegramRetryAfter`, throttling patterns
- `aiogram-streaming` — message drafts and rich messages (Bot API 10.x)
- `aiogram-testing` — offline testing with `feed_update` and a fake session
- [`references/telegram-quirks.md`](./telegram-quirks.md) — Telegram-side behaviour that surprises people
- [`references/recipes.md`](./recipes.md) — short canonical bot recipes
