"""The Claude Code adapter is standard-library only; load it from its file."""

import importlib.util
import io
import json
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "adapters" / "claude-code" / "hook.py"
spec = importlib.util.spec_from_file_location("hook", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def event(tmp_path, **extra):
    transcript = tmp_path / "abc.jsonl"
    transcript.write_text("")
    return {"session_id": "abc", "transcript_path": str(transcript), "cwd": str(tmp_path / "my-repo"), **extra}


def test_named_session_wins(tmp_path):
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "custom-title.json").write_text(json.dumps({"customTitle": "busybar"}))
    assert hook.session_label(event(tmp_path)) == "busybar"


def test_unnamed_session_falls_back_to_the_folder(tmp_path):
    assert hook.session_label(event(tmp_path)) == "my-repo"


def test_broken_sidecar_falls_back_to_the_folder(tmp_path):
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "custom-title.json").write_text("{not json")
    assert hook.session_label(event(tmp_path)) == "my-repo"


def test_session_color_is_the_last_one_chosen(tmp_path):
    ev = event(tmp_path)
    assert hook.session_color(ev) is None
    Path(ev["transcript_path"]).write_text(
        json.dumps({"type": "agent-color", "agentColor": "orange", "sessionId": "abc"}) + "\n"
        + json.dumps({"type": "user", "message": "agent-color pink is just text"}) + "\n"
        + "{not json agent-color\n"
        + json.dumps({"type": "agent-color", "agentColor": "pink", "sessionId": "abc"}) + "\n"
    )
    assert hook.session_color(ev) == "pink"
    assert hook.session_color({"transcript_path": str(tmp_path / "missing.jsonl")}) is None
    assert hook.session_color({}) is None


def test_tool_summary_is_short():
    assert hook.tool_summary("Bash", {"command": "npm test"}) == "Bash: npm test"
    assert len(hook.tool_summary("Bash", {"command": "x" * 200})) <= 40
    assert hook.tool_summary("Edit", {}) == "Edit"


def drive(monkeypatch, capsys, event_dict, answers, env=None):
    """Run hook.main() with a fake CLI that answers from a list, and return stdout JSON."""
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        return answers.pop(0) if answers else ""

    monkeypatch.setattr(hook, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(hook, "run", fake_run)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event_dict)))
    assert hook.main() == 0
    out = capsys.readouterr().out.strip()
    return (json.loads(out) if out else None), calls


QUESTION = {"question": "Which framework?", "header": "Framework", "options": [{"label": "React"}, {"label": "Vue"}], "multiSelect": False}


def test_question_answered_from_the_bar(monkeypatch, capsys, tmp_path):
    ev = event(tmp_path, hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": [QUESTION]})
    out, calls = drive(monkeypatch, capsys, ev, ["Vue\n"], {"BUSYBAR_ASK": "1"})
    assert calls[0][1] == "choose" and "--option" in calls[0]
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert out["hookSpecificOutput"]["updatedInput"]["answers"] == {"Which framework?": "Vue"}
    assert out["hookSpecificOutput"]["updatedInput"]["questions"] == [QUESTION]


def test_question_left_to_the_terminal_on_timeout_or_when_off(monkeypatch, capsys, tmp_path):
    ev = event(tmp_path, hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": [QUESTION]})
    assert drive(monkeypatch, capsys, ev, ["timeout\n"], {"BUSYBAR_ASK": "1"})[0] is None
    monkeypatch.delenv("BUSYBAR_ASK", raising=False)
    assert drive(monkeypatch, capsys, ev, ["Vue\n"])[0] is None


def test_go_ahead_from_the_bar_continues_the_turn(monkeypatch, capsys, tmp_path):
    ev = event(tmp_path, hook_event_name="Stop", stop_hook_active=False, last_assistant_message="Done. Shall I also update the docs?")
    out, calls = drive(monkeypatch, capsys, ev, ["allow\n"], {"BUSYBAR_GO": "1"})
    assert calls[0][1] == "ask" and out["decision"] == "block"
    out, calls = drive(monkeypatch, capsys, ev, ["timeout\n"], {"BUSYBAR_GO": "1"})
    assert out is None and calls[-1][1] == "done"


def test_no_go_prompt_without_a_question_or_when_already_continuing(monkeypatch, capsys, tmp_path):
    ev = event(tmp_path, hook_event_name="Stop", stop_hook_active=False, last_assistant_message="All done.")
    assert drive(monkeypatch, capsys, ev, [], {"BUSYBAR_GO": "1"})[1][0][1] == "done"
    ev = event(tmp_path, hook_event_name="Stop", stop_hook_active=True, last_assistant_message="More?")
    assert drive(monkeypatch, capsys, ev, [], {"BUSYBAR_GO": "1"})[1][0][1] == "done"


def test_auto_mode_denial_raises_a_hand(monkeypatch, capsys, tmp_path):
    ev = event(tmp_path, hook_event_name="PermissionDenied", tool_name="Bash", tool_input={"command": "rm -rf build"}, reason="[Irreversible Local Destruction]")
    out, calls = drive(monkeypatch, capsys, ev, [])
    assert out is None and calls[0][1] == "raise" and "blocked" in calls[0]


def test_color_rides_along_on_every_verb(monkeypatch, capsys, tmp_path):
    ev = event(tmp_path, hook_event_name="Notification", notification_type="idle_prompt")
    Path(ev["transcript_path"]).write_text(json.dumps({"type": "agent-color", "agentColor": "pink"}) + "\n")
    _, calls = drive(monkeypatch, capsys, ev, [])
    assert calls[0][1] == "raise" and calls[0][calls[0].index("--color") + 1] == "pink"
    _, calls = drive(monkeypatch, capsys, event(tmp_path, hook_event_name="Notification", notification_type="idle_prompt"), [])
    assert "--color" not in calls[0]


def test_wheel_file_switches_the_flags_unless_a_variable_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSYBAR_STATE", str(tmp_path / "hands.json"))
    for name in ("BUSYBAR_ASK", "BUSYBAR_GO"):
        monkeypatch.delenv(name, raising=False)
    assert not hook.flag("BUSYBAR_ASK") and not hook.flag("BUSYBAR_GO")
    (tmp_path / "wheel.json").write_text(json.dumps({"ask": True, "go": True}))
    assert hook.flag("BUSYBAR_ASK") and hook.flag("BUSYBAR_GO")
    monkeypatch.setenv("BUSYBAR_GO", "0")
    assert hook.flag("BUSYBAR_ASK") and not hook.flag("BUSYBAR_GO")
    (tmp_path / "wheel.json").write_text("{broken")
    assert not hook.flag("BUSYBAR_ASK")
    assert not hook.flag("BUSYBAR_OTHER")


def test_wheel_command_runs_the_verb_through_the_cli(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(hook, "cli_command", lambda: ["fake-cli"])
    monkeypatch.setattr(hook, "run", lambda cmd, timeout: calls.append(cmd) or "wheel on: ALLOW?, choices and GO? come to the bar\n")
    monkeypatch.setattr(hook.sys, "argv", ["hook.py", "wheel", "on"])
    assert hook.main() == 0
    assert calls == [["fake-cli", "wheel", "on"]]
    assert capsys.readouterr().out.strip() == "wheel on: ALLOW?, choices and GO? come to the bar"
