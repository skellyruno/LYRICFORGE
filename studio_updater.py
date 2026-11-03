"""SkellyMotion: opt-in, digest-verified Windows updater.

Release source: fixed GitHub repository, never arbitrary URLs. This repository
is currently private; prefer an authenticated GitHub CLI session (gh auth login)
and do not store GitHub credentials or tokens in SkellyMotion.

No update is applied until the user explicitly agrees. The running EXE is never
overwritten: an external helper waits for exit and preserves a rollback copy.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

REPO = "skellyruno/LYRICFORGE"
CURRENT_VERSION = "0.9.0"
ASSET_NAME = "SkellyMotion-Windows-x64.zip"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
MAX_DOWNLOAD = 2_000_000_000
MAX_EXTRACTED = 3_000_000_000
MAX_ENTRIES = 20000


def version_tuple(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(value))
    return tuple(map(int, match.groups())) if match else None


def child_flags() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def gh_executable() -> str | None:
    return shutil.which("gh")


def gh_json(args: list[str], timeout: int = 15) -> dict:
    command = gh_executable()
    if not command:
        raise RuntimeError("GitHub CLI is not installed")
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0")
    result = subprocess.run([command, *args], text=True, capture_output=True,
                            timeout=timeout, env=env, **child_flags())
    if result.returncode:
        raise RuntimeError("GitHub authentication or release access is unavailable")
    return json.loads(result.stdout)


def fetch_public_latest() -> dict:
    request = urllib.request.Request(
        LATEST_URL,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "SkellyMotion-Updater/" + CURRENT_VERSION})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def latest_release() -> tuple[dict | None, str]:
    # Private repos require an authorized GitHub CLI session. For a future
    # public binary feed, anonymous HTTPS is also supported.
    if gh_executable():
        try:
            return gh_json(["api", f"repos/{REPO}/releases/latest"]), "github_cli"
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
    try:
        return fetch_public_latest(), "public"
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        return None, "needs_auth"


def validate_release(release: dict, installed_version: str = CURRENT_VERSION) -> dict:
    version = version_tuple(release.get("tag_name", ""))
    current = version_tuple(installed_version)
    if version is None or current is None or release.get("draft") or release.get("prerelease"):
        return {"status": "unavailable"}
    if version <= current:
        return {"status": "current", "current_version": installed_version}
    assets = release.get("assets") or []
    asset = next((item for item in assets if item.get("name") == ASSET_NAME), None)
    if not asset:
        return {"status": "unavailable", "reason": "Release has no Windows ZIP"}
    digest = str(asset.get("digest") or "")
    size = int(asset.get("size") or 0)
    # Download integrity comes from GitHub's verified metadata. If missing,
    # never auto-install unchecked executable code.
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest) or not 100000 < size < MAX_DOWNLOAD:
        return {"status": "unavailable", "reason": "Missing trusted release checksum"}
    return {
        "status": "update",
        "version": release["tag_name"],
        "current_version": installed_version,
        "size_bytes": size,
        "sha256": digest.partition(":")[2].lower(),
        "asset_id": int(asset["id"]),
        "release_url": str(release.get("html_url") or ""),
    }


def check_for_updates() -> dict:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return {"status": "unsupported", "reason": "Updates require an installed Windows portable app"}
    release, auth = latest_release()
    if release is None:
        return {
            "status": "needs_auth",
            "reason": "SkellyMotion's GitHub repo is private. Install GitHub CLI, run 'gh auth login' once, and check again. No token is stored in the app.",
        }
    candidate = validate_release(release)
    candidate["access"] = auth
    return candidate


def verified_zip_extract(archive: Path, destination: Path) -> Path:
    """Reject path traversal, symlink entries and ZIP bombs before extraction."""
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(archive) as zip_file:
        infos = zip_file.infolist()
        if not infos or len(infos) > MAX_ENTRIES:
            raise ValueError("Invalid release archive entry count")
        seen = set()
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or parts[0] != "SkellyMotion" or
                    any(piece in ("..", ".") for piece in parts) or
                    name.startswith("/") or ":" in name or
                    len(name) > 240):
                raise ValueError("Unsafe release archive path")
            normalized = "/".join(p.lower() for p in parts)
            if normalized in seen:
                raise ValueError("Duplicate archive path")
            seen.add(normalized)
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == stat.S_IFLNK:
                raise ValueError("Symlink in release archive")
            total += info.file_size
            if total > MAX_EXTRACTED or info.file_size > 1_000_000_000:
                raise ValueError("Release archive exceeds safe size")
        zip_file.extractall(destination)
    app = destination / "SkellyMotion"
    if not (app / "SkellyMotion.exe").is_file() or not (app / "_internal").is_dir():
        raise ValueError("Release does not contain a complete portable app")
    return app


def _download_release(candidate: dict, output: Path) -> None:
    if gh_executable():
        env = dict(os.environ, GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0")
        cmd = [gh_executable(), "release", "download", candidate["version"],
               "--repo", REPO, "--pattern", ASSET_NAME,
               "--dir", str(output.parent), "--clobber"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                              env=env, **child_flags())
        if proc.returncode == 0 and output.is_file():
            return
    # Public release fallback (private repositories need GitHub CLI auth).
    url = f"https://github.com/{REPO}/releases/download/{candidate['version']}/{ASSET_NAME}"
    request = urllib.request.Request(url, headers={
        "User-Agent": "SkellyMotion-Updater/" + CURRENT_VERSION})
    copied = 0
    with urllib.request.urlopen(request, timeout=30) as inp, output.open("wb") as dest:
        while True:
            chunk = inp.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_DOWNLOAD:
                raise ValueError("Release exceeds download size limit")
            dest.write(chunk)


def prepare_update(home: Path, requested_version: str) -> dict:
    """Stage but do not install a newer release until the user consents."""
    installed = check_for_updates()
    if installed.get("status") != "update" or installed["version"] != requested_version:
        raise RuntimeError("The requested update is unavailable or was replaced")
    version = installed["version"]
    stage = home / "updates" / version
    stage.mkdir(parents=True, exist_ok=True)
    archive = stage / ASSET_NAME
    expected = installed["sha256"]
    if not archive.is_file() or archive.stat().st_size != installed["size_bytes"]:
        _download_release(installed, archive)
    with archive.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if digest != expected:
        archive.unlink(missing_ok=True)
        raise RuntimeError("Update checksum mismatch — installation cancelled")
    prepared = stage / "unpacked"
    if prepared.exists():
        shutil.rmtree(prepared)
    app = verified_zip_extract(archive, prepared)
    return {"status": "ready", "version": version, "prepared_dir": str(app)}


def schedule_install(prepared_dir: Path, install_dir: Path, helper: Path, home: Path) -> None:
    """Spawn an external updater. Caller must then exit the current app."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("In-app install is available in the Windows portable build")
    prepared = prepared_dir.resolve()
    expected_root = (home / "updates").resolve()
    if not prepared.is_relative_to(expected_root) or prepared.name != "SkellyMotion":
        raise ValueError("Invalid staged update directory")
    if not (prepared / "SkellyMotion.exe").is_file() or not (prepared / "_internal").is_dir():
        raise RuntimeError("Incomplete staged update")
    current = Path(sys.executable).resolve().parent
    if install_dir.resolve() != current:
        raise ValueError("Refusing to overwrite a different application folder")
    if not helper.is_file():
        raise RuntimeError("Bundled update installer script is missing")
    log = home / "logs" / "update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
        "-File", str(helper), "-InstallDir", str(current),
        "-PreparedDir", str(prepared), "-OldPid", str(os.getpid()),
        "-LogPath", str(log),
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
       stderr=subprocess.DEVNULL, **child_flags())
