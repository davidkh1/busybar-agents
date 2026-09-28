<p align="center">
  <img src="img/your-turn.png" width="576" alt="The bar's front strip: the Claude Code mascot with an arm up, CLAUDE, your turn">
</p>

<h1 align="center">busybar-agents</h1>

<p align="center">
  Coding agents raise a hand on your <a href="https://busy.app">BUSY Bar</a> when they need you.
</p>

<p align="center">
  <a href="https://github.com/davidkh1/busybar-agents/actions/workflows/ci.yml"><img src="https://github.com/davidkh1/busybar-agents/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS-lightgrey" alt="Linux and macOS">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
</p>

Claude Code asks for permission or waits for you, and the bar shows its
mascot with an arm up and blinking LEDs. Reply and the arm comes down. Finish
and it smiles. Turn the wheel to approve a tool call without the keyboard.

## What you see

| | |
| --- | --- |
| <img src="img/hello.png" width="360"> | **Session starts.** Shown for `BUSYBAR_HELLO_SECONDS`. |
| <img src="img/hand-up.png" width="360"> | **Needs you.** A permission prompt, with the session name. |
| <img src="img/your-turn.png" width="360"> | **Your turn.** Claude finished and you have been away a minute. |
| <img src="img/done.png" width="360"> | **Done.** Shown for `BUSYBAR_DONE_SECONDS`. |
| <img src="img/ask.png" width="360"> | **Ask.** Wheel forward allows, back denies. Opt-in. |
| <img src="img/two-agents.png" width="360"> | **Two sessions.** One strip, one queue. |
| <img src="img/back.png" width="360"> | **Your side.** The back OLED mirrors the front. |

Claude is drawn in Claude orange with a 16-pixel mascot. Other agents get a
`>_` glyph in their own colour.

## Setup

Plug the bar in over USB, then:

```bash
git clone https://github.com/davidkh1/busybar-agents
ln -s "$PWD/busybar-agents/adapters/claude-code" ~/.claude/skills/busybar-agents
claude
```

The plugin runs the CLI from the clone through [uv](https://docs.astral.sh/uv/).
Optional: `uv tool install git+https://github.com/davidkh1/busybar-agents`
puts `busybar-agents` on your PATH. For one session only:
`claude --plugin-dir ./busybar-agents/adapters/claude-code`.

In auto mode Claude approves tools itself, so the permission hand is rare;
everything else works, and a call the classifier blocks raises a hand too.

## Claude Code events

| Event | Bar |
| --- | --- |
| `SessionStart` | `CLAUDE / ready` |
| `Notification` permission prompt | `CLAUDE / permission? - session`, arm up |
| `Notification` idle, subagent input, elicitation | `CLAUDE / your turn - session` or `input? - session`, arm up |
| `PermissionDenied`, auto mode | `CLAUDE / blocked - session`, arm up |
| `UserPromptSubmit`, `SessionEnd` | arm down |
| `Stop` | `DONE / session` |
| `PermissionRequest`, `BUSYBAR_ASK=1` | `ALLOW? / Bash: npm test`, the wheel decides |
| `PreToolUse` for `AskUserQuestion`, `BUSYBAR_ASK=1` | one option at a time, the wheel picks |
| `Stop` after a question, `BUSYBAR_GO=1` | `GO? / wheel = yes`, wheel forward continues |

The session name is the one you gave with `/rename`, else the folder.

## Talk back with the wheel

Off by default:

```bash
BUSYBAR_ASK=1 BUSYBAR_GO=1 claude
```

| Claude asks | Bar shows | Wheel |
| --- | --- | --- |
| permission for a tool call | `ALLOW? / Bash: npm test` | forward allows, back or Back denies |
| a multiple-choice question | `React / 1/3 Framework` | scroll, rest on an option to pick it |
| "shall I…?" at the end of a turn | `GO? / wheel = yes` | forward means go ahead |

Do nothing for `BUSYBAR_ASK_TIMEOUT` seconds and the terminal prompt appears
as usual. Multi-select questions stay in the terminal. Only the wheel and
Back are used: Start and OK drive the bar's own UI.

Works in the BUSY and CUSTOM positions while nothing runs. A running focus
session outranks the plugin; `BUSYBAR_PRIORITY=91` overrides.

## Codex CLI

```bash
python3 busybar-agents/adapters/codex/install.py   # merges into ~/.codex/hooks.json
codex                                               # then /hooks, trust them
```

| Event | Bar |
| --- | --- |
| `SessionStart` | `CODEX / ready` |
| `PermissionRequest` | `CODEX / permission? - folder`; `BUSYBAR_ASK=1`: the wheel decides |
| `UserPromptSubmit`, `PostToolUse`, `Interrupt`, `SessionEnd` | arm down |
| `Stop` | `DONE / folder`; `BUSYBAR_GO=1` after a question: wheel forward continues |

Codex runs only trusted hooks and asks again when one changes.
`install.py --uninstall` removes ours and keeps the rest.

## Command line

```bash
busybar-agents raise  --agent claude --session 1a2b3c4d --project api --reason "permission?"
busybar-agents lower  --agent claude --session 1a2b3c4d
busybar-agents done   --agent claude --session 1a2b3c4d --project api
busybar-agents ask    --question "ALLOW?" --detail "Bash: npm test"   # allow, deny or timeout
busybar-agents choose --title Framework --option React --option Vue    # the label, cancel or timeout
busybar-agents hello  --agent claude --project api
busybar-agents status
busybar-agents redraw
busybar-agents clear
```

One hand per agent and session. Two hands read `2 AGENTS`; lowering one
redraws the other; DONE shows only when nobody waits. Hands expire after
`BUSYBAR_TTL`. The wheel answers whichever session asked first.

## Configuration

All settings are environment variables.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BUSYBAR_ADDR` | `10.0.4.20` | The bar's fixed USB address, or its Wi-Fi address |
| `BUSYBAR_TOKEN` | unset | Access key, Wi-Fi only |
| `BUSYBAR_PRIORITY` | `50` | `91` or more overrides a running focus session |
| `BUSYBAR_SOUND` | off | `1` for the stock `reminder` chime on hand up, or a stock sound name |
| `BUSYBAR_TTL` | `1800` | Seconds a hand may stay up |
| `BUSYBAR_DONE_SECONDS` | `8` | How long DONE stays |
| `BUSYBAR_HELLO_SECONDS` | `4` | Ready blip length, `0` disables |
| `BUSYBAR_ASK_TIMEOUT` | `20` | Seconds to wait for the wheel |
| `BUSYBAR_ASK` | off | `1`: permissions and questions on the wheel |
| `BUSYBAR_GO` | off | `1`: go ahead on the wheel after a question |
| `BUSYBAR_GO_SECONDS` | `8` | How long GO? stays |
| `BUSYBAR_DRY_RUN` | off | `1` prints payloads instead of drawing |
| `BUSYBAR_STATE` | platform default | Hands file: `~/.local/state/busybar-agents/hands.json` on Linux, `~/Library/Application Support/busybar-agents/hands.json` on macOS |
| `BUSYBAR_AGENTS_BIN` | unset | CLI command for the hook bridges |

## How it works

```
Claude Code hook ──▶ adapters/claude-code/hook.py ──▶ busybar-agents ──▶ busylib ──▶ HTTP API ──▶ bar
Codex hook ────────▶ adapters/codex/hook.py ───────────────┘
```

Hands are recorded in one JSON file and the strip is redrawn from the whole
list. Everything is filed under the application name `busybar-agents`, so
`clear` removes only our own work. Drawings carry a timeout. Icons are inline
bitmaps and sounds are stock; nothing is uploaded to the bar.

## Linux and macOS

The bar appears as a USB network interface on both, without drivers. The hook
bridges run on the system `python3` (3.9 is enough); the CLI runs under uv
with Python 3.10 or newer. CI tests both. Windows is untested.

## Development

```bash
uv sync
uv run pytest                      # no hardware needed
uv run busybar-agents status       # with a bar plugged in
claude plugin validate ./adapters/claude-code
```

## Credits

Built on [busylib](https://github.com/busy-app/busylib-py), Flipper Devices'
MIT-licensed Python client, and the bar's
[HTTP API](https://docs.busy.app/bar/dev/http-api). The mascot belongs to
Claude Code. Not affiliated with Flipper Devices or Anthropic.

## License

MIT. Images in `img/` are CC BY 4.0.
