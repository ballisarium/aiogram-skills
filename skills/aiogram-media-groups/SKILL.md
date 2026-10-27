---
name: aiogram-media-groups
description: >
  Use when sending Telegram albums or aggregating incoming media_group_id updates with aiogram 3.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-07"
---

# aiogram media groups

Sending an album is easy. **Receiving** one is the part with no built-in support, and it
is where bots break.

## when to use this skill

- sending several photos or videos as one album
- handling a user who uploads several photos at once
- a handler that fires N times for one album
- captions appearing on the wrong item

## sending

```python
from aiogram.utils.media_group import MediaGroupBuilder

album = MediaGroupBuilder(caption="Trip photos")
album.add_photo(media="https://example.com/1.jpg")
album.add_photo(media="https://example.com/2.jpg")
album.add_photo(media="https://example.com/3.jpg", has_spoiler=True)

media = album.build()
assert len(media) == 3
assert media[0].caption == "Trip photos"
assert media[1].caption is None
```

Verified surface:

```text
MediaGroupBuilder(media=None, caption=None, caption_entities=None)
  .add(**kwargs)          # explicit type= key
  .add_photo(media, caption=None, parse_mode=..., caption_entities=None,
             has_spoiler=None, **kwargs)
  .add_video(media, thumbnail=None, caption=None, ..., width=None, height=None,
             duration=None, supports_streaming=None, has_spoiler=None, **kwargs)
  .add_document(...)
  .add_audio(...)
  .build() -> list[InputMediaAudio | InputMediaPhoto | InputMediaVideo | InputMediaDocument]
```

The builder's `caption` lands on the **first** item, a convention for a shared caption. Telegram accepts captions on individual items;
multiple captions may be displayed separately by the client.

```python
from aiogram import Router
from aiogram.types import FSInputFile, Message
from aiogram.utils.formatting import Bold, Text
from aiogram.utils.media_group import MediaGroupBuilder

router = Router(name="send-album")


@router.message()
async def send_album(message: Message) -> None:
    caption = Text("Report for ", Bold("July"))
    text, entities = caption.render()
    album = MediaGroupBuilder(caption=text, caption_entities=entities)
    album.add_photo(media=FSInputFile("chart-1.png"))
    album.add_photo(media=FSInputFile("chart-2.png"))
    await message.answer_media_group(media=album.build())
```

### the rules Telegram enforces

- **2–10 items.** For one item use its matching single-media send method; chunk longer lists.
- Photos, live photos and videos may be mixed in one album. Documents may only group
  with documents, and audio only with audio. `sendMediaGroup` accepts
  `InputMediaLivePhoto`; `MediaGroupBuilder` has no live-photo helper in 3.31.0.
  Build an explicit list of input-media objects when sending live photos.
- An album cannot carry a `reply_markup`. Buttons need a separate message.
- Each item may be a `file_id`, an http URL, or an `InputFile`.

```python
from aiogram.utils.media_group import MediaGroupBuilder


def split_sizes(count: int) -> list[int]:
    """Chunk into groups of 2-10. A lone tail item borrows one from the group before it."""
    if count == 1:
        raise ValueError("Use a single-media send for one item")
    if count < 1:
        return []
    sizes = [10] * (count // 10)
    remainder = count % 10
    if remainder == 1 and sizes:
        sizes[-1] -= 1  # 10 + 1 -> 9 + 2
        remainder = 2
    if remainder:
        sizes.append(remainder)
    return sizes


def chunk_album(urls: list[str]) -> list[list[object]]:
    groups: list[list[object]] = []
    start = 0
    for size in split_sizes(len(urls)):
        builder = MediaGroupBuilder()
        for url in urls[start : start + size]:
            builder.add_photo(media=url)
        groups.append(list(builder.build()))
        start += size
    return groups


assert split_sizes(11) == [9, 2]
assert split_sizes(12) == [10, 2]
assert split_sizes(20) == [10, 10]
assert split_sizes(21) == [10, 9, 2]
assert [len(g) for g in chunk_album([f"u{i}" for i in range(11)])] == [9, 2]
assert all(2 <= len(g) <= 10 for g in chunk_album([f"u{i}" for i in range(37)]))
```

## receiving: the actual problem

Telegram sends an album as **separate `message` updates** that share a `media_group_id`.
There is no count, no terminator, and no guaranteed ordering window. A naive handler runs
once per item:

<!-- example: run -->
```python
from aiogram import F, Router
from aiogram.types import Message

router = Router(name="naive")


@router.message(F.photo)
async def wrong(message: Message) -> None:
    """Fires 5 times for a 5-photo album, and answers 5 times."""
    await message.answer("Got your photo!")
```

**aiogram has no built-in album aggregator.** Anything you write here is your own code,
not an aiogram feature. The standard approach is a debounce: buffer by `media_group_id`,
wait a short quiet period, then dispatch once.

```python
import asyncio
from collections import defaultdict
from typing import Any

from aiogram import BaseMiddleware, Router
from aiogram.types import Message, TelegramObject

router = Router(name="album")


class AlbumMiddleware(BaseMiddleware):
    """Collects album items and calls the handler once with `album` injected.

    Not an aiogram feature - a debounce you own. `latency` trades responsiveness
    against the risk of splitting an album across two calls.
    """

    def __init__(self, latency: float = 0.6) -> None:
        self.latency = latency
        self.parts: dict[tuple[int, int, str], list[Message]] = defaultdict(list)

    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.media_group_id is None:
            return await handler(event, data)

        key = (data["bot"].id, event.chat.id, event.media_group_id)
        album = self.parts[key]
        if any(item.message_id == event.message_id for item in album):
            return None  # duplicate delivery within this pending bucket
        album.append(event)

        # Only the most recent arrival in this exact bucket may dispatch.
        try:
            await asyncio.sleep(self.latency)
        except asyncio.CancelledError:
            if self.parts.get(key) is album and album[-1] is event:
                self.parts.pop(key, None)
            raise
        if self.parts.get(key) is not album or album[-1] is not event:
            return None
        self.parts.pop(key)

        album.sort(key=lambda item: item.message_id)
        data["album"] = album
        return await handler(album[0], data)


router.message.outer_middleware(AlbumMiddleware())


@router.message()
async def on_album(message: Message, album: list[Message] | None = None) -> None:
    """`album` is present only for grouped messages; keep the default."""
    if album is None:
        await message.answer("single item")
        return
    await message.answer(f"received {len(album)} items")
```

Points that matter in that middleware:

- It must be an **outer** middleware. An inner one runs after filters, so items rejected
  by a filter never reach the buffer.
- Inspect captions on every item; a sender may caption an item other than the first.
- Deduplicate by message id within the bot/chat/group bucket; sort by `message_id`,
  not arrival order. This example deduplicates only while that bucket is pending.
- Handlers must tolerate `album=None`, because non-grouped messages still flow through.

### the trade-offs, stated honestly

| Concern | Reality |
|---|---|
| latency | too short splits albums; too long makes the bot feel slow. 0.5–1.0 s is typical |
| memory | an in-process dict grows if a group never completes; cap it or expire entries |
| multiple replicas | items of one album can land on different processes — a dict cannot see them. Use Redis keyed by `media_group_id`, with bot/chat/group scope and a short TTL |
| holding the handler | `asyncio.sleep` inside a middleware holds that update's task for the whole latency |
| filters | outer middleware sees messages reaching its router |
| concurrency | this example needs concurrent update tasks; FSM isolation may serialise the same user before it reaches this middleware |

Do not disable FSM isolation just to make this collector work. When updates are serialised,
use a collector outside the locked handler path and a managed dispatch task. A quiet
period is a heuristic, never proof that Telegram delivered the entire album.

If you need this to be reliable across replicas, buffer in Redis and dispatch from a
short-lived task keyed on the group id — but the same debounce logic and the same
trade-offs apply. For restart/redelivery protection, store received message ids and
atomically claim a batch before downstream work; an in-memory debounce is not durable
intake. Define a bounded policy for late arrivals rather than treating a quiet period as
a complete album or silently appending to an already running batch.

## ordered multipart delivery

Freeze the ordered source manifest before sending batches. Store each acknowledged
batch's returned message ids and its source range; a cursor must refer to that immutable
manifest, not a newly filtered list of successful conversions. After a known rejection,
resume the same batch. After an ambiguous `send_media_group` outcome, do not resend the
whole album or fan out into single-item sends: either could duplicate accepted items.
Keep result ACKs separate from the following button/summary message and progress cleanup.

Serialise ordered batches for the same destination; concurrent sends can interleave even
if each has its own pacer. Cancellation stops unsent batches, not acknowledged items.
Report partial delivery accurately and retain unresolved in-flight evidence. Use the
existing application's [durable delivery](../using-aiogram/references/durable-operations.md)
when recovery must survive restart; this is not a reason to add a queue to a simple echo.

## sending an album back

This photo-only echo rejects the whole collected album if any item is not a photo;
it never silently drops other media. Pass `AlbumMiddleware()` from the receiving example
to `make_echo_router`, then include the returned router on the dispatcher. Do not also
include the demonstration receiving router: its catch-all would consume the update.

```python
from aiogram import BaseMiddleware, Router
from aiogram.types import Message
from aiogram.utils.media_group import MediaGroupBuilder


def make_echo_router(album_middleware: BaseMiddleware) -> Router:
    router = Router(name="echo-album")
    router.message.outer_middleware(album_middleware)

    @router.message()
    async def echo_album(message: Message, album: list[Message] | None = None) -> None:
        if not album:
            return
        if any(not item.photo for item in album):
            await message.answer("Only photo albums are supported.")
            return
        builder = MediaGroupBuilder(caption="Here they are")
        for item in album:
            if item.photo:
                builder.add_photo(media=item.photo[-1].file_id)
        media = builder.build()
        if len(media) == 1:
            await message.answer_photo(media[0].media, caption="Here they are")
        elif len(media) >= 2:
            await message.answer_media_group(media=media)

    return router
```

Re-sending by `file_id` means no upload at all — see `aiogram-files`.

## checklist

- outgoing albums contain 2–10 items, chunked when longer
- shared caption placed on the first item; per-item captions inspected/preserved as needed
- no `reply_markup` on an album
- incoming albums aggregated deliberately, with the debounce documented as your code
- aggregation done in **outer** middleware
- items deduplicated in bot/chat/group scope and sorted by `message_id`
- late-arrival/redelivery policy explicit; debounce is not durable intake
- batch cursor indexes a frozen manifest; acknowledged batches never restarted
- ambiguous album sends are not retried as albums or individual messages
- partial delivery/cancellation preserves ACKs independently of summary/status cleanup
- captions inspected on all incoming items
- handlers tolerate a missing `album`
- multi-replica deployments use a shared store, not a process-local dict

## see also

- `aiogram-files` — `file_id` reuse and upload sources
- `aiogram-middlewares` — outer versus inner
- `skills/using-aiogram/references/telegram-quirks.md` — album delivery semantics
