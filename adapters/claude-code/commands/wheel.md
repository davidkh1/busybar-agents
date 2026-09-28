---
description: Answer Claude from the BUSY Bar's wheel. on, off or status.
argument-hint: on | off | status
allowed-tools: Bash(python3:*)
---

The wheel switch was just applied. Its result:

!`python3 "${CLAUDE_PLUGIN_ROOT}/hook.py" wheel $ARGUMENTS`

Repeat that one line to the user, in your own words if you like, and
nothing more. It applies to every session on this machine from now on. If
it says a variable in the environment wins, add that the shell variable
takes effect only after Claude is restarted.
