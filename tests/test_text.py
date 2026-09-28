from busybar_agents.text import sanitize


def test_strips_non_ascii_and_control_characters():
    assert sanitize("Claude’s turn — done \U0001f44b\n") == "Claudes turn done"


def test_collapses_whitespace_and_truncates():
    assert sanitize("  needs   \t permission  ") == "needs permission"
    assert sanitize("x" * 100, limit=10) == "x" * 10


def test_empty_stays_empty():
    assert sanitize("\U0001f44b") == ""
