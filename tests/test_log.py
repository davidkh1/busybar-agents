import json
import os
from pathlib import Path

from busybar_agents import log as eventlog
from busybar_agents.cli import main


def test_record_read_and_cursor(tmp_path):
    path = tmp_path / "events.jsonl"
    cursor = eventlog.Cursor(path)
    assert cursor.poll() == []  # nothing yet, and the cursor now sits at the end
    eventlog.record(path, src="cli", verb="hello", skipped=None)
    eventlog.record(path, src="hook", verb="raise")
    assert [e["verb"] for e in eventlog.read(path, 10)] == ["hello", "raise"]
    assert "skipped" not in eventlog.read(path, 10)[0]  # None fields are left out
    assert [e["src"] for e in cursor.poll()] == ["cli", "hook"]
    assert cursor.poll() == []
    assert [e["verb"] for e in eventlog.read(path, 1)] == ["raise"]


def test_a_partial_line_waits_for_its_newline(tmp_path):
    path = tmp_path / "events.jsonl"
    cursor = eventlog.Cursor(path)
    cursor.poll()
    with open(path, "a") as handle:
        handle.write('{"t": 1, "src": "cli", "verb": "lower"}\n{"t": 2, "src": "cli", "ver')
    assert [e["verb"] for e in cursor.poll()] == ["lower"]
    with open(path, "a") as handle:
        handle.write('b": "done"}\n')
    assert [e["verb"] for e in cursor.poll()] == ["done"]


def test_rotation_keeps_one_old_file_and_reading_spans_both(tmp_path, monkeypatch):
    monkeypatch.setattr(eventlog, "MAX_BYTES", 300)
    path = tmp_path / "events.jsonl"
    cursor = eventlog.Cursor(path)
    cursor.poll()
    for n in range(40):
        eventlog.record(path, src="cli", n=n)
    assert (tmp_path / "events.jsonl.1").exists()
    current = len(path.read_text().splitlines())
    numbers = [e["n"] for e in eventlog.read(path, 25)]
    assert numbers == list(range(numbers[0], 40)) and len(numbers) > current  # a contiguous tail, across the rotation
    assert [e["n"] for e in eventlog.read(path, 1000)][-1] == 39
    seen = [e["n"] for e in cursor.poll()]
    assert seen and seen[-1] == 39  # a follower lands in the new file after a rotation


def test_cli_logs_each_verb(monkeypatch, capsys):
    monkeypatch.setenv("BUSYBAR_DRY_RUN", "1")
    monkeypatch.setenv("BUSYBAR_TRACE", "abc123")
    assert main(["hello", "--agent", "claude", "--project", "api"]) == 0
    path = Path(os.environ["BUSYBAR_STATE"]).with_name("events.jsonl")
    (event,) = eventlog.read(path, 10)
    assert event["src"] == "cli" and event["verb"] == "hello" and event["trace"] == "abc123"
    assert event["shown"] == ["READY", "api"] and event["bar"] == ["draw:dry-run"]
    assert event["payload"]["application_name"] == "busybar-agents" and "ms" in event
    capsys.readouterr()
    assert main(["log", "-n", "5"]) == 0
    out = capsys.readouterr().out
    assert "hello" in out and "READY | api" in out and "[abc123]" in out
    assert main(["log", "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verb"] == "hello"


def test_ask_logs_the_question_and_the_answer(monkeypatch, capsys):
    monkeypatch.setenv("BUSYBAR_DRY_RUN", "1")
    assert main(["ask", "--agent", "claude", "--question", "ALLOW?", "--detail", "Bash: npm test", "--timeout", "1"]) == 0
    (event,) = eventlog.read(Path(os.environ["BUSYBAR_STATE"]).with_name("events.jsonl"), 10)
    assert event["shown"] == ["ALLOW?", "Bash: npm test"] and event["result"] == "timeout"
    assert event["bar"] == ["draw:dry-run", "clear:dry-run"] and event["question"] == "ALLOW?" and event["timeout"] == 1


def test_a_failure_is_logged_too(monkeypatch, capsys):
    monkeypatch.setenv("BUSYBAR_ADDR", "127.0.0.1:9")  # nothing listens there
    assert main(["hello", "--agent", "claude", "--project", "api"]) == 1
    path = Path(os.environ["BUSYBAR_STATE"]).with_name("events.jsonl")
    (event,) = eventlog.read(path, 10)
    assert event["verb"] == "hello" and event["error"] and event["addr"] == "127.0.0.1:9"
    assert event["bar"] == ["draw:error"] and event["shown"] == ["READY", "api"]  # what it tried to draw


def test_format_event_names_the_agent_process():
    line = eventlog.format_event({"t": 0, "src": "hook", "agent": "claude", "session": "abcd1234", "event": "SessionStart", "source": "startup",
                                  "verb": "hello", "project": "api", "parents": ["/bin/sh -c python3 hook.py", "claude --resume", "-zsh"], "trace": "0a0b0c"})
    assert "hook   claude abcd1234" in line and "SessionStart startup  -> hello  api  from claude --resume  [0a0b0c]" in line
    assert eventlog.agent_process(["python3.12 x.py", "/usr/bin/node cli.js"]) == "/usr/bin/node cli.js"
    cli = eventlog.format_event({"t": 0, "src": "cli", "agent": "claude", "session": "abcd1234", "verb": "raise", "shown": ["CLAUDE", "permission? - api"], "bar": ["draw:drawn", "play:reminder"], "ms": 212})
    assert cli.endswith("raise  CLAUDE | permission? - api  draw:drawn, play:reminder  212 ms")
    assert "ERROR ConnectError: boom" in eventlog.format_event({"t": 0, "src": "cli", "verb": "raise", "error": "ConnectError: boom"})
