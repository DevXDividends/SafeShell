"""
ai_planner.py — Module 3: AI UNDO PLANNER
Kaam: Command + uska ImpactReport lo, aur ek structured JSON undo plan banao.

Design philosophy (important report/viva point):
- SIMPLE commands (single rm, single mv) -> RULE-BASED plan always.
- COMPOUND commands (rm x && mv y z) -> priority chain, driven ENTIRELY by
  persistent settings (~/.safeshell/settings.json), never by ad-hoc prompts
  mid-run:
    1. Groq API      — only if settings.groq_enabled AND a key is configured
    2. Ollama (local) — only if settings.local_llm_enabled AND Ollama has models
    3. Heuristic      — the ALWAYS-ON default. Cannot be disabled. This is
                        what runs on a fresh install with zero configuration.

Use `safeshell settings` to turn Groq/Ollama on and configure the API key —
nothing here ever silently switches those on by itself.
"""

import json
import os
import re

from .interceptor import ParsedCommand
from .models import ImpactReport
from .settings import load_settings

DEFAULT_OLLAMA_MODEL = "gemma3:4b"
DEFAULT_GROQ_MODEL = os.environ.get("SAFESHELL_GROQ_MODEL", "openai/gpt-oss-20b")

SYSTEM_PROMPT = """You are a Linux systems assistant. Given a shell command and its \
simulated filesystem impact, output ONLY valid JSON describing a rollback plan. \
No prose, no markdown fences, no explanation — JSON only.

Schema:
{
  "original_command": string,
  "risk_level": "low"|"medium"|"high"|"critical",
  "affected_paths": [string],
  "undo_steps": [
    {"action": string, "target": string, "method": "restore_from_snapshot"|"reverse_rename"|"manual_review"}
  ],
  "requires_snapshot": boolean
}"""


# ─────────────────────────────────────────────────────────────
# Helpers: compound detection, sub-command splitting
# ─────────────────────────────────────────────────────────────

def _is_compound(raw_command: str) -> bool:
    return bool(re.search(r"&&|;|\|(?!\|)", raw_command))


def _split_subcommands(raw_command: str) -> list:
    parts = re.split(r"&&|;|\|(?!\|)", raw_command)
    return [p.strip() for p in parts if p.strip()]


def _build_user_prompt(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> tuple:
    subcommands = _split_subcommands(parsed.raw)
    steps_list = "\n".join(f"  Step {i+1}: {s}" for i, s in enumerate(subcommands))
    prompt = (
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
    return prompt, subcommands


# ─────────────────────────────────────────────────────────────
# Rule-based plan (simple commands AND universal fallback)
# ─────────────────────────────────────────────────────────────

def _rule_based_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    return {
        "original_command": parsed.raw,
        "risk_level": risk_level.lower(),
        "affected_paths": impact.affected_paths or parsed.targets,
        "undo_steps": [
            {"action": "restore", "target": path, "method": "restore_from_snapshot"}
            for path in parsed.targets
        ],
        "requires_snapshot": True,
        "_backend": "heuristic",
    }


# ─────────────────────────────────────────────────────────────
# Backend 1: Groq (cloud API) — only called if settings say so
# ─────────────────────────────────────────────────────────────

def _groq_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str, api_key: str, model: str) -> dict:
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        user_prompt, subcommands = _build_user_prompt(parsed, impact, risk_level)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        plan = json.loads(response.choices[0].message.content)

        if "undo_steps" not in plan or len(plan["undo_steps"]) < len(subcommands):
            raise ValueError(
                f"Groq returned incomplete plan ({len(plan.get('undo_steps', []))} steps, "
                f"expected {len(subcommands)})"
            )
        plan["_backend"] = "groq"
        return plan

    except Exception as e:
        print(f"[ai_planner] Groq call failed ({e}), falling back to rule-based plan.")
        plan = _rule_based_plan(parsed, impact, risk_level)
        plan["_backend"] = "heuristic (groq failed)"
        return plan


# ─────────────────────────────────────────────────────────────
# Backend 2: Ollama (local) — only called if settings say so
# ─────────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    """Check karo Ollama installed hai aur kam se kam ek model available hai."""
    try:
        import ollama
        models = ollama.list()
        return len(models.get("models", [])) > 0
    except Exception:
        return False


def _ollama_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str, model: str) -> dict:
    try:
        import ollama

        user_prompt, subcommands = _build_user_prompt(parsed, impact, risk_level)
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format="json",
            keep_alive=0,  # RAM turant free karo call ke baad
        )
        plan = json.loads(response["message"]["content"])

        if "undo_steps" not in plan or len(plan["undo_steps"]) < len(subcommands):
            raise ValueError(
                f"Ollama returned incomplete plan ({len(plan.get('undo_steps', []))} steps, "
                f"expected {len(subcommands)})"
            )
        plan["_backend"] = f"ollama ({model})"
        return plan

    except Exception as e:
        print(f"[ai_planner] Ollama call failed ({e}), falling back to rule-based plan.")
        plan = _rule_based_plan(parsed, impact, risk_level)
        plan["_backend"] = "heuristic (ollama failed)"
        return plan


# ─────────────────────────────────────────────────────────────
# Main entrypoint — settings-driven priority chain
# ─────────────────────────────────────────────────────────────

def generate_undo_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    """
    Simple commands -> instant rule-based (settings never even consulted).
    Compound commands -> read settings once, decide backend, NO interactive
    prompts here. If nothing is enabled, heuristic silently handles it —
    this is the correct behavior on a fresh install.
    """
    if not _is_compound(parsed.raw):
        plan = _rule_based_plan(parsed, impact, risk_level)
        plan["_backend"] = "heuristic (simple command)"
        return plan

    settings = load_settings()

    if settings["groq_enabled"] and settings.get("groq_api_key"):
        return _groq_plan(
            parsed, impact, risk_level,
            api_key=settings["groq_api_key"],
            model=DEFAULT_GROQ_MODEL,
        )

    if settings["local_llm_enabled"] and _ollama_available():
        return _ollama_plan(
            parsed, impact, risk_level,
            model=settings.get("local_llm_model") or DEFAULT_OLLAMA_MODEL,
        )

    plan = _rule_based_plan(parsed, impact, risk_level)
    plan["_backend"] = "heuristic (no AI backend enabled)"
    return plan


# ── Quick manual test ──
if __name__ == "__main__":
    # Direct script execution ke liye absolute import (relative import sirf
    # 'python3 -m safeshell.ai_planner' se chalne par kaam karta, isliye ye safer hai)
    from safeshell.interceptor import parse_command

    simple = parse_command("rm -rf /tmp/demo_folder")
    simple_impact = ImpactReport(files_deleted=1, affected_paths=["/tmp/demo_folder/file.txt"])
    plan1 = generate_undo_plan(simple, simple_impact, "LOW")
    print("Test 1 — Simple command:")
    print(json.dumps(plan1, indent=2))

    compound = parse_command("rm old.txt && mv new.txt old.txt")
    compound_impact = ImpactReport(
        files_deleted=1, files_modified=1,
        affected_paths=["/tmp/old.txt", "/tmp/new.txt"],
    )
    print("\nTest 2 — Compound command (uses current settings, run 'safeshell settings' to change):")
    plan2 = generate_undo_plan(compound, compound_impact, "MEDIUM")
    print(json.dumps(plan2, indent=2))