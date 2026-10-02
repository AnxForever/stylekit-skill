#!/usr/bin/env python3
"""Update this StyleKit Skill from its official GitHub main branch."""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import unicodedata
import zlib
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator
from urllib.parse import urlsplit

REPOSITORY = "AnxForever/stylekit-skill"
BRANCH = "main"
ARCHIVE_URL = "https://codeload.github.com/AnxForever/stylekit-skill/zip/refs/heads/main"
ARCHIVE_PREFIX = "stylekit-skill-main/"
MANIFEST_REL = "scripts/release-manifest.json"
STATE_REL = ".stylekit-update-state.json"
LOCK_REL = ".stylekit-update.lock"
TRANSACTION_REL = ".stylekit-update-transaction.json"
DISABLED_REL = ".stylekit-updates-disabled"
DISABLED_MARKER = b"StyleKit automatic updates disabled\n"
CHECK_INTERVAL = dt.timedelta(hours=24)
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = MAX_UNPACKED_BYTES * 3
MAX_FILES = 2000
MAX_RETRIES = 3
VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class UpdateError(Exception):
    pass


class LocalConflict(UpdateError):
    pass


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _timestamp(value: dt.datetime | None = None) -> str:
    return (value or _utc_now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_payload_path(path: str) -> bool:
    return path == "SKILL.md" or path.startswith(("scripts/", "references/", "agents/", "assets/"))


def _validate_relpath(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise UpdateError("manifest contains an invalid path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(part in ("", ".", "..") for part in posix.parts):
        raise UpdateError("manifest contains an unsafe path")
    if any(":" in part for part in posix.parts):
        raise UpdateError("manifest contains a platform-specific path")
    normalized = posix.as_posix()
    if normalized != value or unicodedata.normalize("NFC", value) != value or not _is_payload_path(normalized) or normalized == MANIFEST_REL:
        raise UpdateError("manifest contains a path outside the Skill payload")
    _validate_portable_components(posix.parts)
    return normalized


def _validate_portable_components(parts: tuple[str, ...]) -> None:
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update("COM" + str(number) for number in range(1, 10))
    reserved.update("LPT" + str(number) for number in range(1, 10))
    for part in parts:
        if part.endswith((".", " ")):
            raise UpdateError("path has a non-portable trailing dot or space")
        stem = part.split(".", 1)[0].upper()
        if stem in reserved:
            raise UpdateError("path contains a reserved device name")


def _validate_manifest(raw: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("release manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise UpdateError("unsupported release manifest")
    if manifest.get("repository") != REPOSITORY or manifest.get("branch") != BRANCH:
        raise UpdateError("release manifest does not name the official repository and branch")
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise UpdateError("release manifest has an invalid version")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > MAX_FILES:
        raise UpdateError("release manifest has an invalid file list")
    normalized: dict[str, dict[str, Any]] = {}
    total_size = 0
    for untrusted_path, entry in files.items():
        path = _validate_relpath(untrusted_path)
        if path in normalized or not isinstance(entry, dict):
            raise UpdateError("release manifest has a duplicate or invalid file entry")
        digest = entry.get("sha256")
        size = entry.get("size")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise UpdateError("release manifest has an invalid SHA-256 digest")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
            raise UpdateError("release manifest has an invalid file size")
        total_size += size
        if total_size > MAX_UNPACKED_BYTES:
            raise UpdateError("release manifest exceeds the unpacked size limit")
        normalized[path] = {"sha256": digest, "size": size}
    if set(files) != set(normalized):
        raise UpdateError("release manifest has colliding paths")
    folded = [path.casefold() for path in normalized]
    if len(folded) != len(set(folded)):
        raise UpdateError("release manifest has case-colliding paths")
    manifest["files"] = normalized
    return manifest


def _validate_and_unpack_archive(archive_bytes: bytes) -> tuple[bytes, dict[str, bytes]]:
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise UpdateError("release archive exceeds the download size limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError("release archive is not a valid ZIP file") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 500:
            raise UpdateError("release archive contains too many entries")
        seen: set[str] = set()
        folded: set[str] = set()
        total_size = 0
        manifest_bytes: bytes | None = None
        payload: dict[str, bytes] = {}
        for info in infos:
            raw_name = info.filename
            if "\\" in raw_name or "\x00" in raw_name:
                raise UpdateError("release archive contains an invalid path")
            is_dir = info.is_dir()
            name = raw_name[:-1] if is_dir and raw_name.endswith("/") else raw_name
            if is_dir and name == ARCHIVE_PREFIX[:-1]:
                continue
            if not name.startswith(ARCHIVE_PREFIX):
                raise UpdateError("release archive has an unexpected top-level directory")
            relative = name[len(ARCHIVE_PREFIX):]
            if not relative:
                if not is_dir:
                    raise UpdateError("release archive root is not a directory")
                continue
            rel = _validate_archive_path(relative, is_dir)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise UpdateError("release archive contains a symbolic link")
            if is_dir:
                continue
            if rel in seen or rel.casefold() in folded:
                raise UpdateError("release archive contains duplicate or case-colliding paths")
            seen.add(rel)
            folded.add(rel.casefold())
            if info.file_size < 0 or info.file_size > MAX_FILE_BYTES:
                raise UpdateError("release archive contains an oversized file")
            total_size += info.file_size
            if total_size > MAX_UNPACKED_BYTES:
                raise UpdateError("release archive exceeds the unpacked size limit")
            if rel == MANIFEST_REL or _is_payload_path(rel):
                try:
                    contents = _read_zip_member_limited(archive, info, MAX_MANIFEST_BYTES if rel == MANIFEST_REL else MAX_FILE_BYTES)
                except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error, OSError) as exc:
                    raise UpdateError("release archive contains a corrupt or unreadable file") from exc
                if rel == MANIFEST_REL:
                    manifest_bytes = contents
                else:
                    payload[rel] = contents
        if manifest_bytes is None:
            raise UpdateError("release archive has no release manifest")
        manifest = _validate_manifest(manifest_bytes)
        if set(payload) != set(manifest["files"]):
            raise UpdateError("release archive files do not match the manifest")
        for path, expected in manifest["files"].items():
            data = payload[path]
            if len(data) != expected["size"] or _sha256(data) != expected["sha256"]:
                raise UpdateError("release archive hash check failed for " + path)
        return manifest_bytes, payload


def _validate_archive_path(value: str, is_dir: bool) -> str:
    if not value or value.startswith("/"):
        raise UpdateError("release archive contains an unsafe path")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or any(part in ("", ".", "..") for part in posix.parts):
        raise UpdateError("release archive contains a path traversal")
    if any(":" in part for part in posix.parts):
        raise UpdateError("release archive contains a platform-specific path")
    normalized = posix.as_posix()
    if normalized != value:
        raise UpdateError("release archive contains a non-normalized path")
    if unicodedata.normalize("NFC", value) != value:
        raise UpdateError("release archive contains a non-normalized Unicode path")
    _validate_portable_components(posix.parts)
    return normalized


def _read_zip_member_limited(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with archive.open(info, "r") as member:
        while True:
            block = member.read(min(64 * 1024, limit - total + 1))
            if not block:
                break
            total += len(block)
            if total > limit:
                raise UpdateError("release archive member exceeds its actual uncompressed size limit")
            chunks.append(block)
    if total != info.file_size:
        raise UpdateError("release archive member size does not match its ZIP directory")
    return b"".join(chunks)


def _open_official_archive(force: bool = False) -> bytes:
    parsed = urlsplit(ARCHIVE_URL)
    if parsed.scheme != "https" or parsed.hostname != "codeload.github.com" or parsed.path != "/AnxForever/stylekit-skill/zip/refs/heads/main":
        raise UpdateError("configured update source is not the official HTTPS archive")
    last_error: Exception | None = None
    max_attempts = MAX_RETRIES if force else 1
    timeout_seconds = 12 if force else 7
    for attempt in range(max_attempts):
        request = urllib.request.Request(
            ARCHIVE_URL,
            headers={"User-Agent": "stylekit-skill-updater/1", "Accept": "application/zip"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                final = urlsplit(response.geturl())
                if final.scheme != "https" or final.hostname not in ("codeload.github.com", "github.com"):
                    raise UpdateError("update source redirected outside official GitHub HTTPS")
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_ARCHIVE_BYTES:
                    raise UpdateError("release archive exceeds the download size limit")
                data = response.read(MAX_ARCHIVE_BYTES + 1)
                if len(data) > MAX_ARCHIVE_BYTES:
                    raise UpdateError("release archive exceeds the download size limit")
                return data
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt + 1 == max_attempts:
                break
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                wait = min(2.0, max(0.0, float(retry_after))) if retry_after else 0.5 * (2 ** attempt)
            except ValueError:
                wait = 0.5 * (2 ** attempt)
            time.sleep(wait)
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                time.sleep(0.5 * (2 ** attempt))
    raise UpdateError("official update source is unavailable" + (": " + type(last_error).__name__ if last_error else ""))


def _root_from_script() -> Path:
    script_path = Path(__file__).absolute()
    root_hint = script_path.parent.parent
    try:
        root = root_hint.resolve(strict=True)
    except OSError as exc:
        raise UpdateError("Skill installation directory is unavailable") from exc
    if not root.is_dir():
        raise UpdateError("Skill installation directory is not a directory")
    # The installation root may itself be a symlink. Internal paths may not be.
    _assert_no_internal_symlink(root, Path("scripts/update-skill.py"), must_exist=True)
    return root


def _assert_no_internal_symlink(root: Path, relative: Path, must_exist: bool = False) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if must_exist:
                raise UpdateError("required Skill file is missing: " + relative.as_posix())
            break
        except OSError as exc:
            raise UpdateError("cannot inspect Skill path: " + relative.as_posix()) from exc
        if _is_link_or_reparse_point(current, info):
            raise UpdateError("refusing to follow an internal link or junction: " + relative.as_posix())
    return current


def _is_link_or_reparse_point(path: Path, info: os.stat_result) -> bool:
    is_junction = getattr(path, "is_junction", None)
    has_reparse_attribute = bool(getattr(info, "st_file_attributes", 0) & 0x400)
    return stat.S_ISLNK(info.st_mode) or (is_junction is not None and is_junction()) or has_reparse_attribute


def _read_regular(root: Path, relative: str, required: bool = False) -> bytes | None:
    path = _assert_no_internal_symlink(root, Path(relative), must_exist=required)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise UpdateError("refusing a non-file Skill path: " + relative)
    size_limit = MAX_FILE_BYTES
    if relative == MANIFEST_REL:
        size_limit = MAX_MANIFEST_BYTES
    elif relative == STATE_REL:
        size_limit = MAX_STATE_BYTES
    elif relative == TRANSACTION_REL:
        size_limit = MAX_JOURNAL_BYTES
    if info.st_size > size_limit:
        raise UpdateError("Skill file exceeds the safe size limit: " + relative)
    return path.read_bytes()


def _safe_manifest_bytes(root: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular(root, MANIFEST_REL, required=True)
    assert raw is not None
    return raw, _validate_manifest(raw)


def _initial_state(root: Path) -> tuple[bytes, dict[str, Any]]:
    manifest_bytes, manifest = _safe_manifest_bytes(root)
    for relative, expected in manifest["files"].items():
        actual = _read_regular(root, relative, required=True)
        assert actual is not None
        if len(actual) != expected["size"] or _sha256(actual) != expected["sha256"]:
            raise LocalConflict("installed file differs from its release manifest: " + relative)
    return manifest_bytes, {
        "schemaVersion": 1,
        "installedVersion": manifest["version"],
        "installedManifestSha256": _sha256(manifest_bytes),
        "managedFiles": manifest["files"],
        "lastCheckedAt": None,
        "disabled": False,
    }


def _load_state(root: Path) -> tuple[bytes, dict[str, Any], bool]:
    raw_state = _read_regular(root, STATE_REL)
    if raw_state is None:
        manifest_bytes, state = _initial_state(root)
        return manifest_bytes, state, True
    try:
        state = json.loads(raw_state.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalConflict("local update state is invalid; preserving the Skill") from exc
    if not isinstance(state, dict) or state.get("schemaVersion") != 1:
        raise LocalConflict("local update state is unsupported; preserving the Skill")
    manifest_bytes, manifest = _safe_manifest_bytes(root)
    if state.get("installedManifestSha256") != _sha256(manifest_bytes):
        raise LocalConflict("local release manifest changed; preserving the Skill")
    if state.get("installedVersion") != manifest["version"] or state.get("managedFiles") != manifest["files"]:
        raise LocalConflict("local update state does not match the installed release manifest")
    if not isinstance(state.get("disabled"), bool):
        raise LocalConflict("local update state has an invalid setting")
    for path in manifest["files"]:
        if _read_regular(root, path) is None:
            raise LocalConflict("installed managed file is missing: " + path)
    return manifest_bytes, state, False


def _write_json_atomic(root: Path, relative: str, value: dict[str, Any]) -> None:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_bytes_atomic(root, relative, data)


def _write_bytes_atomic(root: Path, relative: str, data: bytes) -> None:
    target = _assert_no_internal_symlink(root, Path(relative))
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_internal_symlink(root, Path(relative))
    fd, temporary_name = tempfile.mkstemp(prefix=".stylekit-write-", dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def _exclusive_lock(root: Path) -> Iterator[bool]:
    lock_path = _assert_no_internal_symlink(root, Path(LOCK_REL))
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise UpdateError("cannot open the update lock safely") from exc
    handle = os.fdopen(fd, "r+b", buffering=0)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise UpdateError("update lock is not a regular file")
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError:
                locked = False
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError:
                locked = False
        yield locked
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                with contextlib.suppress(OSError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _atomic_journal(root: Path, entries: list[dict[str, Any]]) -> None:
    journal = {"schemaVersion": 1, "entries": entries}
    _write_json_atomic(root, TRANSACTION_REL, journal)


def _load_journal(root: Path) -> dict[str, Any] | None:
    raw = _read_regular(root, TRANSACTION_REL)
    if raw is None:
        return None
    if len(raw) > MAX_JOURNAL_BYTES:
        raise LocalConflict("pending update journal exceeds the safe size limit")
    try:
        journal = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalConflict("pending update journal is invalid; preserving all files") from exc
    if not isinstance(journal, dict) or journal.get("schemaVersion") != 1 or not isinstance(journal.get("entries"), list):
        raise LocalConflict("pending update journal is unsupported; preserving all files")
    if len(journal["entries"]) > MAX_FILES + 2:
        raise LocalConflict("pending update journal has too many entries")
    seen: set[str] = set()
    for entry in journal["entries"]:
        if not isinstance(entry, dict):
            raise LocalConflict("pending update journal has an invalid entry")
        path = entry.get("path")
        if path not in (STATE_REL, MANIFEST_REL):
            try:
                path = _validate_relpath(path)
            except UpdateError as exc:
                raise LocalConflict("pending update journal has an unsafe path") from exc
        if path in seen:
            raise LocalConflict("pending update journal has duplicate paths")
        seen.add(path)
        entry["path"] = path
        before = entry.get("before")
        before_hash = entry.get("beforeSha256")
        after_hash = entry.get("afterSha256")
        if before is not None:
            if not isinstance(before, str) or len(before) > (MAX_FILE_BYTES * 4 // 3 + 16):
                raise LocalConflict("pending update journal backup is invalid")
            try:
                old_data = base64.b64decode(before, validate=True)
            except ValueError as exc:
                raise LocalConflict("pending update journal backup is invalid") from exc
            if len(old_data) > MAX_FILE_BYTES or _sha256(old_data) != before_hash:
                raise LocalConflict("pending update journal backup hash is invalid")
        elif before_hash is not None:
            raise LocalConflict("pending update journal has an invalid previous-file hash")
        if after_hash is not None and (not isinstance(after_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", after_hash)):
            raise LocalConflict("pending update journal has an invalid target-file hash")
    return journal


def _recover_interrupted_update(root: Path) -> bool:
    journal = _load_journal(root)
    if journal is None:
        return False
    entries = journal["entries"]
    # Preflight every destination before changing any of them. A third hash is a later local edit.
    current_values: dict[str, bytes | None] = {}
    edited_paths: set[str] = set()
    for entry in entries:
        path = entry["path"]
        current = _read_regular(root, path)
        current_values[path] = current
        current_hash = _sha256(current) if current is not None else None
        if current_hash not in (entry.get("beforeSha256"), entry.get("afterSha256")):
            edited_paths.add(path)
    for entry in entries:
        path = entry["path"]
        if path in edited_paths:
            continue
        before = entry.get("before")
        if before is None:
            if current_values[path] is not None:
                target = _assert_no_internal_symlink(root, Path(path), must_exist=True)
                target.unlink()
                _fsync_directory(target.parent)
        else:
            old_data = base64.b64decode(before, validate=True)
            if current_values[path] is None or _sha256(current_values[path] or b"") != entry["beforeSha256"]:
                _write_bytes_atomic(root, path, old_data)
    journal_path = _assert_no_internal_symlink(root, Path(TRANSACTION_REL), must_exist=True)
    journal_path.unlink()
    _fsync_directory(root)
    return True


def _apply_payload(root: Path, old_manifest_bytes: bytes,
                   old_manifest: dict[str, Any], new_manifest_bytes: bytes,
                   new_manifest: dict[str, Any], payload: dict[str, bytes], state: dict[str, Any]) -> None:
    old_files = old_manifest["files"]
    new_files = new_manifest["files"]
    # The updater accepts either a completely unchanged baseline or aborts as one batch.
    conflicts: list[str] = []
    local_paths = _local_payload_paths(root)
    for relative in new_files:
        aliases = local_paths.get(_portable_key(relative), [])
        conflicts.extend(alias + " (portable path collision with " + relative + ")" for alias in aliases if alias != relative)
    for relative, expected in old_files.items():
        current = _read_regular(root, relative, required=True)
        assert current is not None
        if len(current) != expected["size"] or _sha256(current) != expected["sha256"]:
            conflicts.append(relative)
    for relative in new_files:
        if relative not in old_files and _read_regular(root, relative) is not None:
            conflicts.append(relative + " (untracked collision)")
    manifest_current = _read_regular(root, MANIFEST_REL, required=True)
    assert manifest_current is not None
    if _sha256(manifest_current) != _sha256(old_manifest_bytes):
        conflicts.append(MANIFEST_REL)
    if conflicts:
        raise LocalConflict("local changes or file collisions: " + ", ".join(conflicts[:8]))

    new_state = {
        "schemaVersion": 1,
        "installedVersion": new_manifest["version"],
        "installedManifestSha256": _sha256(new_manifest_bytes),
        "managedFiles": new_files,
        "lastCheckedAt": state.get("lastCheckedAt"),
        "disabled": state.get("disabled", False),
    }
    state_bytes = (json.dumps(new_state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    replacements: dict[str, bytes | None] = {path: payload[path] for path in new_files}
    replacements[MANIFEST_REL] = new_manifest_bytes
    replacements[STATE_REL] = state_bytes
    for path in old_files:
        if path not in new_files:
            replacements[path] = None
    ordered_paths = sorted(replacements, key=lambda p: (p in (STATE_REL, MANIFEST_REL), p == "SKILL.md", p == "scripts/update-skill.py", p))
    entries: list[dict[str, Any]] = []
    for relative in ordered_paths:
        before = _read_regular(root, relative)
        after = replacements[relative]
        if relative in new_files and relative not in old_files and before is not None:
            raise LocalConflict("untracked local file collides with update: " + relative)
        entries.append({
            "path": relative,
            "before": base64.b64encode(before).decode("ascii") if before is not None else None,
            "beforeSha256": _sha256(before) if before is not None else None,
            "afterSha256": _sha256(after) if after is not None else None,
        })
    _atomic_journal(root, entries)
    try:
        for relative in ordered_paths:
            new_data = replacements[relative]
            target = _assert_no_internal_symlink(root, Path(relative))
            current = _read_regular(root, relative)
            expected_before = next(item["beforeSha256"] for item in entries if item["path"] == relative)
            if (_sha256(current) if current is not None else None) != expected_before:
                raise LocalConflict("file changed during update: " + relative)
            if new_data is None:
                if current is not None:
                    target.unlink()
                    _fsync_directory(target.parent)
            else:
                _write_bytes_atomic(root, relative, new_data)
        journal_path = _assert_no_internal_symlink(root, Path(TRANSACTION_REL), must_exist=True)
        journal_path.unlink()
        _fsync_directory(root)
    except Exception:
        _recover_interrupted_update(root)
        raise


def _save_state(root: Path, state: dict[str, Any]) -> None:
    _write_json_atomic(root, STATE_REL, state)


def _portable_key(relative: str) -> str:
    return unicodedata.normalize("NFC", relative).casefold()


def _local_payload_paths(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    candidates = ["SKILL.md"]
    for directory in ("scripts", "references", "agents", "assets"):
        base = root / directory
        if not base.exists() and not base.is_symlink():
            continue
        _assert_no_internal_symlink(root, Path(directory), must_exist=True)
        if not base.is_dir():
            raise LocalConflict("Skill payload path is not a directory: " + directory)
        for current, directories, files in os.walk(base, topdown=True, followlinks=False):
            current_path = Path(current)
            for name in list(directories):
                child = current_path / name
                candidates.append(child.relative_to(root).as_posix())
                try:
                    info = child.lstat()
                except OSError as exc:
                    raise LocalConflict("cannot inspect a local payload directory: " + child.relative_to(root).as_posix()) from exc
                if _is_link_or_reparse_point(child, info):
                    directories.remove(name)
            for name in files:
                candidates.append((current_path / name).relative_to(root).as_posix())
    for relative in candidates:
        path = root / relative
        if relative == "SKILL.md" and not path.exists() and not path.is_symlink():
            continue
        found.setdefault(_portable_key(relative), []).append(relative)
    return found


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise UpdateError("invalid release version")
    return tuple(int(part) for part in match.groups())


def _status(mode: str, detail: str = "") -> None:
    print("StyleKit Skill update: " + mode + ("; " + detail if detail else ""))


def _run_auto(root: Path, force: bool = False) -> int:
    try:
        with _exclusive_lock(root) as locked:
            if not locked:
                _status("BUSY", "another update check is running; continuing with the installed Skill")
                return 0
            recovered = _recover_interrupted_update(root)
            if recovered:
                _status("RECOVERED", "interrupted changes were rolled back; later local edits were preserved")
            if _is_disabled(root):
                _status("DISABLED", "automatic and forced checks are disabled")
                return 0
            manifest_bytes, state, first_run = _load_state(root)
            now = _utc_now()
            last_checked = _parse_timestamp(state.get("lastCheckedAt"))
            if not force and last_checked is not None and now - last_checked < CHECK_INTERVAL:
                _status("CHECK_DEFERRED", "checked within the last 24 hours; continuing with " + state["installedVersion"])
                return 0
            old_manifest = _validate_manifest(manifest_bytes)
            state["lastCheckedAt"] = _timestamp(now)
            _save_state(root, state)
            try:
                archive_bytes = _open_official_archive(force=force)
                remote_manifest_bytes, remote_payload = _validate_and_unpack_archive(archive_bytes)
                remote_manifest = _validate_manifest(remote_manifest_bytes)
            except (UpdateError, OSError, TimeoutError, ValueError) as exc:
                _status("UNAVAILABLE", "could not verify an update; continuing with " + state["installedVersion"] + " (" + str(exc) + ")")
                return 1 if force else 0
            if _version_tuple(remote_manifest["version"]) < _version_tuple(state["installedVersion"]):
                _status("REJECTED", "official branch version is older than the installed release")
                return 1 if force else 0
            if remote_manifest["version"] == state["installedVersion"] and _sha256(remote_manifest_bytes) != _sha256(manifest_bytes):
                _status("REJECTED", "release contents changed without a version bump")
                return 1 if force else 0
            if _sha256(remote_manifest_bytes) == _sha256(manifest_bytes):
                _status("UP_TO_DATE", "version " + state["installedVersion"])
                return 0
            _apply_payload(root, manifest_bytes, old_manifest, remote_manifest_bytes,
                           remote_manifest, remote_payload, state)
            _status("UPDATED", state["installedVersion"] + " -> " + remote_manifest["version"] + "; reread SKILL.md before continuing")
            return 0
    except LocalConflict as exc:
        _status("LOCAL_CHANGES_PROTECTED", str(exc) + "; no update was applied")
        return 1 if force else 0
    except (UpdateError, OSError) as exc:
        _status("UNAVAILABLE", str(exc) + "; continuing with the installed Skill")
        return 1 if force else 0


def _change_setting(root: Path, disabled: bool) -> int:
    try:
        with _exclusive_lock(root) as locked:
            if not locked:
                _status("BUSY", "another update check is running")
                return 1
            _recover_interrupted_update(root)
            existing = _read_regular(root, DISABLED_REL)
            if disabled:
                if existing is not None and existing != DISABLED_MARKER:
                    raise LocalConflict("disable marker path contains an unrecognized file")
                if existing is None:
                    _write_bytes_atomic(root, DISABLED_REL, DISABLED_MARKER)
            elif existing is not None:
                if existing != DISABLED_MARKER:
                    raise LocalConflict("disable marker path contains an unrecognized file")
                marker = _assert_no_internal_symlink(root, Path(DISABLED_REL), must_exist=True)
                marker.unlink()
                _fsync_directory(root)
            _status("DISABLED" if disabled else "ENABLED", "automatic update setting saved")
            return 0
    except (UpdateError, LocalConflict, OSError) as exc:
        _status("ERROR", str(exc))
        return 1


def _show_status(root: Path) -> int:
    try:
        if _is_disabled(root):
            try:
                _, manifest = _safe_manifest_bytes(root)
                version = manifest["version"]
            except UpdateError:
                version = "unknown"
            _status("DISABLED", "version " + version + "; automatic and forced checks are disabled")
            return 0
    except (UpdateError, LocalConflict, OSError) as exc:
        _status("ERROR", str(exc))
        return 1
    try:
        _, state, _ = _load_state(root)
    except (UpdateError, LocalConflict, OSError) as exc:
        _status("ERROR", str(exc))
        return 1
    last = state.get("lastCheckedAt") or "not checked yet"
    _status("DISABLED" if state.get("disabled") else "ENABLED",
            "version " + state["installedVersion"] + "; last check " + last)
    return 0


def _is_disabled(root: Path) -> bool:
    marker = _read_regular(root, DISABLED_REL)
    if marker is None:
        return False
    if marker != DISABLED_MARKER:
        raise LocalConflict("disable marker path contains an unrecognized file")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check and update this StyleKit Skill from its official GitHub main branch.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--auto", action="store_true", help="check at most once per 24 hours; safe for Skill startup")
    action.add_argument("--force-check", action="store_true", help="bypass the 24-hour interval; local edits remain protected")
    action.add_argument("--disable", action="store_true", help="disable automatic update checks")
    action.add_argument("--enable", action="store_true", help="enable automatic update checks")
    action.add_argument("--status", action="store_true", help="show the local update setting without network access")
    args = parser.parse_args(argv)
    try:
        root = _root_from_script()
    except UpdateError as exc:
        _status("UNAVAILABLE", str(exc) + "; continuing with the installed Skill")
        return 0 if args.auto else 1
    if args.auto:
        return _run_auto(root)
    if args.force_check:
        return _run_auto(root, force=True)
    if args.disable:
        return _change_setting(root, True)
    if args.enable:
        return _change_setting(root, False)
    return _show_status(root)


if __name__ == "__main__":
    raise SystemExit(main())
