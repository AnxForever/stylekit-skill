#!/usr/bin/env python3
"""Generate or check the published StyleKit Skill payload manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY = "AnxForever/stylekit-skill"
BRANCH = "main"
RELEASE_VERSION = "0.8.0"
MANIFEST = Path(__file__).resolve().with_name("release-manifest.json")
ROOT = MANIFEST.parents[1]
PAYLOAD_FILES = (Path("SKILL.md"),)
PAYLOAD_DIRS = (Path("scripts"), Path("references"), Path("agents"), Path("assets"))
EXCLUDED_NAMES = {"__pycache__", ".DS_Store"}


def payload_paths() -> list[Path]:
    found = list(PAYLOAD_FILES)
    for directory in PAYLOAD_DIRS:
        absolute = ROOT / directory
        if absolute.exists():
            found.extend(path.relative_to(ROOT) for path in absolute.rglob("*") if path.is_file())
    result: list[Path] = []
    folded: set[str] = set()
    for relative in found:
        if any(part in EXCLUDED_NAMES or part.endswith(".pyc") for part in relative.parts):
            continue
        absolute = ROOT / relative
        if absolute.is_symlink():
            raise ValueError("refusing a symbolic link in the Skill payload: " + relative.as_posix())
        normalized = relative.as_posix()
        if normalized == "scripts/release-manifest.json":
            continue
        if normalized.casefold() in folded:
            raise ValueError("case-colliding Skill payload path: " + normalized)
        folded.add(normalized.casefold())
        if absolute.is_file():
            result.append(relative)
    return sorted(result, key=lambda path: path.as_posix())


def render() -> bytes:
    files = {}
    for relative in payload_paths():
        data = (ROOT / relative).read_bytes()
        files[relative.as_posix()] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    document = {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "branch": BRANCH,
        "version": RELEASE_VERSION,
        "files": files,
    }
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def check_version_against(reference: str) -> int:
    exists = subprocess.run(["git", "cat-file", "-e", reference + "^{commit}"], cwd=ROOT, capture_output=True)
    if exists.returncode:
        print("cannot resolve comparison commit " + reference, file=sys.stderr)
        return 1
    old = subprocess.run(
        ["git", "show", reference + ":scripts/release-manifest.json"],
        cwd=ROOT, capture_output=True,
    )
    if old.returncode:
        # The first release manifest has no prior version to compare.
        message = old.stderr.decode("utf-8", "replace")
        if "does not exist in" in message or "exists on disk, but not in" in message:
            return 0
        print("cannot read the base release manifest: " + message.strip(), file=sys.stderr)
        return 1
    try:
        previous = json.loads(old.stdout.decode("utf-8"))
        current = json.loads(render().decode("utf-8"))
        previous_version = previous["version"]
        current_version = current["version"]
        version_pattern = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
        if not version_pattern.fullmatch(previous_version) or not version_pattern.fullmatch(current_version):
            raise ValueError("invalid semantic version")
        previous_files = previous["files"]
        if previous_files != current["files"]:
            previous_tuple = tuple(int(part) for part in previous_version.split("."))
            current_tuple = tuple(int(part) for part in current_version.split("."))
            if current_tuple <= previous_tuple:
                print("bump RELEASE_VERSION when changing a managed Skill payload", file=sys.stderr)
                return 1
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print("cannot compare release versions: " + str(exc), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed manifest is stale")
    parser.add_argument("--check-version-against", metavar="GIT_REF", help="require a higher release version if managed files changed")
    args = parser.parse_args()
    if args.check_version_against:
        return check_version_against(args.check_version_against)
    expected = render()
    if args.check:
        if not MANIFEST.is_file() or MANIFEST.read_bytes() != expected:
            print("release manifest is stale; run python3 scripts/generate-release-manifest.py", file=sys.stderr)
            return 1
        print("release manifest matches Skill payload " + RELEASE_VERSION)
        return 0
    MANIFEST.write_bytes(expected)
    print("wrote scripts/release-manifest.json for Skill payload " + RELEASE_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
