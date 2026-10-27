---
name: aiogram-formatting
description: >
  Use when formatting aiogram 3 messages with entities or HTML, UTF-16 offsets, and escaping.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  source: https://github.com/aiogram/aiogram
  verified: "2026-09-22"
---

# aiogram formatting

Telegram accepts formatting two ways: a `parse_mode` string that it parses, or an explicit
list of `MessageEntity` objects. aiogram supports both, and the choice decides whether
user-supplied text can break your messages.

## when to use this skill

- composing a message with bold, links, code, or spoilers
- inserting user-supplied text into a formatted message
- `TelegramBadRequest: can't parse entities`
- building a report, list, or key/value block
- deciding between HTML, MarkdownV2, and entities
- reading formatting off an incoming message

## the three approaches

| Approach | Escaping | Use when |
|---|---|---|
| `aiogram.utils.formatting` (entities) | no markup escaping; nesting and length rules still apply | anything containing user text — the default choice |
| `aiogram.html` + `ParseMode.HTML` | you must call `html.quote()` | fully static text, or templates you control |
| MarkdownV2 | ~18 characters need escaping | you have a specific reason; otherwise avoid |

Prefer entities for composed text; escaped HTML is also valid. Preserve the application's
existing formatting contract. Entity composition does not validate every Telegram nesting
restriction or split overlong messages for you.

## entities: `aiogram.utils.formatting`

`Text` composes nodes; rendering produces the plain string plus offsets.

```python
from aiogram.utils.formatting import Bold, Italic, Text

content = Text("Hello, ", Bold("world"), " and ", Italic("everyone"), "!")
payload = content.as_kwargs()

assert payload["text"] == "Hello, world and everyone!"
assert payload["parse_mode"] is None
assert [(e.type, e.offset, e.length) for e in payload["entities"]] == [
    ("bold", 7, 5),
    ("italic", 17, 8),
]
```

`as_kwargs()` returns `{"text": ..., "entities": [...], "parse_mode": None}`. Splat it
into any send call:

```python
from aiogram import Router
from aiogram.types import Message
from aiogram.utils.formatting import Bold, Text

router = Router(name="formatting")


@router.message()
async def greet(message: Message) -> None:
    """`parse_mode: None` in the payload overrides the bot default - nothing to escape."""
    name = message.from_user.first_name if message.from_user else "there"
    content = Text("Hi ", Bold(name), "!")
    await message.answer(**content.as_kwargs())
```

That handler is safe even if the user's first name is `<script>` or `**`. The equivalent
HTML version would need `html.quote(name)` and would break the moment someone forgot.

For captions use `as_caption_kwargs()`, which emits `caption` / `caption_entities`:

```python
from aiogram.utils.formatting import Bold, Text

payload = Text("See ", Bold("this")).as_caption_kwargs()
assert set(payload) == {"caption", "caption_entities", "parse_mode"}
```

`Text` also offers `as_poll_question_kwargs()`, `as_poll_explanation_kwargs()`, and
`as_gift_text_kwargs()` for the fields that take their own entity list.

### available nodes

`Bold`, `Italic`, `Underline`, `Strikethrough`, `Spoiler`, `Code`, `Pre`, `BlockQuote`,
`ExpandableBlockQuote`, `TextLink`, `TextMention`, `CustomEmoji`, `Url`, `Email`,
`PhoneNumber`, `HashTag`, `CashTag`, `BotCommand`, `DateTime`.

```python
from aiogram.types import User
from aiogram.utils.formatting import Code, Pre, Spoiler, Text, TextLink, TextMention

block = Text(
    TextLink("docs", url="https://docs.aiogram.dev/"),
    "\n",
    Code("pip install aiogram"),
    "\n",
    Pre("print('hi')", language="python"),
    "\n",
    Spoiler("hidden"),
    "\n",
    TextMention("that user", user=User(id=1, is_bot=False, first_name="U")),
)
assert "docs" in block.as_html()
```

`TextMention` links to a user without needing a username ; an HTML `tg://user?id=...` link is another option, subject to Telegram's mention rules.

### list and section helpers

```python
from aiogram.utils.formatting import (
    Bold,
    Text,
    as_key_value,
    as_list,
    as_marked_section,
    as_numbered_list,
)

report = as_marked_section(
    Bold("Daily report"),
    "orders processed",
    "invoices sent",
    marker="• ",
)
assert report.as_html() == "<b>Daily report</b>\n• orders processed\n• invoices sent"

assert as_numbered_list("first", "second").as_html() == "1. first\n2. second"
assert as_key_value("Total", 42).as_html() == "<b>Total:</b> 42"

combined = as_list(report, as_key_value("Total", 42), sep="\n\n")
assert "Total" in combined.as_html()
```

Also available: `as_line`, `as_section`, `as_marked_list`, `as_numbered_section`.

### rendering to a string

```python
from aiogram.utils.formatting import Bold, Text

content = Text("a ", Bold("b"))
assert content.as_html() == "a <b>b</b>"
assert content.as_markdown() == "a *b*"  # MarkdownV2: * is bold, _ is italic
```

Use these when something outside Telegram needs the text. To *send*, prefer
`as_kwargs()` — it skips parsing entirely.

## HTML

```python
from aiogram import html

user_input = "<script>alert(1)</script> & more"
safe = f"{html.bold('Note')}: {html.quote(user_input)}"
assert "&lt;script&gt;" in safe
assert "<b>Note</b>" in safe
```

`aiogram.html` provides `bold`, `italic`, `underline`, `strikethrough`, `spoiler`, `code`,
`pre`, `pre_language`, `link`, `blockquote`, `expandable_blockquote`, `custom_emoji`,
`date_time`, `quote`, `unparse`, `apply_entity`.

Escape each dynamic plain-text value with `html.quote()` before wrapping it in HTML.
Helpers such as `html.bold()` do not escape their argument. Do not quote an already
rendered trusted HTML fragment again: that turns its tags into visible text.
Treat display names, filenames, titles and configuration values as untrusted text too.
Do not assume that loading a value from storage or a locale placeholder sanitises it.
Quoting text is not URL validation or attribute quoting: use `TextLink` for composed
links and validate destinations against the application's link policy.

Set the mode once on the bot:

```python
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

bot = Bot(
    token="123456:TEST",
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
assert bot.default.parse_mode == ParseMode.HTML
```

`ParseMode` members: `HTML`, `MARKDOWN_V2`, `MARKDOWN` (legacy). Per-call `parse_mode=`
overrides the default; `parse_mode=None` disables it for that call, which is exactly what
`as_kwargs()` does.

Telegram's HTML subset includes `b`, `i`, `u`, `s`, `span class="tg-spoiler"`, `a`,
`code`, `pre`, `blockquote`, `tg-emoji` and `tg-time`. Do not assume arbitrary HTML tags
are accepted or silently ignored.

## MarkdownV2

`aiogram.md` mirrors the HTML helpers, and `md.quote()` escapes the reserved characters.

```python
from aiogram import md

assert md.quote("a_b*c") == r"a\_b\*c"
assert md.bold("x") == "*x*"
```

MarkdownV2 requires escaping `_ * [ ] ( ) ~ ` > # + - = | { } . !` — including inside
otherwise plain text. Legacy `ParseMode.MARKDOWN` is deprecated by Telegram and cannot
express spoilers or expandable quotes. Prefer entities or HTML.

## offsets are UTF-16 code units

`MessageEntity.offset` and `.length` count **UTF-16 code units**, not Python characters.
Emoji outside the Basic Multilingual Plane count as 2.

```python
from aiogram.utils.formatting import sizeof

assert sizeof("abc") == 3
assert sizeof("😀") == 2  # one Python character, two UTF-16 code units
assert len("😀") == 1
```

Slicing a message by `len()` and reusing its entities silently misaligns the formatting.
`sizeof` is the correct measure; the `formatting` module computes offsets with it, which
is another reason to compose entities rather than build them by hand.

## reading incoming formatting

```python
from aiogram import Router
from aiogram.types import Message
from aiogram.utils.formatting import Text

router = Router(name="incoming")


@router.message()
async def echo_formatted(message: Message) -> None:
    """html_text re-renders the message with its entities applied."""
    if message.text or message.caption:
        await message.answer(message.html_text, parse_mode="HTML")


def to_entities(message: Message) -> Text:
    if message.text is not None:
        return Text.from_entities(message.text, message.entities or [])
    return Text.from_entities(message.caption or "", message.caption_entities or [])
```

`message.html_text` uses text or caption, and returns an empty string if both are absent.
Guard against sending that empty result. `md_text` is the
MarkdownV2 equivalent. `Text.from_entities` converts back into the composable form, which
is the clean way to quote a user's message while preserving their formatting.

## localised surfaces and custom emoji

Validate the assembled message, not only individual translation keys. Initial entry and
Back/restoration should call the same renderer with the same runtime placeholders.
Preserve supported-locale key/placeholder parity and escape dynamic substitutions in
the grammar they enter, including values read from configuration. Check actual newline
characters after JSON loading and the ordering of composed paragraphs.
For multilingual bots, keep every visible string in the locale catalogue, not just the
happy-path screen:
validation, cancellation, expiry, recovery and queued-worker messages need the same
language contract. Placeholder parity does not verify translation meaning; review
critical actions, quantities and directions in context. Bound dynamic lists/error details
so the complete rendered message fits the target field; do not truncate raw HTML or
reuse entity offsets after changing the text. Preserve all required controls if a list
must be shortened or paginated.

Callback notifications/alerts use plain text: `answerCallbackQuery` has no `parse_mode`
or entities. Do not reuse HTML message templates or `<tg-emoji>` markup in an alert.
In message text, custom emoji come from `MessageEntity.custom_emoji_id` or
`Sticker.custom_emoji_id`; a Unicode emoji or its code point is not such an ID. In an
inline button, use `icon_custom_emoji_id` when the installed API/client contract supports
it, with a plain label. Keep any legacy Unicode-prefix normalisation in the shared
keyboard helper so attaching an icon does not duplicate it. Use the project's registry
and fallback policy rather than copying another bot's emoji IDs or forcing premium UI.

## checklist

- user-supplied text goes through `formatting` entities, or `html.quote()`
- one parse mode set with `DefaultBotProperties`, not repeated per call
- `as_kwargs()` splatted rather than `text=` plus a manual `entities=`
- captions use `as_caption_kwargs()`
- no `len()`-based slicing of text that carries entities
- text/caption paired with their own entities; empty output is not sent
- only Telegram's supported HTML tags
- all visible branches localised; supported locales agree on keys and placeholders
- full rendered text/caption and controls checked with long translations and hostile substitutions

## see also

- `using-aiogram` — the overview
- `aiogram-keyboards` — the markup beside the text
- `aiogram-streaming` — rich messages and drafts in Bot API 10.x
- `aiogram-errors` — `can't parse entities` and friends
