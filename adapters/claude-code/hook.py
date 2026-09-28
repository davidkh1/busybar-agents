#!/usr/bin/env python3
"""Claude Code hook bridge: one script for every event, standard library only.

Claude Code sends the event as JSON on stdin. This script turns it into one
call of the ``busybar-agents`` CLI, which does the drawing. It never fails
loudly: a missing bar or a missing CLI must not slow Claude down.

Notification and UserPromptSubmit run as background hooks, so they never
delay Claude. Stop and SessionEnd run in the foreground on purpose: Claude
Code exits right after them in print mode and would otherwise leave a
background hook unstarted, and each call takes about a quarter of a second.

Events handled:
  SessionStart       startup or resume    -> short "ready" blip
  Notification       permission_prompt, idle_prompt, agent_needs_input,
                     elicitation_*        -> raise a hand
  UserPromptSubmit   you typed something  -> lower the hand
  SessionEnd         session closed       -> lower the hand
  Stop               turn finished        -> "done" for a few seconds
  PermissionRequest  only with BUSYBAR_ASK=1: ask on the bar, answer with
                     the wheel, and return the decision to Claude Code
  PreToolUse         AskUserQuestion, only with BUSYBAR_ASK=1: scroll the
                     options with the wheel, rest to pick, answer returned
  Stop               only with BUSYBAR_GO=1 and a turn that ended in a
                     question: wheel forward means "go ahead"
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


def session_label(event: dict) -> str:
    """What the bar calls this session: the name given with /rename, else the folder.

    Hooks are not told the session name, but Claude Code keeps it next to the
    transcript as <transcript dir>/<session id>/custom-title.json.
    """
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


def tool_summary(tool_name: str, tool_input: dict) -> str:
    """A few words that fit on a 72 pixel strip: what the tool is about to do."""
    if not isinstance(tool_input, dict):
        tool_input = {}
    for key in ("command", "file_path", "path", "url", "pattern", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"{tool_name}: {value.strip()}"[:40]
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
    common = ["--agent", AGENT, "--session", session, "--project", session_label(event)]

    cmd = cli_command()
    if cmd is None:
        print(
            "busybar-agents: CLI not found. Install it (uv tool install busybar-agents)"
            " or set BUSYBAR_AGENTS_BIN.",
            file=sys.stderr,
        )
        return 0

    if name == "SessionStart":
        if event.get("source", "startup") in ("startup", "resume"):
            run(cmd + ["hello", *common], timeout=15)
    elif name == "Notification":
        reason = REASONS.get(event.get("notification_type", ""))
        if reason:
            run(cmd + ["raise", *common, "--reason", reason], timeout=15)
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
            return 0  # several picks at once is a job for the terminal
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
                return 0  # cancelled or timed out: the terminal takes over
            answers[question.get("question", "")] = picked
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                          "permissionDecisionReason": "answered on the BUSY Bar",
                          "updatedInput": {**tool_input, "answers": answers}}}))
    elif name == "PermissionRequest":
        if not flag("BUSYBAR_ASK"):
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
