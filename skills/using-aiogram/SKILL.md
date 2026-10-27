---
name: using-aiogram
description: >
  Use when writing, reviewing, or debugging aiogram 3 bots, or migrating from 2.x. Not for Telethon.
metadata:
  aiogram: "3.31.0"
  bot_api: "10.3"
  python: ">=3.10,<3.15"
  source: https://github.com/aiogram/aiogram
  documentation: https://docs.aiogram.dev/en/v3.31.0/
  verified: "2026-09-22"
---

# aiogram 3

Use the project's installed version and existing architecture. This material was checked against aiogram 3.31.0 / Bot API 10.3 on 2026-09-07; verify the API surface affected by the task. Examples do not authorise upgrades, new dependencies, deployment, or a bot-wide rewrite.

## when to use this skill

Start here for application structure or a cross-cutting bug; use the focused skills below
for individual APIs. Diagnose the actual handler → service → storage/API boundary before
changing it.

## Choose the smallest relevant reference

For a focused issue, read the matching sibling skill directly; do not load all of them:

| Topic | Reference |
|---|---|
| Handlers, update delivery | [Routing](../aiogram-routing/SKILL.md) |
| Commands and predicates | [Filters](../aiogram-filters/SKILL.md) |
| Middleware and injection | [Middleware](../aiogram-middlewares/SKILL.md) |
| Conversation state | [FSM](../aiogram-fsm/SKILL.md) |
| Experimental wizard API | [Scenes](../aiogram-scenes/SKILL.md) |
| Button payloads | [Callback data](../aiogram-callback-data/SKILL.md) |
| Menus and buttons | [Keyboards](../aiogram-keyboards/SKILL.md) |
| Text and entities | [Formatting](../aiogram-formatting/SKILL.md) |
| Uploads and downloads | [Files](../aiogram-files/SKILL.md) |
| Albums | [Media groups](../aiogram-media-groups/SKILL.md) |
| Webhook serving | [Webhooks](../aiogram-webhooks/SKILL.md) |
| API failures | [Errors](../aiogram-errors/SKILL.md) |
| Flood control | [Rate limits](../aiogram-rate-limits/SKILL.md) |
| Incremental output | [Streaming](../aiogram-streaming/SKILL.md) |
| Offline tests | [Testing](../aiogram-testing/SKILL.md) |

For bootstrap, lifecycle, polling, migration, or a concrete code example, use the matching heading in [core-guide.md](references/core-guide.md). Locate headings with `rg -n '^## '`, then read only the relevant range; do not load the whole guide routinely. Its reviewed examples remain available.

Use [Telegram quirks](references/telegram-quirks.md) for Telegram-specific surprises and [recipes](references/recipes.md) for a requested bot pattern.

For queued sends/mutations, restart recovery, or cancellation across external effects,
read [durable operations](references/durable-operations.md). These are application
patterns; ordinary handlers do not require adopting a queue.

## Inspect installed APIs

Run helpers from this skill's `tools/` with the project's Python interpreter. Resolve their paths from this skill directory, not the working directory:

- `check-version.py`: versions and drift; `get-method.py`: Bot API method arguments.
- `get-type.py`: fields/shortcuts; `get-filter.py`: filter signatures.
- `get-router-api.py`: observers; `get-exception.py`: exceptions.
- `search-source.py`: installed source; `validate-example.py`: validate examples only when relevant.

Inspect `--help` when needed. Helpers may exit non-zero for unknown names or drift; inspect rather than ignore the failure.

## checklist

- Use 3.x Router/Dispatcher APIs and DefaultBotProperties; do not introduce 2.x executor, message_handler, or Bot parse_mode arguments.
- Keep Bot creation and polling out of module import time. Inject dependencies through existing workflow data. Close owned sessions and resources on shutdown.
- Keep handlers cheap: validate, coordinate, enqueue or await asynchronous I/O. Offload blocking rendering/encoding/archive work; `async def` alone does not move it off the event loop. Bound concurrency and check shared native resources for thread safety.
- Answer valid callback queries once before slow work; reject invalid message/owner context with plain feedback. Terminal actions need atomic claims, not just keyboard removal. Respect the 64-byte payload limit; typed CallbackData and builders suit structured/dynamic markup, while simple constants/static markup remain valid.
- Escape dynamic message text and respect UTF-16 entity offsets. Preserve the project's existing formatting contract.
- Keep visible strings in the existing locale catalogue, including alerts, errors and worker messages. Check keys/placeholders across supported languages and the final assembled screen, not only isolated translations.
- Do not run a webhook and poller against the same token. Do not drop pending updates or change delivery mode as a side effect of a small fix.
- Handle API errors explicitly; do not swallow broad exceptions or replace TelegramRetryAfter.retry_after with a hardcoded delay.
- Preserve exact message IDs and text/media kinds through FSM and worker handoff. Clearing state does not retire old buttons; late worker results must not overwrite newer navigation.
- Existing durable jobs need atomic claims, current-owner fences and persisted intent/ACK around external effects. Commit accepted cancellation before stopping work; an accepted cancel forbids the result. Reconcile unknown effects instead of blindly retrying; cleanup cannot undo proven success.
- Never put real tokens, chat IDs, or personal data in examples, fixtures, or logs. Read credentials through existing configuration.
- Reproduce regressions before fixing them; assert exact calls and race outcomes with real models and controlled barriers. Offline feed_update/fake-session tests prove only simulated behaviour, not live Telegram parsing, permissions, or rendering.

## see also

Use the topic table above; application-owned recovery and cancellation contracts live in
[durable operations](references/durable-operations.md).
