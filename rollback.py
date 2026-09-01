"""
rollback.py — Module 8: ROLLBACK ENGINE
Kaam: safeshell undo <id> chalne pe, database se transaction fetch karo,
uska snapshot dhoondo, aur checkpoint.py use karke files wapas restore karo.
"""

import json
from typing import List

import db
from checkpoint import restore_checkpoint


def rollback(transaction_id: int) -> dict:
    """
    Ek transaction ko undo karo.
    Return: dict with 'success' (bool) and 'message' (str) — CLI isse print karega.
    """
    txn = db.get_transaction(transaction_id)

    if txn is None:
        return {"success": False, "message": f"Transaction #{transaction_id} not found."}

    if txn["rolled_back"]:
        return {"success": False, "message": f"Transaction #{transaction_id} was already rolled back."}

    if not txn["snapshot_path"]:
        return {"success": False, "message": f"No snapshot exists for transaction #{transaction_id}. Cannot undo."}

    snapshot_id = txn["snapshot_path"]

    # Undo plan me se targets nikaalo (agar AI plan hai to usme se, warna command se)
    targets = _extract_targets(txn)

    if not targets:
        return {"success": False, "message": "Could not determine which paths to restore."}

    restored = []
    failed = []
    for target in targets:
        ok = restore_checkpoint(snapshot_id, target)
        (restored if ok else failed).append(target)

    if failed and not restored:
        return {
            "success": False,
            "message": f"Snapshot data missing for: {', '.join(failed)}. "
                       f"(Snapshot may have been manually deleted.)",
        }

    db.mark_rolled_back(transaction_id)

    msg = f"Restored: {', '.join(restored)}"
    if failed:
        msg += f" | Could not restore: {', '.join(failed)}"

    return {"success": True, "message": msg}


def _extract_targets(txn: dict) -> List[str]:
    """
    Transaction record se restore karne wale paths nikaalo.
    Priority: undo_plan_json ke 'undo_steps' targets (ye hamesha checkpoint ke
    paths se match karte hain) > affected_paths (sirf informational ho sakta hai,
    deep file paths ho sakte hain jo checkpoint se match na karein) > raw command guess.
    """
    if txn.get("undo_plan_json"):
        try:
            plan = json.loads(txn["undo_plan_json"])
            steps = plan.get("undo_steps", [])
            step_targets = [s["target"] for s in steps if "target" in s]
            if step_targets:
                return step_targets

            paths = plan.get("affected_paths")
            if paths:
                return paths
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: command string se hi targets guess karo (interceptor use karke)
    from interceptor import parse_command
    parsed = parse_command(txn["command"])
    return parsed.targets


# ── Quick manual test ──
if __name__ == "__main__":
    import os
    import tempfile
    from checkpoint import create_checkpoint

    db.init_db()

    # Ek test folder banate hain, checkpoint lete hain, fir "destroy" karte hain
    test_dir = tempfile.mkdtemp(prefix="safeshell_rollback_test_")
    test_file = os.path.join(test_dir, "important.txt")
    with open(test_file, "w") as f:
        f.write("precious original data\n")

    print(f"Test folder: {test_dir}")
    snap_id = create_checkpoint([test_dir])

    txn_id = db.create_transaction(
        command=f"rm -rf {test_dir}",
        risk_level="HIGH",
        risk_score=30,
        snapshot_path=snap_id,
        undo_plan={"affected_paths": [test_dir]},
    )
    print(f"Transaction created: #{txn_id}")

    # Ab "destroy" karte hain (jaise real rm -rf chala ho)
    import shutil
    shutil.rmtree(test_dir)
    print(f"Simulated deletion of {test_dir}")
    print(f"Folder exists after delete: {os.path.exists(test_dir)}")

    # Ab rollback karte hain
    result = rollback(txn_id)
    print(f"\nRollback result: {result}")
    print(f"Folder exists after rollback: {os.path.exists(test_dir)}")
    if os.path.exists(test_file):
        with open(test_file) as f:
            print(f"Content restored: {f.read().strip()}")