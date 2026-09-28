#!/usr/bin/env python3
"""Codex CLI hook bridge: one script for every event, standard library only.

Codex sends the event as JSON on stdin. This script turns it into one call of
the ``busybar-agents`` CLI, which does the drawing. It never fails loudly: a
missing bar or a missing CLI must not slow Codex down.

Events handled:
  SessionStart       startup or resume     -> short "ready" blip
  PermissionRequest  approval needed       -> hand up, "permission?"; with
                     BUSYBAR_ASK=1 the wheel answers and the decision is returned
  UserPromptSubmit   you typed something   -> hand down
  PostToolUse        the approved tool ran -> hand down, if one was up
  Interrupt          you interrupted       -> hand down
  SessionEnd         session closed        -> hand down
  Stop               turn finished         -> "done"; with BUSYBAR_GO=1 and a
                     turn that ended in a question, wheel forward means go ahead

Install with ``python3 adapters/codex/install.py`` and trust the hooks from
``/hooks`` inside Codex. Every hook runs in the foreground, since this Codex
skips background hooks; each call takes well under a second.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

AGENT = "codex"


def flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def ends_with_question(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and lines[-1].endswith("?")


def cli_command() -> list[str] | None:
    """Find the CLI: explicit override, PATH, or the repo this adapter lives in."""
    override = os.environ.get("BUSYBAR_AGENTS_BIN")
    if override:
        return override.split()
    found = shutil.which("busybar-agents")
    if found:
        return [found]
    repo = Path(__file__).resolve().parents[2]
    if (repo / "pyproject.toml").exists() and shutil.which("uv"):
        return ["uv", "run", "--quiet", "--project", str(repo), "busybar-agents"]
    return None


def run(cmd: list[str], timeout: float) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        print(f"busybar-agents: {err}", file=sys.stderr)
        return ""
    if proc.returncode != 0 and proc.stderr:
        print(proc.stderr.strip()[:500], file=sys.stderr)
    return proc.stdout


def tool_summary(tool_name: str, tool_input) -> str:
    """A few words that fit on a 72 pixel strip: what the tool is about to do."""
    if not isinstance(tool_input, dict):
        tool_input = {}
    for key in ("command", "description", "file_path", "path", "url", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"{tool_name}: {value.strip()}"[:40]
    return tool_name or "tool"


def state_path() -> Path:
    """Where the CLI keeps raised hands; mirrors busybar_agents.config."""
    explicit = os.environ.get("BUSYBAR_STATE")
    if explicit:
        return Path(explicit)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "busybar-agents" / "hands.json"


def hand_is_up(session: str) -> bool:
    """Cheap check so PostToolUse, which fires often, only spawns the CLI when needed."""
    try:
        hands = json.loads(state_path().read_text()).get("hands", [])
    except (OSError, ValueError, AttributeError):
        return False
    return any(h.get("agent") == AGENT and h.get("session") == session for h in hands)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0

    name = event.get("hook_event_name", "")
    session = (event.get("session_id") or "")[:8] or "default"
    project = Path(event.get("cwd") or os.getcwd()).name or "project"
    common = ["--agent", AGENT, "--session", session, "--project", project]

    cmd = cli_command()
    if cmd is None:
        print("busybar-agents: CLI not found. Install it (uv tool install busybar-agents) or set BUSYBAR_AGENTS_BIN.", file=sys.stderr)
        return 0

    if name == "SessionStart":
        if event.get("source", "startup") in ("startup", "resume"):
            run(cmd + ["hello", *common], timeout=15)
    elif name == "PermissionRequest":
        detail = tool_summary(event.get("tool_name", ""), event.get("tool_input") or {})
        if not flag("BUSYBAR_ASK"):
            run(cmd + ["raise", *common, "--reason", "permission?"], timeout=15)
            return 0
        answer = run(cmd + ["ask", *common, "--question", "ALLOW?", "--detail", detail], timeout=35).strip()
        if answer in ("allow", "deny"):
            decision = {"behavior": answer}
            if answer == "deny":
                decision["message"] = "Denied from the BUSY Bar."
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))
        else:
            run(cmd + ["raise", *common, "--reason", "permission?"], timeout=15)
    elif name in ("UserPromptSubmit", "Interrupt", "SessionEnd"):
        run(cmd + ["lower", *common], timeout=15)
    elif name == "PostToolUse":
        if hand_is_up(session):
            run(cmd + ["lower", *common], timeout=15)
    elif name == "Stop":
        if flag("BUSYBAR_GO") and not event.get("stop_hook_active") and ends_with_question(event.get("last_assistant_message") or ""):
            seconds = os.environ.get("BUSYBAR_GO_SECONDS", "8")
            answer = run(cmd + ["ask", *common, "--question", "GO?", "--detail", "wheel = yes", "--timeout", seconds], timeout=40).strip()
            if answer == "allow":
                print(json.dumps({"decision": "block", "reason": "Yes, go ahead with what you proposed. (answered from the BUSY Bar)"}))
                return 0
        run(cmd + ["done", *common], timeout=15)
    return 0


if __name__ == "__main__":
    sys.exit(main())
