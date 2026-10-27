---
name: aiogram-files
description: >
  Use when uploading, downloading, or resending files with aiogram 3, choosing InputFile types, or reusing file IDs.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram files

Choose a source by transfer cost, size, and the required Telegram media kind.

```bash
python skills/using-aiogram/tools/get-type.py PhotoSize
python skills/using-aiogram/tools/get-method.py sendDocument
```

## when to use this skill

- sending a photo, document, video, audio, or voice message
- re-sending something the bot already sent
- downloading what a user uploaded
- handling files too large to hold in memory
- a `file_id` that works for one bot but not another

## the four sources

```python
from aiogram.types import BufferedInputFile, FSInputFile, URLInputFile

from_disk = FSInputFile("report.pdf", filename="Monthly report.pdf")
from_memory = BufferedInputFile(b"col1,col2\n1,2\n", filename="data.csv")
from_url = URLInputFile("https://example.com/image.jpg", filename="image.jpg")
by_id = "AgACAgIAAxkBAAExample"  # a plain str is treated as a file_id or an http URL

assert from_disk.filename == "Monthly report.pdf"
assert isinstance(by_id, str)
```

Verified constructors:

```text
FSInputFile(path, filename=None, chunk_size=65536)
BufferedInputFile(file: bytes, filename: str, chunk_size=65536)
URLInputFile(url, headers=None, filename=None, chunk_size=65536, timeout=30, bot=None)
```

| Source | Cost | Use when |
|---|---|---|
| `file_id` (`str`) | **no upload at all** | the bot has sent or received this file before |
| plain http(s) URL (`str`) | Telegram fetches it | the method supports URLs and Telegram can reach it |
| `FSInputFile` | uploads, streamed from disk | a local file |
| `URLInputFile` | your bot downloads, then uploads | the URL needs headers/auth, or Telegram cannot reach it |
| `BufferedInputFile` | uploads from RAM | in-memory content |

Source support is method-specific: `sendVideoNote` does not accept a URL string;
`sendDocument` accepts URL strings only for PDF/ZIP. `URLInputFile` fetches on the bot
side and uploads bytes, so it follows multipart rules, not Telegram's URL-fetch rules.

The cloud Bot API [Sending files](https://core.telegram.org/bots/api#sending-files)
section gives these general limits; check the selected method's format/size constraints too:

| Transfer | Photos | Other files |
|---|---|---|
| Multipart upload | 10 MB | 50 MB |
| Telegram fetches a URL | 5 MB | 20 MB |

Its exact multipart wording is “10 MB max size for photos, 50 MB for other files.”
For URL fetching it specifies “5 MB max size for photos” and “20 MB max” for other content.
These are upload limits, separate from the `getFile` download limit below.

`FSInputFile` streams in `chunk_size` blocks, so a 400 MB file does not become 400 MB of
memory. `BufferedInputFile` holds everything in RAM by definition — use it for in-memory
CSVs and images, not for large media.

`BufferedInputFile.from_file(path, filename=None, chunk_size=...)` also exists, but it
reads the whole file into memory; prefer `FSInputFile`.

## sending

```python
from aiogram import Router
from aiogram.types import BufferedInputFile, FSInputFile, Message
from aiogram.utils.formatting import Bold, Text

router = Router(name="send-files")


@router.message()
async def send(message: Message) -> None:
    await message.answer_document(FSInputFile("report.pdf"))
    await message.answer_photo(
        "https://example.com/chart.png",
        **Text("Chart for ", Bold("July")).as_caption_kwargs(),
    )
    await message.answer_document(
        BufferedInputFile(b"a,b\n1,2\n", filename="data.csv"),
        caption="Raw export",
    )
```

Captions are limited to 1024 characters after entity parsing; message text allows 4096.
Long explanations go in a following text message, not the caption.

## receiving and downloading

```python
from aiogram import Bot, F, Router
from aiogram.types import Message

router = Router(name="receive-files")


@router.message(F.document)
async def got_document(message: Message, bot: Bot) -> None:
    document = message.document
    if document is None:
        return

    await bot.download(
        document,
        destination=f"/tmp/{message.chat.id}-{message.message_id}-{document.file_unique_id}",
    )


@router.message(F.photo)
async def got_photo(message: Message, bot: Bot) -> None:
    """Choose the largest pixel area explicitly."""
    if message.photo:
        photo = max(message.photo, key=lambda item: item.width * item.height)
        await bot.download(photo, destination=f"/tmp/{message.chat.id}-{message.message_id}.jpg")
```

For small documents, use this bounded RAM variant **instead of** the disk download.
The declared size check is only a preflight; the destination enforces the actual cap:

```python
from io import BytesIO

from aiogram import Bot
from aiogram.types import Document


class BoundedBuffer(BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: bytes) -> int:
        if self.tell() + len(data) > self.limit:
            raise ValueError("document exceeds memory budget")
        return super().write(data)


async def download_small(bot: Bot, document: Document, limit: int = 1_000_000) -> bytes:
    if limit < 1:
        raise ValueError("limit must be positive")
    if document.file_size is not None and document.file_size > limit:
        raise ValueError("document exceeds memory budget")
    with BoundedBuffer(limit) as buffer:
        await bot.download(document, destination=buffer, chunk_size=min(limit, 65536))
        return buffer.getvalue()
```

Verified signatures:

```text
Bot.download(file: str | Downloadable, destination=None, timeout=30,
             chunk_size=65536, seek=True) -> BinaryIO | None
Bot.download_file(file_path: str | Path, destination=None, timeout=30,
                  chunk_size=65536, seek=True) -> BinaryIO | None
```

`download` accepts any `Downloadable` — `Document`, `PhotoSize`, `Video`, `Audio`,
`Voice`, `Sticker`, `VideoNote`, `Animation` — or a `file_id` string, and resolves the
file path itself. `download_file` takes an already-resolved `file_path` from `get_file`.

Omitting `destination` returns a `BinaryIO` holding the whole file in memory. Pass a path
or an open file object for anything large.

### the download limits

- **20 MB maximum cloud Bot API download.** Larger files raise `TelegramBadRequest: file is too big`.
  A self-hosted local Bot API server supports downloads without this size limit.
- The `file_path` from `get_file` is valid for **at least one hour**. Do not persist it —
  persist the `file_id` and call `get_file` again when needed.

These transport limits are not an application resource budget. Check declared size
before download and enforce the actual byte cap while streaming; `chunk_size` only
controls individual reads. Bound decompressed archive/gzip data before materialising it,
and validate archive paths and entry counts when that input is supported. Use an owned
temporary workdir, with cleanup on failure/cancellation and explicit retention for jobs
that can resume. Do not trust an extension or MIME label as a decoded-format check.

## file_id and file_unique_id

This trips up almost everyone once:

| | `file_id` | `file_unique_id` |
|---|---|---|
| scope | **one bot** | global |
| can download | yes | **no** |
| stable | may change for the same file | stable |
| use for | re-sending, caching | deduplication, storage keys |

Consequences:

- A `file_id` captured by bot A is meaningless to bot B. Sharing ids across bots does not
  work. Token rotation for the same bot is not a documented reason to invalidate file ids.
- Reuse a `file_id` only with its compatible media type: it does not convert a photo
  into a document or a video into a photo. Upload the bytes for a new media kind.
- `file_unique_id` cannot be turned back into a file. It identifies, it does not fetch.
- Store both: `file_unique_id` as your key, `file_id` as the cheap re-send handle.

Identity has a transformation boundary: Telegram may re-encode an upload. An intermediate
upload identity need not identify the final delivered rendition. Store identities from
the acknowledged final response when available; a mismatch alone does not prove a
mutation failed. Reconcile uncertain effects using the owning operation's evidence.
For derived-media caches, include the transformation settings/revision as well as source
and bot identity so a stale rendition is not reused after an edit.

## caching to skip uploads

aiogram ships no file cache. Re-sending by `file_id` is dramatically cheaper than
re-uploading. Populate the application cache only after an acknowledged send:

```python
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputFile, Message


class FileIdCache:
    """Small application cache; keys include content revision and media kind."""

    def __init__(self) -> None:
        self._ids: dict[tuple[int, str], str] = {}

    def get(self, bot: Bot, key: str) -> str | None:
        return self._ids.get((bot.id, key))

    def remember(self, bot: Bot, key: str, file_id: str) -> None:
        self._ids[(bot.id, key)] = file_id

    def discard(self, bot: Bot, key: str, expected: str) -> None:
        if self.get(bot, key) == expected:  # do not evict a newer concurrent entry
            self._ids.pop((bot.id, key), None)


cache = FileIdCache()


async def send_cached_photo(bot: Bot, chat_id: int, key: str, path: str) -> Message:
    cached = cache.get(bot, key)
    source: str | InputFile = cached if cached else FSInputFile(path)
    try:
        message = await bot.send_photo(chat_id=chat_id, photo=source)
    except TelegramBadRequest:
        if cached:
            cache.discard(bot, key, cached)
        raise  # a 400 may concern the chat/caption, not the id; no hidden resend
    if message.photo:
        photo = max(message.photo, key=lambda item: item.width * item.height)
        cache.remember(bot, key, photo.file_id)
    return message
```

Use a real store (Redis, a table) rather than a dict once you have more than one process.
Key by bot identity, content/settings revision, and media kind. Bound cache size. This
example conservatively evicts a cached handle on `TelegramBadRequest` and propagates the
rejection; it does not claim every 400 means the id expired. Only retry with an upload
when a method-specific rejection proves that fallback safe. Keep the entry on 429 or
ambiguous transport failure; neither proves it invalid. Never cache an attempted upload,
a guessed id, or a result inferred from a timeout. Cache writes/metadata failures after
an ACK must not trigger another send.

## validate before uploading

InputFile classes transport bytes; they do not validate the media. After generation and
serialisation, validate the actual output, not just its source model or filename: decode
or probe the format, check dimensions/duration and the method's byte limits, and bound
compressed/decompressed data where applicable. Finish this postflight before upload or
preview delivery. Invalid output is a preparation failure, not a transient API retry.
Keep the validated artefact unchanged and available until the request and any authorised
recovery finish; `FSInputFile` opens the path when it is read, not at construction.

## replacing media in place

Use `Message.edit_media` / `Bot.edit_message_media` with the **new** media kind:
`InputMediaPhoto` for a photo, `InputMediaAnimation` for an animation. A non-album preview
can switch between these kinds on the same message; do not keep using the old kind just
because its file id was cached. Persist the exact message id and confirmed kind together.
Pass the intended caption and keyboard in that edit. Treat `message is not modified` as
confirmation of the desired state. After a lost edit response, reconcile the same owned
message/current revision before another action; do not create a new message as a blind
fallback. Album edits and inline edits have extra restrictions; inspect `editMessageMedia`.

## thumbnails and streaming

```python
from aiogram import Router
from aiogram.types import FSInputFile, Message

router = Router(name="video")


@router.message()
async def send_video(message: Message) -> None:
    await message.answer_video(
        FSInputFile("clip.mp4"),
        thumbnail=FSInputFile("thumb.jpg"),
        supports_streaming=True,
        width=1280,
        height=720,
        duration=42,
    )
```

`supports_streaming=True` lets clients play before the download finishes. Supplying
`width`, `height`, and `duration` supplies metadata; it does not guarantee that Telegram
will skip transcoding.

Thumbnails must be JPEG, under 200 kB, and at most 320×320.

## which send method

| Content | Method | Notes |
|---|---|---|
| photo | `answer_photo` | Telegram re-encodes and strips metadata |
| any file, unchanged | `answer_document` | use when the bytes must survive intact |
| video | `answer_video` | pass `supports_streaming` |
| looping muted video | `answer_animation` | GIF-style |
| music | `answer_audio` | shows a player, `performer` / `title` |
| voice message | `answer_voice` | OGG/Opus, MP3, or M4A |
| round video | `answer_video_note` | square, ≤60 s |
| sticker | `answer_sticker` | WEBP/TGS/WEBM |

Sending a photo as `answer_photo` compresses it. When the user needs the original file —
a scan, a design asset — send it as a document.

Choose the method for the user-visible media contract, not just the filename: sending
a video as a document does not establish inline video playback. Photo previews may lose
transparency; verify downloaded/decoded output when it matters, and keep preview
composition separate from the original media artefact. Local rendering and metadata alone
do not prove Telegram acceptance; do not weaken format validation to make a mock pass.

## checklist

- valid cached re-sends use `file_id`; definite rejection handled without a blind fallback
- `file_unique_id` used as the storage key, `file_id` as the send handle
- caches keyed by bot id, media kind and content/settings revision; populated only after ACK
- cached 400 rejection evicts; 429/unknown outcome does not invalidate or trigger a resend
- output bytes validated after serialisation and retained through upload/recovery
- media edits use the new kind and the exact owned message id
- large local files sent with `FSInputFile`, not `BufferedInputFile`
- downloads over ~20 MB expected to fail, and handled
- `file_path` from `get_file` never persisted
- choose photo size by pixel area when the largest size is required
- captions kept within 1024 characters

## see also

- `aiogram-media-groups` — albums
- `aiogram-errors` — `file is too big`, `wrong file identifier`
- `aiogram-streaming` — drafts and rich messages
- `skills/using-aiogram/references/telegram-quirks.md` — the full limit table
