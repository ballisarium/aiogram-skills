---
name: aiogram-streaming
description: >
  Use when streaming aiogram 3 text/progress with message drafts, rich messages, throttled edits, or chat actions.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram streaming

Incremental output uses Bot API drafts, rich content, repeated edits, or chat actions.
Edit throttling is application code; rich content alone is not incremental delivery.

| Approach | Real API? | Best for |
|---|---|---|
| **message drafts** (`sendMessageDraft`) | yes, Bot API 10.x | incremental text, animated in-progress text |
| **rich messages** (`sendRichMessage`) | yes, Bot API 10.x | structured long-form output |
| **edit throttling** | pattern you write | anything, any Bot API version |
| chat actions (`typing`) | yes | short waits with no partial output |

Verified present in aiogram 3.31.0: `Bot.send_message_draft`, `Bot.send_rich_message`,
`Bot.send_rich_message_draft`.

```bash
python skills/using-aiogram/tools/get-method.py sendMessageDraft
python skills/using-aiogram/tools/get-type.py InputRichMessage
```

## when to use this skill

- streaming text into a chat
- showing progress on a long job
- a bot hitting flood limits while editing a message repeatedly
- deciding between a draft, a rich message, and edit throttling

## message drafts

`sendMessageDraft` shows evolving text in the chat before a real message exists. Quoted
from the field documentation carried by aiogram 3.31.0:

- `draft_id` — *"Unique identifier of the message draft; must be non-zero. Changes to
  drafts with the same identifier are animated"*
- `text` — *"Text of the message to be sent, 0-4096 characters after entities parsing.
  Pass an empty text to show a 'Thinking…' placeholder"*
- `chat_id` — *"Unique identifier for the target private chat"*

Two consequences that decide the design: **reuse one `draft_id`** so updates animate
rather than replace, and drafts are for **private chats**.

```python
import time
from collections.abc import AsyncIterator

from aiogram import Bot


async def stream_with_draft(
    bot: Bot,
    chat_id: int,
    chunks: AsyncIterator[str],
    draft_id: int,
) -> str:
    """Single-message example; the caller allocates a non-zero id per generation."""
    if draft_id == 0:
        raise ValueError("draft_id must be non-zero")
    await bot.send_message_draft(chat_id=chat_id, draft_id=draft_id, text="", parse_mode=None)
    buffer = ""
    last_update = time.monotonic()
    async for chunk in chunks:
        buffer += chunk
        if len(buffer.encode("utf-16-le")) // 2 > 4096:
            raise ValueError("Split long output into messages in the caller")
        if buffer and time.monotonic() - last_update >= 1.2:
            await bot.send_message_draft(
                chat_id=chat_id,
                draft_id=draft_id,
                text=buffer,
                parse_mode=None,
            )
            last_update = time.monotonic()
    if buffer:
        await bot.send_message(chat_id=chat_id, text=buffer, parse_mode=None)
    return buffer
```

`send_message_draft` returns `bool`, not a `Message`. Its method documentation calls the
draft a "temporary 30-second preview": final output **must** be sent with `send_message`
to persist it, not merely when a message id is convenient. A lost final-send response
is ambiguous; do not restart the stream and resend the result blindly.

Draft updates are paced here, but 429 and transport errors propagate. Apply the bounded
`with_flood_retry` pattern from `aiogram-rate-limits` at the call boundary where needed.
Pacing does not guarantee avoiding Telegram limits.

## rich messages

`sendRichMessage` takes an `InputRichMessage` and returns a real `Message`. Content is
given as `html`, `markdown`, or a list of typed `blocks`:

```python
from aiogram import Bot
from aiogram.types import (
    InputRichBlockParagraph,
    InputRichBlockPreformatted,
    InputRichBlockSectionHeading,
    InputRichMessage,
)


async def send_report(bot: Bot, chat_id: int) -> None:
    content = InputRichMessage(
        blocks=[
            InputRichBlockSectionHeading(text="Build report"),
            InputRichBlockParagraph(text="All checks passed."),
            InputRichBlockPreformatted(text="pytest: 42 passed"),
        ]
    )
    await bot.send_rich_message(chat_id=chat_id, rich_message=content)


block = InputRichBlockParagraph(text="hello")
assert block.type == "paragraph"
assert InputRichMessage(blocks=[block]).blocks is not None
```

`InputRichMessage` fields: `html`, `markdown`, `is_rtl`, `skip_entity_detection`,
`blocks`, `media`. Use `blocks` for structure you control; use `html`/`markdown` when the
content already exists in that form, with `media` supplying the `tg://photo?id=` targets.

Block types available in aiogram 3.31.0 include paragraph, section heading, preformatted,
list and list item, table, block quotation, pull quotation, details, divider, footer,
anchor, collage, slideshow, map, mathematical expression, thinking, and the media blocks
(photo, video, audio, animation, voice note).

`send_rich_message_draft(chat_id, draft_id, rich_message, ...)` is the
draft form — the same animation behaviour, with structured content. It is ephemeral too;
use `send_rich_message` to persist final rich output.

## edit throttling: the portable pattern

This works on any Bot API version and in any chat type. It is **your code**, not an
aiogram feature.

```python
import asyncio
import time
from collections.abc import AsyncIterator

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

MIN_INTERVAL = 1.2  # application pacing; Telegram may require a longer delay
MAX_LENGTH = 4096


async def stream_by_editing(
    bot: Bot,
    chat_id: int,
    chunks: AsyncIterator[str],
) -> Message:
    """Coalesce a single message; reject overflow instead of silently losing text."""
    message = await bot.send_message(chat_id=chat_id, text="…", parse_mode=None)
    buffer = ""
    shown = ""
    last_edit = time.monotonic()

    async def flush() -> None:
        nonlocal shown, last_edit
        if buffer == shown or not buffer:
            return
        await asyncio.sleep(max(0.0, MIN_INTERVAL - (time.monotonic() - last_edit)))
        for attempt in range(3):
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text=buffer,
                    parse_mode=None,
                )
            except TelegramRetryAfter as error:
                if attempt == 2:
                    raise
                await asyncio.sleep(error.retry_after)
                continue
            except TelegramBadRequest as error:
                if "message is not modified" not in error.message.casefold():
                    raise
            shown = buffer
            last_edit = time.monotonic()
            return

    async for chunk in chunks:
        buffer += chunk
        if len(buffer.encode("utf-16-le")) // 2 > MAX_LENGTH:
            raise ValueError("Split long output into messages in the caller")
        if time.monotonic() - last_edit >= MIN_INTERVAL:
            await flush()
    if not buffer:
        buffer = "No output was produced."
    await flush()  # retry the tail too; exhaustion is reported to the caller
    return message
```

Every line there exists for a reason:

- **Coalesce.** Token-by-token edits are the fastest way to a flood limit.
- **Compare before editing.** Identical text raises `message is not modified`.
- **Check UTF-16 length.** This example rejects overflow; the caller must split long output.
- **Honour `retry_after`.** Never a hardcoded sleep.
- **Flush the tail.** Otherwise the last few tokens never appear.

This example has one producer. With concurrent progress callbacks, serialise updates at
the message owner, keep only the newest revision, and prevent counters from regressing.
Persist recovery checkpoints independently of how often the UI is edited; throttling
one must not lose the other. Bound maximum status staleness as well as edit frequency.

Before cancellation, deletion, or a terminal edit, invalidate pending progress and drain
or fence in-flight edits so a late callback cannot replace the final message. Cleanup
must target the exact status message and task generation. For durable jobs, defer/drop
cosmetic updates on FloodWait rather than sleeping in the shared worker slot; final
result delivery keeps its own checkpoint and retry policy. Stop the progress producer
first, settle/checkpoint result delivery next, and clean the exact status surface last.
A failed status delete, caption update, cache write, or telemetry call cannot turn a
confirmed result into failure or justify resending it. Report cleanup separately with
redacted diagnostics. If the producer fails before completion, deliberately retire or
mark its owned placeholder; do not leave it showing permanent progress.

### streaming partial markup

Never send partial HTML or MarkdownV2. A half-written `<b>` raises
`can't parse entities` and the edit is lost. Two safe options:

1. Stream as **plain text** (`parse_mode=None`) and send one final formatted edit.
2. Compose with `aiogram.utils.formatting` entities, which cannot produce malformed
   markup — see `aiogram-formatting`.

## chat actions

When there is no partial output to show, an action indicator is enough:

```python
import asyncio

from aiogram import Bot, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

router = Router(name="thinking")


@router.message()
async def slow(message: Message, bot: Bot) -> None:
    async with ChatActionSender.typing(
        bot=bot, chat_id=message.chat.id, message_thread_id=message.message_thread_id
    ):
        await asyncio.sleep(0)  # the real work
    await message.answer("finished")
```

`ChatActionSender` re-sends every 5 seconds, to refresh the indicator, which Telegram keeps for at most five seconds. `@flags.chat_action("typing")` plus `ChatActionMiddleware` does the same
declaratively — see `aiogram-middlewares`.

Use `ChatActionSender.upload_document`, `.upload_photo`, `.record_voice`, and friends when
the work is an upload; the indicator then matches what the user is waiting for.

## choosing

| Situation | Use |
|---|---|
| incremental text, private chat, Bot API 10.x | message draft, then a final `send_message` |
| structured long-form output | rich message with `blocks` |
| group chat, or older Bot API | edit throttling |
| under ~3 seconds, no partial output | `ChatActionSender` |
| output over 4096 characters | split into several messages |

## cancellation

The application owns generation tasks. Keep a task per conversation (including bot and
thread when relevant), cancel and await a previous task before replacing it, and remove
it on completion only if the registry still points to that same task. Propagate
`CancelledError` after cleanup and settle the visible message deliberately. Local task
cancellation does not retract an in-flight send. Arbitrate cancellation against the
send-intent/ACK boundary before claiming "cancelled"; preserve already delivered parts
and unresolved outcomes. Mandatory asynchronous settlement must finish even if the
caller is cancelled again: shielding without retaining and draining the task is not
enough. Do not delete artefacts that an in-flight upload still reads.

Bot API 10.3 adds `can_stop` and `keep_on_stop` to text/rich drafts, plus
`router.stopped_message_generation()` updates carrying `chat`, `draft_id`, and optional
`message_thread_id`. Map these to your own task registry; the event has no `from_user`.
Include this observer in webhook `allowed_updates` when offering stop controls.

## checklist

- edits or draft updates coalesced to roughly one per second or slower
- text compared before every edit
- long output split deliberately; never silently truncated
- `retry_after` honoured
- the tail always flushed
- no partial HTML or Markdown sent
- drafts used only in private chats, with a stable non-zero `draft_id`
- final text/rich output persisted by an explicit send; ephemeral drafts are not delivery
- one stream per bot/conversation/thread scope; previous producers cancelled and awaited
- pending/in-flight progress fenced before terminal UI; exact owned placeholder settled
- confirmed result remains successful when status cleanup or telemetry fails
- cancellation cannot claim to undo in-flight sends; mandatory settlement drained

## see also

- `aiogram-formatting` — entity-safe text
- `aiogram-rate-limits` — flood limits and pacing
- `aiogram-errors` — `message is not modified`, `can't parse entities`
- `aiogram-middlewares` — `@flags.chat_action`
