import time

from busybar_agents.bar import ask_payload, done_payload, hands_payload
from busybar_agents.config import APP_NAME, Config
from busybar_agents.state import Hand


def hand(agent="claude", project="busybar-agents", reason="needs permission", since=None):
    return Hand(agent=agent, session="s1", project=project, reason=reason, since=since or time.time())


def texts(payload):
    return [e.text for e in payload.elements if getattr(e, "text", None)]


def test_single_hand_names_the_agent_and_project():
    payload = hands_payload([hand()], Config(ttl=600, priority=77))
    assert payload.application_name == APP_NAME
    assert payload.priority == 77
    assert payload.led_notification_color is not None
    assert texts(payload) == ["CLAUDE", "needs permission - busybar-agents"]
    assert all(e.timeout == 600 for e in payload.elements)


def test_many_hands_are_counted():
    hands = [hand(agent="claude", project="api", since=1.0), hand(agent="codex", project="web", since=2.0)]
    assert texts(hands_payload(hands, Config())) == ["2 AGENTS", "api, web"]


def test_text_is_ascii_safe():
    payload = hands_payload([hand(project="café \U0001f44b", reason="wait…")], Config())
    for text in texts(payload):
        assert text.isascii() and text.isprintable()


def test_done_and_ask_expire_on_their_own():
    cfg = Config(done_seconds=6, ask_timeout=15)
    assert all(e.timeout == 6 for e in done_payload(hand(), "DONE", cfg).elements)
    assert all(e.timeout == 15 for e in ask_payload("ALLOW?", "Bash: npm test", 15, cfg).elements)


def test_long_lines_scroll_after_a_pause_and_short_lines_do_not():
    long = hands_payload([hand(project="a-rather-long-project-name", reason="needs permission")], Config())
    scrolling = [e for e in long.elements if getattr(e, "scroll_rate", None)]
    assert scrolling and all(e.scroll_start_delay == 1500 and e.scroll_repeat_delay == 1200 for e in scrolling)
    title = next(e for e in long.elements if getattr(e, "text", None) == "CLAUDE")
    assert not title.scroll_rate  # the agent name is short and stays put
