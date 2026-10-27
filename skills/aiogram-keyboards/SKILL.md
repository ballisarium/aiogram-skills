---
name: aiogram-keyboards
description: >
  Use when building aiogram 3 inline/reply keyboards, menus, pagination, or Mini App buttons.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram keyboards

Use direct `InlineKeyboardMarkup(inline_keyboard=[[...]])` for small static layouts;
use builders when buttons or rows are built dynamically.

```bash
python skills/using-aiogram/tools/get-type.py InlineKeyboardButton
python skills/using-aiogram/tools/get-type.py KeyboardButton
```

## when to use this skill

- building a menu, a confirmation prompt, or a selection list
- laying buttons out in rows
- pagination
- asking the user for a contact, a location, or a chat
- deciding whether to edit the current message or send a new one
- removing a reply keyboard

## inline versus reply

| | Inline | Reply |
|---|---|---|
| attached to | a specific message | the chat's input area |
| type | `InlineKeyboardMarkup` | `ReplyKeyboardMarkup` |
| builder | `InlineKeyboardBuilder` | `ReplyKeyboardBuilder` |
| press produces | depends on action: callback, URL, inline switch, etc. | text or requested contact/location/service data |
| use for | menus, actions on an item, pagination, confirmation | persistent input choices, contact/location requests |

Ordinary reply buttons send **text**, distinct from contact/location/request buttons, so handling them means matching strings — which breaks
across locales and is spoofable by anyone typing the same text. Prefer inline keyboards
for anything that performs an action.

## InlineKeyboardBuilder

```python
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CopyTextButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


class Item(CallbackData, prefix="item"):
    item_id: int


builder = InlineKeyboardBuilder()
builder.button(text="Open docs", url="https://docs.aiogram.dev/")
builder.button(text="Pick", callback_data=Item(item_id=1))
builder.button(text="Copy code", copy_text=CopyTextButton(text="ABC-123"))
builder.adjust(2, 1)
markup = builder.as_markup()

assert [len(row) for row in markup.inline_keyboard] == [2, 1]
assert markup.inline_keyboard[1][0].copy_text.text == "ABC-123"
assert markup.inline_keyboard[1][0].callback_data is None
```

Verified `button()` signature — these are the button kinds Telegram accepts:

```text
button(*, text, icon_custom_emoji_id=None, style=None, url=None,
       callback_data=None, web_app=None, login_url=None,
       switch_inline_query=None, switch_inline_query_current_chat=None,
       switch_inline_query_chosen_chat=None, copy_text=None,
       callback_game=None, pay=None, **kwargs)
```

`callback_data` accepts a `str` **or** a `CallbackData` instance, which is packed for you.
Each inline button must specify exactly one action field, including `disabled` for an
inert button; `text`, `icon_custom_emoji_id`, and `style` are presentation fields.
`style` accepts only `danger`, `success`, or `primary`, even for URL buttons.
The enum's `LINK` member is not a valid inline-button style; constructing the model
does not enforce this server-side restriction.

`icon_custom_emoji_id` is available to bots with additional usernames purchased on
Fragment, or in messages sent directly by the bot to private, group, or supergroup chats
when the **bot owner** has Telegram Premium. The recipient's Premium status is irrelevant.

Bot API 10.3 adds `disabled=DisabledButton()` (passed through builder `**kwargs`)
and `InlineKeyboardMarkup.force_reply`. The last field enables reply
input alongside an inline keyboard and cannot be changed when editing that keyboard.
In 3.31.0 the inline builder's `as_markup(**kwargs)` ignores extra keyword arguments,
so construct `InlineKeyboardMarkup` explicitly when setting `force_reply`. Reply-keyboard
builders do forward markup options.

```python
from aiogram.enums import ButtonStyle
from aiogram.types import DisabledButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

builder = InlineKeyboardBuilder()
builder.button(text="Unavailable", disabled=DisabledButton())
builder.button(text="Documentation", url="https://docs.aiogram.dev/", style=ButtonStyle.PRIMARY)
markup = InlineKeyboardMarkup(inline_keyboard=builder.export(), force_reply=True)
assert markup.inline_keyboard[0][0].disabled is not None
assert markup.inline_keyboard[0][1].style == "primary"
assert markup.force_reply is True
```

### layout

| Method | Effect |
|---|---|
| `button(**kwargs)` | construct a button and pass it to `add()` |
| `add(*buttons)` | fill the last row to `max_width`, then append rows |
| `row(*buttons, width=None)` | append new rows, splitting at `width` (default `max_width`); later `add()` can still fill the last row |
| `adjust(*sizes, repeat=False)` | reflow everything into rows of the given widths |
| `attach(other)` | append rows from a builder with the same button type |
| `copy()` | independent duplicate |
| `export()` | a deep copy of the `list[list[Button]]` |
| `as_markup(**kwargs)` | produce the markup model |
| `from_markup(markup)` | build from an existing markup (class method) |

```python
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

main = InlineKeyboardBuilder()
for index in range(5):
    main.button(text=str(index), callback_data=f"n:{index}")
main.adjust(3, repeat=True)  # 3, 3, ... -> rows of 3, 2

footer = InlineKeyboardBuilder()
footer.row(InlineKeyboardButton(text="Close", callback_data="close"))
main.attach(footer)

assert [len(row) for row in main.export()] == [3, 2, 1]
main.adjust(3)
assert [len(row) for row in main.export()] == [3, 3]  # attached rows also reflow

pair = InlineKeyboardBuilder()
pair.row(InlineKeyboardButton(text="A", callback_data="a"))
pair.add(InlineKeyboardButton(text="B", callback_data="b"))
assert [[button.text for button in row] for row in pair.export()] == [["A", "B"]]
```

`adjust(2, 3, repeat=True)` cycles widths 2, 3, 2, 3. With `repeat=False`,
the final width is repeated after the supplied sizes are exhausted.
Attach fixed footer rows **after** the final `adjust()` if their layout must survive.

In aiogram 3.31.0, `InlineKeyboardBuilder` declares `max_width=8`, `max_buttons=100`;
`ReplyKeyboardBuilder` declares `max_width=10`, `max_buttons=300`. `row()` validates its
width; `adjust()` validates sizes as it consumes them. Total counts are checked when
validating supplied markup, not reliably during incremental construction or `as_markup()`.
These are builder constants, not a statement of Telegram server limits.

## ReplyKeyboardBuilder

```python
from aiogram.types import KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

builder = ReplyKeyboardBuilder()
builder.add(KeyboardButton(text="Share phone", request_contact=True))
builder.add(KeyboardButton(text="Share location", request_location=True))
builder.adjust(1)
markup = builder.as_markup(
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder="Choose an option",
)

assert markup.resize_keyboard is True
```

`as_markup(**kwargs)` forwards keyword arguments to the markup model, which is how
`resize_keyboard`, `one_time_keyboard`, `is_persistent`, `selective`, and
`input_field_placeholder` are set.

`resize_keyboard=True` requests a compact vertical fit; omit it for standard keyboard
height. This is a presentation choice, not a requirement. `one_time_keyboard=True`
requests hiding after use, not removal: the user can reopen the keyboard.
`is_persistent=True` requests that clients keep it visible when the regular keyboard is
hidden. The placeholder is 1–64 characters (`ReplyKeyboardMarkup.input_field_placeholder`).
`selective` targets mentioned users or the sender being replied to in the same chat/topic;
it is a display hint, not authorisation. Validate actions independently.

### removing a reply keyboard

```python
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove

router = Router(name="remove")


@router.message(Command("done"))
async def finish(message: Message) -> None:
    """Remove the current reply keyboard, not the message or an inline keyboard."""
    await message.answer("Done.", reply_markup=ReplyKeyboardRemove())
```

`ReplyKeyboardRemove()` removes the current custom keyboard so it cannot be reopened;
it does not delete messages or remove inline controls. Reply keyboards and their removal
are unsupported in channels and in messages sent on behalf of a business account.

`ForceReply()` makes the client open the reply composer pointed at your message — useful
for a single free-text answer without a state machine.

## special buttons

```python
from aiogram.types import (
    CopyTextButton,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

inline = InlineKeyboardBuilder()
inline.button(text="Open app", web_app=WebAppInfo(url="https://example.com/app"))
inline.button(text="Copy token", copy_text=CopyTextButton(text="ABC-123"))
inline.button(text="Share this bot", switch_inline_query="")

reply = ReplyKeyboardBuilder()
reply.add(
    KeyboardButton(
        text="Choose users",
        request_users=KeyboardButtonRequestUsers(request_id=1, max_quantity=3),
    )
)

app, copy, switch = inline.export()[0]
assert app.web_app.url == "https://example.com/app"
assert copy.copy_text.text == "ABC-123"
assert copy.callback_data is None
assert switch.switch_inline_query == ""
request = reply.export()[0][0].request_users
assert request.request_id == 1
assert request.max_quantity == 3
```

- Inline-switch buttons require [inline mode](https://core.telegram.org/bots/inline)
  enabled and an inline-query handler. `switch_inline_query=""` opens a chat picker;
  `switch_inline_query_current_chat` stays in the current chat. The current-chat form is
  unsupported in channels; switch buttons are unsupported for business-account messages
  and channel direct messages chats.
- `request_users` / `request_chat` deliver `users_shared` / `chat_shared` service
  messages: use `F.users_shared` / `F.chat_shared` respectively, and match the returned
  `request_id` to the expected request in the user's flow. Use `request_users`, not the
  deprecated singular `request_user`.
- Reply `request_*` and both kinds of `web_app` buttons are private-chat-only.
  Inline `web_app` is unsupported for business-account messages; reply keyboards have
  the broader restrictions above. `web_app` requires HTTPS; validate init data server-side
  with `aiogram.utils.web_app`.
- `login_url` requires HTTPS and a domain linked to the bot; it is unsupported in
  ephemeral messages. Verify the returned authorisation data before trusting it.
- `callback_game` and `pay=True` must occupy the first button of the first row; pay
  buttons belong only in invoice messages. See the
  [Bot API button restrictions](https://core.telegram.org/bots/api#inlinekeyboardbutton).

## pagination

```python
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

PAGE_SIZE = 5


class Nav(CallbackData, prefix="nav"):
    page: int


def paginate(items: list[str], page: int) -> InlineKeyboardBuilder:
    last = max(0, (len(items) - 1) // PAGE_SIZE)
    page = min(max(page, 0), last)  # clamp: never trust the payload

    builder = InlineKeyboardBuilder()
    if not items:
        return builder
    for offset, item in enumerate(items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]):
        builder.button(text=item, callback_data=f"pick:{page * PAGE_SIZE + offset}")
    builder.adjust(1, repeat=True)

    controls = InlineKeyboardBuilder()
    if page > 0:
        controls.button(text="‹", callback_data=Nav(page=page - 1))
    controls.button(text=f"{page + 1}/{last + 1}", callback_data=Nav(page=page))
    if page < last:
        controls.button(text="›", callback_data=Nav(page=page + 1))
    controls.adjust(3)

    builder.attach(controls)
    return builder


assert paginate([], 0).export() == []
assert [len(r) for r in paginate([str(i) for i in range(12)], 0).export()][-1] == 2
assert [len(r) for r in paginate([str(i) for i in range(12)], 1).export()][-1] == 3
```

Three rules: **clamp the page** (the payload is user-controlled), always show where the
user is, and handle the empty-list case rather than rendering a lone page counter.
The positional item indexes here assume an unchanged list. For a changing collection,
use stable item IDs or a versioned server-side snapshot; re-check existence and access
when selecting. A valid page number does not prove an item still occupies that position.

## show the applied selection

Pass the current canonical setting to the keyboard builder on every render, including
Back and cached-preview paths. A single-choice menu marks exactly one applied option;
derive the marker from state, not from the last callback or a hardcoded default. Keep
the payload unchanged when adding a marker. A marker is presentation, not authorisation.

```python
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def mode_keyboard(current: str) -> InlineKeyboardMarkup:
    choices = (("compact", "Compact"), ("full", "Full"))
    if current not in {key for key, _ in choices}:
        raise ValueError("unknown mode")
    builder = InlineKeyboardBuilder()
    for key, label in choices:
        builder.button(
            text=f"✓ {label}" if key == current else label,
            callback_data=f"mode:{key}",
        )
    return builder.adjust(1).as_markup()


for current in ("compact", "full"):
    buttons = [row[0] for row in mode_keyboard(current).inline_keyboard]
    assert sum(button.text.startswith("✓ ") for button in buttons) == 1
    selected = next(button for button in buttons if button.text.startswith("✓ "))
    assert selected.callback_data == f"mode:{current}"
```

Use localised labels in the application. Custom values need an explicit Custom choice
or a displayed value, not a falsely selected preset. Recompute action availability from
current permissions/limits when rebuilding a menu, and still validate old callbacks
server-side; hiding a button does not invalidate one already sent.

## edit versus send

| Situation | Do |
|---|---|
| navigating a menu, paging, toggling a selection | `edit_text` / `edit_reply_markup` |
| changing the text beside existing media | `edit_caption` / `edit_reply_markup` |
| responding after new user input | send the next prompt/result below that input |
| the previous message must remain in history | send a new one |
| a documented edit restriction applies to this message/method | retire its controls before replacing it |
| the message has media and you are changing media | `edit_media` |

```python
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="edit")


@router.callback_query(F.data == "refresh")
async def refresh(callback: CallbackQuery) -> None:
    if not isinstance(callback.message, Message):
        await callback.answer("This menu is no longer available.", show_alert=True)
        return
    await callback.answer()
    builder = InlineKeyboardBuilder()
    builder.button(text="Refresh", callback_data="refresh")
    try:
        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
```

Ordinary callback handlers filter by payload. Register an unfiltered stale-button
fallback only in the last router, after all specific callback handlers.

Editing to identical text **and** identical markup can raise
`TelegramBadRequest: message is not modified`. Treat a repeated selection as a no-op or
handle that specific error as above; do not add timestamps just to force an edit.

`callback.message` may be an `InaccessibleMessage` or `None`. For this message-based menu,
reject that branch before state changes. Inline-mode menus need an explicit
`inline_message_id` path; a non-`None` check is not sufficient for message shortcuts.

### transitions and message ownership

Carry the exact control message ID and its kind (text or media) through FSM/worker handoff.
Do not infer a photo from the job name or edit its text with `edit_text`. Returning from
a submenu should use the same renderer as initial entry, including interpolation,
permissions, link-preview policy, and contextual Back target.

One callback transition normally updates one action surface. When changing text/caption
and buttons together, pass `reply_markup` in the same edit instead of editing the content
and then the keyboard separately. Record the returned message ID for replacement and
recovery surfaces, not the old ID or a zero placeholder; stale cleanup must never target
the replacement menu.

Before opening a replacement interactive prompt, remove or disable the old controls.
When the old media/result must remain, remove only its keyboard. For conversational input
flows, default to sending the next surface below the new input; do not delete the user's
input or repurpose an earlier prompt just to tidy the chat. A deliberate persistent
editor can stay where it is while the current prompt owns input and actions. Preserve
the product's message lifecycle rather than imposing one screen model on every bot.

If cleanup fails, do not blindly send a second actionable menu. Handle only known benign
errors (such as unchanged markup); propagate unexpected failures. Test the exact IDs,
cleanup-before-replacement order, and one reachable action surface on failure as well as
success. See [callback claims](../aiogram-callback-data/SKILL.md#acknowledgement-ownership-and-one-shot-actions)
for concurrent taps, which keyboard removal alone cannot prevent.

## keep markup out of handlers

Keep reusable or complex keyboard construction in the existing keyboard module and
text in the localisation layer. A small one-off keyboard can stay local to its handler.

```python
from typing import Literal

from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder


class Confirm(CallbackData, prefix="confirm"):
    action: Literal["ok", "no"]
    token: str


def confirmation_keyboard(token: str) -> InlineKeyboardBuilder:
    """One function per menu; handlers call it and pass the markup along."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Yes", callback_data=Confirm(action="ok", token=token))
    builder.button(text="No", callback_data=Confirm(action="no", token=token))
    builder.adjust(2)
    return builder


assert len(confirmation_keyboard("t").export()[0]) == 2
try:
    confirmation_keyboard("x" * 64)  # builder calls pack(), including prefix/action bytes
except ValueError as error:
    assert "too long" in str(error)
else:
    raise AssertionError("expected oversized callback rejection")
```

Returning the *builder* rather than the markup lets callers `attach()` more rows.

## checklist

- builders for dynamic layouts; static markup is also valid
- structured `callback_data` produced by a `CallbackData` factory
- reply-keyboard sizing and persistence chosen deliberately; hiding is not removal
- reply keyboards removed with `ReplyKeyboardRemove` when the flow ends
- pagination clamps the page number and handles an empty list
- selections use stable identity; exactly one current option is marked on every render
- availability refreshed on redisplay and enforced again when an old callback arrives
- edits guarded against "message is not modified"
- `callback.message` type-checked before use
- callback navigation edits one surface; new input closes old controls and gets a new reply
- replacement/error prompts bound to their actual returned IDs and media kinds
- reusable keyboards use the existing shared module and localisation

## see also

- `aiogram-callback-data` — the payloads on these buttons
- `aiogram-routing` — routing the resulting callback queries
- `aiogram-formatting` — the text beside the markup
- `skills/using-aiogram/references/telegram-quirks.md` — edit limits and callback expiry
