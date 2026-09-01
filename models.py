"""
models.py — Shared data structures
Ye file me hum common dataclasses rakhte hain jo multiple modules use karte hain
(simulator, risk_scorer, ai_planner sab isko import karenge).
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class ImpactReport:
    """
    Module 2 (Simulator) ye object banayega after dry-run.
    Abhi ke liye hum ise manually bhi bana sakte hain testing ke liye.
    """
    files_deleted: int = 0
    files_modified: int = 0
    bytes_changed: int = 0
    system_paths_touched: int = 0
    running_processes_affected: int = 0
    affected_paths: List[str] = field(default_factory=list)
