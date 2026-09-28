#!/usr/bin/env python3
"""Add the BUSY Bar hooks to ~/.codex/hooks.json, or remove them.

    python3 adapters/codex/install.py              # merge ours in
    python3 adapters/codex/install.py --uninstall  # take ours out
    python3 adapters/codex/install.py --print      # show the JSON only

Other hooks in the file are kept. Afterwards, trust the hooks in /hooks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "hook.py"
COMMAND = f'python3 "{HOOK}"'


def our_hooks() -> dict:
    def handler(**extra):
        return {"type": "command", "command": COMMAND, **extra}

    # All foreground: this Codex skips hooks marked async.
    return {
        "SessionStart": [{"matcher": "startup|resume", "hooks": [handler(timeout=20)]}],
        "UserPromptSubmit": [{"hooks": [handler(timeout=20)]}],
        "PermissionRequest": [{"hooks": [handler(timeout=40)]}],
        "PostToolUse": [{"hooks": [handler(timeout=20)]}],
        "Stop": [{"hooks": [handler(timeout=45)]}],
        "Interrupt": [{"hooks": [handler(timeout=3)]}],
        "SessionEnd": [{"hooks": [handler(timeout=3)]}],
    }


def hooks_file() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "hooks.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"hooks": {}}
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a JSON object")
    data.setdefault("hooks", {})
    return data


def is_ours(entry: dict) -> bool:
    return any(str(HOOK) in str(h.get("command", "")) or "busybar-agents" in str(h.get("command", "")) for h in entry.get("hooks", []))


def strip_ours(hooks: dict) -> None:
    for event in list(hooks):
        kept = [e for e in hooks[event] if not is_ours(e)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--print", action="store_true", dest="show")
    args = parser.parse_args()

    ours = our_hooks()
    if args.show:
        print(json.dumps({"hooks": ours}, indent=2))
        return 0

    path = hooks_file()
    data = load(path)
    strip_ours(data["hooks"])
    if not args.uninstall:
        for event, entries in ours.items():
            data["hooks"].setdefault(event, []).extend(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"removed from {path}" if args.uninstall else f"wrote {path}; now trust the hooks in /hooks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
