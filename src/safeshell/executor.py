"""
executor.py — Module 6: REAL EXECUTION
Kaam: user ka original command actually chalao (real world me), aur
uska output (stdout/stderr/exit code) capture karo.
"""

import subprocess
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    success: bool


def execute_command(raw_command: str) -> ExecutionResult:
    """
    Raw command string ko shell me actually run karo.
    shell=True use kar rahe hain kyunki user ka command jaisa-tha-waisa chalana hai
    (including && , pipes, etc — jo Module 3 me AI planner handle karega).
    """
    result = subprocess.run(
        raw_command,
        shell=True,
        capture_output=True,
        text=True,
    )
    return ExecutionResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        success=(result.returncode == 0),
    )


# ── Quick manual test ──
if __name__ == "__main__":
    result = execute_command("echo 'Hello from SafeShell executor'")
    print(f"Exit code: {result.exit_code}")
    print(f"Success: {result.success}")
    print(f"Stdout: {result.stdout.strip()}")

    # Ek failing command bhi test kar lete hain
    fail_result = execute_command("ls /this/path/does/not/exist")
    print(f"\nFailing command exit code: {fail_result.exit_code}")
    print(f"Success: {fail_result.success}")
    print(f"Stderr: {fail_result.stderr.strip()}")
