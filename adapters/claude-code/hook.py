#!/usr/bin/env python3
"""Claude Code hook bridge: one script for every event, standard library only.

Claude Code sends the event as JSON on stdin. This script turns it into one
call of the ``busybar-agents`` CLI, which does the drawing. It never fails
loudly: a missing bar or a missing CLI must not slow Claude down.

Events handled:
  Notification       permission_prompt, idle_prompt, agent_needs_input,
                     elicitation_*        -> raise a hand
  UserPromptSubmit   you typed something  -> lower the hand
  SessionEnd         session closed       -> lower the hand
  Stop               turn finished        -> "done" for a few seconds
  PermissionRequest  only with BUSYBAR_ASK=1: ask on the bar, answer with
                     the wheel, and return the decision to Claude Code
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

AGENT = "claude"

REASONS = {
    "permission_prompt": "needs permission",
    "idle_prompt": "waiting for you",
    "agent_needs_input": "subagent needs input",
    "elicitation_dialog": "needs input",
    "elicitation_url_dialog": "needs input",
}


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


def tool_summary(tool_name: str, tool_input: dict) -> str:
    """A few words that fit on a 72 pixel strip: what the tool is about to do."""
    if not isinstance(tool_input, dict):
        tool_input = {}
    for key in ("command", "file_path", "path", "url", "pattern", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"{tool_name}: {value.strip()}"[:60]
    return tool_name or "tool"


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
        print(
            "busybar-agents: CLI not found. Install it (uv tool install busybar-agents)"
            " or set BUSYBAR_AGENTS_BIN.",
            file=sys.stderr,
        )
        return 0

    if name == "Notification":
        reason = REASONS.get(event.get("notification_type", ""))
        if reason:
            run(cmd + ["raise", *common, "--reason", reason], timeout=15)
    elif name in ("UserPromptSubmit", "SessionEnd"):
        run(cmd + ["lower", *common], timeout=15)
    elif name == "Stop":
        run(cmd + ["done", *common], timeout=15)
    elif name == "PermissionRequest":
        if os.environ.get("BUSYBAR_ASK", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return 0
        detail = tool_summary(event.get("tool_name", ""), event.get("tool_input") or {})
        answer = run(cmd + ["ask", *common, "--question", "ALLOW?", "--detail", detail], timeout=35)
        answer = answer.strip()
        if answer in ("allow", "deny"):
            decision = {
                "behavior": answer,
                "message": f"{answer} from the BUSY Bar",
            }
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
