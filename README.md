# aiogram-skills

Agent Skills for building Telegram bots with [aiogram](https://github.com/aiogram/aiogram) 3.x.

Sixteen skills and eight lookup tools. The tools inspect the aiogram installed in your project.
The skills were verified against aiogram 3.31.0 and Telegram Bot API 10.3 on 2026-09-07.

## skills

### entry point

| Skill | Covers |
|---|---|
| [**using-aiogram**](./skills/using-aiogram/SKILL.md) | compact entry point that selects a focused sibling; the full bootstrap, lifecycle, API and migration guide is loaded on demand |

### siblings

| Skill | Covers |
|---|---|
| [aiogram-routing](./skills/aiogram-routing/SKILL.md) | routers, observers, registration order, propagation, `allowed_updates`, `feed_update` |
| [aiogram-filters](./skills/aiogram-filters/SKILL.md) | magic `F`, `Command`, `StateFilter`, `MagicData`, membership transitions, custom `BaseFilter` |
| [aiogram-middlewares](./skills/aiogram-middlewares/SKILL.md) | inner vs outer middleware, workflow data as DI, reserved keys, flags |
| [aiogram-fsm](./skills/aiogram-fsm/SKILL.md) | `StatesGroup`, `FSMContext`, storages, `StorageKey`, `FSMStrategy`, isolation, stale-state recovery |
| [aiogram-scenes](./skills/aiogram-scenes/SKILL.md) | the class-based wizard API — **marked experimental upstream** |
| [aiogram-callback-data](./skills/aiogram-callback-data/SKILL.md) | typed payloads, the 64-**byte** budget, packable types, stale buttons |
| [aiogram-keyboards](./skills/aiogram-keyboards/SKILL.md) | inline and reply builders, layout, pagination, edit-vs-send |
| [aiogram-formatting](./skills/aiogram-formatting/SKILL.md) | entity-based text, HTML/MarkdownV2, escaping, UTF-16 offsets |
| [aiogram-files](./skills/aiogram-files/SKILL.md) | upload sources, downloads, `file_id` vs `file_unique_id`, caching |
| [aiogram-media-groups](./skills/aiogram-media-groups/SKILL.md) | sending albums, and aggregating incoming ones (no built-in support) |
| [aiogram-webhooks](./skills/aiogram-webhooks/SKILL.md) | aiohttp integration, secret tokens, IP filtering, multi-bot, troubleshooting |
| [aiogram-errors](./skills/aiogram-errors/SKILL.md) | the exception tree, `@router.error`, reading `TelegramBadRequest` messages, retry policy |
| [aiogram-rate-limits](./skills/aiogram-rate-limits/SKILL.md) | `TelegramRetryAfter`, Telegram's documented limits, broadcasting, throttling patterns |
| [aiogram-streaming](./skills/aiogram-streaming/SKILL.md) | Bot API 10.x message drafts and rich messages, edit throttling, chat actions |
| [aiogram-testing](./skills/aiogram-testing/SKILL.md) | `feed_update`, a fake `BaseSession`, fixtures, FSM assertions |

### references

- [core-guide](./skills/using-aiogram/references/core-guide.md) — detailed framework guide and migration examples

- [telegram-quirks](./skills/using-aiogram/references/telegram-quirks.md) — documented limits and Telegram-side behaviour that surprises people
- [recipes](./skills/using-aiogram/references/recipes.md) — 15 short canonical bot recipes

## install

Skills live under `skills/<skill-name>/SKILL.md`, which is both the
[Codex Agent Skill](https://learn.chatgpt.com/docs/build-skills) layout and the location
the [plugin manifest](https://developers.openai.com/codex/plugins/build) requires. So the
repository works two ways: as a Codex plugin that installs the whole set, or as ordinary
Agent Skills you symlink one at a time.

### as a Codex plugin

```bash
codex plugin marketplace add ballisarium/aiogram-skills
codex plugin add aiogram-skills@aiogram-skills
```

Start a new Codex task after installing so the skills are available from the beginning.

### as Agent Skills

Codex discovers skills in `.agents/skills` (repository scope) and `$HOME/.agents/skills`
(user scope).

#### user scope

```bash
git clone https://github.com/ballisarium/aiogram-skills.git \
  "$HOME/.local/share/aiogram-skills"

mkdir -p "$HOME/.agents/skills"
for skill in "$HOME/.local/share/aiogram-skills"/skills/*; do
  ln -sfn "$skill" "$HOME/.agents/skills/$(basename "$skill")"
done
```

#### repository scope

```bash
mkdir -p .agents/skills
git submodule add https://github.com/ballisarium/aiogram-skills.git vendor/aiogram-skills
for skill in vendor/aiogram-skills/skills/*; do
  ln -sfn "../../$skill" ".agents/skills/$(basename "$skill")"
done
```

#### one skill only

Symlink or copy just the directories you want; each `SKILL.md` stands alone, though the
siblings cross-reference each other by name.

## compatible agents

`SKILL.md` with `name` and `description` frontmatter is a shared format. These skills are
written to that contract and are known to load in:

| Agent | Location |
|---|---|
| Codex CLI / ChatGPT | `.agents/skills/`, `$HOME/.agents/skills/` |
| Claude Code | `.claude/skills/`, `~/.claude/skills/` |

The lookup tools are plain Python scripts; any agent that can run a shell command can use
them regardless of skill support.

## lookup tools

`skills/using-aiogram/tools/` resolves the aiogram installed in the current environment. Nothing
is hardcoded, so the tools stay correct across upgrades.

```bash
python skills/using-aiogram/tools/check-version.py               # installed versions + drift check
python skills/using-aiogram/tools/get-method.py sendMessage      # method -> args, types, return
python skills/using-aiogram/tools/get-type.py Message            # type -> fields + shortcuts
python skills/using-aiogram/tools/get-filter.py Command          # filter -> constructor signature
python skills/using-aiogram/tools/get-router-api.py --observers  # every valid @router.<name>()
python skills/using-aiogram/tools/get-exception.py --tree        # exception hierarchy
python skills/using-aiogram/tools/search-source.py <pattern>     # grep installed aiogram source
python skills/using-aiogram/tools/validate-example.py <path.md>  # execute a file's examples
```

All support `--help`; most support `--list` and `--json`. They exit `1` on an unknown name
or detected drift, so they compose into CI steps.

Example:

```console
$ python skills/using-aiogram/tools/get-method.py sendMessage
sendMessage  ->  aiogram.methods.SendMessage
aiogram 3.31.0 | telegram bot api 10.3
https://core.telegram.org/bots/api#sendmessage

required arguments (2):
  chat_id: int | str
  text: str
...
returns: Message
```

Unknown names fail loudly with suggestions rather than inventing an answer:

```console
$ python skills/using-aiogram/tools/get-method.py sendmesage
unknown name: 'sendmesage'

did you mean:
  sendMessage
  sendRichMessage
```

## limitations

- Written against **one** aiogram release. Run `check-version.py` first; it exits non-zero
  when your installed version has drifted from the pins.
- aiogram 2.x is not covered and never will be.
- `aiogram-scenes` documents an API upstream calls experimental.
- Payments, Telegram Passport, stickers, inline mode, and i18n
  (`aiogram.utils.i18n`) are mentioned but have no dedicated skill.
- The album aggregator, throttlers, and file caches shown in the skills are **application
  code**, clearly labelled as such — aiogram ships none of them.

## licence

[MIT](./LICENSE).
