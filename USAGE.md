# SafeShell — Usage Guide

A friendly, step-by-step walkthrough. If you just installed SafeShell, start at Section 1.

---

## 1. First-Time Setup (do this once)

```bash
# System dependencies
sudo apt install -y pipx rsync zstd
pipx ensurepath
exec bash                     # reload your shell so pipx's PATH change applies

# Install SafeShell globally (no venv needed, works in every terminal)
pipx install https://github.com/DevXDividends/SafeShell/releases/latest/download/safeshell_cli-0.2.0-py3-none-any.whl

# Wire up shell integration (so safeshell-activate works everywhere)
safeshell setup
source ~/.bashrc
```

Verify it worked:
```bash
safeshell --help
```
You should see 6 commands: `run`, `history`, `undo`, `shellinit`, `setup`, `settings`.

> ⚠️ **Important:** SafeShell's simulation engine needs a native Linux filesystem. If you're on WSL, test on paths under `/tmp` or your home directory (`~/...`) — **not** `/mnt/c/...` or `/mnt/d/...` (Windows-mounted drives don't support the kernel feature it relies on).

---

## 2. Two Ways to Use SafeShell

### Mode A — Explicit (`safeshell run`)
Works anywhere, anytime, no setup:
```bash
safeshell run "rm -rf /tmp/some_folder"
```

### Mode B — Transparent (recommended for daily use)
```bash
safeshell-activate
```
Your prompt changes to `(safeshell) $`. Now `rm`, `mv`, and `chmod` are **automatically** routed through SafeShell:
```bash
rm -rf /tmp/some_folder      # just type it normally
```
When you're done:
```bash
safeshell-down
```

---

## 3. Try It: A Complete Walkthrough

```bash
# Set up a little test project
mkdir -p ~/demo/build
echo "compiled output" > ~/demo/build/bundle.js

safeshell-activate

# Delete the build folder — this is where SafeShell kicks in
rm -rf ~/demo/build
```

You'll see something like:
```
🔍 Simulating on /home/you/demo/build (dry-run, real files untouched)...

⚠️  RISK ANALYSIS
Command: rm -rf /home/you/demo/build
Risk Level: LOW (score: 2)
  - 1 files deleted

Proceed? [y/N]:
```

Type `y`. Then check your history and undo it:
```bash
safeshell history
safeshell undo 1        # use whatever ID showed up in history
ls ~/demo/build          # it's back!

safeshell-down
```

---

## 4. Core Commands Reference

| Command | What it does |
|---|---|
| `safeshell run "<command>"` | Runs a command through the full pipeline |
| `safeshell history` | Shows every transaction ever run |
| `safeshell undo <id>` | Rolls back a specific transaction |
| `safeshell settings` | Interactive menu to configure AI backends |
| `safeshell setup` | One-time: wires shell integration into `~/.bashrc` |
| `safeshell-activate` | Starts transparent interception in this shell |
| `safeshell-down` | Stops interception, restores normal `rm`/`mv`/`chmod` |

---

## 5. Understanding the AI Backend (Optional, Off by Default)

**On a fresh install, nothing AI-related ever runs — by design.** Simple commands (single `rm`, single `mv`) always use an instant, rule-based undo plan. No network calls, no local model use.

AI only becomes relevant for **compound commands** — ones chained with `&&`, `;`, or `|`, like:
```bash
rm old.txt && mv new.txt old.txt
```
Here, figuring out the *correct order* to undo two chained operations is a real reasoning problem, so an LLM can help generate a clearer, better-explained undo plan. If you never chain commands like this, you'll never see AI mentioned at all — heuristic handles everything.

### Turning it on

```bash
safeshell settings
```

You'll see a menu:
```
                       SafeShell AI Backend Settings
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Backend                ┃ Status    ┃ Detail                              ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Groq (cloud)           │ disabled  │ API key: (not set)                  │
│ Ollama (local)         │ disabled  │ Model: default (detected)           │
│ Heuristic (rule-based) │ always on │ Cannot be disabled — the safety net │
└────────────────────────┴───────────┴─────────────────────────────────────┘

1. Set/Update Groq API key
2. Enable/Disable Groq backend
3. Enable/Disable local LLM (Ollama) backend
4. Reset to defaults (heuristic only)
5. Exit
```

- **To use Groq (cloud, fast, free tier available):** choose `1` to paste your API key (get one free at [console.groq.com](https://console.groq.com)), then `2` to enable it.
- **To use Ollama (local, private, needs more RAM):** install [Ollama](https://ollama.com) and pull a model (`ollama pull gemma3:4b`) first, then choose `3` to enable it in SafeShell.
- **Heuristic can never be disabled** — it's always there as the fallback, no matter what.

Your choice is saved in `~/.safeshell/settings.json` and persists across sessions. If both Groq and Ollama are enabled, Groq takes priority. If either backend fails at runtime for any reason, SafeShell automatically falls back to heuristic — it never just crashes or blocks you.

### Try it
```bash
mkdir -p ~/ai_demo
echo "OLD" > ~/ai_demo/old.txt
echo "NEW" > ~/ai_demo/new.txt

rm ~/ai_demo/old.txt && mv ~/ai_demo/new.txt ~/ai_demo/old.txt
```
Look for `🧩 Undo plan generated via groq (2 step(s))` in the output once enabled — versus `via heuristic` before you turned it on.

---

## 6. More Demo Scenarios

**Permission change on your own files:**
```bash
mkdir -p ~/demo2 && touch ~/demo2/file.txt
safeshell run "chmod -R 777 ~/demo2"
```

**A safe, non-destructive command (passes through untouched):**
```bash
safeshell-activate
ls -la ~
safeshell-down
```

---

## 7. Running the Test Suite

```bash
git clone https://github.com/DevXDividends/SafeShell
cd SafeShell
pip install -e ".[dev]"
pytest tests/test_safeshell.py -v
```

To also run the sudo-dependent OverlayFS test:
```bash
SAFESHELL_TEST_ALLOW_SUDO=1 pytest tests/test_safeshell.py -v
```

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `safeshell-activate: command not found` | Run `safeshell setup && source ~/.bashrc`, or open a brand-new terminal. If you just ran `pipx ensurepath` or `safeshell setup`, existing terminals won't pick it up automatically. |
| `safeshell: command not found` (even after pipx install) | Run `pipx ensurepath` and open a new terminal — pipx's install directory needs to be on your `PATH`. |
| `sudo: authenticate` password prompt | Normal — OverlayFS simulation needs `sudo` to mount. Just enter your password. |
| Simulation silently skipped / risk shows 0 files for a folder you know has files | You're likely on a Windows-mounted path (`/mnt/c`, `/mnt/d` in WSL) — OverlayFS doesn't work there. Test on `/tmp` or `~/...` instead. |
| `ModuleNotFoundError` / missing command | `sudo apt install rsync zstd`, and make sure you installed via `pipx`, not a stale `pip install -e .` in an unrelated venv. |
| Groq call fails with `model_not_found` | Groq periodically deprecates models — check [console.groq.com/docs/models](https://console.groq.com/docs/models) and set `export SAFESHELL_GROQ_MODEL="<new-model-id>"`. |
| Groq call fails with `Invalid API Key` (401) | Re-check the key via `safeshell settings` (option 1) — paste it fresh, no surrounding quotes or spaces. |
| `safeshell-activate` works once but not in a *new* terminal | Check `~/.bashrc` — the SafeShell integration block must come **after** any `pipx`/PATH-related lines, otherwise `safeshell` isn't on the PATH yet when it tries to run. Run `tail -15 ~/.bashrc` to check the order. |
| Undo says "Snapshot data missing" | The exact path in the undo plan doesn't match what was checkpointed — this can happen with unusual compound commands (see Known Limitations in the README). |

---

## 9. Quick Reference — A Full Session

```bash
safeshell-activate

mkdir -p ~/quicktest && echo "test" > ~/quicktest/f.txt
rm -rf ~/quicktest
# y

safeshell history
safeshell undo <id>
ls ~/quicktest    # f.txt is back

safeshell-down
```