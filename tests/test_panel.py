"""The panel server without a bar: dry-run verbs, state, the log and the stream."""

import json
import threading
import urllib.error
import urllib.request

from busybar_agents.config import Config
from busybar_agents.panel import PanelServer, argv_for


def start(monkeypatch):
    monkeypatch.setenv("BUSYBAR_DRY_RUN", "1")
    monkeypatch.setenv("BUSYBAR_ADDR", "127.0.0.1:9")  # nothing listens there
    server = PanelServer(("127.0.0.1", 0), Config.from_env())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read()


def post(url, body, headers=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def test_argv_follows_the_cli():
    assert argv_for({"verb": "raise", "agent": "claude", "session": "p1", "project": "api", "reason": "test", "question": "ignored"}) == ["raise", "--agent", "claude", "--session", "p1", "--project", "api", "--reason", "test"]
    assert argv_for({"verb": "choose", "title": "Framework", "options": ["React", " Vue ", ""], "timeout": 7}) == ["choose", "--title", "Framework", "--option", "React", "--option", "Vue", "--timeout", "7"]
    assert argv_for({"verb": "wheel", "state": "on"}) == ["wheel", "on"]
    assert argv_for({"verb": "clear", "agent": "claude"}) == ["clear"]


def test_state_actions_and_log(monkeypatch):
    server, base = start(monkeypatch)
    try:
        status, page = get(base + "/")
        assert status == 200 and b"<title>BUSY Bar panel</title>" in page
        state = json.loads(get(base + "/api/state")[1])
        assert state["hands"] == [] and state["config"]["dry_run"] is True and state["bar"]["reachable"] is False
        status, out = post(base + "/api/do", {"verb": "raise", "agent": "claude", "session": "p1", "project": "api", "reason": "test"})
        assert status == 200 and out["ok"] and out["result"] is None
        assert [h["session"] for h in json.loads(get(base + "/api/state")[1])["hands"]] == ["p1"]
        events = json.loads(get(base + "/api/log?n=5")[1])
        assert events[-1]["src"] == "panel" and events[-1]["verb"] == "raise" and events[-1]["shown"] == ["CLAUDE", "test - api"]
        assert post(base + "/api/do", {"verb": "lower", "agent": "claude", "session": "p1"})[0] == 200
        assert json.loads(get(base + "/api/state")[1])["hands"] == []
        status, out = post(base + "/api/input", {"key": "up"})
        assert status == 200 and out["bar"] == ["input:up:dry-run"]
        assert post(base + "/api/do", {"verb": "rm -rf"})[0] == 400
        assert post(base + "/api/do", {"verb": "ask", "timeout": "x"})[0] == 400
        assert post(base + "/api/input", {"key": "busy"})[0] == 400
        assert post(base + "/api/do", {"verb": "hello"}, {"Origin": "http://evil.example"})[0] == 403
        assert post(base + "/api/do", {"verb": "hello"}, {"Origin": base})[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_stream_starts_with_history_then_state(monkeypatch):
    server, base = start(monkeypatch)
    try:
        post(base + "/api/do", {"verb": "hello", "agent": "claude", "project": "api"})
        with urllib.request.urlopen(base + "/api/stream?n=10", timeout=10) as response:
            assert response.headers["Content-Type"] == "text/event-stream"
            seen = []
            for _ in range(60):
                line = response.readline().decode()
                if line.startswith("event: "):
                    seen.append(line.split()[1])
                if line.startswith("data: ") and seen[-1] == "history":
                    assert json.loads(line[6:])[-1]["verb"] == "hello"
                if "state" in seen:
                    break
        assert seen[:2] == ["history", "state"]
    finally:
        server.shutdown()
        server.server_close()
