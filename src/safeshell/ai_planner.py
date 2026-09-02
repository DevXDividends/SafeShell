"""
ai_planner.py — Module 3: AI UNDO PLANNER
Kaam: Command + uska ImpactReport lo, aur ek structured JSON undo plan banao.

Design philosophy (important report/viva point):
- SIMPLE commands (single rm, single mv) -> RULE-BASED plan always (fast,
  deterministic, no LLM call needed regardless of what backends are available)
- COMPOUND commands (rm x && mv y z, chained with &&/;/|) -> Try an LLM backend,
  in this PRIORITY ORDER:
    1. Groq API      — if GROQ_API_KEY is set, use it directly (user already
                        gave consent by providing the key; fast, no local RAM cost)
    2. Ollama (local) — if Groq unavailable but Ollama is installed with models,
                        ASK THE USER for permission (once, cached) before sending
                        any command data to a local model
    3. Heuristic       — if neither is available/consented, fall back to the same
                        rule-based plan used for simple commands.

NOTE on safety: because SafeShell's rollback restores each affected path
INDEPENDENTLY from its own pre-command snapshot (not by "replaying" inverse
commands in sequence), getting the undo_steps' ORDER wrong does not break
correctness — it only affects how readable/explainable the plan is in the
audit log. The safety net is the checkpoint, not the AI's reasoning.
"""

import json
import os
import re

from .interceptor import ParsedCommand
from .models import ImpactReport
from .config import GROQ_API_KEY, GROQ_MODEL, PREFS_PATH

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
    {"action": string, "target": string, "method": "restore_from_snapshot"|"reverse_rename"|"manual_review"}
  ],
  "requires_snapshot": boolean
}"""


# ─────────────────────────────────────────────────────────────
# Helpers: compound detection, sub-command splitting
# ─────────────────────────────────────────────────────────────

def _is_compound(raw_command: str) -> bool:
    """Command me &&, ; ya | (chaining) hai ya nahi check karo."""
    return bool(re.search(r"&&|;|\|(?!\|)", raw_command))


def _split_subcommands(raw_command: str) -> list:
    """Compound command ko uske individual parts me todo, taaki LLM ko clearly bata sakein."""
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
# Rule-based plan (used for simple commands AND as universal fallback)
# ─────────────────────────────────────────────────────────────

def _rule_based_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    """
    'affected_paths' ko snapshot se restore karo. undo_steps ke 'target' me
    hamesha parsed.targets use karo (wahi paths jinka checkpoint liya gaya tha) —
    impact.affected_paths sirf informational hai, checkpoint keys se match nahi karega.
    """
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
# Backend 1: Groq (cloud API)
# ─────────────────────────────────────────────────────────────

def _groq_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    try:
        from groq import Groq

        client = Groq(api_key=GROQ_API_KEY)
        user_prompt, subcommands = _build_user_prompt(parsed, impact, risk_level)

        response = client.chat.completions.create(
            model=GROQ_MODEL,
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
# Backend 2: Ollama (local LLM, needs user consent)
# ─────────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    """Check karo Ollama installed hai aur kam se kam ek model available hai."""
    try:
        import ollama
        models = ollama.list()
        return len(models.get("models", [])) > 0
    except Exception:
        return False


def _load_prefs() -> dict:
    if os.path.exists(PREFS_PATH):
        try:
            with open(PREFS_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_prefs(prefs: dict):
    os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
    with open(PREFS_PATH, "w") as f:
        json.dump(prefs, f, indent=2)


def _get_local_llm_consent() -> bool:
    """
    User se ek baar poochho ki local LLM (Ollama) use karne ki permission hai ya nahi.
    Jawaab cache ho jaata hai (~/.safeshell/prefs.json) — dobara nahi poochhega.
    """
    prefs = _load_prefs()
    if "use_local_llm" in prefs:
        return prefs["use_local_llm"]

    print("\n[SafeShell] A local AI model (Ollama) was detected on this system.")
    print("It can generate smarter undo plans for compound/chained commands.")
    answer = input("Allow SafeShell to use the local LLM for this? [y/N]: ").strip().lower()
    consent = answer == "y"

    prefs["use_local_llm"] = consent
    _save_prefs(prefs)
    print(f"[SafeShell] Preference saved. (Change anytime by editing {PREFS_PATH})\n")
    return consent


def _ollama_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    try:
        import ollama

        user_prompt, subcommands = _build_user_prompt(parsed, impact, risk_level)
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            format="json",
            keep_alive=0,  # RAM turant free karo call ke baad, background me model load rakhne ki zaroorat nahi
        )
        plan = json.loads(response["message"]["content"])

        if "undo_steps" not in plan or len(plan["undo_steps"]) < len(subcommands):
            raise ValueError(
                f"Ollama returned incomplete plan ({len(plan.get('undo_steps', []))} steps, "
                f"expected {len(subcommands)})"
            )
        plan["_backend"] = f"ollama ({OLLAMA_MODEL})"
        return plan

    except Exception as e:
        print(f"[ai_planner] Ollama call failed ({e}), falling back to rule-based plan.")
        plan = _rule_based_plan(parsed, impact, risk_level)
        plan["_backend"] = "heuristic (ollama failed)"
        return plan


# ─────────────────────────────────────────────────────────────
# Main entrypoint — priority chain
# ─────────────────────────────────────────────────────────────

def generate_undo_plan(parsed: ParsedCommand, impact: ImpactReport, risk_level: str) -> dict:
    """
    Simple commands -> instant rule-based (no backend selection needed).
    Compound commands -> Groq (if key set) > Ollama (if available + consented) > heuristic.
    Returned dict always has a '_backend' key so the caller can display which
    path was taken (transparency for the user).
    """
    if not _is_compound(parsed.raw):
        plan = _rule_based_plan(parsed, impact, risk_level)
        plan["_backend"] = "heuristic (simple command)"
        return plan

    if GROQ_API_KEY:
        print("[SafeShell] Using Groq API for undo-plan reasoning "
              "(command details will be sent to Groq's cloud servers).")
        return _groq_plan(parsed, impact, risk_level)

    if _ollama_available():
        if _get_local_llm_consent():
            return _ollama_plan(parsed, impact, risk_level)

    plan = _rule_based_plan(parsed, impact, risk_level)
    plan["_backend"] = "heuristic (no AI backend available/consented)"
    return plan


# ── Quick manual test ──
if __name__ == "__main__":
    from interceptor import parse_command

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
    print("\nTest 2 — Compound command (backend chain will be tried)...")
    plan2 = generate_undo_plan(compound, compound_impact, "MEDIUM")
    print(json.dumps(plan2, indent=2))
