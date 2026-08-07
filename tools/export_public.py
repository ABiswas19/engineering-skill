from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


class ExportError(RuntimeError):
    pass


def _git_common(root: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    path = Path(result.stdout.strip())
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def _safe_file(root: Path, relative: str) -> Path:
    path = root / relative
    if (
        not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not path.is_file()
        or path.is_symlink()
        or bool(
            getattr(path.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise ExportError(f"unsafe or missing export file: {relative}")
    return path


def _safe_destination(root: Path, relative: str) -> Path:
    candidate = root / relative
    current = root
    for part in Path(relative).parts[:-1]:
        current /= part
        if not current.exists():
            break
        if current.is_symlink() or bool(
            getattr(current.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise ExportError(f"unsafe export destination: {relative}")
    if os.path.lexists(candidate) and (
        not candidate.is_file()
        or candidate.is_symlink()
        or candidate.lstat().st_nlink != 1
        or bool(
            getattr(candidate.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise ExportError(f"unsafe export destination: {relative}")
    return candidate


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path, files: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update((root / relative).read_bytes() + b"\0")
    return "sha256:" + digest.hexdigest()


def _atomic_private_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def export_tree(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    destination_git = destination / ".git"
    if (
        not (source / ".git").exists()
        or not destination_git.is_dir()
        or destination_git.is_symlink()
        or bool(
            getattr(destination_git.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
    ):
        raise ExportError("source and destination must be independent Git repositories")
    if _git_common(source) == _git_common(destination):
        raise ExportError("public export must use independent Git history")
    manifest_path = source / "release" / "public-export.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        set(manifest) != {"schema", "files"}
        or manifest.get("schema") != "engineering.public-export.v1"
        or not isinstance(manifest.get("files"), list)
        or manifest["files"] != sorted(set(manifest["files"]))
    ):
        raise ExportError("public export manifest is invalid")
    files = manifest["files"]
    sources = {relative: _safe_file(source, relative) for relative in files}
    receipt_path = _safe_destination(destination_git, "engineering-public-export.json")
    previous = {}
    if receipt_path.is_file():
        retained = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            isinstance(retained, dict)
            and retained.get("schema") == "engineering.public-export-receipt.v2"
            and isinstance(retained.get("files"), dict)
        ):
            previous = retained["files"]
    for relative, expected_digest in previous.items():
        if (
            relative not in files
            and isinstance(relative, str)
            and relative
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and isinstance(expected_digest, str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest)
        ):
            target = _safe_destination(destination, relative)
            if target.is_file() and _file_digest(target) == expected_digest:
                target.unlink()
    for relative, source_path in sources.items():
        target = _safe_destination(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = _safe_destination(destination, relative)
        shutil.copy2(source_path, target)
    receipt = {
        "schema": "engineering.public-export-receipt.v2",
        "files": {relative: _file_digest(destination / relative) for relative in files},
    }
    _atomic_private_text(receipt_path, json.dumps(receipt, indent=2) + "\n")
    blockers = [] if (destination / "LICENSE").is_file() else ["license_missing"]
    return {
        "schema": "engineering.public-export-result.v1",
        "tree_digest": _tree_digest(destination, files),
        "file_count": len(files),
        "publication_ready": not blockers,
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="export-public")
    parser.add_argument("source")
    parser.add_argument("destination")
    arguments = parser.parse_args()
    try:
        result = export_tree(Path(arguments.source), Path(arguments.destination))
    except (OSError, ValueError, subprocess.SubprocessError, ExportError) as error:
        print(f"ERROR: {error}")
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
