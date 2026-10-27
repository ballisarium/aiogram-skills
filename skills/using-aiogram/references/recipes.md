# Recipes

Short patterns and focused helpers for aiogram **3.31.0**. Every block here is executed
against the installed package by `validate-example.py`, so the imports and signatures are real.

Examples use a fake token (`123456:TEST`) and never contact Telegram.
Literal labels keep examples self-contained; use the application's locale catalogue in
real flows. Plain dynamic output explicitly disables inherited parse modes.

## 1. entrypoint with graceful shutdown

```python
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

router = Router(name="app")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## 2. command with arguments

```python
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

router = Router(name="echo-command")


@router.message(Command("say"))
async def say(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Usage: /say <text>", parse_mode=None)
        return
    await message.answer(command.args, parse_mode=None)
```

## 3. deep link with a payload

```python
from aiogram import Bot, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from aiogram.utils.deep_linking import create_start_link

router = Router(name="deeplink")


@router.message(CommandStart(deep_link=True, deep_link_encoded=True))
async def start_with_referral(message: Message, command: CommandObject) -> None:
    referrer = command.args  # CommandStart already decoded the payload
    await message.answer(f"Invited by {referrer}", parse_mode=None)


async def make_link(bot: Bot, user_id: int) -> str:
    """create_start_link calls get_me(), so it needs a live bot at run time."""
    return await create_start_link(bot, payload=str(user_id), encode=True)
```

## 4. inline menu that edits itself

```python
from typing import Literal

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="menu")


class Menu(CallbackData, prefix="menu"):
    page: Literal["home", "settings", "about"]


def build_menu(active: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for page in ("home", "settings", "about"):
        label = f"• {page}" if page == active else page
        builder.button(text=label, callback_data=Menu(page=page))
    builder.adjust(3)
    return builder


@router.message(Command("menu"), StateFilter(None))
async def open_menu(message: Message) -> None:
    await message.answer("Menu", parse_mode=None, reply_markup=build_menu("home").as_markup())


@router.callback_query(Menu.filter())
async def switch_page(callback: CallbackQuery, callback_data: Menu) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("This menu is no longer available.", show_alert=True)
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"Menu — {callback_data.page}",
            parse_mode=None,
            reply_markup=build_menu(callback_data.page).as_markup(),
        )
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
```

`/menu` opens only outside an FSM flow. Register global exits such as `/cancel` before
input-flow handlers; route them through the flow's cleanup. If the application requires
one current menu, track its message ID and retire its controls before sending a replacement,
then record the returned ID. This compact example does not implement that lifecycle.
Register the stale-button fallback **after** the menu router so unknown or retired payloads
receive an explanatory answer without intercepting valid navigation.

## 5. pagination controls with bounded page numbers

```python
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

PAGE_SIZE = 10


class Page(CallbackData, prefix="pg"):
    number: int


def pager(number: int, total_items: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    if total_items <= 0:
        return builder
    last = max(0, (total_items - 1) // PAGE_SIZE)
    number = min(max(number, 0), last)
    if number > 0:
        builder.button(text="‹ prev", callback_data=Page(number=number - 1))
    builder.button(text=f"{number + 1}/{last + 1}", callback_data=Page(number=number))
    if number < last:
        builder.button(text="next ›", callback_data=Page(number=number + 1))
    return builder


assert pager(0, 0).export() == []
assert len(pager(0, 5).export()[0]) == 1  # single page: no prev, no next
assert len(pager(1, 100).export()[0]) == 3
assert pager(-10, 100).export() == pager(0, 100).export()
assert pager(100, 100).export() == pager(9, 100).export()
```

This builds controls, not a complete paginator. The real handler validates context,
ACKs once before slow work, reloads the accessible items, clamps against that fresh count,
and edits the page content and markup together. Render an empty state without controls;
ignore only the specific `message is not modified` error. Reuse the same clamped page
for slicing and controls, and use stable item IDs if the collection can change.

## 6. admin-only handlers via a filter

```python
from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

router = Router(name="admin")


class IsAdmin(BaseFilter):
    """A reusable filter is better than an `if` at the top of every handler."""

    def __init__(self, admin_ids: frozenset[int]) -> None:
        self.admin_ids = admin_ids

    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in self.admin_ids


admin_filter = IsAdmin(frozenset({1, 2}))


@router.message(Command("shutdown"), admin_filter)
async def shutdown(message: Message) -> None:
    await message.answer("shutting down")
```

Applying it to a whole router is cleaner than repeating it: `router.message.filter(admin_filter)`.

## 7. per-update database session

```python
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject


class Session:
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...


class SessionMiddleware(BaseMiddleware):
    """Open one session per update; commit on success, roll back on failure."""

    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = Session()
        data["session"] = session
        try:
            result = await handler(event, data)
            await session.commit()
        except BaseException:  # includes cancellation; always re-raise
            await session.rollback()
            raise
        else:
            return result
        finally:
            await session.close()


dispatcher = Dispatcher()
dispatcher.update.outer_middleware(SessionMiddleware())
```

`Session` is application code, not an aiogram storage class. This illustrates lifecycle,
not a transaction spanning Telegram and a database: rollback cannot retract an accepted
send. Prefer short transactions around the owning storage transition, and finish rollback
before returning a connection to a pool, including cancellation paths.

## 8. throttling incoming updates

```python
import time
from typing import Any

from aiogram import BaseMiddleware, Dispatcher
from aiogram.types import TelegramObject, Update


class Throttle(BaseMiddleware):
    """Outer middleware: drops the update before filters even run."""

    def __init__(self, seconds: float = 0.5) -> None:
        self.seconds = seconds
        self.seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None:
            now = time.monotonic()
            if now - self.seen.get(user.id, float("-inf")) < self.seconds:
                if isinstance(event, Update) and event.callback_query is not None:
                    await event.callback_query.answer("Please wait.")
                return None
            self.seen[user.id] = now
        return await handler(event, data)


dispatcher = Dispatcher()
dispatcher.update.outer_middleware(Throttle())
assert isinstance(Update(update_id=1), TelegramObject)
```

An in-memory dict is per-process and needs expiry/size bounds for a long-running bot.
Use the application's shared store when several replicas must enforce one budget.
This is application throttling, not an aiogram feature; restrict it to suitable traffic,
not payments, cancellation or other safety-critical updates that must not be dropped.

## 9. typing indicator during slow work

```python
import asyncio

from aiogram import Bot, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

router = Router(name="slow")


@router.message()
async def slow_work(message: Message, bot: Bot) -> None:
    async with ChatActionSender.typing(
        bot=bot, chat_id=message.chat.id, message_thread_id=message.message_thread_id
    ):
        await asyncio.sleep(0)  # real work here
    await message.answer("done")
```

`ChatActionSender` re-sends the action every 5 seconds, which is what Telegram requires
for the indicator to persist.
The work must still yield: a synchronous renderer inside this context blocks both update
handling and chat-action refresh. Offload blocking work; a typing indicator is not a worker.

## 10. sending an album

```python
from aiogram import Router
from aiogram.types import Message
from aiogram.utils.media_group import MediaGroupBuilder

router = Router(name="album")


@router.message()
async def send_album(message: Message) -> None:
    album = MediaGroupBuilder(caption="Only the first item shows the caption")
    album.add_photo(media="https://example.com/1.jpg")
    album.add_photo(media="https://example.com/2.jpg")
    await message.answer_media_group(media=album.build())
```

Telegram requires **2–10** items; building one with a single item will be rejected.

## 11. safe edit that tolerates "not modified"

```python
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup


async def safe_edit(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Return True when the message changed, False when it was already current."""
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=None,
            reply_markup=markup,
        )
    except TelegramBadRequest as error:
        if "message is not modified" in str(error):
            return False
        raise
    return True
```

## 12. broadcast that respects flood limits

```python
import asyncio
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter


async def broadcast(bot: Bot, user_ids: Iterable[int], text: str) -> tuple[int, int]:
    """Returns (delivered, deactivated); unresolved failures stop the job."""
    delivered = 0
    deactivated = 0
    for user_id in user_ids:
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=user_id, text=text, parse_mode=None)
            except TelegramRetryAfter as error:
                if attempt == 2:
                    raise
                await asyncio.sleep(error.retry_after)
                continue
            except TelegramForbiddenError:
                deactivated += 1
            else:
                delivered += 1
            break
        await asyncio.sleep(0.05)  # chosen application pace; still honour 429s
    return delivered, deactivated
```

## 13. registering the visible command menu

```python
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats

COMMANDS = [
    BotCommand(command="start", description="Start the bot"),
    BotCommand(command="help", description="Show help"),
]


async def setup_commands(bot: Bot) -> None:
    await bot.set_my_commands(COMMANDS, scope=BotCommandScopeAllPrivateChats())
```

Update this whenever you add or remove a command; Telegram caches the menu client-side.

## 14. reacting to members joining and leaving

```python
from aiogram import Router
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated

router = Router(name="membership")


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def joined(event: ChatMemberUpdated) -> None:
    await event.answer(f"Welcome, {event.new_chat_member.user.first_name}!", parse_mode=None)


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def left(event: ChatMemberUpdated) -> None:
    pass
```

`chat_member` updates only arrive if `chat_member` is in `allowed_updates` —
`resolve_used_update_types()` handles that for you.

## 15. validating Web App init data

```python
from datetime import datetime, timezone

from aiogram.utils.web_app import safe_parse_webapp_init_data

TOKEN = "123456:TEST"  # application configuration in production
MAX_AGE_SECONDS = 300  # application policy, not enforced by aiogram


def authenticate(init_data: str) -> int | None:
    """Verify the signature AND an application-defined freshness window."""
    try:
        parsed = safe_parse_webapp_init_data(TOKEN, init_data)
    except ValueError:
        return None
    age = datetime.now(timezone.utc).timestamp() - parsed.auth_date.timestamp()
    if not 0 <= age <= MAX_AGE_SECONDS:
        return None
    return parsed.user.id if parsed.user else None


assert authenticate("query_id=x&hash=deadbeef") is None
```
