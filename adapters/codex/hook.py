#!/usr/bin/env python3
"""Codex CLI hook bridge: one event in on stdin, one busybar-agents call out.

Standard library only. Never blocks Codex on a missing bar or CLI. Every
event leaves a line in events.jsonl beside the hands file, with the process
that fired it; ``busybar-agents log`` and ``busybar-agents panel`` read it.

  SessionStart (startup, resume)              hello
  PermissionRequest                           raise; BUSYBAR_ASK=1: ALLOW? on the wheel, decision returned
  UserPromptSubmit, Interrupt, SessionEnd     lower
  PostToolUse                                 lower, if a hand was up
  Stop                                        done; BUSYBAR_GO=1: GO? on the wheel after a question

Install with ``python3 adapters/codex/install.py``, then trust the hooks in
``/hooks``. All hooks run in the foreground: this Codex skips async hooks.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

AGENT = "codex"


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


def cli_command() -> list[str] | None:
    """BUSYBAR_AGENTS_BIN, then PATH, then the repo this file lives in."""
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
        log_event(src="hook", agent=AGENT, trace=os.environ.get("BUSYBAR_TRACE"), error=f"{type(err).__name__}: {err}"[:300])
        return ""
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.strip()[:500], file=sys.stderr)
        log_event(src="hook", agent=AGENT, trace=os.environ.get("BUSYBAR_TRACE"), error=f"exit {proc.returncode}: {proc.stderr.strip()[:300]}".rstrip(": "))
    return proc.stdout


def tool_summary(tool_name: str, tool_input) -> str:
    """Tool name and its main argument, short enough for the strip."""
    if not isinstance(tool_input, dict):
        tool_input = {}
    for key in ("command", "description", "file_path", "path", "url", "query"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return f"{tool_name}: {value.strip()}"[:40]
    return tool_name or "tool"


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


def hand_is_up(session: str) -> bool:
    """Cheap check, so PostToolUse only spawns the CLI when it matters."""
    try:
        hands = json.loads(state_path().read_text()).get("hands", [])
    except (OSError, ValueError, AttributeError):
        return False
    return any(h.get("agent") == AGENT and h.get("session") == session for h in hands)


LOG_NAME = "events.jsonl"
LOG_MAX_BYTES = 2_000_000


def log_event(**fields) -> None:
    """One JSON line in events.jsonl beside the hands file, the shape busybar_agents.log reads. Never raises."""
    path = state_path().with_name(LOG_NAME)
    entry = {"t": round(time.time(), 3), **{key: value for key, value in fields.items() if value is not None}}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass


def parents(limit: int = 5) -> list:
    """The commands of this process's ancestors, nearest first; the agent that fired the hook is among them."""
    try:
        table = subprocess.run(["ps", "axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = {}
    for line in table.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), parts[2].strip())
    chain, pid = [], os.getppid()
    while pid > 1 and pid in rows and len(chain) < limit:
        pid, command = rows[pid]
        chain.append(command[:120])
    return chain


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

    trace = os.urandom(3).hex()  # shared by this hook's log lines and the CLI's
    os.environ["BUSYBAR_TRACE"] = trace
    identity = {"src": "hook", "trace": trace, "agent": AGENT, "event": name, "session": session, "project": project,
                "cwd": event.get("cwd"), "pid": os.getpid(), "term": os.environ.get("TERM_PROGRAM")}
    lineage: dict = {}

    def note(**fields) -> None:
        """One log line: who fired this event and what the hook made of it."""
        if "parents" not in lineage:
            lineage["parents"] = parents()
        log_event(**identity, parents=lineage["parents"], **fields)

    cmd = cli_command()
    if cmd is None:
        note(error="CLI not found; install it or set BUSYBAR_AGENTS_BIN")
        print("busybar-agents: CLI not found; install it or set BUSYBAR_AGENTS_BIN", file=sys.stderr)
        return 0

    if name == "SessionStart":
        source = event.get("source", "startup")
        if source in ("startup", "resume"):
            note(verb="hello", source=source)
            run(cmd + ["hello", *common], timeout=15)
        else:
            note(skip="only startup and resume say hello", source=source)
    elif name == "PermissionRequest":
        tool = event.get("tool_name", "")
        detail = tool_summary(tool, event.get("tool_input") or {})
        if not flag("BUSYBAR_ASK"):
            note(verb="raise", tool=tool, detail=detail)
            run(cmd + ["raise", *common, "--reason", "permission?"], timeout=15)
            return 0
        note(verb="ask", tool=tool, detail=detail)
        answer = run(cmd + ["ask", *common, "--question", "ALLOW?", "--detail", detail], timeout=35).strip()
        if answer in ("allow", "deny"):
            note(decision=answer)
            decision = {"behavior": answer}
            if answer == "deny":
                decision["message"] = "Denied from the BUSY Bar."
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))
        else:
            note(verb="raise", tool=tool, result=answer or None)
            run(cmd + ["raise", *common, "--reason", "permission?"], timeout=15)
    elif name in ("UserPromptSubmit", "Interrupt", "SessionEnd"):
        note(verb="lower")
        run(cmd + ["lower", *common], timeout=15)
    elif name == "PostToolUse":
        if hand_is_up(session):
            note(verb="lower")
            run(cmd + ["lower", *common], timeout=15)
    elif name == "Stop":
        if flag("BUSYBAR_GO") and not event.get("stop_hook_active") and ends_with_question(event.get("last_assistant_message") or ""):
            seconds = os.environ.get("BUSYBAR_GO_SECONDS", "8")
            note(verb="ask", detail="GO?")
            answer = run(cmd + ["ask", *common, "--question", "GO?", "--detail", "wheel = yes", "--timeout", seconds], timeout=40).strip()
            if answer == "allow":
                note(decision="go ahead")
                print(json.dumps({"decision": "block", "reason": "Yes, go ahead with what you proposed. (answered from the BUSY Bar)"}))
                return 0
        note(verb="done")
        run(cmd + ["done", *common], timeout=15)
    return 0


if __name__ == "__main__":
    sys.exit(main())
