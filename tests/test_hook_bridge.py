"""The Claude Code adapter is standard-library only; load it from its file."""

import importlib.util
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


def test_tool_summary_is_short():
    assert hook.tool_summary("Bash", {"command": "npm test"}) == "Bash: npm test"
    assert len(hook.tool_summary("Bash", {"command": "x" * 200})) <= 40
    assert hook.tool_summary("Edit", {}) == "Edit"
