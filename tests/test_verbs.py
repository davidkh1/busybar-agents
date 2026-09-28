import asyncio

from busybar_agents.cli import build_parser, perform
from busybar_agents.config import Config
from busybar_agents.state import HandsFile


class FakeBar:
    """Records what the CLI would have done to the bar."""

    def __init__(self):
        self.calls = []

    async def draw(self, payload):
        self.calls.append(("draw", [e.text for e in payload.elements if getattr(e, "text", None)]))

    async def clear(self):
        self.calls.append(("clear",))

    async def play(self, sound):
        self.calls.append(("play", sound))

    async def ask(self, question, detail, timeout):
        self.calls.append(("ask", question, detail, timeout))
        return "allow"


def run(hands_file, bar, *argv):
    args = build_parser().parse_args(list(argv))
    return asyncio.run(perform(args, Config(), hands_file, bar))


def test_raise_then_lower_clears(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "raise", "--agent", "claude", "--session", "a", "--project", "api", "--reason", "needs permission")
    run(hands, bar, "lower", "--agent", "claude", "--session", "a")
    assert bar.calls == [("draw", ["CLAUDE", "needs permission - api"]), ("clear",)]


def test_done_then_session_end_keeps_the_done_message(tmp_path):
    """Stop draws DONE, then SessionEnd lowers a hand that is not up: DONE must survive."""
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "done", "--agent", "claude", "--session", "a", "--project", "api")
    run(hands, bar, "lower", "--agent", "claude", "--session", "a")
    assert bar.calls == [("draw", ["DONE", "claude: api"])]


def test_lowering_one_of_two_hands_redraws_the_other(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    run(hands, bar, "raise", "--agent", "claude", "--session", "a", "--project", "api", "--reason", "idle")
    run(hands, bar, "raise", "--agent", "codex", "--session", "b", "--project", "web", "--reason", "idle")
    run(hands, bar, "lower", "--agent", "codex", "--session", "b")
    assert bar.calls[-1] == ("draw", ["CLAUDE", "idle - api"])


def test_ask_prints_the_answer_and_restores_the_strip(tmp_path):
    bar, hands = FakeBar(), HandsFile(tmp_path / "h.json")
    assert run(hands, bar, "ask", "--question", "ALLOW?", "--detail", "Bash: npm test", "--timeout", "7") == "allow"
    assert bar.calls == [("ask", "ALLOW?", "Bash: npm test", 7), ("clear",)]
