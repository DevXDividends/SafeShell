"""
ai_planner.py — Module 3: AI UNDO PLANNER
Kaam: Command + uska ImpactReport lo, aur ek structured JSON undo plan banao.

Design philosophy (important report/viva point):
- SIMPLE commands (single rm, single mv) -> RULE-BASED plan (fast, deterministic,
  no LLM call needed — "restore from snapshot" is always correct here)
- COMPOUND commands (rm x && mv y z, chained with &&/;/|) -> LLM call, kyunki
  yahan multiple steps ka sahi ORDER aur DEPENDENCY samajhna padta hai, jo
  simple rules se express karna mushkil hai.

Isse tum viva me bol sakte ho: "AI is used selectively, not as a blanket
dependency" — engineering judgement dikhta hai.
"""

import json
import os
import re

import ollama

from interceptor import ParsedCommand
from models import ImpactReport

# Agar WSL se Windows ke Ollama server ko connect karna ho, OLLAMA_HOST env var set karo
# (e.g. export OLLAMA_HOST=http://172.x.x.1:11434) — code khud pick kar lega.
OLLAMA_MODEL = os.environ.get("SAFESHELL_OLLAMA_MODEL", "gemma3:4b")

SYSTEM_PROMPT = """You are a Linux systems assistant. Given a shell command and its \
simulated filesystem impact, output ONLY valid JSON describing a rollback plan. \
No prose, no markdown fences, no explanation — JSON only.

Schema:
{
  "original_command": string,
  "risk_level": "low"|"medium"|"high"|"critical",
  "affected_paths": [string],
  "undo_steps": [
    {"action": string, "target": string, "method": "restore_from_snapshot"|"reverse_permission"|"manual_review"}
  ],
  "requires_snapshot": boolean
}"""


def _is_compound(raw_command: str) -> bool:
    """
    Command 'compound/chained' hai ya nahi check karo — matlab isme
    multiple commands hain (&&, ;, | se jude hue).
    Simple commands ke liye LLM ki zaroorat nahi.
    """
    return bool(re.search(r"&&|;|\|(?!\|)", raw_command))


def _rule_based_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    """
    Simple/deterministic commands ke liye — bina LLM ke, seedha rule follow karo:
    'jo bhi paths affect hue, unhe snapshot se restore karo'.

    IMPORTANT: undo_steps ke 'target' me hamesha parsed.targets use karo (wahi paths
    jinka checkpoint liya gaya tha), na ki impact.affected_paths (jo simulation se
    aaye deep/individual file paths ho sakte hain aur checkpoint keys se match nahi karenge).
    """
    return {
        "original_command": parsed.raw,
        "risk_level": risk_level.lower(),
        "affected_paths": impact.affected_paths or parsed.targets,  # informational only
        "undo_steps": [
            {"action": "restore", "target": path, "method": "restore_from_snapshot"}
            for path in parsed.targets
        ],
        "requires_snapshot": True,
    }


def _split_subcommands(raw_command: str) -> list:
    """Compound command ko uske individual parts me todo, taaki LLM ko clearly bata sakein."""
    parts = re.split(r"&&|;|\|(?!\|)", raw_command)
    return [p.strip() for p in parts if p.strip()]


def _llm_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    """
    Compound/ambiguous commands ke liye — Ollama (local LLM) se undo plan generate karwao.
    Agar LLM fail ho jaaye (model missing, Ollama band hai, etc), rule-based pe fallback karo.
    """
    subcommands = _split_subcommands(parsed.raw)
    steps_list = "\n".join(f"  Step {i+1}: {s}" for i, s in enumerate(subcommands))

    user_prompt = (
        f'Full command: "{parsed.raw}"\n'
        f"This command has {len(subcommands)} sequential steps, executed in this order:\n"
        f"{steps_list}\n\n"
        f"Simulated impact: {impact.files_deleted} files deleted, "
        f"{impact.files_modified} files modified, {impact.bytes_changed} bytes changed, "
        f"affected paths: {impact.affected_paths or parsed.targets}, "
        f"risk level: {risk_level}.\n\n"
        f"IMPORTANT: You MUST generate exactly {len(subcommands)} undo_steps — one for each "
        f"original step above — and they MUST be in REVERSE order (undo the last step first). "
        f"For a mv step, the undo is renaming the file back to its original name "
        f'(use method value "reverse_rename" with target = original path before the mv). '
        f'For an rm step, the undo method is "restore_from_snapshot".'
    )

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format="json",
        )
        content = response["message"]["content"]
        plan = json.loads(content)
        # Basic sanity check — agar schema ka core hissa missing hai, fallback karo
        if "undo_steps" not in plan or len(plan["undo_steps"]) < len(subcommands):
            raise ValueError(
                f"LLM returned incomplete plan ({len(plan.get('undo_steps', []))} steps, "
                f"expected {len(subcommands)})"
            )
        return plan

    except Exception as e:
        print(f"[ai_planner] LLM call failed/incomplete ({e}), falling back to rule-based plan.")
        return _rule_based_plan(parsed, impact, risk_level)


def generate_undo_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    """
    Main entrypoint — decide karo rule-based use karna hai ya LLM,
    aur final undo plan (dict, JSON-serializable) return karo.
    """
    if _is_compound(parsed.raw):
        return _llm_plan(parsed, impact, risk_level)
    return _rule_based_plan(parsed, impact, risk_level)


# ── Quick manual test ──
if __name__ == "__main__":
    from interceptor import parse_command

    # Test 1: Simple command -> rule-based (no LLM call, instant)
    simple = parse_command("rm -rf /tmp/demo_folder")
    simple_impact = ImpactReport(files_deleted=1, affected_paths=["/tmp/demo_folder/file.txt"])
    plan1 = generate_undo_plan(simple, simple_impact, "LOW")
    print("Test 1 — Simple command (rule-based, no LLM):")
    print(json.dumps(plan1, indent=2))

    # Test 2: Compound command -> LLM call
    compound = parse_command("rm old.txt && mv new.txt old.txt")
    compound_impact = ImpactReport(
        files_deleted=1, files_modified=1,
        affected_paths=["/tmp/old.txt", "/tmp/new.txt"],
    )
    print("\nTest 2 — Compound command (LLM call, may take a few seconds)...")
    plan2 = generate_undo_plan(compound, compound_impact, "MEDIUM")
    print(json.dumps(plan2, indent=2))