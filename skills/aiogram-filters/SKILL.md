---
name: aiogram-filters
description: >
  Use when choosing or debugging aiogram 3 command, magic F, state, chat-member, or custom filters.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  magic_filter: "1.0.12"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram filters

A filter is any callable returning a truthy value. Several filters on one handler are
ANDed. A filter may also return a `dict`, and those keys are injected into the handler —
that is how `Command` delivers a `CommandObject`.

```bash
python skills/using-aiogram/tools/get-filter.py --list
python skills/using-aiogram/tools/get-filter.py Command
```

## when to use this skill

- deciding between `F`, a built-in filter class, and a custom `BaseFilter`
- matching commands, text, content types, chat types, or membership transitions
- narrowing callback queries
- writing a reusable permission check
- a filter that matches too much or too little

## the magic filter `F`

`F` builds a lazy predicate over the event object. `F.text` means "read `.text` from the
event and treat the result as a condition".

```python
import re

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

router = Router(name="magic")


@router.message(F.text == "ping")
async def exact(message: Message) -> None:
    await message.answer("pong")


@router.message(F.text.lower().startswith("hello"))
async def prefixed(message: Message) -> None:
    await message.answer("hi")


@router.message(F.text.regexp(r"^\d{4}$"))
async def four_digits(message: Message) -> None:
    await message.answer("code accepted")


@router.message(F.text.in_({"yes", "no"}))
async def choice(message: Message) -> None:
    await message.answer("noted")


@router.message(F.photo)
async def has_photo(message: Message) -> None:
    """Truthiness: fires when the photo list is present and non-empty."""
    await message.answer("photo")


@router.message(~F.text)
async def not_text(message: Message) -> None:
    await message.answer("that is not text")


@router.message(F.chat.type == ChatType.PRIVATE, F.text.len() > 10)
async def long_private(message: Message) -> None:
    await message.answer("long message in a private chat")


@router.message(F.func(lambda event: bool(re.match(r"^!", event.text or ""))))
async def bang(message: Message) -> None:
    await message.answer("bang")
```

Verified operations on `magic_filter` 1.0.12: `contains`, `not_contains`, `in_`, `not_in`,
`is_`, `is_not`, `len`, `regexp`, `func`, `cast`, `extract`, `attr_`, plus aiogram's
`as_`. Comparison and arithmetic operators build predicates too.

Combine with `&`, `|`, and `~`. Parenthesise — Python's operator precedence does not
match intuition here:

```python
from aiogram import F

combined = (F.text.startswith("/")) | (F.caption.startswith("/"))
negated = ~(F.text.len() < 3)
assert combined is not None and negated is not None
```

### `F.as_()` injects the resolved value

```python
from aiogram import F, Router
from aiogram.types import Message

router = Router(name="as-")


@router.message(F.text.regexp(r"^order (\d+)$").as_("match"))
async def order(message: Message, match: object) -> None:
    """`match` is the re.Match object the filter produced."""
    await message.answer(str(match), parse_mode=None)
```

## commands

```python
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

router = Router(name="commands")


@router.message(CommandStart(deep_link=False))
async def start(message: Message) -> None:
    await message.answer("started")


@router.message(CommandStart(deep_link=True))
async def start_with_payload(message: Message, command: CommandObject) -> None:
    await message.answer(f"payload: {command.args}", parse_mode=None)


@router.message(Command("help", "faq"))
async def help_or_faq(message: Message, command: CommandObject) -> None:
    await message.answer(f"you used /{command.command}", parse_mode=None)


@router.message(Command("admin", prefix="!/"))
async def admin(message: Message) -> None:
    await message.answer("admin")


@router.message(Command("grep", magic=F.args.is_not(None)))
async def grep(message: Message, command: CommandObject) -> None:
    """`magic` takes a MagicFilter evaluated against the CommandObject, not a lambda."""
    await message.answer(f"searching {command.args}", parse_mode=None)
```

Verified signature:

```text
Command(*values, commands=None, prefix="/", ignore_case=False,
        ignore_mention=False, magic=None)
```

`CommandStart(deep_link=None)` (the default) accepts both plain and payload starts.
Use `deep_link=False` for the plain handler above so it cannot shadow the payload handler.
With `deep_link_encoded=True`, `command.args` is already decoded.

`CommandObject` fields: `prefix`, `command`, `mention`, `args`, `regexp_match`,
`magic_result`. `args` is the raw remainder of the message or `None` — split it yourself.

`Command` handles the `@botname` suffix that Telegram appends in groups. Comparing
`message.text == "/start"` does not, which is why hand-rolled command matching breaks in
groups.

`Command` accepts compiled regexes as values, in which case `regexp_match` is populated.

### text and captions are separate inputs

In 3.31.0 `Command.__call__` reads `message.text or message.caption`, despite its
text-only docstring. A caption command can therefore win before a media handler. Use
`F.text, Command(...)` if only text commands are supported; otherwise read the matching
`text`/`entities` or `caption`/`caption_entities` pair. Never parse a caption with offsets
from `message.entities`.

```python
from datetime import datetime, timezone

from aiogram import F
from aiogram.types import Chat, Message, MessageEntity, PhotoSize

photo = Message(
    message_id=1,
    date=datetime.fromtimestamp(0, timezone.utc),
    chat=Chat(id=1, type="private"),
    photo=[PhotoSize(file_id="example", file_unique_id="example", width=32, height=32)],
    caption="/inspect",
    caption_entities=[MessageEntity(type="bot_command", offset=0, length=8)],
)
assert F.caption.startswith("/").resolve(photo)
assert not F.text.resolve(photo)
assert (~F.text).resolve(photo)  # This does NOT mean 'has no command'.
content = photo.text if photo.text is not None else photo.caption
entities = photo.entities if photo.text is not None else photo.caption_entities
assert content == "/inspect"
assert entities is not None and entities[0].type == "bot_command"
```

## state filters

```python
from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

router = Router(name="states")


class Form(StatesGroup):
    name = State()
    age = State()


@router.message(Form.name)
async def in_name(message: Message) -> None:
    """A State used as a filter is shorthand for StateFilter(Form.name)."""
    await message.answer("name")


@router.message(StateFilter(Form))
async def anywhere_in_form(message: Message) -> None:
    await message.answer("somewhere in the form")


@router.message(StateFilter(None))
async def stateless(message: Message) -> None:
    await message.answer("no active state")


@router.message(StateFilter("*"))
async def any_state(message: Message) -> None:
    await message.answer("any state at all")
```

`StateFilter(None)` and `StateFilter("*")` are different: `None` means *no* state,
`"*"` means *any* state including none. `/cancel` handlers want `"*"`.

No state filter means the handler can match in **any** state, not just idle. Decide
whether a utility command preserves the current conversation or exits it. A state
filter is evaluated at dispatch; it is not a concurrency fence. Re-check current state
and draft identity after application-lock waits before consuming input or changing a
surface; see [event isolation](../aiogram-fsm/SKILL.md#event-isolation).

## membership transitions

```python
from aiogram import Router
from aiogram.filters import (
    ADMINISTRATOR,
    IS_MEMBER,
    IS_NOT_MEMBER,
    ChatMemberUpdatedFilter,
)
from aiogram.types import ChatMemberUpdated

router = Router(name="membership")


@router.chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def joined(event: ChatMemberUpdated) -> None:
    await event.answer("welcome")


@router.chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> IS_NOT_MEMBER))
async def left(event: ChatMemberUpdated) -> None: ...


@router.my_chat_member(ChatMemberUpdatedFilter(ADMINISTRATOR))
async def promoted(event: ChatMemberUpdated) -> None:
    """my_chat_member tracks the bot's own status."""
```

`>>` builds a transition (old status on the left, new on the right). Exported markers
include `CREATOR`, `ADMINISTRATOR`, `MEMBER`, `RESTRICTED`, `LEFT`, `KICKED`, and the
composites `IS_MEMBER`, `IS_NOT_MEMBER`, `IS_ADMIN`, `JOIN_TRANSITION`,
`LEAVE_TRANSITION`, `PROMOTED_TRANSITION`.

## workflow-data filters

`MagicData` runs a magic filter over the **workflow data dict** rather than the event —
useful for feature flags and injected config.

```python
from aiogram import F, Router
from aiogram.filters import MagicData
from aiogram.types import Message

router = Router(name="magic-data")


@router.message(MagicData(F.config["maintenance"].is_(True)))
async def during_maintenance(message: Message) -> None:
    await message.answer("Back shortly.")
```

## exception filters

```python
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import ExceptionMessageFilter, ExceptionTypeFilter
from aiogram.types import ErrorEvent

router = Router(name="exception-filters")


@router.error(ExceptionMessageFilter(pattern=r".*message is not modified"))
async def not_modified(event: ErrorEvent, match_exception: object) -> None:
    """ExceptionMessageFilter regex-matches str(exception) and injects `match_exception`."""


@router.error(ExceptionTypeFilter(TelegramBadRequest))
async def bad_request(event: ErrorEvent) -> None: ...
```

`ExceptionMessageFilter` uses `re.match`, so the pattern is anchored at the start of the
exception string. Use `.*` or a substring-tolerant pattern when matching mid-message text.

## combining filters

```python
from aiogram import F
from aiogram.filters import Command, and_f, invert_f, or_f

either = or_f(Command("start"), F.text == "start")
both = and_f(F.text, F.chat.type == "private")
neither = invert_f(Command("stop"))
assert either and both and neither
```

`and_f` / `or_f` / `invert_f` compose filter callables, including custom classes.
`Filter` subclasses also support `~filter` via `invert_f`, for example `~Command("stop")`.
Unlike `F`, they do not implement `&` or `|`; use the helpers for mixed compositions.

Use separate handler filters (implicit AND) or `and_f` when combining `F` with an
aiogram `Filter`, for example `F.text.regexp(pattern), invert_f(Command("lookup"))`.
A regexp may return a `re.Match`, not a boolean; putting it in a bitwise expression with
another filter object can raise instead of rejecting the update. Exercise matching text,
the excluded command, and non-text input through the real filter chain.

## custom filters

Subclass `BaseFilter` (an alias of `Filter`) when a check needs constructor arguments,
dependencies, or a name.

```python
from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

router = Router(name="custom")


class HasArgs(BaseFilter):
    """Returning a dict injects its keys into the handler."""

    def __init__(self, minimum: int = 1) -> None:
        self.minimum = minimum

    async def __call__(self, message: Message) -> bool | dict[str, list[str]]:
        parts = (message.text or "").split()[1:]
        if len(parts) < self.minimum:
            return False
        return {"args": parts}


@router.message(HasArgs(minimum=2))
async def with_args(message: Message, args: list[str]) -> None:
    await message.answer(f"got {len(args)} arguments")
```

Rules for custom filters:

- `__call__` may be sync or async; async is conventional.
- Return `False` to reject, `True` to accept, or a **non-empty** `dict` to accept and inject. An empty dict rejects.
- A filter receives the same workflow data as handlers — declare `bot`, `state`, or your
  own injected services as parameters.
- Keep filters cheap. They run for every candidate handler until one matches; a database
  query inside a filter runs far more often than you expect.

## ordering and precision

Filters do not reorder handlers — registration order does. Two rules avoid nearly all
routing bugs:

1. Make each filter as narrow as the intent. `F.text` matches every text message
   including commands, so register command handlers first or add `~F.text.startswith("/")`.
2. Put catch-alls in a router included last.

A waiting-for-file flow also needs an invalid-input branch in that state, after its
accepted-content handlers but before generic media/text handlers elsewhere. Otherwise
ordinary text or an unsupported document may fall into another feature or receive no
feedback. Invalid input keeps the state and repeats the actionable constraint. Keep
global commands before that branch. Test actual filters with text, captioned media,
unsupported content and the same updates when idle.

## checklist

- commands matched with `Command`, never with raw string comparison
- `F` used for content and attribute checks instead of `if` inside the handler
- `StateFilter("*")` on cancel handlers, `StateFilter(None)` on stateless entry points
- custom checks that need configuration expressed as a `BaseFilter`, not a closure
- filters free of I/O where possible
- injected values (`command`, `callback_data`, `.as_()` names) declared in the signature
- caption commands handled intentionally with the matching content/entity pair
- state-specific invalid input stays in its flow; global commands take precedence
- no-filter handlers are not assumed idle-only; state checks are not atomic claims

## see also

- `aiogram-routing` — where filters sit in propagation
- `aiogram-fsm` — state filters in context
- `aiogram-callback-data` — `.filter()` on callback factories
- `aiogram-errors` — exception filters
