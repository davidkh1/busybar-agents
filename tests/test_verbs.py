import asyncio

from busybar_agents.bar import texts
from busybar_agents.cli import build_parser, perform
from busybar_agents.config import Config
from busybar_agents.state import HandsFile


class FakeBar:
    """Records what the CLI would have done to the bar."""

    def __init__(self):
        self.calls = []

    async def draw(self, payload):
        self.calls.append(("draw", texts(payload)))

    async def clear(self):
        self.calls.append(("clear",))

    async def play(self, sound):
        self.calls.append(("play", sound))

    async def ask(self, agent, question, detail, timeout):
        self.calls.append(("ask", agent, question, detail, timeout))
        return "allow"


def run(hands_file, bar, *argv, cfg=None):
    args = build_parser().parse_args(list(argv))
    return asyncio.run(perform(args, cfg or Config(), hands_file, bar))


def test_raise_then_lower_clears(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "raise", "--agent", "claude", "--session", "a", "--project", "api", "--reason", "permission?")
    run(hands, bar, "lower", "--agent", "claude", "--session", "a")
    assert bar.calls == [("draw", ["CLAUDE", "permission?"]), ("clear",)]


def test_done_then_session_end_keeps_the_done_message(tmp_path):
    """Stop draws DONE, then SessionEnd lowers a hand that is not up: DONE must survive."""
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "done", "--agent", "claude", "--session", "a", "--project", "api")
    run(hands, bar, "lower", "--agent", "claude", "--session", "a")
    assert bar.calls == [("draw", ["DONE", "api"])]


def test_lowering_one_of_two_hands_redraws_the_other(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "raise", "--agent", "claude", "--session", "a", "--project", "api", "--reason", "idle")
    run(hands, bar, "raise", "--agent", "codex", "--session", "b", "--project", "web", "--reason", "idle")
    run(hands, bar, "lower", "--agent", "codex", "--session", "b")
    assert bar.calls[-1] == ("draw", ["CLAUDE", "idle"])


def test_ask_prints_the_answer_and_restores_the_strip(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    assert run(hands, bar, "ask", "--question", "ALLOW?", "--detail", "Bash: npm test", "--timeout", "7") == "allow"
    assert bar.calls == [("ask", "agent", "ALLOW?", "Bash: npm test", 7), ("clear",)]


def test_hello_is_a_blip_that_changes_no_state(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "hello", "--agent", "claude", "--project", "api")
    assert bar.calls == [("draw", ["CLAUDE", "ready"])]
    assert hands.load() == []


def test_hello_can_be_switched_off(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "hello", "--agent", "claude", cfg=Config(hello_seconds=0))
    assert bar.calls == []


def test_done_keeps_the_board_when_another_session_is_waiting(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "raise", "--agent", "claude", "--session", "a", "--project", "api", "--reason", "permission?")
    run(hands, bar, "raise", "--agent", "claude", "--session", "b", "--project", "web", "--reason", "your turn")
    run(hands, bar, "done", "--agent", "claude", "--session", "a", "--project", "api")
    assert bar.calls[-1] == ("draw", ["CLAUDE", "your turn"])
    assert [h.session for h in hands.load()] == ["b"]
