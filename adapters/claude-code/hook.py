#!/usr/bin/env python3
"""Claude Code hook bridge: one event in on stdin, one busybar-agents call out.

Standard library only. Never blocks Claude on a missing bar or CLI.

  SessionStart (startup, resume)             hello
  Notification (permission, idle, input)     raise
  PermissionDenied (auto mode blocked a call)  raise
  UserPromptSubmit, SessionEnd               lower
  Stop                                       done; BUSYBAR_GO=1: GO? on the wheel after a question
  PermissionRequest, BUSYBAR_ASK=1           ALLOW? on the wheel, decision returned
  PreToolUse AskUserQuestion, BUSYBAR_ASK=1  options on the wheel, answers returned

`busybar-agents wheel on` switches both without the variables; /busybar-agents:wheel
runs it through this file (``hook.py wheel on|off|status``).

Stop and SessionEnd run in the foreground: Claude Code exits right after
them in print mode and would skip a background hook.
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
    "permission_prompt": "permission?",
    "idle_prompt": "your turn",
    "agent_needs_input": "input?",
    "elicitation_dialog": "input?",
    "elicitation_url_dialog": "input?",
}


WHEEL_KEYS = {"BUSYBAR_ASK": "ask", "BUSYBAR_GO": "go"}


def flag(name: str) -> bool:
    """A set variable decides; otherwise the wheel file written by `busybar-agents wheel on`."""
    value = os.environ.get(name, "").strip()
    if value:
        return value.lower() in {"1", "true", "yes", "on"}
    key = WHEEL_KEYS.get(name)
    if not key:
        return False
    try:
        return bool(json.loads(state_path().with_name("wheel.json").read_text()).get(key))
    except (OSError, ValueError, AttributeError):
        return False


def ends_with_question(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return bool(lines) and lines[-1].endswith("?")


# Pinned to a commit: uvx resolves a full SHA from its cache, a branch or tag costs a fetch every run.
PACKAGE_URL = "git+https://github.com/davidkh1/busybar-agents@5df9a19ed01758e903e361ff9697d1bf1da46f7f"


def cli_command() -> list[str] | None:
    """BUSYBAR_AGENTS_BIN, then PATH, then the repo this file lives in, then uvx from GitHub.

    A plugin installed from the marketplace is a copy of this folder alone, so
    the repo fallback misses and uvx fetches the package once into its cache.
    """
    override = os.environ.get("BUSYBAR_AGENTS_BIN")
    if override:
        return override.split()
    found = shutil.which("busybar-agents")
    if found:
        return [found]
    uv = shutil.which("uv")
    repo = Path(__file__).resolve().parents[2]
    if (repo / "pyproject.toml").exists() and uv:
        return ["uv", "run", "--quiet", "--project", str(repo), "busybar-agents"]
    if uv:
        return ["uvx", "--quiet", "--from", PACKAGE_URL, "busybar-agents"]
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


def session_label(event: dict) -> str:
    """The /rename title from custom-title.json beside the transcript, else the folder."""
    transcript, session_id = event.get("transcript_path"), event.get("session_id")
    if transcript and session_id:
        sidecar = Path(transcript).parent / session_id / "custom-title.json"
        try:
            title = json.loads(sidecar.read_text()).get("customTitle", "")
        except (OSError, ValueError, AttributeError):
            title = ""
        if isinstance(title, str) and title.strip():
            return title.strip()
    return Path(event.get("cwd") or os.getcwd()).name or "project"


def session_color(event: dict) -> str | None:
    """The /color choice: the last agent-color record in the transcript, else None."""
    transcript = event.get("transcript_path")
    if not transcript:
        return None
    color = None
    try:
        with open(transcript, encoding="utf-8", errors="replace") as lines:
            for line in lines:
                if '"agent-color"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("type") == "agent-color":
                    value = record.get("agentColor")
                    if isinstance(value, str) and value.strip():
                        color = value.strip()
    except OSError:
        return None
    return color


def state_path() -> Path:
    """Same rule as busybar_agents.config."""
    explicit = os.environ.get("BUSYBAR_STATE")
    if explicit:
        return Path(explicit)
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "busybar-agents" / "hands.json"


def tool_summary(tool_name: str, tool_input: dict) -> str:
    """Tool name and its main argument, short enough for the strip."""
    if not isinstance(tool_input, dict):
        tool_input = {}
    for key in ("command", "file_path", "path", "url", "pattern", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"{tool_name}: {value.strip()}"[:40]
    return tool_name or "tool"


def main() -> int:
    if sys.argv[1:2] == ["wheel"]:  # the /busybar-agents:wheel command, not a hook event
        cmd = cli_command()
        if cmd is None:
            print("busybar-agents: CLI not found; install uv or set BUSYBAR_AGENTS_BIN")
            return 0
        print(run(cmd + ["wheel", *sys.argv[2:3]], timeout=30).strip() or "busybar-agents: no answer from the CLI")
        return 0
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(event, dict):
        return 0

    name = event.get("hook_event_name", "")
    session = (event.get("session_id") or "")[:8] or "default"
    common = ["--agent", AGENT, "--session", session, "--project", session_label(event)]
    color = session_color(event)
    if color:
        common += ["--color", color]

    cmd = cli_command()
    if cmd is None:
        print("busybar-agents: CLI not found; install it or set BUSYBAR_AGENTS_BIN", file=sys.stderr)
        return 0

    if name == "SessionStart":
        if event.get("source", "startup") in ("startup", "resume"):
            run(cmd + ["hello", *common], timeout=15)
    elif name == "Notification":
        reason = REASONS.get(event.get("notification_type", ""))
        if reason:
            run(cmd + ["raise", *common, "--reason", reason], timeout=15)
    elif name == "PermissionDenied":
        run(cmd + ["raise", *common, "--reason", "blocked"], timeout=15)
    elif name in ("UserPromptSubmit", "SessionEnd"):
        run(cmd + ["lower", *common], timeout=15)
    elif name == "Stop":
        if flag("BUSYBAR_GO") and not event.get("stop_hook_active") and ends_with_question(event.get("last_assistant_message", "")):
            seconds = os.environ.get("BUSYBAR_GO_SECONDS", "8")
            answer = run(cmd + ["ask", *common, "--question", "GO?", "--detail", "wheel = yes", "--timeout", seconds], timeout=40).strip()
            if answer == "allow":
                print(json.dumps({"decision": "block", "reason": "The user answered yes from the BUSY Bar: go ahead with what you proposed, without asking again."}))
                return 0
        run(cmd + ["done", *common], timeout=15)
    elif name == "PreToolUse":
        tool_input = event.get("tool_input") or {}
        questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
        if event.get("tool_name") != "AskUserQuestion" or not flag("BUSYBAR_ASK") or not questions:
            return 0
        if any(q.get("multiSelect") for q in questions):
            return 0  # multi-select stays in the terminal
        answers = {}
        for question in questions:
            labels = [o.get("label", "") for o in question.get("options", []) if o.get("label")]
            if not labels:
                return 0
            args = ["choose", *common, "--title", question.get("header") or "?"]
            for label in labels:
                args += ["--option", label]
            picked = run(cmd + args, timeout=150).strip()
            if picked not in labels:
                return 0  # cancelled or timed out; the terminal takes over
            answers[question.get("question", "")] = picked
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                          "permissionDecisionReason": "answered on the BUSY Bar",
                          "updatedInput": {**tool_input, "answers": answers}}}))
    elif name == "PermissionRequest":
        if not flag("BUSYBAR_ASK"):
            return 0
        detail = tool_summary(event.get("tool_name", ""), event.get("tool_input") or {})
        answer = run(cmd + ["ask", *common, "--question", "ALLOW?", "--detail", detail], timeout=35).strip()
        if answer in ("allow", "deny"):
            decision = {"behavior": answer, "message": f"{answer} from the BUSY Bar"}
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
