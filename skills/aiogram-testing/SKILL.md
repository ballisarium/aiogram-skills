---
name: aiogram-testing
description: >
  Use when testing aiogram 3 handlers and FSM with feed_update, fake sessions, or offline assertions.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  pytest: ">=9.1"
  pytest_asyncio: ">=1.4"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram testing

Test at the **dispatcher boundary**: feed an `Update` in, assert on the API calls that
come out. No network, no token, no polling.

## the thing to know first

`aiogram.test_utils` is **not part of the distributed package**. Verified on aiogram
3.31.0:

```text
$ python -c "import aiogram.test_utils"
ModuleNotFoundError: No module named 'aiogram.test_utils'
```

`mocked_bot.py` exists in the aiogram repository under `tests/`, but the wheel ships only
`client`, `dispatcher`, `enums`, `exceptions.py`, `filters`, `fsm`, `handlers`,
`loggers.py`, `methods`, `types`, `utils`, and `webhook`. Any guide telling you to
`from aiogram.test_utils.mocked_bot import MockedBot` is describing the repository, not
an installed release.

So you write a fake session. It is about thirty lines, and you own it.

## when to use this skill

- unit-testing handlers, filters, or middleware
- asserting what the bot sent
- testing an FSM flow end to end
- testing without a token or network
- setting up pytest for an async bot

## the recording session

`BaseSession` has exactly three abstract methods: `make_request`, `stream_content`,
`close`. Implement them and `Bot` never touches the network.

```python
import datetime
from collections.abc import AsyncGenerator
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message


class RecordingSession(BaseSession):
    """Application fake: records calls and returns results or raises configured failures."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.results: dict[str, Any] = {}

    def will_return(self, method_name: str, value: Any) -> None:
        """Configure a result or exception for one API method."""
        self.results[method_name] = value

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.calls.append(method)
        name = type(method).__name__
        if name in self.results:
            result = self.results[name]
            if isinstance(result, BaseException):
                raise result
            if isinstance(result, Message):
                return result.as_(bot)
            if isinstance(result, list):
                return [item.as_(bot) if isinstance(item, Message) else item for item in result]
            return result
        if not isinstance(method, SendMessage):
            raise AssertionError(f"Configure a result for {name}")
        return Message(
            message_id=len(self.calls),
            date=datetime.datetime.now(datetime.timezone.utc),
            chat=Chat(id=getattr(method, "chat_id", 1) or 1, type="private"),
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

    def calls_to(self, method_name: str) -> list[TelegramMethod[Any]]:
        return [call for call in self.calls if type(call).__name__ == method_name]


session = RecordingSession()
bot = Bot(token="123456:TEST", session=session)
assert bot.id == 123456
```

`123456:TEST` passes `aiogram.utils.token.validate_token`, which only requires
`<digits>:<non-empty>` without whitespace. No real token is needed anywhere in a test suite.

This fake does not validate Telegram's server rules or serialise bot defaults. Inspect
`parse_mode`/entities explicitly, including calls made with a global HTML default. Its
download stream is an empty fixture, not proof that media downloaded or decoded. Replace
it with controlled bytes or fail-fast behaviour when the changed flow can download.
Configure exceptions to exercise real handler error paths; returning an exception object
is not the same as raising it. Use a scripted per-call sequence when testing retry or
partial success, and fail on extra calls rather than returning unlimited successes.

## update fixtures

```python
import datetime

from aiogram.types import CallbackQuery, Chat, Message, Update, User

USER = User(id=42, is_bot=False, first_name="Tester", username="tester")
CHAT = Chat(id=42, type="private")


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def message_update(text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=now(),
            chat=CHAT,
            from_user=USER,
            text=text,
        ),
    )


def callback_update(data: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=USER,
            chat_instance="test",
            data=data,
            message=Message(message_id=1, date=now(), chat=CHAT, text="menu"),
        ),
    )


assert message_update("/start").message is not None
assert callback_update("ping").callback_query is not None
```

Build these once in `conftest.py`. Hand-writing an `Update` in every test is the fastest
way to a brittle suite.

`feed_raw_update(bot, {...})` takes the raw JSON dict instead. Sanitise any captured
payload before using it as a fixture; preserve the field shape, not private content.

## a complete test

```python
import asyncio
import datetime
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.filters import CommandStart
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User


def make_router() -> Router:
    router = Router(name="under-test")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer("Welcome!")

    return router


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        assert isinstance(method, SendMessage), type(method).__name__
        return Message(
            message_id=1,
            date=datetime.datetime.now(datetime.timezone.utc),
            chat=Chat(id=1, type="private"),
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


@pytest.mark.asyncio
async def test_start_greets() -> None:
    session = FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(make_router())

    update = Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.datetime.now(datetime.timezone.utc),
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="T"),
            text="/start",
        ),
    )
    try:
        await dispatcher.feed_update(bot, update)

        assert len(session.calls) == 1
        sent = session.calls[0]
        assert isinstance(sent, SendMessage)
        assert sent.text == "Welcome!"
        assert sent.chat_id == 1
    finally:
        await dispatcher.storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(test_start_greets())
```

Assert on the **method object**, not on a string. `isinstance(sent, SendMessage)` plus
field checks survives refactors that a `str(call)` comparison would not.

## injecting fakes

Anything a handler pulls from workflow data can be replaced per test by passing it to
`feed_update`:

```python
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, Update

router = Router(name="di-test")


class Repository:
    async def name_for(self, user_id: int) -> str:
        raise NotImplementedError


@router.message()
async def show_name(message: Message, repository: Repository) -> None:
    if message.from_user is not None:
        await message.answer(await repository.name_for(message.from_user.id))


class FakeRepository(Repository):
    async def name_for(self, user_id: int) -> str:
        return "fake name"


async def run_case(bot: Bot, dispatcher: Dispatcher, update: Update) -> None:
    """Extra kwargs join workflow data for this update only."""
    await dispatcher.feed_update(bot, update, repository=FakeRepository())
```

This is why handlers should depend on injected services rather than reaching for module
globals — the seam already exists.

## FSM assertions

```python
import asyncio

from aiogram import Bot
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage


class Form(StatesGroup):
    name = State()


async def check_state() -> None:
    storage = MemoryStorage()
    bot = Bot(token="123456:TEST")
    key = StorageKey(bot_id=bot.id, chat_id=42, user_id=42)

    await storage.set_state(key, Form.name)
    await storage.set_data(key, {"name": "Ada"})

    assert await storage.get_state(key) == "Form:name"
    assert await storage.get_data(key) == {"name": "Ada"}


asyncio.run(check_state())
```

Build the `StorageKey` with the same fields your `FSMStrategy` uses — with the default
`USER_IN_CHAT`, that is `bot_id`, `chat_id`, and `user_id`. Pass the storage to
`Dispatcher(storage=storage)` so a test can drive a flow update by update and inspect the
state between steps.

## testing filters and middleware directly

Filters and middleware are plain callables — no dispatcher required:

```python
import asyncio
import datetime

from aiogram.filters import Command
from aiogram.types import Chat, Message, User


async def check_filter() -> None:
    message = Message(
        message_id=1,
        date=datetime.datetime.now(datetime.timezone.utc),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="T"),
        text="/help now",
    )
    # No @mention is present, so this filter path does not consult Bot.get_me().
    result = await Command("help")(message, bot=None)
    assert isinstance(result, dict)
    assert result["command"].args == "now"

    assert await Command("other")(message, bot=None) is False


asyncio.run(check_filter())
```

A filter returning a `dict` is what injection looks like from the inside.

## pytest setup

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
filterwarnings = ["error"]
```

`asyncio_mode = "auto"` removes the need for `@pytest.mark.asyncio` on every test.
Setting `asyncio_default_fixture_loop_scope` explicitly silences a pytest-asyncio
deprecation warning that `filterwarnings = ["error"]` would otherwise turn into a failure.

Use the project's existing fixtures. When a bot fixture is needed, create a fresh
`RecordingSession` and `Bot` per test and close the bot session in fixture teardown.
Do not share a router instance between dispatcher fixtures: a router can have only one
parent. Construct the router per test or use the application's router factory.

## what to test

| Layer | Assert |
|---|---|
| routing | the intended update matches, unrelated ones do not |
| filters | accept, reject, and injected values |
| handlers | the API calls produced, and their fields |
| callbacks | payload packing, parsing, and stale payloads |
| FSM | every transition, invalid input, cancel, cleanup |
| middleware | continues, short-circuits, and tears down |
| durable work | claim/owner fences, cancel versus intent/ACK, terminal settlement, restart |
| rendering/locales | assembled text + controls, placeholders, actual decoded output |
| registration | every router included, and the module imports without side effects |

For import-side-effect regressions, import the application's handler module with its
network/loop-start entry points replaced by fail-fast sentinels. Importing `aiogram`
itself does not verify that the application's module starts nothing.

### regressions at real boundaries

Derive expected results from the requirement or observed reference, not from the new
implementation. Run the regression before the fix and confirm it fails at the intended
boundary; a broken fixture or worker that never started is not the expected red signal.
Use real aiogram `Message`/`CallbackQuery` objects, including the
actual photo/caption or inaccessible-message branch. They are frozen models; use
`model_copy(update=...)` to derive a fixture. A permissive message double can wrongly
accept `edit_text` on a photo and hide the very regression being tested.
Typed models do not enforce Telegram's server-side edit rules either: assert the exact
method and media kind, or make the fake session reject an incompatible edit.

For transitions, record API call order and exact message IDs: one ACK before slow work,
old controls retired before a replacement, and one reachable next surface. Exercise
double taps with explicit events/barriers, not arbitrary sleeps. For job/retry tests,
assert acknowledged items are skipped, the delay/checkpoint survives recovery, and
unknown outcomes do not trigger a second mutation. Keep real owner/cooldown/format guards
in the path; replace only the external boundary. Format claims need real decoding, while
orchestration tests can stub expensive conversion.

For bots with durable jobs, test both orders at cancellation, intent and ACK boundaries,
including a queued job
cancelled before any worker runs. Assert persisted state after reopening storage, no
result after accepted cancel, idempotent reservation settlement and no effect from a stale
owner. Inject cancellation during rollback/cleanup as well as the main request. For
process tests, wait for explicit worker/child readiness with a bounded startup budget
before starting the behaviour deadline; clean up only processes the test owns.

For UI changes, assert the final assembled text **and** keyboard for entry, success,
error, Back and Cancel across supported locales. Check exact message/media targets and
that recovery remains reachable with old controls retired. For visual claims, inspect
the actual final artefact at its intended viewing size; structure/parity checks and a
permissive fake cannot establish legibility or client rendering.

Use disposable configuration, DBs, paths, storage, and caches before importing the app.
Prevent `.env`/production credentials and unintended network access in the offline suite;
a mocked `send_message` alone does not isolate download/profile/error-report paths.
Removing environment variables is insufficient if a later dotenv reader restores them;
isolate that reader while preserving the real parser/validation. A new temporary cache
directory also does not reset an already-loaded in-memory cache: reset its loaded state
and drain owned pending writes before teardown.
Avoid global `sys.modules` dependency stubs or disabling guards across the suite. When
collection order causes failures, verify both orders in fresh processes. Report local
dispatch, real artefact validation, and an explicitly authorised current Telegram
walkthrough as separate evidence; an old message with matching text proves neither flow.

## what not to do

- **Do not hit the Telegram API.** No real tokens in tests, not even in "integration"
  ones that CI will run on every push.
- Use `feed_update` for dispatch behaviour. It does **not** test HTTP authentication,
  webhook acknowledgement, polling offsets, or live Telegram rendering. Test transport
  separately with a local HTTP fixture when that is the changed contract.
- **Do not assert on log output** when you can assert on the recorded method object.
- **Do not share one `MemoryStorage` across tests** — state leaks between them.
- **Do not mock `aiohttp`.** Replace the whole session; it is a smaller, more stable
  surface.

## checklist

- a fake `BaseSession` records calls; no network anywhere in the suite
- fake tokens only
- fixtures for `Update`, `Message`, `CallbackQuery` in `conftest.py`
- assertions on `TelegramMethod` instances and their fields
- dependencies injected per test through `feed_update` kwargs
- fresh storage per test
- FSM transitions covered including invalid input and cancel
- import side effects tested when that is the behaviour being changed
- regression red for the intended reason before the fix, then green with real guards
- race tests use barriers/readiness, fresh storage and both competing orderings
- cancellation/restart preserve owner, reservation and intent/ACK invariants
- final assembled surfaces/locales checked; local, artefact and live evidence reported separately

## see also

- `using-aiogram` — the `feed_update` overview
- `aiogram-routing` — `feed_update` / `feed_raw_update`
- `aiogram-fsm` — storage and keys
- `aiogram-middlewares` — injecting fakes through workflow data
