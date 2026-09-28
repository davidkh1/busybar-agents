<p align="center">
  <img src="img/hand-up.png" width="576" alt="The bar's front strip: Clawd with an arm up, CLAUDE, permission?">
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

Claude Code asks for permission, or waits for your answer, and the bar on your
desk shows Clawd with an arm up. Its LEDs blink. You reply and the arm comes
down. The turn ends and Clawd looks happy. Turn the wheel, and the tool call
is approved without touching the keyboard.

It started with [a post by Caitlin Kalinowski](https://x.com/kalinowski007/status/2096446783883001945)
asking for a little minibot that does something cute when her AI agents need
her. The BUSY Bar was already on the desk.

## What you see

| | |
| --- | --- |
| <img src="img/hello.png" width="360"> | **Session starts.** Clawd says hello for four seconds. |
| <img src="img/hand-up.png" width="360"> | **Needs you.** A permission prompt. Arm up, orange LEDs. |
| <img src="img/your-turn.png" width="360"> | **Your turn.** Claude finished and you have been away a minute. |
| <img src="img/done.png" width="360"> | **Done.** The turn ended, in the session named with `/rename`, or in that folder. |
| <img src="img/ask.png" width="360"> | **Ask.** Wheel forward to allow, back to deny. Opt-in. |
| <img src="img/two-agents.png" width="360"> | **Two sessions.** One strip, one queue. |
| <img src="img/back.png" width="360"> | **Your side.** The back OLED mirrors the front. |

Claude speaks in Claude orange, with Clawd drawn as a 16-pixel bitmap. Other
agents get a `>_` glyph in their own colour.

## Setup in a minute

```bash
# 1. Plug the bar in over USB. It answers at 10.0.4.20, no drivers.

# 2. Clone, and link the Claude Code plugin so it loads in every session.
git clone https://github.com/davidkh1/busybar-agents
ln -s "$PWD/busybar-agents/adapters/claude-code" ~/.claude/skills/busybar-agents

# 3. Open claude. Clawd says ready.
claude
```

The plugin runs the CLI from the clone through [uv](https://docs.astral.sh/uv/).
To have `busybar-agents` on your PATH as well:

```bash
uv tool install git+https://github.com/davidkh1/busybar-agents
busybar-agents status
```

To try it for one session only, skip the link and pass the plugin directly:
`claude --plugin-dir ./busybar-agents/adapters/claude-code`.

> Permission screens appear in the default permission mode. Auto mode never
> prompts, so there you get the ready blip, DONE, and "your turn".

## What Claude Code tells the bar

| Claude Code event | Bar |
| --- | --- |
| `SessionStart` | `CLAUDE / ready`, four seconds |
| `Notification` permission prompt | arm up, `CLAUDE / permission?` |
| `Notification` idle, subagent needs input, elicitation | arm up, `CLAUDE / your turn` or `input?` |
| `UserPromptSubmit`, `SessionEnd` | arm down |
| `Stop` | `DONE / session`, eight seconds |
| `PermissionRequest`, with `BUSYBAR_ASK=1` | `ALLOW? / Bash: npm test`, then your wheel decides |

The second line names the session: the name you gave it with `/rename`, or
the folder you started `claude` in.

Hand up and hand down run in the background. Stop and SessionEnd run in the
foreground, because Claude Code exits right after them in print mode; each
takes about a quarter of a second.

## Answer from the bar

```bash
BUSYBAR_ASK=1 claude
```

When a tool call needs permission, the bar shows `ALLOW?` and what the tool
wants to do. Wheel forward allows, wheel back or the Back button denies. Do
nothing for `BUSYBAR_ASK_TIMEOUT` seconds and the usual terminal prompt
appears. The terminal waits for that window, so keep it short. The bar's own
UI sees the gesture too: on the idle screen the wheel only moves a highlight.

## The command line

Every adapter calls these. So can any script.

```bash
busybar-agents raise --agent claude --session 1a2b3c4d --project api --reason "permission?"
busybar-agents lower --agent claude --session 1a2b3c4d
busybar-agents done  --agent claude --session 1a2b3c4d --project api
busybar-agents ask   --question "ALLOW?" --detail "Bash: npm test"   # prints allow, deny or timeout
busybar-agents hello --agent claude --project api
busybar-agents status
busybar-agents clear
```

One hand per `agent` and `session`. Several Claude Code sessions, or Claude
next to another agent, share the strip: two hands read `2 AGENTS` over the
project names, lowering one redraws the other, and DONE shows only when
nobody else is waiting. Hands older than `BUSYBAR_TTL` are dropped. The wheel
is the one thing not shared: a gesture answers whichever session asked first.

## Configuration

Everything is an environment variable, so the same settings apply from a
shell, a Claude Code hook, or any other adapter.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BUSYBAR_ADDR` | `10.0.4.20` | USB address, or the bar's Wi-Fi address |
| `BUSYBAR_TOKEN` | unset | Access key, needed over Wi-Fi only |
| `BUSYBAR_PRIORITY` | `50` | `91` or more shows even over a running BUSY session |
| `BUSYBAR_SOUND` | off | `1` for the stock `reminder` chime on hand up, or any stock sound |
| `BUSYBAR_TTL` | `1800` | Seconds a hand stays up if nobody lowers it |
| `BUSYBAR_DONE_SECONDS` | `8` | How long DONE stays |
| `BUSYBAR_HELLO_SECONDS` | `4` | Length of the ready blip. `0` turns it off |
| `BUSYBAR_ASK_TIMEOUT` | `20` | Seconds to wait for the wheel |
| `BUSYBAR_ASK` | off | `1` lets the Claude Code plugin answer permission prompts from the bar |
| `BUSYBAR_DRY_RUN` | off | `1` prints payloads instead of drawing |
| `BUSYBAR_STATE` | see below | Where raised hands are recorded |
| `BUSYBAR_AGENTS_BIN` | unset | Explicit CLI command for the hook bridge |

The state file lives at `~/.local/state/busybar-agents/hands.json` on Linux
and `~/Library/Application Support/busybar-agents/hands.json` on macOS.

## How it works

```
Claude Code hook ──▶ adapters/claude-code/hook.py ──▶ busybar-agents ──▶ busylib ──▶ HTTP API ──▶ bar
Codex, Gemini hooks ─┘ (adapters to come)                │
MCP server (to come) ────────────────────────────────────┘
```

The CLI records hands in a small JSON file and redraws the strip from the
whole list, so agents never fight over the display. Everything it draws is
filed under the application name `busybar-agents`, so `busybar-agents clear`
removes only its own work and leaves the bar's timers alone. Drawings carry
a timeout, so an unplugged laptop never leaves an arm up forever. Icons are
inline bitmaps and sounds are stock; nothing is uploaded to the bar.

## Linux and macOS

Both work the same way. The bar appears as a USB network interface without
drivers and answers at `10.0.4.20`. The hook bridge runs on the system
`python3`, including the 3.9 that Apple's developer tools ship, while the
CLI runs under uv with its own Python 3.10 or newer. CI runs the tests on
Ubuntu and macOS. Windows is untested.

## Development

```bash
git clone https://github.com/davidkh1/busybar-agents
cd busybar-agents
uv sync
uv run pytest                      # no hardware needed
uv run busybar-agents status       # smoke test with a bar plugged in
claude plugin validate ./adapters/claude-code
```

## Roadmap

- Codex CLI adapter, through its hooks.
- Gemini CLI adapter, through its `Notification` and `AfterAgent` hooks.
- An MCP server exposing `raise_hand` and `ask_user`, for agents without hooks.
- A waving Clawd, using the bar's animation element.

## Credits

Built on [busylib](https://github.com/busy-app/busylib-py), Flipper Devices'
MIT-licensed Python client, and the bar's
[open HTTP API](https://docs.busy.app/bar/dev/http-api). Clawd belongs to
Claude Code. Not affiliated with Flipper Devices or Anthropic.

## License

MIT. Images in `img/` are CC BY 4.0.
