from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from config import UPDATE_MAX_DOWNLOAD_BYTES, UPDATE_REQUIRE_SAME_HOST


class UpdateError(Exception):
    pass


class NetworkError(UpdateError):
    pass


class SecurityError(UpdateError):
    pass


class DownloadError(UpdateError):
    pass


class ChecksumError(UpdateError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    checksum: str
    manifest_host: str


def _require_https(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise SecurityError("Updates require HTTPS.")
    if not parsed.netloc:
        raise SecurityError("Invalid HTTPS URL.")


def _host(url: str) -> str:
    return urllib.parse.urlparse(url).netloc.lower()


class _SecureRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]):
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme.lower() != "https":
            raise SecurityError("Redirect to non-HTTPS URL blocked.")
        if self._allowed_hosts and parsed.netloc.lower() not in self._allowed_hosts:
            raise SecurityError("Redirect to different host blocked.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _parse_semver(version: str) -> Tuple[int, int, int, Tuple[str, ...]]:
    # Accept "1.2.3" and "1.2.3-rc.1". Pre-release is treated as lower than stable.
    v = version.strip()
    if not v:
        raise UpdateError("Invalid version string.")

    main, sep, prerelease = v.partition("-")
    parts = main.split(".")
    if len(parts) != 3:
        raise UpdateError(f"Invalid semantic version: {version}")

    try:
        major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as e:
        raise UpdateError(f"Invalid semantic version: {version}") from e

    pre_parts: Tuple[str, ...] = tuple(prerelease.split(".")) if sep else tuple()
    return major, minor, patch, pre_parts


def _compare_semver(a: str, b: str) -> int:
    a_major, a_minor, a_patch, a_pre = _parse_semver(a)
    b_major, b_minor, b_patch, b_pre = _parse_semver(b)

    if (a_major, a_minor, a_patch) != (b_major, b_minor, b_patch):
        return -1 if (a_major, a_minor, a_patch) < (b_major, b_minor, b_patch) else 1

    # Stable (no prerelease) is higher than prerelease
    if not a_pre and not b_pre:
        return 0
    if not a_pre and b_pre:
        return 1
    if a_pre and not b_pre:
        return -1

    # Compare prerelease identifiers lexicographically with numeric preference
    for x, y in zip(a_pre, b_pre):
        if x == y:
            continue
        x_is_num = x.isdigit()
        y_is_num = y.isdigit()
        if x_is_num and y_is_num:
            return -1 if int(x) < int(y) else 1
        if x_is_num and not y_is_num:
            return -1
        if not x_is_num and y_is_num:
            return 1
        return -1 if x < y else 1

    if len(a_pre) == len(b_pre):
        return 0
    return -1 if len(a_pre) < len(b_pre) else 1


def _normalize_sha256(checksum: str) -> str:
    c = checksum.strip().lower()
    if c.startswith("sha256:"):
        c = c.removeprefix("sha256:").strip()
    c = c.replace(" ", "")
    if not re.fullmatch(r"[0-9a-f]{64}", c):
        raise ChecksumError("Invalid SHA256 checksum format.")
    return c


def check_for_update(manifest_url: str, current_version: str, timeout_s: int = 10) -> Optional[UpdateInfo]:
    _require_https(manifest_url)
    manifest_host = _host(manifest_url)
    allowed_hosts = {manifest_host} if UPDATE_REQUIRE_SAME_HOST else set()

    req = urllib.request.Request(
        manifest_url,
        headers={
            "User-Agent": f"WoodCutListUpdater/{current_version}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        opener = urllib.request.build_opener(_SecureRedirectHandler(allowed_hosts))
        ctx = ssl.create_default_context()
        try:
            resp_obj = opener.open(req, timeout=timeout_s, context=ctx)  # type: ignore[arg-type]
        except TypeError:
            resp_obj = urllib.request.urlopen(req, timeout=timeout_s, context=ctx)
        with resp_obj as resp:
            raw = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        raise NetworkError("Unable to check for updates (network error).") from e

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise UpdateError("Update manifest is not valid JSON.") from e

    version = str(data.get("version", "")).strip()
    url = str(data.get("url", "")).strip()
    checksum = str(data.get("checksum", "")).strip()

    if not version or not url or not checksum:
        raise UpdateError("Update manifest is missing required fields.")

    _require_https(url)
    if UPDATE_REQUIRE_SAME_HOST and _host(url) != manifest_host:
        # Enforce same-host by default; GUI can decide to loosen this by changing URL.
        raise SecurityError("Update download host must match manifest host.")
    checksum = _normalize_sha256(checksum)

    # Ensure versions are valid semver early
    _parse_semver(current_version)
    _parse_semver(version)

    if _compare_semver(version, current_version) <= 0:
        return None

    return UpdateInfo(version=version, url=url, checksum=checksum, manifest_host=manifest_host)


ProgressCallback = Callable[[int, Optional[int]], None]


def download_update(
    info: UpdateInfo,
    progress_cb: Optional[ProgressCallback] = None,
    timeout_s: int = 30,
) -> str:
    _require_https(info.url)
    if UPDATE_REQUIRE_SAME_HOST and _host(info.url) != info.manifest_host:
        raise SecurityError("Update download host must match manifest host.")

    # Unique temp file to avoid collisions/races.
    fd, partial_path = tempfile.mkstemp(prefix=f"woodcutlist_update_{info.version}_", suffix=".exe.part")
    os.close(fd)
    dest_path = partial_path.removesuffix(".part")

    req = urllib.request.Request(
        info.url,
        headers={"User-Agent": "WoodCutListUpdater", "Accept": "application/octet-stream"},
        method="GET",
    )

    downloaded = 0
    total: Optional[int] = None
    try:
        allowed_hosts = {info.manifest_host} if UPDATE_REQUIRE_SAME_HOST else set()
        opener = urllib.request.build_opener(_SecureRedirectHandler(allowed_hosts))
        ctx = ssl.create_default_context()
        try:
            resp_obj = opener.open(req, timeout=timeout_s, context=ctx)  # type: ignore[arg-type]
        except TypeError:
            resp_obj = urllib.request.urlopen(req, timeout=timeout_s, context=ctx)
        with resp_obj as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit():
                total = int(cl)
                if total < 0:
                    raise DownloadError("Invalid Content-Length.")
                if total > UPDATE_MAX_DOWNLOAD_BYTES:
                    raise DownloadError("Update file is too large.")

            with open(partial_path, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > UPDATE_MAX_DOWNLOAD_BYTES:
                        raise DownloadError("Update file is too large.")
                    if total is not None and downloaded > total:
                        raise DownloadError("Downloaded more bytes than expected.")
                    if progress_cb:
                        progress_cb(downloaded, total)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        try:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        except OSError:
            pass
        raise DownloadError("Download failed (network error).") from e
    except OSError as e:
        try:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        except OSError:
            pass
        raise DownloadError("Download failed (filesystem error).") from e
    except Exception:
        try:
            if os.path.exists(partial_path):
                os.remove(partial_path)
        except OSError:
            pass
        raise

    try:
        os.replace(partial_path, dest_path)
    except OSError as e:
        raise DownloadError("Unable to finalize downloaded update file.") from e

    return dest_path


def verify_checksum(file_path: str, expected_sha256: str) -> None:
    expected = _normalize_sha256(expected_sha256)

    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as e:
        raise ChecksumError("Unable to read downloaded file for checksum verification.") from e

    actual = h.hexdigest().lower()
    if actual != expected:
        raise ChecksumError("Checksum mismatch. Update file may be corrupted or tampered.")


def _verify_windows_exe_header(file_path: str) -> None:
    # Basic PE validation to avoid installing a non-executable blob.
    try:
        with open(file_path, "rb") as f:
            mz = f.read(2)
            if mz != b"MZ":
                raise SecurityError("Downloaded file is not a valid Windows executable (MZ header missing).")
            f.seek(0x3C)
            pe_off = int.from_bytes(f.read(4), "little", signed=False)
            if pe_off <= 0 or pe_off > 10_000_000:
                raise SecurityError("Downloaded file is not a valid Windows executable (invalid PE offset).")
            f.seek(pe_off)
            pe = f.read(4)
            if pe != b"PE\x00\x00":
                raise SecurityError("Downloaded file is not a valid Windows executable (PE header missing).")
    except OSError as e:
        raise SecurityError("Unable to validate downloaded executable.") from e


def _is_frozen_exe() -> bool:
    return bool(getattr(sys, "frozen", False)) and sys.executable.lower().endswith(".exe")


def run_updater(downloaded_exe_path: str) -> None:
    if not _is_frozen_exe():
        raise UpdateError("Auto-update is only supported for packaged Windows .exe builds.")

    current_exe = os.path.abspath(sys.executable)
    pid = os.getpid()

    # Restart with same argv (excluding any updater args)
    restart_args = [arg for arg in sys.argv[1:] if arg != "--updater-runner"]

    # IMPORTANT: the updater runner must NOT execute from the same path it will replace.
    # Copy current exe to a temp helper and run updater runner from that helper.
    helper_dir = tempfile.gettempdir()
    helper_name = f"woodcutlist_updater_helper_{pid}.exe"
    helper_exe = os.path.join(helper_dir, helper_name)

    import shutil
    import subprocess

    try:
        shutil.copy2(current_exe, helper_exe)
    except OSError as e:
        raise UpdateError("Unable to prepare updater helper executable.") from e

    _verify_windows_exe_header(downloaded_exe_path)

    cmd = [
        helper_exe,
        "--updater-runner",
        "--pid",
        str(pid),
        "--src",
        os.path.abspath(downloaded_exe_path),
        "--dst",
        current_exe,
        "--cleanup-self",
    ]
    for a in restart_args:
        cmd.extend(["--restart-arg", a])

    try:
        subprocess.Popen(cmd, close_fds=True)
    except OSError as e:
        raise UpdateError("Unable to start updater process.") from e
