import time

from busybar_agents.state import Hand, HandsFile


def hand(agent="claude", session="abc12345", since=None):
    return Hand(agent=agent, session=session, project="demo", reason="needs permission", since=since or time.time())


def test_raise_lower_roundtrip(tmp_path):
    hands = HandsFile(tmp_path / "hands.json")
    assert hands.load() == []
    assert [h.key for h in hands.raise_hand(hand())] == ["claude:abc12345"]
    assert [h.key for h in hands.raise_hand(hand(agent="codex"))] == ["claude:abc12345", "codex:abc12345"]
    assert [h.key for h in hands.lower("claude", "abc12345")] == ["codex:abc12345"]
    assert hands.lower("nobody", "x") == [h for h in hands.load()]


def test_raise_replaces_same_session(tmp_path):
    hands = HandsFile(tmp_path / "hands.json")
    hands.raise_hand(hand(since=100.0))
    again = hands.raise_hand(hand(since=200.0))
    assert len(again) == 1 and again[0].since == 200.0


def test_prune_drops_stale_hands(tmp_path):
    hands = HandsFile(tmp_path / "hands.json")
    hands.raise_hand(hand(session="old", since=time.time() - 10_000))
    hands.raise_hand(hand(session="new"))
    assert [h.session for h in hands.prune(ttl=3600)] == ["new"]


def test_corrupt_file_is_treated_as_empty(tmp_path):
    path = tmp_path / "hands.json"
    path.write_text("{not json")
    assert HandsFile(path).load() == []
