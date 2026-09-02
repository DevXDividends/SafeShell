"""
db.py — Module 7: AUDIT LOG (SQLite)
Kaam: har command jo SafeShell se guzarta hai, uski entry database me save karo.
Isse "safeshell history" aur "safeshell undo <id>" dono kaam kar payenge.
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    risk_level TEXT,
    risk_score INTEGER,
    snapshot_path TEXT,
    undo_plan_json TEXT,
    execution_status TEXT,   -- pending / success / failed
    rolled_back BOOLEAN DEFAULT 0
);
"""


@contextmanager
def get_connection():
    """Ek reusable connection context manager — taaki har jagah try/finally na likhna pade."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows ko dict jaisa access karne ke liye
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Database aur table banao agar already nahi hai to."""
    with get_connection() as conn:
        conn.execute(SCHEMA)


def create_transaction(command: str, risk_level: str, risk_score: int,
                        snapshot_path: str = None, undo_plan: dict = None) -> int:
    """
    Naya transaction record banao (command run hone se PEHLE, status='pending').
    Return: naya transaction id (baad me checkpoint/execution isi id se link hoga)
    """
    undo_plan_json = json.dumps(undo_plan) if undo_plan else None
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO transactions
               (command, risk_level, risk_score, snapshot_path, undo_plan_json, execution_status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (command, risk_level, risk_score, snapshot_path, undo_plan_json, "pending"),
        )
        return cursor.lastrowid


def update_execution_status(transaction_id: int, status: str):
    """Command actually chal jaane ke baad status update karo: 'success' ya 'failed'."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET execution_status = ? WHERE id = ?",
            (status, transaction_id),
        )


def mark_rolled_back(transaction_id: int):
    """Jab rollback ho jaaye, flag set karo."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET rolled_back = 1 WHERE id = ?",
            (transaction_id,),
        )


def get_transaction(transaction_id: int):
    """Ek specific transaction fetch karo (rollback ke time use hoga)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        return dict(row) if row else None


def get_history(limit: int = 20):
    """Latest N transactions fetch karo, safeshell history command ke liye."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


# ── Quick manual test ──
if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {DB_PATH}")

    # Test: ek dummy transaction insert karo
    txn_id = create_transaction(
        command="rm -rf /home/user/project/build",
        risk_level="CRITICAL",
        risk_score=94,
        snapshot_path="/home/user/.safeshell/snapshots/20260831_120000",
        undo_plan={"undo_steps": [{"action": "restore", "method": "restore_from_snapshot"}]},
    )
    print(f"Created transaction id: {txn_id}")

    update_execution_status(txn_id, "success")
    print("Marked as success")

    print("\nHistory:")
    for txn in get_history():
        print(f"  [{txn['id']}] {txn['command']} | {txn['risk_level']} | {txn['execution_status']}")
