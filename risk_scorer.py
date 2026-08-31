"""
risk_scorer.py — Module 4: RISK SCORER
Kaam: ImpactReport lo aur ek explainable, rule-based risk score do.
Ye AI nahi hai — pure math/rules. Isliye ye fast aur predictable hai.
"""

from models import ImpactReport
from config import RISK_THRESHOLDS


def score_risk(impact: ImpactReport) -> dict:
    """
    ImpactReport ke basis pe numeric score calculate karo,
    fir usko CRITICAL/HIGH/MEDIUM/LOW label do.
    Return: dict with score + level + reasoning (taaki UI me dikha sakein)
    """
    score = 0
    reasons = []

    if impact.files_deleted > 0:
        points = impact.files_deleted * 2
        score += points
        reasons.append(f"{impact.files_deleted} files deleted (+{points})")

    if impact.system_paths_touched > 0:
        points = impact.system_paths_touched * 10
        score += points
        reasons.append(f"{impact.system_paths_touched} system paths touched (+{points})")

    if impact.running_processes_affected > 0:
        points = impact.running_processes_affected * 15
        score += points
        reasons.append(f"{impact.running_processes_affected} running processes affected (+{points})")

    # Bytes changed ka bhi thoda weight de dete hain (bahut zyada data change = risky)
    if impact.bytes_changed > 100 * 1024 * 1024:  # 100MB se zyada
        score += 10
        reasons.append("Large data volume changed (+10)")

    # Level decide karo thresholds ke basis pe
    if score > RISK_THRESHOLDS["CRITICAL"]:
        level = "CRITICAL"
    elif score > RISK_THRESHOLDS["HIGH"]:
        level = "HIGH"
    elif score > RISK_THRESHOLDS["MEDIUM"]:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "score": score,
        "level": level,
        "reasons": reasons if reasons else ["No significant risk factors detected"],
    }


# ── Quick manual test ──
if __name__ == "__main__":
    # Simulate ek dummy impact report (jaise "rm -rf /home/user/build" chalane se aata)
    test_impact = ImpactReport(
        files_deleted=47,
        bytes_changed=12 * 1024 * 1024,
        system_paths_touched=0,
        running_processes_affected=0,
    )
    result = score_risk(test_impact)
    print("Test 1 (normal rm -rf on user folder):")
    print(f"  Score: {result['score']} | Level: {result['level']}")
    for r in result["reasons"]:
        print(f"   - {r}")

    # CRITICAL case: system path touched
    critical_impact = ImpactReport(
        files_deleted=200,
        system_paths_touched=1,
        running_processes_affected=2,
    )
    result2 = score_risk(critical_impact)
    print("\nTest 2 (chmod -R 777 /etc/sensitive):")
    print(f"  Score: {result2['score']} | Level: {result2['level']}")
    for r in result2["reasons"]:
        print(f"   - {r}")
