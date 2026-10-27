---
name: aiogram-scenes
description: >
  Use when using the experimental aiogram 3 Scene, SceneWizard, or ScenesManager conversation API.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  stability: experimental
  source: https://github.com/aiogram/aiogram
  documentation: https://docs.aiogram.dev/en/v3.31.0/dispatcher/finite_state_machine/scene.html
  verified: "2026-09-07"
---

# aiogram scenes

> The official aiogram documentation states: **"This feature is experimental and may be
> changed in future versions."**

Take that seriously. Scenes are a convenience layer over FSM; anything built on them may
need edits on a minor upgrade. For code that must survive upgrades untouched, use plain
FSM (`aiogram-fsm`). Choose scenes when the wizard is long enough that the boilerplate of
manual state handling actually hurts.

## when to use this skill

- a linear or branching wizard with many steps
- you want enter/leave hooks and a built-in history (`back`)
- an existing codebase already uses `aiogram.fsm.scene`
- deciding whether to migrate a scene-based flow to plain FSM

## what scenes add over FSM

| Need | Plain FSM | Scenes |
|---|---|---|
| step state | `State` in a `StatesGroup` | one `Scene` subclass per step |
| entering | `state.set_state(...)` | `@on.message.enter()` hook |
| leaving | manual | `@on.message.leave()` / `.exit()` hooks |
| going back | you keep the order yourself | `wizard.back()` with real history |
| data | `FSMContext` | `wizard` with the same operations |

Scenes are still FSM underneath: each scene occupies a state, and the same storage,
strategy, and isolation settings apply.

## a complete scene

```python
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.scene import Scene, SceneRegistry, ScenesManager, on
from aiogram.types import Message


class NameScene(Scene, state="registration_name"):
    @on.message.enter()
    async def greet(self, message: Message) -> None:
        await message.answer("What is your name?")

    @on.message(F.text)
    async def got_name(self, message: Message) -> None:
        await self.wizard.update_data(name=message.text)
        await self.wizard.goto(AgeScene)

    @on.message()
    async def not_text(self, message: Message) -> None:
        await message.answer("Please send your name as text.")


class AgeScene(Scene, state="registration_age"):
    @on.message.enter()
    async def ask(self, message: Message) -> None:
        await message.answer("How old are you?")

    @on.message(F.text.regexp(r"^\d{1,3}$"))
    async def got_age(self, message: Message) -> None:
        data = await self.wizard.update_data(age=int(message.text or "0"))
        await message.answer(f"Thanks, {data['name']} ({data['age']}).", parse_mode=None)
        await self.wizard.clear_data()
        await self.wizard.exit()

    @on.message()
    async def bad(self, message: Message) -> None:
        await message.answer("Send a number.")


router = Router(name="scenes")
router.message.register(NameScene.as_handler(), Command("register"))

dispatcher = Dispatcher()
dispatcher.include_router(router)

registry = SceneRegistry(router)
registry.add(NameScene, AgeScene)

assert issubclass(NameScene, Scene)
assert ScenesManager is not None
```

Register command entry points on the same router **before** `registry.add(...)`, so
a broad active-scene text handler cannot swallow the command.

Three wiring steps, all required:

1. **Declare** the scene with a `state=` name. That string is persisted, exactly like an
   FSM state name.
2. **Register** every scene with `SceneRegistry.add(...)`. A scene you can `goto` but did
   not register will fail at run time.
3. **Provide an entry point** — `Scene.as_handler()` produces a callback you register on a
   router, usually behind a command.

`SceneRegistry(router, register_on_add=True)` attaches scenes to that router as they are
added. With `register_on_add=False`, `add(...)` only records them unless `router=` is
supplied. `register(*scenes)` always adds and attaches to the registry's router; it is
not the lookup-only variant. Do not add a scene twice to obtain both behaviours.

## the `on` marker

`on` exposes 14 markers, a subset of the router observers: `message`, `callback_query`, `edited_message`,
`channel_post`, `edited_channel_post`, `inline_query`, `chosen_inline_result`,
`chat_member`, `my_chat_member`, `chat_join_request`, `poll`, `poll_answer`,
`pre_checkout_query`, `shipping_query`.

Each supports four forms:

| Form | Fires |
|---|---|
| `@on.message(*filters)` | while the scene is active and filters pass |
| `@on.message.enter()` | when the scene is entered |
| `@on.message.leave()` | when leaving for another scene |
| `@on.message.exit()` | when the whole scene stack is exited |

Note the observer prefix on the lifecycle hooks: `@on.message.enter()` runs when the
scene is entered *via a message*. A scene entered from a callback query needs
`@on.callback_query.enter()` as well, or the user gets no prompt.

## SceneWizard

`self.wizard` inside a scene:

| Method | Behaviour |
|---|---|
| `goto(scene, **kwargs)` | leave the current scene and enter another |
| `back(**kwargs)` | return to the previous scene in history |
| `retake(**kwargs)` | re-enter the current scene, re-running its enter hook |
| `exit(**kwargs)` | leave the scene stack entirely |
| `enter(**kwargs)` | run the enter hooks of the current scene |
| `leave(**kwargs)` | run the leave hooks |
| `set_data(data)` / `get_data()` / `update_data(...)` / `clear_data()` | scene data |
| `get_value(key, default=None)` | read one key |

`goto` accepts a `Scene` subclass, a `State`, or a raw state string.

`retake()` re-runs entry actions and also applies `reset_data_on_enter`. If that flag is
true it discards collected data. For invalid input, repeat the prompt directly when you
need to preserve data.

`exit()` clears the current state and scene history, **not FSM data**. Call
`clear_data()` explicitly when completion should discard the collected answers.

`back()` restores the previous history snapshot of both state **and data**, not just a
screen. Do not use it for a cosmetic submenu return that must retain newly edited
values. It also does not remove Telegram buttons or undo external effects. Revoke any
confirmation permission when leaving its step; returning to an item is not permission
to replay a confirmation from a previous visit.

With empty history, `back()` still runs **leave** hooks, then rollback clears state and
data and enters the default scene/state; it does **not** run the departing scene's exit
hooks. Choose a root-Back policy explicitly: omit Back at the root, show the root prompt
without navigation, or call `exit()` and render the destination yourself. If exiting
should discard answers, clear data explicitly. Do not rely on an empty-history Back to
perform exit-hook cleanup.

## `After` — declarative transitions

Declare navigation with the decorator's `after=` argument:

```python
from aiogram import F
from aiogram.fsm.scene import After, Scene, on
from aiogram.types import Message


class ConfirmScene(Scene, state="confirm"):
    @on.message.enter()
    async def ask(self, message: Message) -> None:
        await message.answer("Confirm? yes/no")

    @on.message(F.text.lower() == "yes", after=After.exit())
    async def yes(self, message: Message) -> None:
        await message.answer("Confirmed.")

    @on.message(F.text.lower() == "no", after=After.back())
    async def no(self, message: Message) -> None:
        await message.answer("Going back.")
```

`After.exit()`, `After.back()`, and `After.goto(SomeScene)` run after the handler body
returns.

## SceneConfig

Verified fields: `state`, `handlers`, `actions`, `reset_data_on_enter`,
`reset_history_on_enter`, `callback_query_without_state`, `attrs_resolver`.

Set them as class keyword arguments:

```python
from aiogram.fsm.scene import Scene, on
from aiogram.types import Message


class FreshScene(
    Scene,
    state="fresh",
    reset_data_on_enter=True,
    reset_history_on_enter=True,
    callback_query_without_state=True,
):
    @on.message.enter()
    async def enter(self, message: Message) -> None:
        await message.answer("clean slate")
```

- `reset_data_on_enter=True` clears scene data on every entry — right for a flow that
  should never inherit a previous attempt's answers.
- `reset_history_on_enter=True` clears history on each entry; it does not make root Back
  a no-op. Apply the explicit root-Back policy above.
- `callback_query_without_state=True` lets the scene's callback handlers fire even when
  the user has any state (or none): it removes the scene state filter entirely. Keep
  payload and permission filters narrow so old buttons cannot hijack another flow.

## entering from elsewhere

Outside a scene, aiogram injects a `ScenesManager` as `scenes`:

```python
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.scene import Scene, ScenesManager, on
from aiogram.types import Message

router = Router(name="entry")


class Start(Scene, state="start"):
    @on.message.enter()
    async def enter(self, message: Message) -> None:
        await message.answer("in the scene")


@router.message(Command("go"))
async def go(message: Message, scenes: ScenesManager) -> None:
    await scenes.enter(Start)


@router.message(Command("leave"))
async def leave(message: Message, scenes: ScenesManager, state: FSMContext) -> None:
    await scenes.close()
    await state.clear()  # close() runs exit hooks; clear() also discards form data.
```

`Scene.as_router(name=None)` returns a ready-made `Router` for the scene if you prefer
composing routers over registering handlers.

Wire global exits before broad scene handlers and use `scenes.close()` while the scene
is still active so its exit hooks run; clearing FSM first can bypass them. Save control
IDs needed for cleanup before discarding data. Apply the same exit policy to command
and button navigation. Closing a scene alone does not revoke application contexts,
pending publications, or keyboards, and it does not imply cancelling accepted jobs.

For callback entry, acknowledge in the application entry handler before
`scenes.enter(...)`, after synchronous owner/source checks. An enter hook is too late
for the first ACK: scene entry already awaits FSM storage before invoking it. Hooks run
for the triggering event kind; callback-driven `goto`, `back` and `retake` also need the
corresponding callback hooks. Reuse a renderer but keep message and callback adapters
separate, with exact message identity and no second answer in the renderer.

## limits and cautions

- **Experimental.** Pin your aiogram version and re-read the changelog before upgrading.
- Scene `state=` strings are persisted. Renaming one strands users mid-flow exactly as
  with plain FSM; keep the recovery handler described in `aiogram-fsm`.
- History uses a separate `scenes_history` destiny, with a default depth of 10. It
  shares the storage and JSON constraints. Redis keys need `with_destiny=True`.
- A scene entered from a callback query needs `@on.callback_query.enter()`; forgetting it
  is the most common scenes bug.
- Scene data is shared with normal FSM data under the same key. Do not run a hand-written
  FSM flow and a scene over the same user at the same time.
- Private prompts from a group require an explicit `bot.send_message(user_id, ...)`
  and permission to contact that user. Scene hooks do not move the FSM key to a DM.

## migrating a scene to plain FSM

If the experimental status becomes a problem: one scene becomes one `State`; `enter`
hooks become the code that runs right after `set_state`; `wizard.goto` becomes
`set_state`; `wizard.exit` clears state/history but retains data (use `state.clear()`
if full cleanup is intended); `back()` becomes an explicit step
list. The persisted state strings can be kept identical, so users mid-flow are not lost.

## checklist

- the experimental status is acceptable for this codebase, and the aiogram version is pinned
- every scene registered with `SceneRegistry.add(...)`
- at least one entry point via `Scene.as_handler()` or `ScenesManager.enter(...)`
- `@on.callback_query.enter()` present wherever a scene can be entered from a button
- invalid input repeats a prompt without unintentionally resetting collected data
- `wizard.exit()` on success, cancel, and unrecoverable failure
- global exits close the active scene before clearing data; old controls/permissions revoked
- callback entry ACKs before scene transitions; lifecycle hooks cover each triggering event kind
- Back's state/data snapshot rollback is intentional, not used as a cosmetic menu return
- scene `state=` strings treated as persisted values, not renamed casually
- only JSON-serialisable values in scene data
- a recovery handler for states left behind by a previous deployment
- no hand-written FSM flow running over the same user at the same time

## see also

- `aiogram-fsm` — the stable foundation, and the fallback if scenes change
- `aiogram-routing` — where `as_handler()` / `as_router()` attach
- `aiogram-keyboards` — driving a wizard from buttons
