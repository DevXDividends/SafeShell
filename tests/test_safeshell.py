"""
tests/test_safeshell.py — SINGLE-FILE TEST SUITE for SafeShell

Sabhi 8 modules yahan test hote hain: interceptor, risk_scorer, checkpoint,
executor, db, rollback, simulator, ai_planner.

Run karne ka tareeka:
    cd safeshell/
    pytest tests/test_safeshell.py -v

Ya seedha:
    python3 tests/test_safeshell.py

NOTE:
- simulator tests SKIP ho jayenge agar sudo/OverlayFS available na ho
  (jaise CI runners me) — WSL2 me ye chalte hain.
- ai_planner ke Groq/Ollama-dependent tests network/local-model pe depend
  nahi karte — humne unhe monkeypatch se isolate kiya hai taaki test suite
  bina internet/Ollama ke bhi predictably chale.
"""

import os
import shutil
import sys
import tempfile

import pytest

import safeshell.db as db
import safeshell.ai_planner as ai_planner
from safeshell.interceptor import parse_command
from safeshell.risk_scorer import score_risk
from safeshell.models import ImpactReport
from safeshell.checkpoint import create_checkpoint, restore_checkpoint
from safeshell.executor import execute_command
from safeshell.rollback import rollback
from safeshell.simulator import simulate, SimulationError


# ═══════════════════════════════════════════════════════════════
# MODULE 1: INTERCEPTOR
# ═══════════════════════════════════════════════════════════════

class TestInterceptor:
    def test_detects_risky_delete_command(self):
        result = parse_command("rm -rf /home/user/project/build")
        assert result.is_risky is True
        assert result.category == "delete"
        assert result.targets == ["/home/user/project/build"]

    def test_safe_command_not_flagged_risky(self):
        result = parse_command("ls -la")
        assert result.is_risky is False
        assert result.category == "unknown"

    def test_detects_system_path_touch(self):
        result = parse_command("chmod -R 777 /etc/sensitive")
        assert result.is_risky is True
        assert result.touches_system_path is True

    def test_user_path_not_flagged_as_system(self):
        result = parse_command("mv old.txt new.txt")
        assert result.touches_system_path is False

    @pytest.mark.xfail(
        reason="KNOWN LIMITATION: interceptor doesn't split compound commands "
               "(&&/;/|) — target extraction picks up literal tokens like '&&' "
               "and 'mv' as targets. Documented in README. Does not affect "
               "simple/single-action commands.",
        strict=False,
    )
    def test_compound_command_targets_are_clean(self):
        result = parse_command("rm old.txt && mv new.txt old.txt")
        # Ideally targets should ONLY be file paths, no shell operators/keywords
        assert "&&" not in result.targets
        assert "mv" not in result.targets


# ═══════════════════════════════════════════════════════════════
# MODULE 4: RISK SCORER
# ═══════════════════════════════════════════════════════════════

class TestRiskScorer:
    def test_low_risk_single_file(self):
        impact = ImpactReport(files_deleted=1)
        result = score_risk(impact)
        assert result["level"] == "LOW"

    def test_critical_risk_system_path(self):
        impact = ImpactReport(files_deleted=200, system_paths_touched=1, running_processes_affected=2)
        result = score_risk(impact)
        assert result["level"] == "CRITICAL"
        assert result["score"] > 50

    def test_no_impact_gives_low_with_default_reason(self):
        impact = ImpactReport()
        result = score_risk(impact)
        assert result["level"] == "LOW"
        assert "No significant risk factors" in result["reasons"][0]


# ═══════════════════════════════════════════════════════════════
# MODULE 5: CHECKPOINT ENGINE
# ═══════════════════════════════════════════════════════════════

class TestCheckpoint:
    def test_checkpoint_and_restore_roundtrip(self):
        test_dir = tempfile.mkdtemp(prefix="safeshell_test_ckpt_")
        test_file = os.path.join(test_dir, "sample.txt")
        try:
            with open(test_file, "w") as f:
                f.write("original content\n")

            snap_id = create_checkpoint([test_dir])
            assert snap_id  # non-empty snapshot id returned

            # Corrupt the file (simulate a destructive command)
            with open(test_file, "w") as f:
                f.write("CORRUPTED\n")

            success = restore_checkpoint(snap_id, test_dir)
            assert success is True

            with open(test_file) as f:
                assert f.read() == "original content\n"
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_restore_missing_snapshot_returns_false(self):
        result = restore_checkpoint("nonexistent_snapshot_id_12345", "/tmp")
        assert result is False


# ═══════════════════════════════════════════════════════════════
# MODULE 6: REAL EXECUTION
# ═══════════════════════════════════════════════════════════════

class TestExecutor:
    def test_successful_command(self):
        result = execute_command("echo 'hello from test'")
        assert result.success is True
        assert result.exit_code == 0
        assert "hello from test" in result.stdout

    def test_failing_command_captured_not_raised(self):
        result = execute_command("ls /this/path/definitely/does/not/exist")
        assert result.success is False
        assert result.exit_code != 0


# ═══════════════════════════════════════════════════════════════
# MODULE 7 + 8: AUDIT LOG + ROLLBACK (isolated DB per test)
# ═══════════════════════════════════════════════════════════════

class TestDbAndRollback:
    @pytest.fixture(autouse=True)
    def isolated_db(self, tmp_path, monkeypatch):
        """Har test apna alag temp SQLite DB use kare — real ~/.safeshell/safeshell.db pollute na ho."""
        test_db_path = str(tmp_path / "test_safeshell.db")
        monkeypatch.setattr(db, "DB_PATH", test_db_path)
        db.init_db()
        yield

    def test_create_and_fetch_transaction(self):
        txn_id = db.create_transaction("rm -rf /tmp/x", "LOW", 2, snapshot_path="snap1")
        txn = db.get_transaction(txn_id)
        assert txn["command"] == "rm -rf /tmp/x"
        assert txn["risk_level"] == "LOW"
        assert txn["rolled_back"] == 0

    def test_history_returns_latest_first(self):
        db.create_transaction("cmd1", "LOW", 1)
        db.create_transaction("cmd2", "HIGH", 30)
        history = db.get_history()
        assert history[0]["command"] == "cmd2"  # latest first

    def test_full_rollback_cycle(self):
        """End-to-end: checkpoint -> delete -> db record -> rollback -> verify restored."""
        test_dir = tempfile.mkdtemp(prefix="safeshell_test_rollback_")
        test_file = os.path.join(test_dir, "important.txt")
        try:
            with open(test_file, "w") as f:
                f.write("precious data\n")

            snap_id = create_checkpoint([test_dir])
            txn_id = db.create_transaction(
                command=f"rm -rf {test_dir}",
                risk_level="HIGH",
                risk_score=30,
                snapshot_path=snap_id,
                undo_plan={"undo_steps": [{"target": test_dir, "method": "restore_from_snapshot"}]},
            )

            shutil.rmtree(test_dir)
            assert not os.path.exists(test_dir)

            result = rollback(txn_id)
            assert result["success"] is True
            assert os.path.exists(test_file)
            with open(test_file) as f:
                assert f.read() == "precious data\n"

            txn = db.get_transaction(txn_id)
            assert txn["rolled_back"] == 1
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_rollback_nonexistent_transaction(self):
        result = rollback(99999)
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_rollback_twice_is_rejected(self):
        test_dir = tempfile.mkdtemp(prefix="safeshell_test_double_")
        try:
            snap_id = create_checkpoint([test_dir])
            txn_id = db.create_transaction(
                "rm -rf x", "LOW", 2, snapshot_path=snap_id,
                undo_plan={"undo_steps": [{"target": test_dir, "method": "restore_from_snapshot"}]},
            )
            rollback(txn_id)  # first undo - should succeed
            second = rollback(txn_id)  # second undo - should be rejected
            assert second["success"] is False
            assert "already" in second["message"]
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# MODULE 2: SIMULATION ENGINE (OverlayFS) — needs sudo, skip if unavailable
# ═══════════════════════════════════════════════════════════════

def _overlayfs_available() -> bool:
    """Quick check: is sudo+mount actually usable here? Avoids hanging on password prompts in CI."""
    return shutil.which("sudo") is not None and shutil.which("mount") is not None and os.geteuid() == 0 \
        or os.environ.get("SAFESHELL_TEST_ALLOW_SUDO") == "1"


class TestSimulator:
    @pytest.mark.skipif(
        not _overlayfs_available(),
        reason="Needs sudo/OverlayFS (run in WSL2 with passwordless sudo, or "
               "set SAFESHELL_TEST_ALLOW_SUDO=1 if you'll enter the password manually).",
    )
    def test_simulation_does_not_touch_real_files(self):
        test_dir = tempfile.mkdtemp(prefix="safeshell_test_sim_")
        try:
            for i in range(3):
                with open(os.path.join(test_dir, f"file{i}.txt"), "w") as f:
                    f.write("data\n")

            files_before = sorted(os.listdir(test_dir))
            impact = simulate(f"rm -rf {test_dir}/*", test_dir)
            files_after = sorted(os.listdir(test_dir))

            assert impact.files_deleted == 3
            assert files_before == files_after  # REAL files must be untouched
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_simulation_raises_clean_error_for_missing_dir(self):
        with pytest.raises(SimulationError):
            simulate("rm -rf x", "/this/does/not/exist")


# ═══════════════════════════════════════════════════════════════
# MODULE 3: AI UNDO PLANNER (Groq/Ollama isolated via monkeypatch)
# ═══════════════════════════════════════════════════════════════

class TestAiPlanner:
    @pytest.fixture(autouse=True)
    def isolated_settings(self, tmp_path, monkeypatch):
        """Har test apni khud ki temp settings.json use kare — real ~/.safeshell/settings.json affect na ho."""
        import safeshell.settings as settings_module
        monkeypatch.setattr(settings_module, "SETTINGS_PATH", str(tmp_path / "settings.json"))
        monkeypatch.setattr(ai_planner, "load_settings", settings_module.load_settings)
        yield

    def test_simple_command_uses_heuristic_no_network_call(self):
        """Simple commands should NEVER hit an LLM backend — must be instant + deterministic."""
        parsed = parse_command("rm -rf /tmp/demo_folder")
        impact = ImpactReport(files_deleted=1, affected_paths=["/tmp/demo_folder/file.txt"])
        plan = ai_planner.generate_undo_plan(parsed, impact, "LOW")

        assert plan["_backend"] == "heuristic (simple command)"
        assert len(plan["undo_steps"]) == 1
        assert plan["undo_steps"][0]["target"] == "/tmp/demo_folder"

    def test_fresh_install_defaults_to_heuristic_no_prompts(self):
        """CRITICAL: on a fresh install (no settings file), compound commands must
        silently use heuristic — NO API calls, NO prompts, NO local LLM use."""
        parsed = parse_command("rm old.txt && mv new.txt old.txt")
        impact = ImpactReport(files_deleted=1, files_modified=1)
        plan = ai_planner.generate_undo_plan(parsed, impact, "MEDIUM")

        assert plan["_backend"] == "heuristic (no AI backend enabled)"
        assert plan["requires_snapshot"] is True

    def test_groq_disabled_even_with_key_present(self, monkeypatch):
        """If a Groq key exists in settings but groq_enabled=False, Groq must NOT be used."""
        from safeshell.settings import load_settings, save_settings
        s = load_settings()
        s["groq_enabled"] = False
        s["groq_api_key"] = "some-key-that-should-be-ignored"
        save_settings(s)

        parsed = parse_command("rm old.txt && mv new.txt old.txt")
        impact = ImpactReport(files_deleted=1, files_modified=1)
        plan = ai_planner.generate_undo_plan(parsed, impact, "MEDIUM")

        assert plan["_backend"] == "heuristic (no AI backend enabled)"

    def test_groq_backend_selected_when_explicitly_enabled(self, monkeypatch):
        """Verify Groq is used when settings explicitly enable it + key is set (mocked, no real API call)."""
        from safeshell.settings import load_settings, save_settings
        s = load_settings()
        s["groq_enabled"] = True
        s["groq_api_key"] = "fake-key-for-test"
        save_settings(s)

        fake_plan = {
            "original_command": "rm old.txt && mv new.txt old.txt",
            "undo_steps": [
                {"action": "rename", "target": "/tmp/new.txt", "method": "reverse_rename"},
                {"action": "restore", "target": "/tmp/old.txt", "method": "restore_from_snapshot"},
            ],
        }
        monkeypatch.setattr(ai_planner, "_groq_plan", lambda *a, **kw: {**fake_plan, "_backend": "groq"})

        parsed = parse_command("rm old.txt && mv new.txt old.txt")
        impact = ImpactReport(files_deleted=1, files_modified=1)
        plan = ai_planner.generate_undo_plan(parsed, impact, "MEDIUM")

        assert plan["_backend"] == "groq"
        assert len(plan["undo_steps"]) == 2

    def test_local_llm_disabled_by_default_even_if_ollama_installed(self, monkeypatch):
        """Even if Ollama IS installed on the machine, it must not be used unless
        the user explicitly enabled it via 'safeshell settings'."""
        monkeypatch.setattr(ai_planner, "_ollama_available", lambda: True)  # simulate Ollama present

        parsed = parse_command("rm old.txt && mv new.txt old.txt")
        impact = ImpactReport(files_deleted=1, files_modified=1)
        plan = ai_planner.generate_undo_plan(parsed, impact, "MEDIUM")

        # local_llm_enabled defaults to False -> must stay heuristic despite Ollama being available
        assert plan["_backend"] == "heuristic (no AI backend enabled)"

    def test_local_llm_used_when_explicitly_enabled(self, monkeypatch):
        """When the user turns local LLM ON via settings, and Ollama is available, it should be used."""
        from safeshell.settings import load_settings, save_settings
        s = load_settings()
        s["local_llm_enabled"] = True
        save_settings(s)

        monkeypatch.setattr(ai_planner, "_ollama_available", lambda: True)
        fake_plan = {"undo_steps": [{"action": "restore", "target": "/tmp/old.txt", "method": "restore_from_snapshot"}]}
        monkeypatch.setattr(ai_planner, "_ollama_plan", lambda *a, **kw: {**fake_plan, "_backend": "ollama (gemma3:4b)"})

        parsed = parse_command("rm old.txt && mv new.txt old.txt")
        impact = ImpactReport(files_deleted=1, files_modified=1)
        plan = ai_planner.generate_undo_plan(parsed, impact, "MEDIUM")

        assert plan["_backend"] == "ollama (gemma3:4b)"


# ═══════════════════════════════════════════════════════════════
# Entry point — allows `python3 tests/test_safeshell.py` too
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))