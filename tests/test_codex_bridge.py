"""The Codex adapter is standard-library only; load it from its files."""

import importlib.util
import io
import json
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1] / "adapters" / "codex"


def load(name):
    spec = importlib.util.spec_from_file_location(f"codex_{name}", ADAPTER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load("hook")
install = load("install")


def drive(monkeypatch, capsys, event, answers, env=None):
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(hook, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(hook, "run", fake_run)
    for key in ("BUSYBAR_ASK", "BUSYBAR_GO"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "thr_12345678", "cwd": "/w/api", **event})))
    assert hook.main() == 0
    out = capsys.readouterr().out.strip()
    return (json.loads(out) if out else None), calls


def test_session_start_and_prompt(monkeypatch, capsys):
    assert drive(monkeypatch, capsys, {"hook_event_name": "SessionStart", "source": "startup"}, [])[1][0][1] == "hello"
    assert drive(monkeypatch, capsys, {"hook_event_name": "SessionStart", "source": "compact"}, [])[1] == []
    assert drive(monkeypatch, capsys, {"hook_event_name": "UserPromptSubmit", "prompt": "hi"}, [])[1][0][1] == "lower"


def test_permission_raises_a_hand_or_decides(monkeypatch, capsys):
    ev = {"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "npm test"}}
    out, calls = drive(monkeypatch, capsys, ev, [])
    assert out is None and calls[0][1] == "raise" and "permission?" in calls[0]
    out, calls = drive(monkeypatch, capsys, ev, ["allow\n"], {"BUSYBAR_ASK": "1"})
    assert calls[0][1] == "ask" and "Bash: npm test" in calls[0]
    assert out["hookSpecificOutput"]["decision"] == {"behavior": "allow"}
    out, calls = drive(monkeypatch, capsys, ev, ["timeout\n"], {"BUSYBAR_ASK": "1"})
    assert out is None and calls[-1][1] == "raise"


def test_post_tool_use_lowers_only_a_raised_hand(monkeypatch, capsys, tmp_path):
    state = tmp_path / "hands.json"
    monkeypatch.setenv("BUSYBAR_STATE", str(state))
    ev = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": "ok"}
    assert drive(monkeypatch, capsys, ev, [])[1] == []
    state.write_text(json.dumps({"hands": [{"agent": "codex", "session": "thr_1234", "project": "api", "reason": "permission?", "since": 1.0}]}))
    assert drive(monkeypatch, capsys, ev, [])[1][0][1] == "lower"


def test_stop_done_or_go_ahead(monkeypatch, capsys):
    ev = {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "Shall I continue?"}
    assert drive(monkeypatch, capsys, ev, [])[1][0][1] == "done"
    out, calls = drive(monkeypatch, capsys, ev, ["allow\n"], {"BUSYBAR_GO": "1"})
    assert calls[0][1] == "ask" and out["decision"] == "block"
    ev["stop_hook_active"] = True
    assert drive(monkeypatch, capsys, ev, [], {"BUSYBAR_GO": "1"})[1][0][1] == "done"


def test_installer_merges_and_removes(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 mine.py"}]}]}}))
    monkeypatch.setattr("sys.argv", ["install.py"])
    assert install.main() == 0
    data = json.loads(path.read_text())
    assert [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]] == ["python3 mine.py", install.COMMAND]
    assert "async" not in json.dumps(data)  # this Codex skips background hooks
    assert install.main() == 0  # idempotent
    assert len(json.loads(path.read_text())["hooks"]["Stop"]) == 2
    monkeypatch.setattr("sys.argv", ["install.py", "--uninstall"])
    assert install.main() == 0
    assert json.loads(path.read_text())["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "python3 mine.py"}]}]}


def test_wheel_file_switches_the_codex_flags_too(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSYBAR_STATE", str(tmp_path / "hands.json"))
    for name in ("BUSYBAR_ASK", "BUSYBAR_GO"):
        monkeypatch.delenv(name, raising=False)
    assert not hook.flag("BUSYBAR_ASK")
    (tmp_path / "wheel.json").write_text(json.dumps({"ask": True, "go": False}))
    assert hook.flag("BUSYBAR_ASK") and not hook.flag("BUSYBAR_GO")
