"""
simulator.py — Module 2: SIMULATION ENGINE (OverlayFS dry-run)

Kaam: target directory ke upar OverlayFS mount karo, uske andar command
chalao, dekho kya-kya change hua (upperdir me), fir unmount karke real
data ko waisa hi chhod do jaisa tha.

IMPORTANT: Isko sudo chahiye (mount/umount ke liye). WSL2 me ye chalega
kyunki real Linux kernel hai. Plain Docker container ke andar bhi chalega
agar --privileged flag diya ho.
"""

import os
import shutil
import stat
import subprocess
import tempfile

from .config import SNAPSHOT_DIR, SYSTEM_PATHS
from .models import ImpactReport


class SimulationError(Exception):
    """Jab simulation setup/mount fail ho jaaye."""
    pass


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def simulate(command: str, target_dir: str) -> ImpactReport:
    """
    target_dir par overlay mount karke 'command' ko dry-run karo.

    target_dir: wo directory jispe command apna asar dikhayega
                (e.g. agar command hai "rm -rf /tmp/x/file.txt", to
                 target_dir = "/tmp/x")
    command:    poora original command, jaisa-tha-waisa (target_dir ke
                andar ke paths ke saath)

    Return: ImpactReport — command asal me chalne se kya hota, uska summary.
    Guarantee: is function ke chalne ke baad target_dir ke andar ki asli
    files bilkul waisi hi rahengi jaisi pehle thi.
    """
    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        raise SimulationError(f"'{target_dir}' is not an existing directory — cannot simulate.")

    work_root = tempfile.mkdtemp(prefix="sim_", dir=SNAPSHOT_DIR)
    upper = os.path.join(work_root, "upper")
    work = os.path.join(work_root, "work")
    os.makedirs(upper)
    os.makedirs(work)

    mount_cmd = [
        "sudo", "mount", "-t", "overlay", "overlay",
        "-o", f"lowerdir={target_dir},upperdir={upper},workdir={work}",
        target_dir,
    ]

    mounted = False
    try:
        try:
            result = _run(mount_cmd)
        except FileNotFoundError as e:
            raise SimulationError(f"'sudo' or 'mount' not found on this system: {e}")

        if result.returncode != 0:
            raise SimulationError(f"Failed to mount overlay: {result.stderr.strip()}")
        mounted = True

        # Command ko target_dir ke UPAR (overlay ke andar) chalao —
        # isse asli path structure bhi same rehta hai, sirf writes upper me jaate hain
        _run(command, shell=True)

        impact = _analyze_upper(upper, target_dir)
        return impact

    finally:
        # Chahe kuch bhi ho jaaye, unmount ZAROOR karo — warna real folder
        # "stuck" reh jayega overlay ke peeche
        if mounted:
            unmount_result = _run(["sudo", "umount", target_dir])
            if unmount_result.returncode != 0:
                # Lazy unmount fallback — agar koi process abhi bhi folder use kar raha ho
                _run(["sudo", "umount", "-l", target_dir])
        shutil.rmtree(work_root, ignore_errors=True)


def _analyze_upper(upper: str, target_dir: str) -> ImpactReport:
    """
    upperdir ke andar jo bhi mila, uska matlab hai "ye change hua tha".
    OverlayFS me deleted files ek special 'whiteout' marker (char device,
    major=0, minor=0) ke roop me dikhte hain upperdir me.
    """
    files_deleted = 0
    files_modified = 0
    bytes_changed = 0
    affected_paths = []

    for root, dirs, files in os.walk(upper):
        for name in files + dirs:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, upper)
            real_equivalent = os.path.join(target_dir, rel_path)

            try:
                st = os.lstat(full_path)
            except FileNotFoundError:
                continue

            is_whiteout = (
                stat.S_ISCHR(st.st_mode)
                and os.major(st.st_rdev) == 0
                and os.minor(st.st_rdev) == 0
            )

            if is_whiteout:
                files_deleted += 1
            else:
                files_modified += 1
                if stat.S_ISREG(st.st_mode):
                    bytes_changed += st.st_size

            affected_paths.append(real_equivalent)

    system_paths_touched = sum(
        1 for p in affected_paths if any(p.startswith(s) for s in SYSTEM_PATHS)
    )

    return ImpactReport(
        files_deleted=files_deleted,
        files_modified=files_modified,
        bytes_changed=bytes_changed,
        system_paths_touched=system_paths_touched,
        affected_paths=affected_paths,
    )


# ── Quick manual test ──
if __name__ == "__main__":
    test_dir = tempfile.mkdtemp(prefix="safeshell_sim_test_")
    for i in range(3):
        with open(os.path.join(test_dir, f"file{i}.txt"), "w") as f:
            f.write(f"content {i}\n" * 100)

    print(f"Test folder: {test_dir}")
    print(f"Files before simulation: {os.listdir(test_dir)}")

    try:
        impact = simulate(f"rm -rf {test_dir}/*", test_dir)
        print(f"\nSimulated impact:")
        print(f"  Files deleted: {impact.files_deleted}")
        print(f"  Files modified: {impact.files_modified}")
        print(f"  Bytes changed: {impact.bytes_changed}")
        print(f"  Affected paths: {impact.affected_paths}")
    except SimulationError as e:
        print(f"\nSimulation failed: {e}")
        print("(This likely needs sudo/root privileges and OverlayFS support — run in WSL2.)")

    print(f"\nFiles AFTER simulation (should be unchanged!): {os.listdir(test_dir)}")
    shutil.rmtree(test_dir, ignore_errors=True)
