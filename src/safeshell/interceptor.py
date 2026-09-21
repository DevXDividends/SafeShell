"""
interceptor.py — Module 1: COMMAND INTERCEPTOR
Kaam: user ne jo command type kiya hai, usko parse karo,
aur pata lagao ki ye "risky" hai ya nahi, aur konsi category me aata hai.
"""

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import List

from .config import RISKY_COMMANDS, MULTI_WORD_RISKY, SYSTEM_PATHS

# Shell control operators that separate sub-commands in a compound command.
# Same pattern ai_planner.py uses to detect compound commands — kept in sync
# so both modules agree on where one sub-command ends and the next begins.
_COMPOUND_SPLIT_RE = re.compile(r"&&|;|\|(?!\|)")


@dataclass
class ParsedCommand:
    raw: str
    tokens: List[str]
    base_command: str
    category: str
    is_risky: bool
    touches_system_path: bool
    targets: List[str] = field(default_factory=list)


def parse_command(raw_command: str) -> ParsedCommand:
    tokens = shlex.split(raw_command)
    if not tokens:
        return ParsedCommand(raw_command, [], "", "unknown", False, False, [])

    base_command = tokens[0]

    category = "unknown"
    is_risky = False
    if len(tokens) >= 2:
        two_word = f"{tokens[0]} {tokens[1]}"
        if two_word in MULTI_WORD_RISKY:
            category = MULTI_WORD_RISKY[two_word]
            is_risky = True

    if not is_risky and base_command in RISKY_COMMANDS:
        category = RISKY_COMMANDS[base_command]
        is_risky = True

    # Targets nikaalo — flags (-xyz) chhodke baaki sab arguments.
    # os.path.expanduser() zaroori hai: '~' sirf bash khud expand karta hai
    # jab unquoted ho — Python ke andar humein isse MANUALLY expand karna
    # padta hai, warna simulation/checkpoint silently skip ho jaate hain.
    #
    # IMPORTANT: raw_command can be a COMPOUND command (rm x && mv y z).
    # A plain shlex.split() over the whole string turns operators like
    # '&&' and the next sub-command's verb (e.g. 'mv') into bogus targets,
    # which then get treated as real files by the simulator/checkpoint
    # engine. So we split the raw command into its sub-commands first
    # (same operator set ai_planner.py uses), then pull targets out of
    # EACH sub-command separately and merge them — this way checkpointing
    # actually covers every file touched across the whole chain, and no
    # operator/verb token leaks into the target list.
    sub_commands = [sc for sc in _COMPOUND_SPLIT_RE.split(raw_command) if sc.strip()]

    # chmod/chown ka pehla non-flag argument ek path nahi hota — ye mode
    # (e.g. "777", "u+x") ya owner:group (e.g. "user:group") hota hai.
    # Isse target maan lena galat checkpoint/rollback targets create karta
    # hai (e.g. rollback "777" naam ka nonexistent path restore karne ki
    # koshish karta hai).
    _MODE_ARG_COMMANDS = {"chmod", "chown"}

    targets: List[str] = []
    seen = set()
    for sub in sub_commands:
        try:
            sub_tokens = shlex.split(sub)
        except ValueError:
            # Unbalanced quotes etc. in a sub-command — skip it rather than crash.
            continue
        skip_next_non_flag = sub_tokens[0] in _MODE_ARG_COMMANDS if sub_tokens else False
        for t in sub_tokens[1:]:
            if t.startswith("-"):
                continue
            if skip_next_non_flag:
                skip_next_non_flag = False
                continue
            expanded = os.path.expanduser(t)
            if expanded not in seen:
                seen.add(expanded)
                targets.append(expanded)

    touches_system = any(
        any(target == p or target.startswith(p + "/") for p in SYSTEM_PATHS)
        for target in targets
    )

    return ParsedCommand(
        raw=raw_command,
        tokens=tokens,
        base_command=base_command,
        category=category,
        is_risky=is_risky,
        touches_system_path=touches_system,
        targets=targets,
    )


if __name__ == "__main__":
    test_cases = [
        "rm -rf /home/user/project/build",
        "chmod -R 777 /etc/sensitive",
        "ls -la",
        "mv old.txt new.txt",
    ]
    for cmd in test_cases:
        result = parse_command(cmd)
        print(f"\nCommand: {cmd}")
        print(f"  Risky: {result.is_risky} | Category: {result.category}")
        print(f"  Targets: {result.targets} | Touches system path: {result.touches_system_path}")