"""
checkpoint.py — Module 5: CHECKPOINT ENGINE
Kaam: real command chalne se PEHLE, target paths ka ek backup (snapshot) le lo.
Hum rsync --link-dest use karte hain — matlab jo files change nahi hui unko
hardlink kar dete hain (disk space bachta hai), sirf changed files copy hoti hain.
"""

import os
import subprocess
from datetime import datetime
from typing import List

from .config import SNAPSHOT_DIR


def _latest_snapshot_link(target_key: str) -> str:
    """Har target ke liye ek 'latest' symlink track karte hain, taaki --link-dest use kar sakein."""
    return os.path.join(SNAPSHOT_DIR, f"{target_key}_latest")


def _target_key(path: str) -> str:
    """File/folder path ko ek safe folder-name jaisa banao (snapshot dir ke andar use hoga)."""
    return path.strip("/").replace("/", "_") or "root"


def create_checkpoint(paths: List[str]) -> str:
    """
    Diye gaye paths ka backup lo. Return: snapshot_id (timestamp based folder name)
    Agar path exist hi nahi karta (naya file jo abhi banega), usko skip kar dete hain.
    """
    snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_root = os.path.join(SNAPSHOT_DIR, snapshot_id)
    os.makedirs(snapshot_root, exist_ok=True)

    for path in paths:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            continue  # naye files jo abhi create honge, unka backup lena possible nahi

        target_key = _target_key(abs_path)
        dest_dir = os.path.join(snapshot_root, target_key)
        os.makedirs(os.path.dirname(dest_dir), exist_ok=True) if os.path.dirname(dest_dir) else None

        link_dest = _latest_snapshot_link(target_key)

        cmd = ["rsync", "-a"]
        # Agar pehle ka snapshot maujood hai, to link-dest use karo (space saving)
        if os.path.exists(link_dest):
            cmd += [f"--link-dest={link_dest}"]

        # Agar path ek directory hai, trailing slash zaroori hai rsync ke liye
        source = abs_path + ("/" if os.path.isdir(abs_path) else "")
        cmd += [source, dest_dir + ("/" if os.path.isdir(abs_path) else "")]

        os.makedirs(dest_dir if os.path.isdir(abs_path) else os.path.dirname(dest_dir), exist_ok=True)
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        # 'latest' pointer update karo agli baar ke liye
        if os.path.islink(link_dest) or os.path.exists(link_dest):
            os.remove(link_dest) if os.path.islink(link_dest) else None
        try:
            os.symlink(dest_dir, link_dest)
        except FileExistsError:
            pass

    return snapshot_id


def restore_checkpoint(snapshot_id: str, target_path: str) -> bool:
    """
    Ek snapshot se ek specific path wapas restore karo.
    Return: True agar successful, False agar snapshot me wo path mila hi nahi.
    """
    abs_target = os.path.abspath(target_path)
    target_key = _target_key(abs_target)
    snapshot_source = os.path.join(SNAPSHOT_DIR, snapshot_id, target_key)

    if not os.path.exists(snapshot_source):
        return False

    source = snapshot_source + ("/" if os.path.isdir(snapshot_source) else "")
    dest = os.path.dirname(abs_target) + "/" if os.path.isdir(snapshot_source) else abs_target

    cmd = ["rsync", "-a", "--delete", source, abs_target + "/" if os.path.isdir(snapshot_source) else dest]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return True


# ── Quick manual test ──
if __name__ == "__main__":
    import tempfile

    # Ek temporary test folder banate hain taaki real files ko touch na karein
    test_dir = tempfile.mkdtemp(prefix="safeshell_test_")
    test_file = os.path.join(test_dir, "sample.txt")
    with open(test_file, "w") as f:
        f.write("original content\n")

    print(f"Test folder: {test_dir}")
    snap_id = create_checkpoint([test_dir])
    print(f"Checkpoint created: {snap_id}")

    # Ab file ko modify/delete kar dete hain (jaise real command karega)
    with open(test_file, "w") as f:
        f.write("MODIFIED / CORRUPTED content\n")
    print("File modified to simulate a destructive command.")

    # Ab restore karke check karte hain
    success = restore_checkpoint(snap_id, test_dir)
    print(f"Restore success: {success}")

    with open(test_file) as f:
        print(f"Content after restore: {f.read().strip()}")
