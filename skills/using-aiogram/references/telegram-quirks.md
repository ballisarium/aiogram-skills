# Telegram-side quirks

Behaviour that comes from Telegram, not from aiogram. Getting these wrong produces bugs
that look like aiogram bugs.

Every limit below is quoted from the field documentation carried by **aiogram 3.31.0**
(Telegram Bot API **10.3**), which derives from the Bot API reference. Re-check any
of them against the installed package:

```bash
python skills/using-aiogram/tools/get-method.py sendMessage
python skills/using-aiogram/tools/get-type.py InlineKeyboardButton
```

## documented limits

| Thing | Limit | Source field |
|---|---|---|
| message text | 1–4096 characters *after entities parsing* | `SendMessage.text` |
| media caption | 0–1024 characters after entities parsing | `SendPhoto.caption` |
| `callback_data` | 1–64 **bytes** | `InlineKeyboardButton.callback_data` |
| media group | must include **2–10** items | `SendMediaGroup.media` |
| callback answer text | 0–200 characters | `AnswerCallbackQuery.text` |
| poll question | 1–300 characters | `SendPoll.question` |
| poll options | 1–12 options | `SendPoll.options` |
| file download link | valid for **at least 1 hour**; max download size 20 MB | `File` docstring |

Two traps in that table:

- `callback_data` is measured in **bytes**, not characters. A visible emoji may be a
  multi-code-point sequence: `👨‍👩‍👧‍👦` occupies 25 UTF-8 bytes. Measure the complete
  payload with `len(payload.encode("utf-8"))`. aiogram raises on `pack()` above 64 bytes
  (`MAX_CALLBACK_LENGTH = 64`); plain callback strings receive no equivalent check.
- Text limits apply *after* entity parsing, so HTML tags do not count toward the 4096 but
  the characters they wrap do.

## rate limits

Quoted verbatim from the [Telegram bot FAQ](https://core.telegram.org/bots/faq):

> "In a single chat, avoid sending more than one message per second."

> "In a group, bots are not be able to send more than 20 messages per minute."

> "For bulk notifications, bots are not able to broadcast more than about 30 messages per
> second, unless they enable paid broadcasts to increase the limit."

These are soft limits and are not published as exact numbers per method. Exceeding them
yields HTTP 429, which aiogram raises as `TelegramRetryAfter` carrying `retry_after`.
Honour that value; do not substitute a guess. See the `aiogram-rate-limits` skill.

## file_id and file_unique_id

- `file_id` is **bot-scoped**. An id captured by one bot cannot be used by another.
  Token rotation for the same bot does not change that scope; do not assume cache loss.
- `file_id` can change for the same physical file; do not use it as a primary key.
- `file_unique_id` is stable across bots but **cannot be used to download** anything. Use
  it for deduplication only.
- Re-sending by `file_id` skips the upload entirely and is dramatically cheaper than
  re-uploading bytes. Cache ids yourself — aiogram ships no cache.

## callback queries

- A callback query **must be answered**, even with an empty `answer()`. Until then the
  client shows a spinner on the button.
- Query ids expire. Answering late raises
  `TelegramBadRequest: query is too old and response timeout expired or query ID is invalid`.
- After a restart your bot will receive callback queries for buttons rendered by the
  *previous* deployment. Payloads that no longer parse, or that reference deleted
  entities, must be handled — not crashed on.
- `message` on a `CallbackQuery` may be an `InaccessibleMessage` rather than a `Message`
  when the original is too old. Check the type before touching `message.text`.

## editing and deleting

- Editing a message to *identical* text **and** identical markup raises
  `TelegramBadRequest: message is not modified`. Compare before editing, or catch it.
- `DeleteMessage` requires messages to be less than 48 hours old. Private-chat dice
  messages must also be more than 24 hours old. Service messages announcing supergroup,
  channel, or forum-topic creation cannot be deleted.
- Bots may delete their outgoing messages in private chats, groups, and supergroups,
  and **incoming private-chat messages without admin rights**. In channels,
  `can_post_messages` permits deleting their outgoing messages. A group administrator
  can delete others' messages; supergroups/channels require `can_delete_messages` for
  that. Channel direct messages chats require `can_manage_direct_messages`. These rights
  do not bypass the age/type restrictions. A rejection raises `TelegramBadRequest` or
  `TelegramForbiddenError`; `message can't be deleted` does not by itself diagnose rights.
- Message editing supports messages with no reply markup or an inline keyboard, not
  reply keyboards. Supply `chat_id` plus `message_id` for a chat message, or
  `inline_message_id` for an inline-mode message; the text/caption/media/markup edit
  methods return `Message` for the former and `True` for the latter. Preserve
  `business_connection_id` when editing on behalf of a business connection.
- The edit methods' 48-hour restriction concerns business messages that were **not sent
  by the bot and do not contain an inline keyboard**; it is not a general edit deadline.
- Match the edit to the field: `edit_message_caption` changes a media caption,
  `edit_message_reply_markup` changes controls, and `edit_message_media` replaces media.
  In Bot API 10.3, `edit_message_media` also replaces a text/rich message with media;
  `edit_message_text` cannot turn media into a text-only message. Inline-mode media edits
  cannot upload a new file: supply an existing `file_id` or a URL. Within albums, audio
  remains audio, documents remain documents, and other album items can become a photo,
  live photo, or video. Preserve the exact message ID and media kind rather than
  catching any failed text edit and deleting the result. Method/album restrictions still
  apply; a typed `Message` shortcut does not validate server-side edit rules.

Sources: installed `DeleteMessage`, `EditMessageText`, `EditMessageCaption`,
`EditMessageMedia`, and `EditMessageReplyMarkup`; the
[Bot API updating-messages section](https://core.telegram.org/bots/api#updating-messages)
also specifies the reply-markup restriction.

## updates and delivery

- Webhook redelivery depends on the HTTP acknowledgement, not handler success.
  Background acknowledgement can happen before the handler runs. Polling advances the
  offset independently of successful handler completion; a raised handler is not an
  automatic application retry. Use explicit durable jobs when delivery must survive failure.
- `allowed_updates` is **sticky**: it is stored server-side by `getUpdates`/`setWebhook`.
  Update types omitted there are dropped by Telegram and never reach your code. Use
  `dispatcher.resolve_used_update_types()` so the list follows your handlers.
- Long polling and a webhook are mutually exclusive per token. Polling while a webhook is
  set raises `TelegramConflictError`; so does a second poller.
- `drop_pending_updates=True` on `delete_webhook`/`set_webhook` discards the backlog.
  Use only when intentionally discarding those updates is authorised.

## groups, privacy mode, and forums

- **Privacy mode is on by default.** Non-admin bots receive a restricted subset:
  service events, addressed commands, some general commands, via-bot messages, and
  replies to them. Admin bots receive broader traffic. See the Telegram FAQ for the
  exact rules; privacy-mode changes may require re-adding the bot.
- A command sent in a group may carry an `@mention` suffix (`/start@my_bot`). aiogram's
  `Command` filter strips it; hand-rolled text comparisons will not match.
- Forum topics arrive as `message_thread_id`. Replies must carry it back or they land in
  the wrong topic. FSM keys can include it via `FSMStrategy.USER_IN_TOPIC`.
- When a group is upgraded to a supergroup the chat id changes; aiogram surfaces this as
  `TelegramMigrateToChat`, which carries the new `migrate_to_chat_id`.

## media groups on the way in

An album is **not one update**. Telegram delivers each item as a separate `Message`
sharing a `media_group_id`, with no count and no terminator. There is no built-in
aggregator in aiogram. Buffering strategy is discussed in `aiogram-media-groups`.

Individual album items may each carry a caption; inspect all items.

## blocked users

When a user blocks the bot, every send to them raises `TelegramForbiddenError`. This is
permanent until they unblock; retrying is wasted quota. Mark the user inactive instead.
