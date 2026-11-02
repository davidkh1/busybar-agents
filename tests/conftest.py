"""Every test gets its own state directory, so hands, the wheel switch and the event log stay out of the real one."""

import pytest


@pytest.fixture(autouse=True)
def _own_state(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSYBAR_STATE", str(tmp_path / "state" / "hands.json"))
    monkeypatch.delenv("BUSYBAR_TRACE", raising=False)
