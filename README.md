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

A small USB desk gadget that does something cute when your agents need you.
Claude Code waits for permission or for your answer: the bar shows its mascot
with an arm up, blinks its LEDs, and plays a chime if you turn sound on. You
reply, the arm comes down. The turn ends, it smiles. Turn the wheel to
approve a tool call without the keyboard.

| | |
| --- | --- |
| <img src="img/done.png" width="360"> | **Done.** The turn ended. |
| <img src="img/ask.png" width="360"> | **Ask.** Wheel forward allows, back denies. |
| <img src="img/two-agents.png" width="360"> | **Two sessions.** One strip, one queue. |
| <img src="img/back.png" width="360"> | **Your side.** The back OLED mirrors the front. |

## Setup

Plug the bar in over USB, then:

```bash
git clone https://github.com/davidkh1/busybar-agents
ln -s "$PWD/busybar-agents/adapters/claude-code" ~/.claude/skills/busybar-agents
claude
```

Needs [uv](https://docs.astral.sh/uv/). Linux and macOS.

The hand goes up when Claude needs permission, waits for you, needs input,
or auto mode blocks a call. It comes down when you type. Every turn ends
with DONE. The name after the reason is the session's `/rename` title, or
the folder.

## The wheel

```bash
BUSYBAR_ASK=1 BUSYBAR_GO=1 claude
```

| Claude asks | Bar shows | Wheel |
| --- | --- | --- |
| permission for a tool call | `ALLOW? / Bash: npm test` | forward allows, back denies |
| a multiple-choice question | `React / 1/3 Framework` | scroll, rest to pick |
| "shall I…?" at the end of a turn | `GO? / wheel = yes` | forward means go ahead |

Leave it alone and the terminal prompt appears as usual. A running focus
session outranks the plugin unless `BUSYBAR_PRIORITY=91`.

## Codex CLI

```bash
python3 busybar-agents/adapters/codex/install.py   # merges into ~/.codex/hooks.json
codex                                               # then /hooks, trust them
```

Same hands, same wheel. `install.py --uninstall` removes them.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `BUSYBAR_ADDR` | `10.0.4.20` | The bar's fixed USB address, or its Wi-Fi address |
| `BUSYBAR_TOKEN` | unset | Access key, Wi-Fi only |
| `BUSYBAR_PRIORITY` | `50` | `91` or more overrides a running focus session |
| `BUSYBAR_SOUND` | off | `1` plays the bar's reminder chime when a hand goes up; or a stock sound name (`event`, `reminder`) |
| `BUSYBAR_ASK` | off | `1`: permissions and questions on the wheel |
| `BUSYBAR_GO` | off | `1`: go ahead on the wheel after a question |

<details>
<summary>More settings</summary>

| Variable | Default | Meaning |
| --- | --- | --- |
| `BUSYBAR_TTL` | `1800` | Seconds a hand may stay up |
| `BUSYBAR_DONE_SECONDS` | `8` | How long DONE stays |
| `BUSYBAR_HELLO_SECONDS` | `4` | Ready blip at session start, `0` disables |
| `BUSYBAR_ASK_TIMEOUT` | `20` | Seconds to wait for the wheel |
| `BUSYBAR_GO_SECONDS` | `8` | How long GO? stays |
| `BUSYBAR_DRY_RUN` | off | `1` prints payloads instead of drawing |
| `BUSYBAR_STATE` | platform default | Hands file: `~/.local/state/busybar-agents/hands.json` on Linux, `~/Library/Application Support/busybar-agents/hands.json` on macOS |
| `BUSYBAR_AGENTS_BIN` | unset | CLI command for the hook bridges |

</details>

<details>
<summary>Command line and internals</summary>

```bash
busybar-agents raise  --agent claude --session 1a2b3c4d --project api --reason "permission?"
busybar-agents lower  --agent claude --session 1a2b3c4d
busybar-agents done   --agent claude --session 1a2b3c4d --project api
busybar-agents ask    --question "ALLOW?" --detail "Bash: npm test"   # allow, deny or timeout
busybar-agents choose --title Framework --option React --option Vue    # the label, cancel or timeout
busybar-agents hello | status | redraw | clear
```

Each adapter is one standard-library script that turns hook events into
these verbs. Hands are recorded in one JSON file, one per agent and
session, and the strip is redrawn from the whole list, so several sessions
share it. Everything is filed under the application name `busybar-agents`
and carries a timeout; icons are inline bitmaps, sounds are stock, nothing
is uploaded to the bar.

```bash
uv sync && uv run pytest          # no hardware needed
claude plugin validate ./adapters/claude-code
```

</details>

## Credits

Built on [busylib](https://github.com/busy-app/busylib-py), Flipper Devices'
MIT-licensed Python client, and the bar's
[HTTP API](https://docs.busy.app/bar/dev/http-api). The mascot belongs to
Claude Code. Not affiliated with Flipper Devices or Anthropic.

MIT. Images in `img/` are CC BY 4.0.
