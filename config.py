"""
config.py — Module: shared config
Yahan pe hum saari settings, risky commands ki list,
aur paths define karte hain jo baaki modules use karenge.
"""

import os
from dotenv import load_dotenv

# .env file (agar project root me hai) ko environment variables me load karo.
# override=True zaroori hai: agar terminal me pehle se koi stale/purana
# GROQ_API_KEY export kiya hua hai, to .env wali value hamesha priority legi.
load_dotenv(override=True)

# ── Risky commands dictionary ──
# Key = command name, Value = category (isse baad me risk score me use karenge)
RISKY_COMMANDS = {
    "rm": "delete",
    "mv": "move",
    "chmod": "permission_change",
    "chown": "ownership_change",
    "dd": "disk_write",
    "userdel": "account_removal",
    "kill": "process_termination",
}

# apt remove alag se check karenge kyunki ye 2 words ka command hai
MULTI_WORD_RISKY = {
    "apt remove": "package_removal",
    "apt-get remove": "package_removal",
}

# ── System-critical paths ──
# Agar command in paths ko touch kare, to risk automatically high ho jaana chahiye
SYSTEM_PATHS = ["/etc", "/bin", "/usr", "/boot", "/lib", "/sbin", "/sys", "/proc"]

# ── Base directory for SafeShell data ──
BASE_DIR = os.path.expanduser("~/.safeshell")
SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots")
DB_PATH = os.path.join(BASE_DIR, "safeshell.db")

# Risk score thresholds (Module 4 me use hoga)
RISK_THRESHOLDS = {
    "CRITICAL": 50,
    "HIGH": 20,
    "MEDIUM": 5,
}

# ── AI backend config (Module 3) ──
# Priority: Groq (cloud, if key present) > Ollama (local, needs user consent) > heuristic
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("SAFESHELL_GROQ_MODEL", "openai/gpt-oss-20b")
PREFS_PATH = os.path.join(BASE_DIR, "prefs.json")

# Ensure base folders exist jab bhi config import ho
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(SNAPSHOT_DIR, exist_ok=True)