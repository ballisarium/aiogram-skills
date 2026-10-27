---
name: aiogram-callback-data
description: >
  Use when designing or debugging aiogram 3 callback payloads, CallbackData filters, byte limits, or stale buttons.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram callback data

`callback_data` is Telegram's **1–64 byte** payload attached to an inline button. Treat it
as routing data, not storage. `CallbackData` gives you a typed factory with packing,
parsing, size checking, and a dispatch-ready filter.

## when to use this skill

- any inline button that must be identified when pressed
- replacing string concatenation or `json.dumps` in `callback_data`
- payloads that exceed 64 bytes
- routing several button kinds to different handlers
- callbacks arriving from buttons an older deployment rendered

## defining a factory

```python
from aiogram.filters.callback_data import CallbackData


class Product(CallbackData, prefix="prod"):
    action: str
    product_id: int


assert Product(action="buy", product_id=42).pack() == "prod:buy:42"
assert Product.unpack("prod:buy:42") == Product(action="buy", product_id=42)
```

- `prefix=` is **required**. Omitting it raises
  `ValueError: prefix required, usage example: ...` at class-definition time.
- `sep=":"` is the default separator; override with `sep="|"` if your values legitimately
  contain colons. The separator may not appear inside the prefix.
- Fields are ordinary pydantic fields, so defaults, `Optional`, and validation all work.

## using it

```python
from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router(name="products")


class Product(CallbackData, prefix="prod"):
    action: str
    product_id: int


def keyboard(product_id: int) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Buy", callback_data=Product(action="buy", product_id=product_id))
    builder.button(text="Info", callback_data=Product(action="info", product_id=product_id))
    builder.adjust(2)
    return builder


@router.callback_query(Product.filter(F.action == "buy"))
async def buy(callback: CallbackQuery, callback_data: Product) -> None:
    """The filter parses the payload and injects it as `callback_data`."""
    await callback.answer(f"buying {callback_data.product_id}")


@router.callback_query(Product.filter())
async def other_product_actions(callback: CallbackQuery, callback_data: Product) -> None:
    await callback.answer(callback_data.action)
```

- `builder.button(callback_data=...)` accepts a `CallbackData` instance directly and packs
  it for you — no manual `.pack()`.
- `Product.filter()` matches payloads that successfully unpack with this factory, not
  every string with that prefix.
- `Product.filter(F.action == "buy")` narrows with a magic filter over the parsed instance.
- The narrow handler must be registered **before** the broad one, as always.

## what can be packed

Verified from `CallbackData._encode_value`. Packing support alone does not guarantee
round-trip validation: use `IntEnum` for integer enum values, and `str, Enum` for strings.
A short constant callback string is fine; use a factory for structured fields:

| Type | Encoded as |
|---|---|
| `None` | empty string |
| `Enum` | `str(value.value)` |
| `UUID` | `value.hex` (32 chars) |
| `bool` | `"1"` / `"0"` |
| `int`, `str`, `float`, `Decimal`, `Fraction` | `str(value)` |
| anything else | **`ValueError`** |

```python
from enum import Enum
from uuid import UUID

from aiogram.filters.callback_data import CallbackData


class Action(str, Enum):
    approve = "a"
    reject = "r"


class Review(CallbackData, prefix="rv"):
    action: Action
    item: UUID
    silent: bool


packed = Review(
    action=Action.approve,
    item=UUID("00000000-0000-0000-0000-00000000002a"),
    silent=True,
).pack()
assert packed == "rv:a:0000000000000000000000000000002a:1"
```

A short `Enum` value is the cheapest way to keep an action name to one byte.

Lists, dicts, dataclasses, and model instances raise `ValueError`. That restriction is the
point: if it does not fit in a flat 64-byte line, it belongs server-side.

## the 64-byte budget

`pack()` raises when the encoded string exceeds `MAX_CALLBACK_LENGTH = 64` **bytes**:

```python
from aiogram.filters.callback_data import CallbackData
from aiogram.filters.callback_data import MAX_CALLBACK_LENGTH


class TooBig(CallbackData, prefix="big"):
    note: str


assert MAX_CALLBACK_LENGTH == 64

try:
    TooBig(note="x" * 100).pack()
except ValueError as error:
    assert "too long" in str(error)
else:  # pragma: no cover
    raise AssertionError("expected ValueError")
```

Bytes, not characters. A visible emoji can contain multiple code points joined together;
it is not limited to four bytes. Measure `len(payload.encode("utf-8"))`, including the
prefix and separators. `pack()` checks this limit; a plain `callback_data` string does not.

```python
assert len("👨‍👩‍👧‍👦".encode("utf-8")) == 25
```

Ways to stay inside the budget, best first:

1. Store the context server-side and put an id on the button.
2. Use a short `Enum` for the action instead of a word.
3. Shorten the prefix — it is repeated on every button.
4. Use a compact id (an integer, or a `UUID` — 32 hex chars — rather than a formatted string).

## separator collisions

A value containing the separator raises on `pack()`:

```python
from aiogram.filters.callback_data import CallbackData


class Search(CallbackData, prefix="s", sep="|"):
    query: str


assert Search(query="a:b").pack() == "s|a:b"

try:
    Search(query="a|b").pack()
except ValueError as error:
    assert "Separator symbol" in str(error)
else:  # pragma: no cover
    raise AssertionError("expected ValueError")
```

Never put free-form user text in a payload. If you must, choose a separator the text
cannot contain, and validate before packing.

## stale and hostile payloads

After a deploy, users still have buttons from the previous version on screen. `unpack`
raises rather than returning garbage:

- wrong prefix → `ValueError: Bad prefix (...)`
- wrong field count → `TypeError: ... takes N arguments but M were given`
- unparseable field → pydantic `ValidationError`

The `.filter()` used in a handler catches these and simply does not match, so a stale
payload falls through to whatever comes next. Give it somewhere sane to land:

```python
from aiogram import Router
from aiogram.types import CallbackQuery

router = Router(name="stale")  # include LAST


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    """Catch-all so obsolete buttons do not leave a spinner on the client."""
    await callback.answer("This button has expired.", show_alert=True)
```

Two more rules for the same class of problem:

- **Re-check authorisation and existence in the handler.** The payload says what the user
  clicked, not what they are allowed to do. A `product_id` in a button is user-controlled
  data — anyone can send an arbitrary `callback_data` string.
- **Claim terminal actions once.** Users double-tap, and Telegram redelivers. Removing
  a keyboard does not stop a second update already in flight. Use the application's
  atomic claim or transaction before enqueueing or applying the effect; see below.

### acknowledgement, ownership, and one-shot actions

For a callback tied to a chat message, validate the payload, accessible `Message`, and
locally available owner/expiry/revision synchronously. Reject an invalid branch with one
plain-text alert and return. A valid branch acknowledges once before application-level
FSM/storage access, locks, rendering, queue admission, or another API request. Check application
decorators/helpers too: an ACK at the top of the handler is late if its wrapper already
waited for a lock or loaded FSM data. When authorisation
requires I/O, acknowledge first, then check it before any protected action; an ACK is
neither authorisation nor success. Coordinate manual ACKs with callback-answer middleware.
Built-in FSM middleware can wait before the handler is reached; check the
[assembled middleware chain](../aiogram-middlewares/SKILL.md#ordering) under contention.
Inline-mode callbacks use `inline_message_id` instead and need their own supported path.

`callback.answer()` itself does not track whether you already answered. Give one layer
ownership of the answer; a manual call does not mark `CallbackAnswerMiddleware`'s injected
`callback_answer` as answered. Disable its automatic answer for manually answered handlers
with `flags={"callback_answer": {"disabled": True}}`. Put feedback known synchronously in
the first answer. If a refusal is discovered after ACK, show it in a message or the still
current menu, not a second `answer(show_alert=True)`.

An opaque short key is a lookup handle, not an access grant. For owner-bound actions,
missing, malformed, expired, or mismatched ownership must reject before consuming the
context. Do not make a historical ownerless payload public to keep old buttons working.
Public/group actions may have different permissions; retain the application's policy.

For current-menu actions, require an exact stored bot/chat/message identity and the
current draft/revision. A missing or zero message ID is not a wildcard. Bind the returned
`Message` after publication, including error/recovery prompts; never resurrect a context
revoked while that send was awaiting. After waiting for a lock or I/O, re-read the context
before applying the action. A stale/foreign tap must not clear current FSM data, revoke
a newer confirmation, or redraw the newest menu. Retire only the obsolete source's
controls when their ownership is proven. Navigating away revokes confirmation permission
even if the surrounding item context remains usable for Back.

Keep claim scope tied to the action and owner, with bot/chat/message or draft revision
where required. A synchronous in-memory consume can precede the first `await` in one
event loop; a durable claim needs a transaction after ACK and before effects. An
in-process lock alone does not survive restart or coordinate replicas.

Claims also apply to a navigation button that creates a flow: a second tap must not
re-enter and wipe the first prompt or its in-progress work. This is application code,
not a `CallbackData` feature. Consume only after checking the caller and source message;
a foreign press must not consume the rightful owner's action.

Return a claim only when admission or execution is confirmed not to have accepted the
action and retry remains safe. An ambiguous send or accepted job keeps its fence. Cleanup
must release only the claim it owns, never a newer action on the same key. Test concurrent
presses, rejection without mutation, and safe claim restoration at the real boundary.

## changing a factory safely

Adding, removing, or reordering fields changes the wire format and breaks every button
already on a user's screen. When you must change one:

- bump the prefix (`prod` → `prod2`) so old payloads clearly mismatch rather than
  mis-parse, and keep the catch-all handler above to explain the expiry; or
- add the new field with a default and accept that old buttons fail the field-count check.

Field **order** matters — `unpack` zips positionally against `model_fields`. Reordering
fields silently reinterprets old payloads if the count happens to match, which is worse
than an error. Do not reorder.

## checklist

- structured payloads use `CallbackData`; simple constants remain valid
- prefixes are short and unique across the codebase
- actions are short `Enum` values
- no free-form user text in a payload
- packed size verified for the worst case, counted in bytes
- narrow `.filter(F...)` handlers registered before broad `.filter()` ones
- a catch-all `@router.callback_query()` answers unknown payloads
- authorisation and entity existence re-checked inside the handler
- mutating handlers safe against repeated presses
- exactly one ACK before slow work; owner-bound contexts fail closed
- application wrappers ACK before their waits; post-ACK errors use message feedback
- exact source identity/revision re-checked after waits; stale taps leave newer flows alone
- flow entry and confirmations claimed once; permission revoked on navigation away

## see also

- `aiogram-keyboards` — building the buttons these payloads ride on
- `aiogram-routing` — handler order
- `aiogram-filters` — magic filters used in `.filter(...)`
- `skills/using-aiogram/references/telegram-quirks.md` — callback expiry and spinner behaviour
