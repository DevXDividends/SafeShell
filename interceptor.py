"""
interceptor.py — Module 1: COMMAND INTERCEPTOR
Kaam: user ne jo command type kiya hai, usko parse karo,
aur pata lagao ki ye "risky" hai ya nahi, aur konsi category me aata hai.
"""

import shlex
from dataclasses import dataclass, field
from typing import List

from config import RISKY_COMMANDS, MULTI_WORD_RISKY, SYSTEM_PATHS


@dataclass
class ParsedCommand:
    raw: str                      # jo user ne type kiya, as-is
    tokens: List[str]              # shlex se split kiya hua
    base_command: str               # e.g. "rm"
    category: str                  # e.g. "delete", ya "unknown" agar risky nahi
    is_risky: bool
    touches_system_path: bool
    targets: List[str] = field(default_factory=list)  # files/folders jo command affect karega


def parse_command(raw_command: str) -> ParsedCommand:
    """
    Raw command string lo (jaise "rm -rf /home/user/build")
    aur usko ek structured ParsedCommand object me convert karo.
    """
    tokens = shlex.split(raw_command)
    if not tokens:
        return ParsedCommand(raw_command, [], "", "unknown", False, False, [])

    base_command = tokens[0]

    # Pehle multi-word commands check karo (jaise "apt remove")
    category = "unknown"
    is_risky = False
    if len(tokens) >= 2:
        two_word = f"{tokens[0]} {tokens[1]}"
        if two_word in MULTI_WORD_RISKY:
            category = MULTI_WORD_RISKY[two_word]
            is_risky = True

    # Agar multi-word match nahi hua, single word check karo
    if not is_risky and base_command in RISKY_COMMANDS:
        category = RISKY_COMMANDS[base_command]
        is_risky = True

    # Targets nikaalo — simple heuristic: flags (-xyz) chhodke baaki sab arguments
    targets = [t for t in tokens[1:] if not t.startswith("-")]

    # Check karo ki koi target system-critical path ko touch to nahi kar raha
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


# ── Quick manual test ──
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
