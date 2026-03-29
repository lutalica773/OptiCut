from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import List


def _wait_for_pid(pid: int, timeout_s: int = 60) -> None:
    # Best-effort wait for the main process to exit
    end = time.time() + timeout_s
    if pid <= 0:
        return
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return
        try:
            while time.time() < end:
                code = ctypes.c_ulong()
                if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) == 0:
                    break
                STILL_ACTIVE = 259
                if code.value != STILL_ACTIVE:
                    return
                time.sleep(0.25)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        # Fallback: sleep a bit and continue
        time.sleep(2)


def replace_executable(src_path: str, dst_path: str, retries: int = 60, delay_s: float = 0.5) -> None:
    src = os.path.abspath(src_path)
    dst = os.path.abspath(dst_path)

    if not os.path.exists(src):
        raise RuntimeError("Source update file does not exist.")

    dst_dir = os.path.dirname(dst)
    if not os.path.isdir(dst_dir):
        raise RuntimeError("Destination directory does not exist.")

    backup = dst + ".old"
    backup_tmp = backup + ".tmp"

    last_error = None
    for _ in range(max(1, retries)):
        try:
            # Create/refresh backup by COPYING the current exe first.
            # This avoids ever leaving the destination path missing if the updater crashes mid-flight.
            if os.path.exists(dst):
                try:
                    if os.path.exists(backup_tmp):
                        os.remove(backup_tmp)
                except OSError:
                    pass

                with open(dst, "rb") as src_f, open(backup_tmp, "wb") as dst_f:
                    while True:
                        buf = src_f.read(1024 * 1024)
                        if not buf:
                            break
                        dst_f.write(buf)
                os.replace(backup_tmp, backup)

            # Atomically replace destination with the downloaded update.
            os.replace(src, dst)
            return
        except Exception as e:
            last_error = e
            time.sleep(delay_s)

    raise RuntimeError(f"Failed to replace executable: {last_error}") from last_error


def restart_app(exe_path: str, args: List[str]) -> None:
    exe = os.path.abspath(exe_path)
    cmd = [exe, *args]
    subprocess.Popen(cmd, close_fds=True)


def _schedule_self_delete() -> None:
    helper = os.path.abspath(sys.executable)
    cmd_str = f'ping 127.0.0.1 -n 3 >nul & del /f /q "{helper}"'
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(["cmd.exe", "/c", cmd_str], close_fds=True, creationflags=creationflags)
    except Exception:
        pass


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--src", type=str, required=True)
    p.add_argument("--dst", type=str, required=True)
    p.add_argument("--restart-arg", action="append", default=[])
    p.add_argument("--cleanup-self", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    ns = _parse_args(args)

    _wait_for_pid(ns.pid, timeout_s=120)

    # Extra wait for filesystem locks (AV/scanner)
    time.sleep(0.75)

    replace_executable(ns.src, ns.dst, retries=120, delay_s=0.5)
    restart_app(ns.dst, list(ns.restart_arg))
    if ns.cleanup_self:
        _schedule_self_delete()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
