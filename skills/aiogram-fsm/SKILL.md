---
name: aiogram-fsm
description: >
  Use when building or debugging aiogram 3 multi-step conversations, state storage, isolation, or cancel/back flows.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram FSM

Use FSM when the bot must remember progress **across updates**. A single-step action
needs no state — reaching for FSM there adds cleanup obligations for nothing.

## when to use this skill

- a conversation that spans several messages or button presses
- collecting a form field by field
- choosing a storage backend, or losing state on restart
- deciding what the FSM key should be scoped to
- users stuck in a state that no longer exists
- implementing cancel, back, or retry

## states

```python
from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    waiting_for_item = State()
    waiting_for_quantity = State()
    waiting_for_confirmation = State()


assert OrderForm.waiting_for_item.state == "OrderForm:waiting_for_item"
assert OrderForm.__all_states_names__ == (
    "OrderForm:waiting_for_item",
    "OrderForm:waiting_for_quantity",
    "OrderForm:waiting_for_confirmation",
)
```

The stored value is the string `"Group:attribute"`. That string is **persisted**. Renaming
a class or an attribute strands every user currently sitting in the old name — treat
state names as a migration surface, not as free-form identifiers.

Name states after what the bot is waiting for (`waiting_for_quantity`), never after the
handler (`step2`).

## FSMContext

aiogram injects an `FSMContext` as `state` into any handler that declares it.

```python
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

router = Router(name="order")


class OrderForm(StatesGroup):
    waiting_for_item = State()
    waiting_for_quantity = State()


@router.message(Command("order"))
async def begin(message: Message, state: FSMContext) -> None:
    await state.clear()  # This entry starts a fresh form, not a resume.
    await state.set_state(OrderForm.waiting_for_item)
    await message.answer("What would you like to order?")


@router.message(OrderForm.waiting_for_item, F.text)
async def got_item(message: Message, state: FSMContext) -> None:
    await state.update_data(item=message.text)
    await state.set_state(OrderForm.waiting_for_quantity)
    await message.answer("How many?")


@router.message(OrderForm.waiting_for_quantity, F.text.regexp(r"^[1-9]\d{0,3}$"))
async def got_quantity(message: Message, state: FSMContext) -> None:
    data = await state.update_data(quantity=int(message.text or "0"))
    await state.clear()
    await message.answer(f"{data['quantity']} x {data['item']}", parse_mode=None)


@router.message(OrderForm.waiting_for_quantity)
async def bad_quantity(message: Message) -> None:
    """Invalid input stays in the state and explains the problem."""
    await message.answer("Send a number between 1 and 9999.")
```

Verified `FSMContext` surface:

| Method | Behaviour |
|---|---|
| `set_state(state=None)` | accepts a `State`, a raw string, or `None` to clear the state |
| `get_state()` | returns the stored string or `None` |
| `update_data(data=None, **kwargs)` | merges and **returns the merged dict** |
| `get_data()` | returns the whole dict |
| `get_value(key, default=None)` | returns one key; the default storage implementation loads `get_data()` |
| `set_data(data)` | replaces the dict wholesale |
| `clear()` | drops **both** state and data |

`update_data` returning the merged dict is worth using — it saves a follow-up `get_data`.

## state filters

A `State` object used directly as a filter is shorthand for `StateFilter(that_state)`.

```python
from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

router = Router(name="state-filters")


class Form(StatesGroup):
    a = State()
    b = State()


@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("Cancelled.")


@router.message(Form.a)
async def in_a(message: Message) -> None: ...


@router.message(StateFilter(Form))
async def anywhere_in_form(message: Message) -> None:
    """Passing the group matches any state inside it."""


@router.message(StateFilter(None))
async def no_state(message: Message) -> None: ...
```

`StateFilter(None)` means *no state*; `StateFilter("*")` means *any state, including
none*. Cancel handlers want `"*"`, and they must be registered **before** the state
handlers that would otherwise consume the message.

## storage

`MemoryStorage` is the default and loses everything on restart. That is fine for
development or intentionally disposable sessions. Choose persistent storage when state must survive restarts.

```python
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

dispatcher = Dispatcher(storage=MemoryStorage())
```

Redis, using the `redis` extra (`pip install "aiogram[redis]"`):

```python
from aiogram import Dispatcher
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage

storage = RedisStorage.from_url(
    "redis://localhost:6379/0",
    key_builder=DefaultKeyBuilder(prefix="mybot", with_bot_id=True),
)
dispatcher = Dispatcher(storage=storage)
```

Verified constructors:

```text
RedisStorage(redis, key_builder=None, state_ttl=None, data_ttl=None,
             json_loads=json.loads, json_dumps=json.dumps)
RedisStorage.from_url(url, connection_kwargs=None, **kwargs)
```

- `state_ttl` / `data_ttl` accept `int` seconds or `timedelta`. Setting them is how you
  garbage-collect abandoned conversations; without a TTL, every half-finished form lives
  forever.
- `with_bot_id=True` is required when several bots share one Redis database — otherwise
  their keys collide.
- State and data TTLs expire independently; setting a state does not refresh data TTL.
- Scenes history needs `DefaultKeyBuilder(with_destiny=True)`. Enable
  `with_business_connection_id=True` when business connections need separate keys.
- Use the same key builder for storage and `RedisEventIsolation` (or use
  `storage.create_isolation()`). Changing key options changes persisted key names.
- FSM data is JSON-serialised. Do not store `datetime`, `Decimal`, model instances, or
  anything else that will not round-trip. Store ids and re-fetch.

Durable jobs do not make the conversation durable: choose FSM persistence separately.
For a custom backend, round-trip both state and data through a fresh storage/Dispatcher
instance. If it validates known state names, derive that inventory from the actual
`StatesGroup` definitions so a new state is not silently discarded. Test key isolation,
expiry, corrupt/legacy records, and rollback on cancellation at that backend boundary.
Use the existing storage architecture; this does not require adding Redis or a new DB.
If conversations are intentionally disposable, provide an expiry/restart path. Restore
only from validated durable context; never infer lost state from the last chat message.

`MongoStorage` under `aiogram.fsm.storage.mongo` is deprecated. Prefer
`PyMongoStorage` under `aiogram.fsm.storage.pymongo` with the `mongo` extra.

### writing a storage

`BaseStorage` has exactly five abstract methods: `set_state`, `get_state`, `set_data`,
`get_data`, `close`. Implement them and any backend works.

```python
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey


class NullStorage(BaseStorage):
    """Minimal conforming storage; useful as a template."""

    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None: ...

    async def get_state(self, key: StorageKey) -> str | None:
        return None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None: ...

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return {}

    async def close(self) -> None: ...
```

## keys and scope

`StorageKey` fields: `bot_id`, `chat_id`, `user_id`, `thread_id`,
`business_connection_id`, `destiny`.

`FSMStrategy` chooses which of those the key uses:

| Strategy | State is shared across |
|---|---|
| `USER_IN_CHAT` (default) | one user in one chat |
| `CHAT` | the whole chat — every member shares one conversation |
| `GLOBAL_USER` | one user across all chats |
| `USER_IN_TOPIC` | one user in one forum topic |
| `CHAT_TOPIC` | one forum topic |

```python
from aiogram import Dispatcher
from aiogram.fsm.strategy import FSMStrategy

dispatcher = Dispatcher(fsm_strategy=FSMStrategy.USER_IN_TOPIC)
```

Pick deliberately. `USER_IN_CHAT` means a user filling a form in a private chat and in a
group has two independent conversations — usually what you want. `CHAT` means one user
can advance a form another user started.

`destiny` separates independent state machines under the same key; `FSMContext` accepts a
custom `StorageKey`, which is how you run a second, parallel FSM for the same user.

## event isolation

Without isolation, a user sending two messages quickly can have both processed
concurrently against the same state, producing interleaved writes.

```python
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

dispatcher = Dispatcher(
    storage=MemoryStorage(),
    events_isolation=SimpleEventIsolation(),
)
```

`SimpleEventIsolation` and `MemoryStorage` are in-process only. Multiple replicas need
both shared storage (such as `RedisStorage`) and shared isolation (such as
`RedisEventIsolation`); a shared lock cannot make separate memory stores agree.
`DisabledEventIsolation` is the default no-op.

Isolation orders incoming updates; it does not fence a background worker's stale result.
Persist the draft revision and intended control-message identity when handing work off.
Before applying a result or rollback, compare ownership/revision and current navigation
state so an old render cannot restore an obsolete menu or overwrite a newer edit.

A state filter checks the `raw_state` loaded for dispatch, not a live condition that
stays true across awaits. If an application lock is acquired inside the handler, re-read
`state.get_state()` and the draft key/revision **after acquiring it**, before cleanup,
mutation or enqueue. Serialise the whole `read → retire old controls → send → remember
returned ID` transition, not only the final write. All competing transitions must use
the same ownership/locking policy. A re-read without a lock or compare-and-set is not
an atomic guard; use the application's storage fence for cross-process work. Do not
restore a draft after an exception if navigation has already revoked it.

## cancel, back, and retry

```python
from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

router = Router(name="navigation")


class Wizard(StatesGroup):
    one = State()
    two = State()
    three = State()


ORDER = (Wizard.one, Wizard.two, Wizard.three)


@router.message(Command("back"), StateFilter("*"))
async def go_back(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    names = [step.state for step in ORDER]
    if current not in names:
        await message.answer("Nothing to go back to.")
        return
    index = names.index(current)
    if index == 0:
        await state.clear()
        await message.answer("Cancelled.")
        return
    await state.set_state(ORDER[index - 1])
    await message.answer("Back one step.")
```

aiogram has no built-in history. Either keep an explicit step order as above, or push
visited states into FSM data yourself. (The experimental Scenes API does provide history —
see `aiogram-scenes`.)

The first-step cancellation above is a demo policy. Define Back and Cancel separately for
the actual product: Back preserves still-valid earlier input; Cancel ends the flow and
cleans up its controls. Do not silently discard an edited draft through an innocuous Back.

## stale state after a deploy

Users keep their state across your deployments. After renaming or removing a state, their
stored string no longer matches the intended state-specific handler; global handlers
can still match, but the conversation may appear dead.

Reject recognised/idle states in the **filter**, not by returning from an already matched
handler: returning still consumes the update. This recovery router belongs after normal
flows but before any unconditional message fallback:

```python
from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

recovery = Router(name="recovery")


class OrderForm(StatesGroup):
    waiting_for_item = State()
    waiting_for_quantity = State()


# Include ALL current StatesGroup classes; these names are application policy.
KNOWN_STATES = set(OrderForm.__all_states_names__)


class UnknownState(BaseFilter):
    async def __call__(self, message: Message, raw_state: str | None = None) -> bool:
        return raw_state is not None and raw_state not in KNOWN_STATES


@recovery.message(UnknownState())
async def unknown_state(message: Message, state: FSMContext) -> None:
    """Only an obsolete persisted state reaches this handler."""
    await state.clear()
    await message.answer("That conversation expired. Send /start to begin again.")
```

Also worth doing: set `state_ttl` so abandoned states expire on their own, and prefer
adding a new state over renaming an old one.

## clear on every exit path

State must be cleared on success, on cancel, on unrecoverable failure, when the user
loses permission, and when the entity the flow was about is deleted. A missed path is the
single most common FSM bug — the user is stuck and every message they send is swallowed
by a state handler.

`state.clear()` does not remove Telegram keyboards, application drafts, or queued work.
Read the IDs needed for cleanup before clearing them. Route global exits through the
same cleanup used by Cancel, including surfaces created by workers and recorded outside
FSM. A global utility command may intentionally leave the active flow intact; make that
policy explicit and test both command and retained-button entry paths.

Starting a fresh flow must clear incompatible data, not just call `set_state`: changing
the state retains the previous data dict. Revoke old confirmation permissions as well as
visible buttons, scoped to the current bot/chat/user; a late old callback must not clear
the new flow. Accepted background jobs have their own lifetime: leaving the conversation
is not automatically job cancellation. Match every prompt to the state already installed
and cover valid input, invalid input, Back, Cancel and global exits through the composed
Dispatcher, not just direct handler calls.

## checklist

- state names describe what is awaited, and are treated as persisted values
- every state has a handler for invalid input that does not advance
- `/cancel` uses `StateFilter("*")` and is registered before state handlers
- `clear()` on success, cancel, failure, and permission loss
- storage persistence and TTL match the required conversation lifetime
- only JSON-serialisable values in FSM data
- `with_bot_id=True` when several bots share a backend
- recovery filters match only unknown persisted states, before unconditional fallbacks
- `events_isolation` set when double-sends can corrupt a flow
- state/draft re-checked after application-lock waits; complete surface transitions serialised
- global exits/fresh entry clear incompatible data and revoke old action permissions
- late callbacks/results cannot clear or restore a newer flow

## see also

- `using-aiogram` — the overview
- `aiogram-scenes` — the experimental class-based wizard layer over this
- `aiogram-filters` — `StateFilter` semantics
- `aiogram-callback-data` — driving flows from buttons
- `aiogram-testing` — exercising transitions offline
