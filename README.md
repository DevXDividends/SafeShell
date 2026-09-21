# 🛡️ SafeShell

**A Transactional Command Execution Framework with AI-Generated Undo Plans and Simulation-Based Safety Guarantees**

Every terminal user has typed `rm -rf` on the wrong path at least once. SafeShell simulates destructive commands *before* they run, checkpoints your data automatically, and lets you roll back with a single command — like database transactions, but for your shell.

```
$ rm -rf ~/projects/demo/build

⚠️  RISK ANALYSIS
Command: rm -rf ~/projects/demo/build
Risk Level: LOW (score: 4)
  - 2 files deleted

Proceed? [y/N]: y
📸 Checkpoint created
▶️  Executing...
✅ Done. Transaction #12 logged.

$ safeshell undo 12
✅ Restored: ~/projects/demo/build
```

---

## ✨ What Makes SafeShell Different

| | |
|---|---|
| 🔬 **Real dry-run, not a guess** | Mounts an OverlayFS layer over the target directory and *actually runs* the command in a kernel-level sandbox before touching real files |
| 📸 **Automatic checkpoints** | Every risky command is backed up (incremental, hardlink-based) *before* it executes |
| 🧠 **AI used selectively** | Simple commands get instant rule-based undo plans. Multi-step chained commands (`rm x && mv y z`) can optionally use an LLM to reason about the correct undo order |
| 🔒 **Opt-in AI, by design** | Fresh install = zero API calls, zero local model usage, ever — until *you* explicitly enable it via `safeshell settings` |
| 🫥 **Transparent or explicit** | Use `safeshell run "..."` directly, or `safeshell-activate` to transparently intercept `rm`/`mv`/`chmod` in your shell |
| 📜 **Full audit trail** | Every command, its risk score, and its outcome is logged to a local SQLite database |

---

## 🏗️ Architecture

```
 User types a command
        │
        ▼
 1. COMMAND INTERCEPTOR  (parses, classifies risk)
        │
        ├──────────────┬───────────────────┐
        ▼              ▼                   ▼
 2. SIMULATION    3. AI UNDO          4. RISK SCORER
    ENGINE           PLANNER             (rule-based)
 (OverlayFS      (Groq / Ollama /
  dry-run)        heuristic — user-
        │         controlled priority)     │
        │              │                   │
        └──────────────┴───────────────────┘
                        │
                        ▼
         Show user: impact report + risk level
                  → CONFIRM? (y/n)
                        │ yes
                        ▼
              5. CHECKPOINT ENGINE  (rsync snapshot before run)
                        │
                        ▼
              6. REAL EXECUTION     (actual command runs)
                        │
                        ▼
              7. AUDIT LOG (SQLite) (command + plan + snapshot id)
                        │
                        ▼
              safeshell undo <id> → 8. ROLLBACK ENGINE
```

## 🧩 Module Breakdown

| # | Module | File | What it does |
|---|--------|------|---------------|
| 1 | Command Interceptor | `interceptor.py` | Parses the raw command, classifies risk, extracts and expands target paths |
| 2 | Simulation Engine | `simulator.py` | Mounts an OverlayFS layer over the target directory and dry-runs the command; inspects the copy-on-write layer for a real impact report |
| 3 | AI Undo Planner | `ai_planner.py` | Simple commands → instant rule-based plan. Compound commands → Groq → Ollama → heuristic, entirely driven by persistent settings |
| 4 | Risk Scorer | `risk_scorer.py` | Deterministic, explainable scoring: LOW / MEDIUM / HIGH / CRITICAL |
| 5 | Checkpoint Engine | `checkpoint.py` | Incremental, hardlink-based backups (`rsync --link-dest`) before execution |
| 6 | Real Execution | `executor.py` | Runs the actual command, captures stdout/stderr/exit code |
| 7 | Audit Log | `db.py` | SQLite-backed transaction history |
| 8 | Rollback Engine | `rollback.py` | Restores affected paths from their checkpoint, by transaction ID |
| — | Settings | `settings.py` | Persistent, explicit opt-in config for AI backends (`~/.safeshell/settings.json`) |
| — | Shell Integration | `shell_integration.py` | `safeshell-activate` / `safeshell-down` bash functions for transparent interception |

## 🧠 Design Philosophy: AI as a Scoped Tool, Not a Crutch

- **Risk scoring is 100% rule-based** — explainable and auditable, never dependent on model quality.
- **Single-action commands** (`rm -rf folder`) always get a rule-based undo plan — an LLM call would only add latency for zero benefit here.
- **The LLM is reserved for genuinely ambiguous, multi-step commands** — where correctly ordering a sequence of operations is a real reasoning problem.
- **Nothing is enabled by default.** A fresh install makes zero external API calls and never touches a local model until you explicitly turn it on via `safeshell settings`.
- **If an AI backend fails, the system falls back to heuristic automatically** — the safety-critical path never depends on AI being available or correct.
- Because rollback restores each path **independently from its own snapshot** (not by replaying inverse commands), even an imperfect undo *plan* doesn't compromise the safety guarantee — the checkpoint is the real safety net.

## ⚙️ Requirements

- **Linux** (tested on WSL2/Ubuntu). OverlayFS simulation needs `sudo` and a **native Linux filesystem** — it will not work on `/mnt/c` or `/mnt/d` under WSL.
- `rsync`, `zstd`
- Python 3.9+
- Optional: a [Groq](https://console.groq.com) API key (free tier available) for cloud AI, or [Ollama](https://ollama.com) for local AI

## 📦 Installation

The recommended way — installs `safeshell` as a global command, no virtualenv juggling required:

```bash
sudo apt install -y pipx rsync zstd
pipx ensurepath
# open a new terminal (or `exec bash`) so the PATH change takes effect

pipx install https://github.com/DevXDividends/SafeShell/releases/latest/download/safeshell_cli-0.2.0-py3-none-any.whl
```

One-time shell setup, so `safeshell-activate` works in every terminal:

```bash
safeshell setup
source ~/.bashrc
```

See **[USAGE.md](USAGE.md)** for the full walkthrough, demo scenarios, and troubleshooting.

## 🚀 Quick Start

```bash
safeshell-activate                  # rm/mv/chmod are now intercepted in this shell
rm -rf some_folder                  # simulated → risk-scored → checkpointed → executed
safeshell history                   # view every transaction ever run
safeshell undo <id>                 # roll back any transaction
safeshell-down                      # deactivate, back to plain rm/mv/chmod
```

## 🧪 Testing

```bash
pytest tests/test_safeshell.py -v
```

25 tests covering all 8 modules, including the settings-driven AI backend priority chain (mocked — no real API calls or local model required to run the suite).

## ⚠️ Known Limitations / Future Work

- Simulation operates at directory granularity (an OverlayFS mount targets a directory, not an individual file).
- **Stretch goals:** `ptrace`-based syscall interception for lower-level OS interception, a web dashboard for transaction history, Btrfs snapshots as an alternative to `rsync` for instant rollback.

## 🎓 OS Concepts Demonstrated

Filesystem layering and copy-on-write (OverlayFS), process execution (`subprocess`/fork-exec semantics), snapshotting via hardlinks, and risk-based access control — with the AI layer scoped narrowly as a differentiator, not a dependency.

## 📄 License

MIT — see [LICENSE](LICENSE).