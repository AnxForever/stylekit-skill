import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import struct
import subprocess
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_skill", ROOT / "scripts" / "update-skill.py")
updater = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = updater
spec.loader.exec_module(updater)


def manifest_bytes(version, files):
    manifest = {
        "schemaVersion": 1,
        "repository": updater.REPOSITORY,
        "branch": updater.BRANCH,
        "version": version,
        "files": {
            path: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for path, data in sorted(files.items())
        },
    }
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def make_archive(version, files):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(updater.ARCHIVE_PREFIX, "")
        archive.writestr(updater.ARCHIVE_PREFIX + updater.MANIFEST_REL, manifest_bytes(version, files))
        for path, data in sorted(files.items()):
            archive.writestr(updater.ARCHIVE_PREFIX + path, data)
    return result.getvalue()


class SkillUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "skill"
        self.root.mkdir()
        self.old = {
            "SKILL.md": b"old instructions\n",
            "scripts/update-skill.py": b"old updater bytes\n",
            "references/keep.md": b"old reference\n",
            "references/removed.md": b"old upstream file\n",
        }
        self._install("0.6.0", self.old)

    def tearDown(self):
        self.temporary.cleanup()

    def _install(self, version, files):
        for relative, data in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / updater.MANIFEST_REL).write_bytes(manifest_bytes(version, files))

    def _ready_state(self, last_checked=None):
        raw_manifest, state = updater._initial_state(self.root)
        state["lastCheckedAt"] = last_checked
        updater._save_state(self.root, state)
        return raw_manifest, updater._validate_manifest(raw_manifest), state

    def _new_release(self):
        return {
            "SKILL.md": b"new instructions\n",
            "scripts/update-skill.py": b"new updater bytes\n",
            "references/keep.md": b"updated reference\n",
            "references/added.md": b"new upstream file\n",
        }

    def test_update_replaces_managed_files_adds_new_and_deletes_only_old_managed(self):
        raw, old_manifest, state = self._ready_state()
        (self.root / "personal-note.txt").write_text("preserve me", encoding="utf-8")
        new_files = self._new_release()
        remote_raw = manifest_bytes("0.7.0", new_files)
        updater._apply_payload(self.root, raw, old_manifest, remote_raw,
                               updater._validate_manifest(remote_raw), new_files, state)

        self.assertEqual((self.root / "SKILL.md").read_bytes(), new_files["SKILL.md"])
        self.assertEqual((self.root / "references/keep.md").read_bytes(), new_files["references/keep.md"])
        self.assertEqual((self.root / "references/added.md").read_bytes(), new_files["references/added.md"])
        self.assertFalse((self.root / "references/removed.md").exists())
        self.assertEqual((self.root / "personal-note.txt").read_text(encoding="utf-8"), "preserve me")
        saved_state = json.loads((self.root / updater.STATE_REL).read_text(encoding="utf-8"))
        self.assertEqual(saved_state["installedVersion"], "0.7.0")
        self.assertFalse((self.root / updater.TRANSACTION_REL).exists())

    def test_no_update_reports_current_version_without_replacing_files(self):
        raw, _, state = self._ready_state("2000-01-01T00:00:00Z")
        before = {path: (self.root / path).read_bytes() for path in self.old}
        output = io.StringIO()
        with patch.object(updater, "_open_official_archive", return_value=make_archive("0.6.0", self.old)):
            with contextlib.redirect_stdout(output):
                result = updater._run_auto(self.root)
        self.assertEqual(result, 0)
        self.assertIn("UP_TO_DATE", output.getvalue())
        self.assertEqual({path: (self.root / path).read_bytes() for path in self.old}, before)

    def test_offline_check_is_non_blocking_and_keeps_skill_files(self):
        self._ready_state("2000-01-01T00:00:00Z")
        before = (self.root / "SKILL.md").read_bytes()
        output = io.StringIO()
        with patch.object(updater, "_open_official_archive", side_effect=updater.UpdateError("offline")):
            with contextlib.redirect_stdout(output):
                result = updater._run_auto(self.root)
        self.assertEqual(result, 0)
        self.assertIn("UNAVAILABLE", output.getvalue())
        self.assertEqual((self.root / "SKILL.md").read_bytes(), before)
        self.assertIsNotNone(json.loads((self.root / updater.STATE_REL).read_text())["lastCheckedAt"])

    def test_auto_fetch_is_single_attempt_and_force_fetch_retries(self):
        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return updater.ARCHIVE_URL

            def read(self, _limit):
                return b"archive bytes"

        with patch.object(updater.urllib.request, "urlopen", side_effect=OSError("offline")) as request:
            with patch.object(updater.time, "sleep"):
                with self.assertRaises(updater.UpdateError):
                    updater._open_official_archive()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["timeout"], 7)

        with patch.object(updater.urllib.request, "urlopen", side_effect=[OSError("temporary"), Response()]) as request:
            with patch.object(updater.time, "sleep"):
                self.assertEqual(updater._open_official_archive(force=True), b"archive bytes")
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.kwargs["timeout"] == 12 for call in request.call_args_list))

    def test_recent_check_defers_network_for_24_hours(self):
        _, _, state = self._ready_state(updater._timestamp())
        output = io.StringIO()
        with patch.object(updater, "_open_official_archive") as fetch:
            with contextlib.redirect_stdout(output):
                result = updater._run_auto(self.root)
        self.assertEqual(result, 0)
        self.assertIn("CHECK_DEFERRED", output.getvalue())
        fetch.assert_not_called()

    def test_first_run_tampering_is_detected_before_network(self):
        (self.root / "SKILL.md").write_bytes(b"user-edited instructions\n")
        output = io.StringIO()
        with patch.object(updater, "_open_official_archive") as fetch:
            with contextlib.redirect_stdout(output):
                result = updater._run_auto(self.root)
        self.assertEqual(result, 0)
        self.assertIn("LOCAL_CHANGES_PROTECTED", output.getvalue())
        fetch.assert_not_called()
        self.assertFalse((self.root / updater.STATE_REL).exists())

    def test_modified_managed_file_skips_whole_update_even_when_forced(self):
        self._ready_state("2000-01-01T00:00:00Z")
        (self.root / "references/keep.md").write_bytes(b"my custom edit\n")
        output = io.StringIO()
        with patch.object(updater, "_open_official_archive", return_value=make_archive("0.7.0", self._new_release())):
            with contextlib.redirect_stdout(output):
                result = updater._run_auto(self.root, force=True)
        self.assertEqual(result, 1)
        self.assertIn("LOCAL_CHANGES_PROTECTED", output.getvalue())
        self.assertEqual((self.root / "SKILL.md").read_bytes(), self.old["SKILL.md"])
        self.assertEqual((self.root / "references/keep.md").read_bytes(), b"my custom edit\n")
        self.assertFalse((self.root / "references/added.md").exists())

    def test_modified_file_removed_upstream_is_preserved_with_whole_update_skipped(self):
        raw, old_manifest, state = self._ready_state()
        (self.root / "references/removed.md").write_bytes(b"local replacement\n")
        new_files = self._new_release()
        remote_raw = manifest_bytes("0.7.0", new_files)
        with self.assertRaises(updater.LocalConflict):
            updater._apply_payload(self.root, raw, old_manifest, remote_raw,
                                   updater._validate_manifest(remote_raw), new_files, state)
        self.assertEqual((self.root / "references/removed.md").read_bytes(), b"local replacement\n")
        self.assertEqual((self.root / "SKILL.md").read_bytes(), self.old["SKILL.md"])
        self.assertFalse((self.root / "references/added.md").exists())

    def test_untracked_exact_or_casefold_collision_is_protected(self):
        raw, old_manifest, state = self._ready_state()
        (self.root / "references/added.md").write_bytes(b"user file\n")
        new_files = self._new_release()
        remote_raw = manifest_bytes("0.7.0", new_files)
        with self.assertRaises(updater.LocalConflict):
            updater._apply_payload(self.root, raw, old_manifest, remote_raw,
                                   updater._validate_manifest(remote_raw), new_files, state)
        (self.root / "references/added.md").unlink()
        (self.root / "references/Added.md").write_bytes(b"case alias\n")
        with self.assertRaises(updater.LocalConflict):
            updater._apply_payload(self.root, raw, old_manifest, remote_raw,
                                   updater._validate_manifest(remote_raw), new_files, state)

    def test_failed_replace_rolls_back_files_and_clears_transaction(self):
        raw, old_manifest, state = self._ready_state()
        new_files = self._new_release()
        remote_raw = manifest_bytes("0.7.0", new_files)
        original_write = updater._write_bytes_atomic
        failed = False

        def fail_once(root, relative, data):
            nonlocal failed
            if relative == "SKILL.md" and not failed:
                failed = True
                raise OSError("simulated write failure")
            return original_write(root, relative, data)

        with patch.object(updater, "_write_bytes_atomic", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "simulated"):
                updater._apply_payload(self.root, raw, old_manifest, remote_raw,
                                       updater._validate_manifest(remote_raw), new_files, state)
        for relative, data in self.old.items():
            self.assertEqual((self.root / relative).read_bytes(), data)
        self.assertFalse((self.root / "references/added.md").exists())
        self.assertFalse((self.root / updater.TRANSACTION_REL).exists())

    def test_interrupted_transaction_recovers_before_or_after_states(self):
        target = "references/keep.md"
        old_bytes = (self.root / target).read_bytes()
        new_bytes = b"partially applied\n"
        entries = [{
            "path": target,
            "before": base64.b64encode(old_bytes).decode("ascii"),
            "beforeSha256": hashlib.sha256(old_bytes).hexdigest(),
            "afterSha256": hashlib.sha256(new_bytes).hexdigest(),
        }]
        updater._atomic_journal(self.root, entries)
        (self.root / target).write_bytes(new_bytes)
        self.assertTrue(updater._recover_interrupted_update(self.root))
        self.assertEqual((self.root / target).read_bytes(), old_bytes)
        self.assertFalse((self.root / updater.TRANSACTION_REL).exists())

    def test_interrupted_transaction_keeps_later_user_edit_and_rolls_back_other_files(self):
        first = "references/keep.md"
        second = "references/removed.md"
        first_before = (self.root / first).read_bytes()
        second_before = (self.root / second).read_bytes()
        first_after = b"new version\n"
        second_user_edit = b"edited during interrupted update\n"
        entries = [
            {
                "path": first,
                "before": base64.b64encode(first_before).decode("ascii"),
                "beforeSha256": hashlib.sha256(first_before).hexdigest(),
                "afterSha256": hashlib.sha256(first_after).hexdigest(),
            },
            {
                "path": second,
                "before": base64.b64encode(second_before).decode("ascii"),
                "beforeSha256": hashlib.sha256(second_before).hexdigest(),
                "afterSha256": hashlib.sha256(b"updated upstream\n").hexdigest(),
            },
        ]
        updater._atomic_journal(self.root, entries)
        (self.root / first).write_bytes(first_after)
        (self.root / second).write_bytes(second_user_edit)
        self.assertTrue(updater._recover_interrupted_update(self.root))
        self.assertEqual((self.root / first).read_bytes(), first_before)
        self.assertEqual((self.root / second).read_bytes(), second_user_edit)
        self.assertFalse((self.root / updater.TRANSACTION_REL).exists())

    def test_concurrent_check_sees_busy_and_does_not_fetch(self):
        self._ready_state("2000-01-01T00:00:00Z")
        output = io.StringIO()
        with updater._exclusive_lock(self.root) as locked:
            self.assertTrue(locked)
            with patch.object(updater, "_open_official_archive") as fetch:
                with contextlib.redirect_stdout(output):
                    result = updater._run_auto(self.root, force=True)
        self.assertEqual(result, 0)
        self.assertIn("BUSY", output.getvalue())
        fetch.assert_not_called()

    def test_force_does_not_bypass_disabled_setting(self):
        self._ready_state("2000-01-01T00:00:00Z")
        self.assertEqual(updater._change_setting(self.root, True), 0)
        output = io.StringIO()
        with patch.object(updater, "_open_official_archive") as fetch:
            with contextlib.redirect_stdout(output):
                result = updater._run_auto(self.root, force=True)
        self.assertEqual(result, 0)
        self.assertIn("DISABLED", output.getvalue())
        fetch.assert_not_called()

    def test_disable_remains_available_after_a_local_edit(self):
        (self.root / "SKILL.md").write_bytes(b"user edit\n")
        self.assertEqual(updater._change_setting(self.root, True), 0)
        self.assertTrue(updater._is_disabled(self.root))
        self.assertEqual(updater._change_setting(self.root, False), 0)
        self.assertFalse(updater._is_disabled(self.root))
        self.assertEqual((self.root / "SKILL.md").read_bytes(), b"user edit\n")

    def test_archive_rejects_traversal_symlinks_and_nonportable_names(self):
        traversal = io.BytesIO()
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr(updater.ARCHIVE_PREFIX + "../escape.txt", b"bad")
        with self.assertRaisesRegex(updater.UpdateError, "unsafe|traversal"):
            updater._validate_and_unpack_archive(traversal.getvalue())

        linked = io.BytesIO()
        with zipfile.ZipFile(linked, "w") as archive:
            info = zipfile.ZipInfo(updater.ARCHIVE_PREFIX + "scripts/shortcut.py")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, b"target")
        with self.assertRaisesRegex(updater.UpdateError, "symbolic link"):
            updater._validate_and_unpack_archive(linked.getvalue())

        oversized = io.BytesIO()
        with zipfile.ZipFile(oversized, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(updater.ARCHIVE_PREFIX + "scripts/large.py", b"x" * (updater.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(updater.UpdateError, "oversized file"):
            updater._validate_and_unpack_archive(oversized.getvalue())

        unsupported = io.BytesIO(make_archive("0.7.0", {"scripts/update-skill.py": b"x"}))
        with zipfile.ZipFile(unsupported) as archive:
            member = next(info for info in archive.infolist() if info.filename.endswith("scripts/update-skill.py"))
            member_name = member.filename.encode("utf-8")
            original = unsupported.getvalue()
            central_name_pos = original.rfind(member_name)
            central_header_pos = original.rfind(bytes((0x50, 0x4B, 0x01, 0x02)), 0, central_name_pos)
            raw_archive = bytearray(original)
            struct.pack_into("<H", raw_archive, member.header_offset + 8, 99)
            struct.pack_into("<H", raw_archive, central_header_pos + 10, 99)
        with self.assertRaisesRegex(updater.UpdateError, "corrupt or unreadable"):
            updater._validate_and_unpack_archive(bytes(raw_archive))

        for path in ("scripts/CON.py", "scripts/name.", "scripts/cafe\u0301.py"):
            with self.subTest(path=path), self.assertRaises(updater.UpdateError):
                updater._validate_relpath(path)

    def test_internal_symlink_file_is_rejected(self):
        target = self.root / "references/keep.md"
        link = self.root / "references/link.md"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        with self.assertRaisesRegex(updater.UpdateError, "link"):
            updater._read_regular(self.root, "references/link.md")

    @unittest.skipUnless(sys.platform == "win32", "Windows junction behavior")
    def test_internal_windows_junction_is_rejected(self):
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        junction = self.root / "scripts/junction"
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        command = "New-Item -ItemType Junction -Path " + quote(junction) + " -Target " + quote(outside) + " | Out-Null"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("could not create a temporary Windows junction: " + result.stderr.strip())
        with self.assertRaisesRegex(updater.UpdateError, "junction|link"):
            updater._assert_no_internal_symlink(self.root, Path("scripts/junction"), must_exist=True)

    @unittest.skipUnless(sys.platform == "win32", "Windows junction behavior")
    def test_nested_windows_junction_is_not_traversed_during_collision_scan(self):
        outside = Path(self.temporary.name) / "outside-nested"
        outside.mkdir()
        sentinel = outside / "must-not-be-scanned.md"
        sentinel.write_text("outside payload", encoding="utf-8")
        junction = self.root / "references/custom-junction"
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        command = "New-Item -ItemType Junction -Path " + quote(junction) + " -Target " + quote(outside) + " | Out-Null"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest("could not create a temporary Windows junction: " + result.stderr.strip())
        try:
            scanned = updater._local_payload_paths(self.root)
            self.assertIn(updater._portable_key("references/custom-junction"), scanned)
            self.assertNotIn(updater._portable_key("references/custom-junction/must-not-be-scanned.md"), scanned)
        finally:
            junction.rmdir()

    def test_git_autocrlf_checkout_keeps_manifest_hashes(self):
        git = shutil.which("git")
        if not git:
            self.skipTest("git is unavailable")
        source = Path(self.temporary.name) / "line-ending-source"
        checkout = Path(self.temporary.name) / "line-ending-checkout"
        source.mkdir()
        manifest = json.loads((ROOT / updater.MANIFEST_REL).read_text(encoding="utf-8"))
        paths = list(manifest["files"]) + [updater.MANIFEST_REL]
        for relative in paths + [".gitattributes"]:
            destination = source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        subprocess.run([git, "init", str(source)], check=True, capture_output=True)
        subprocess.run([git, "-C", str(source), "add", "."], check=True, capture_output=True)
        subprocess.run([
            git, "-C", str(source), "-c", "user.name=StyleKit test", "-c",
            "user.email=stylekit-test@example.invalid", "commit", "-m", "test payload",
        ], check=True, capture_output=True)
        env = os.environ.copy()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "core.autocrlf"
        env["GIT_CONFIG_VALUE_0"] = "true"
        subprocess.run([git, "clone", str(source), str(checkout)], check=True, capture_output=True, env=env)
        result = subprocess.run(
            [sys.executable, str(checkout / "scripts/generate-release-manifest.py"), "--check"],
            cwd=checkout, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
