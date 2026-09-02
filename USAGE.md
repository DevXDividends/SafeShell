# SafeShell — Usage Guide

## 1. One-Time Setup (already done, for reference)

```bash
pip install -e .          # installs the 'safeshell' command globally in your venv
safeshell setup            # adds shell integration to ~/.bashrc
source ~/.bashrc           # reload so it takes effect in this terminal
```

After this, every **new terminal** will automatically have `safeshell-activate` and `safeshell-down` available — no need to run `eval "$(safeshell shellinit)"` manually again.

---

## 2. Two Ways to Use SafeShell

### Mode A — Direct command (no activation needed)
Explicitly wrap any command:
```bash
safeshell run "rm -rf /tmp/some_folder"
```
Works anywhere, anytime, doesn't touch your `rm`/`mv`/`chmod`.

### Mode B — Transparent interception (the "real" experience)
```bash
safeshell-activate
```
Prompt changes to `(safeshell) $`. Now typing `rm`, `mv`, or `chmod` **directly** routes through SafeShell automatically:
```bash
rm -rf /tmp/some_folder      # automatically intercepted, no need to type "safeshell run"
```
When done:
```bash
safeshell-down
```
Prompt and `rm`/`mv`/`chmod` return to normal.

---

## 3. Core Commands

| Command | What it does |
|---|---|
| `safeshell run "<command>"` | Runs a command through the full pipeline (simulate → risk → confirm → checkpoint → execute → log) |
| `safeshell history` | Shows a table of every transaction ever run |
| `safeshell undo <id>` | Rolls back a specific transaction by its ID |
| `safeshell-activate` | Starts transparent interception in the current shell |
| `safeshell-down` | Stops interception, restores normal `rm`/`mv`/`chmod` |
| `safeshell setup` | One-time: wires shell integration into `~/.bashrc` |
| `safeshell shellinit` | Prints the raw bash functions (used internally by `setup`) |

---

## 4. Try These Demo Scenarios

### Scenario 1 — Basic delete + undo
```bash
mkdir -p /tmp/demo1 && echo "important data" > /tmp/demo1/file.txt
safeshell run "rm -rf /tmp/demo1"
# → shows risk analysis (LOW, 1 file), confirm with 'y'
safeshell history
safeshell undo <id-shown-above>
ls /tmp/demo1   # file.txt is back
```

### Scenario 2 — Permission mistake on a system path (should be flagged risky)
```bash
mkdir -p /tmp/demo2/etc_sim   # safe stand-in, don't test on real /etc unless you're confident
safeshell run "chmod -R 777 /etc/some_fake_sensitive_path"
# → simulation may fail gracefully since path doesn't exist; try with a real owned test dir instead:
safeshell run "chmod -R 777 /tmp/demo2"
```

### Scenario 3 — Compound command (triggers AI undo planner)
```bash
mkdir -p /tmp/demo3
echo "OLD DATA" > /tmp/demo3/old.txt
echo "NEW DATA" > /tmp/demo3/new.txt

export GROQ_API_KEY="your_key"   # or put it in a .env file in the project root
safeshell run "rm /tmp/demo3/old.txt && mv /tmp/demo3/new.txt /tmp/demo3/old.txt"
# → look for: "🧩 Undo plan generated via groq (2 step(s))"
safeshell history
safeshell undo <id>
cat /tmp/demo3/old.txt   # should show "OLD DATA" again
```

### Scenario 4 — Transparent interception end-to-end
```bash
safeshell-activate
mkdir -p /tmp/demo4 && echo "data" > /tmp/demo4/f.txt
rm -rf /tmp/demo4          # just type rm normally — SafeShell catches it
safeshell history
safeshell-down
```

### Scenario 5 — Safe command passes through untouched
```bash
safeshell-activate
ls -la /tmp
rm --help                   # not destructive in effect, but still routed — check it doesn't break
safeshell-down
```

---

## 5. AI Backend Behavior (What You'll See)

- **Simple commands** (`rm -rf folder`) → always instant, rule-based. No AI call, no delay.
- **Compound commands** (`&&`, `;`, `|`) → tries in order:
  1. **Groq** (if `GROQ_API_KEY` is set) — fast, cloud-based, shows `_backend: groq`
  2. **Ollama** (if installed locally) — asks for your permission the *first* time only:
     ```
     [SafeShell] A local AI model (Ollama) was detected on this system.
     Allow SafeShell to use the local LLM for this? [y/N]:
     ```
     Your answer is cached in `~/.safeshell/prefs.json`.
  3. **Heuristic fallback** — if neither is available, or you decline consent.

To reset the Ollama consent prompt:
```bash
rm ~/.safeshell/prefs.json
```

To switch models:
```bash
export SAFESHELL_GROQ_MODEL="openai/gpt-oss-120b"     # bigger Groq model
export SAFESHELL_OLLAMA_MODEL="qwen2.5:14b"            # bigger local model
```

---

## 6. Running Tests

```bash
pytest tests/test_safeshell.py -v
```

To also run the sudo-dependent OverlayFS test (will prompt for your password):
```bash
SAFESHELL_TEST_ALLOW_SUDO=1 pytest tests/test_safeshell.py -v
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `sudo: authenticate` password prompt during `safeshell run` | Normal — simulation needs `sudo` for the OverlayFS mount. Just type your password. |
| `FileNotFoundError: rsync` | `sudo apt install rsync` |
| `ModuleNotFoundError: No module named 'X'` | `pip install -r requirements.txt` (or `pip install -e .` again) |
| Groq call fails with `model_not_found` | Groq deprecates models periodically — check `console.groq.com/docs/models` and update `SAFESHELL_GROQ_MODEL` |
| Groq call fails with `Invalid API Key` (401) | Check `.env` has no stray quotes/spaces; make sure no stale `export GROQ_API_KEY=...` is set in the same shell session (it overrides `.env` otherwise — we fixed this with `override=True`, but double check) |
| `safeshell-activate` says nothing happened / `rm` isn't intercepted | Did you run `source ~/.bashrc` (or open a new terminal) after `safeshell setup`? |
| Undo says "Snapshot data missing" | The path in the undo plan doesn't match what was checkpointed — usually only happens with unusual compound commands (known limitation, see README) |

---

## 8. Quick Reference — Full Session Example

```bash
cd /mnt/d/aditya/safeshell
source venv/bin/activate
safeshell-activate

mkdir -p /tmp/quicktest && echo "test" > /tmp/quicktest/f.txt
rm -rf /tmp/quicktest
# y

safeshell history
safeshell undo <id>
ls /tmp/quicktest    # f.txt is back

safeshell-down
```