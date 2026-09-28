import time

from busybar_agents.bar import CLAUDE_ORANGE, CLAWD, PROMPT_GLYPH, ask_payload, choice_payload, done_payload, hands_payload, hello_payload, texts
from busybar_agents.config import APP_NAME, Config
from busybar_agents.state import Hand


def hand(agent="claude", project="api", reason="permission?", since=None):
    return Hand(agent=agent, session="s1", project=project, reason=reason, since=since or time.time())


def test_single_hand_is_the_agent_and_the_reason():
    payload = hands_payload([hand()], Config(ttl=600, priority=77))
    assert payload["application_name"] == APP_NAME
    assert payload["priority"] == 77
    assert payload["led_notification_color"] == CLAUDE_ORANGE
    assert texts(payload) == ["CLAUDE", "permission? - api"]
    assert all(e["timeout"] == 600 for e in payload["elements"])


def test_claude_gets_clawd_and_others_get_a_prompt_glyph():
    clawd = hands_payload([hand()], Config())["elements"][0]
    assert clawd["type"] == "xpmbitmap" and clawd["data"].startswith("! XPM2\n16 10 3 1")
    assert "#D97757" in clawd["data"] and "#FFFFFF" in clawd["data"]
    glyph = hands_payload([hand(agent="codex")], Config())["elements"][0]
    assert glyph["type"] == "xpmbitmap" and "#FFFFFF" in glyph["data"] and "#D97757" not in glyph["data"]


def test_every_bitmap_is_well_formed():
    for rows in (*CLAWD.values(), PROMPT_GLYPH):
        assert len(rows) == 10 and all(len(row) == 16 for row in rows)
        assert set("".join(rows)) <= {".", "o", "w"}


def test_moods_follow_the_moment():
    up = hands_payload([hand()], Config())["elements"][0]["data"]
    done = done_payload(hand(), "DONE", Config())["elements"][0]["data"]
    ready = hello_payload("claude", "api", Config())["elements"][0]["data"]
    assert len({up, done, ready}) == 3


def test_many_hands_are_counted():
    hands = [hand(agent="claude", project="api", since=1.0), hand(agent="codex", project="web", since=2.0)]
    assert texts(hands_payload(hands, Config())) == ["2 AGENTS", "api, web"]


def test_text_is_ascii_safe():
    payload = hands_payload([hand(project="caf\u00e9 \U0001f44b", reason="wait\u2026")], Config())
    for text in texts(payload):
        assert text.isascii() and text.isprintable()


def test_done_hello_and_ask_expire_on_their_own():
    cfg = Config(done_seconds=6, hello_seconds=3, ask_timeout=15)
    assert all(e["timeout"] == 6 for e in done_payload(hand(), "DONE", cfg)["elements"])
    assert all(e["timeout"] == 3 for e in hello_payload("claude", "api", cfg)["elements"])
    assert all(e["timeout"] == 15 for e in ask_payload("claude", "ALLOW?", "Bash: npm test", 15, cfg)["elements"])
    assert texts(hello_payload("claude", "api", cfg)) == ["CLAUDE", "ready"]


def test_long_lines_scroll_after_a_pause_and_short_lines_do_not():
    long = hands_payload([hand(reason="a rather long reason")], Config())
    scrolling = [e for e in long["elements"] if e.get("scroll_rate")]
    assert scrolling and all(e["scroll_start_delay"] == 1500 and e["scroll_repeat_delay"] == 1200 for e in scrolling)
    short = done_payload(hand(project="api"), "DONE", Config())
    assert not any(e.get("scroll_rate") for e in short["elements"])


def test_a_long_bold_headline_scrolls_too():
    payload = done_payload(hand(), "FINISHED!", Config())
    headline = next(e for e in payload["elements"] if e.get("font") == "bold")
    assert headline["scroll_rate"]


def test_choice_shows_one_option_with_its_position():
    payload = choice_payload("claude", "Framework", ["React", "Vue", "Svelte"], 1, 30, Config())
    assert texts(payload) == ["Vue", "2/3 Framework"]
    assert all(e["timeout"] == 30 for e in payload["elements"])
