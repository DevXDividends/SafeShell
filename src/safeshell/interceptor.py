"""
interceptor.py — Module 1: COMMAND INTERCEPTOR
Kaam: user ne jo command type kiya hai, usko parse karo,
aur pata lagao ki ye "risky" hai ya nahi, aur konsi category me aata hai.
"""

import os
import shlex
from dataclasses import dataclass, field
from typing import List

from .config import RISKY_COMMANDS, MULTI_WORD_RISKY, SYSTEM_PATHS


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
    targets = [os.path.expanduser(t) for t in tokens[1:] if not t.startswith("-")]

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
